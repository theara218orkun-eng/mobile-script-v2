"""
WhatsApp Database Monitor: ADB pull + poll for new messages.
Works when WhatsApp is in background. No Frida required.
Requires: root, SELinux permissive.
"""
import base64
import os
import sqlite3
import subprocess
import tempfile
import threading
from datetime import datetime
from queue import Queue
from typing import Optional, Set

from aid_utils import logger

def _db_base(package: str) -> str:
    return f"/data/data/{package}/databases"
MSGSTORE = "msgstore.db"
WA_DB = "wa.db"
TABLE = "message"
POLL_INTERVAL = float(os.getenv("WHATSAPP_MONITOR_INTERVAL", "2.0"))


def _run_adb(device_id: Optional[str], *args) -> tuple[bool, str]:
    cmd = ["adb"]
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return False, str(e)


def _pull_db(device_id: Optional[str], db_name: str, package: str = "com.whatsapp") -> Optional[str]:
    """Pull db to temp file. Requires root."""
    remote = f"{_db_base(package)}/{db_name}"
    tmp_remote = f"/sdcard/wa_monitor_{db_name}"
    ok, _ = _run_adb(device_id, "shell", "su", "-c", f"cp \"{remote}\" {tmp_remote} 2>/dev/null")
    if not ok:
        return None
    fd, local = tempfile.mkstemp(suffix=f"_{db_name}")
    os.close(fd)
    ok, _ = _run_adb(device_id, "pull", tmp_remote, local)
    _run_adb(device_id, "shell", "rm", "-f", tmp_remote)
    if ok:
        return local
    try:
        os.unlink(local)
    except OSError:
        pass
    return None


def _poll_once(
    device_id: Optional[str],
    seen: Set[tuple],
    incoming_queue: Queue,
    initialized: list,
    fail_count: list,
    package: str = "com.whatsapp",
) -> None:
    local_msg = _pull_db(device_id, MSGSTORE, package)
    if not local_msg:
        fail_count[0] += 1
        if fail_count[0] == 1 or fail_count[0] % 30 == 0:
            logger.warning(f"[{device_id}] [WaMonitor] DB pull failed (need root)")
        return
    fail_count[0] = 0
    local_wa = _pull_db(device_id, WA_DB, package)
    try:
        conn = sqlite3.connect(local_msg)
        if local_wa:
            try:
                conn.execute(f"ATTACH DATABASE ? AS wa_db", (local_wa,))
            except Exception:
                local_wa = None
        cur = conn.execute(
            """
            SELECT m._id, m.text_data, m.from_me, m.timestamp, m.chat_row_id, m.sender_jid_row_id, m.message_type
            FROM message m
            WHERE m.text_data IS NOT NULL AND m.text_data != ''
              AND (m.message_type IS NULL OR m.message_type = 0)
            ORDER BY m.timestamp DESC LIMIT 500
            """
        )
        rows = cur.fetchall()
        for row in rows:
            msg_id, text_data, from_me, timestamp, chat_row_id, sender_jid_row_id, msg_type = row
            if from_me == 1:
                continue
            key = (msg_id, timestamp or 0)
            if key in seen:
                continue
            seen.add(key)
            if not initialized[0]:
                continue
            try:
                chat_jid = ""
                sender_jid = ""
                chat_name = ""
                sender_name = ""
                cur2 = conn.execute(
                    "SELECT jid.raw_string FROM chat JOIN jid ON jid._id=chat.jid_row_id WHERE chat._id=?",
                    (chat_row_id,),
                )
                if cur2:
                    r = cur2.fetchone()
                    if r:
                        chat_jid = r[0] or ""
                    cur2.close()
                if sender_jid_row_id and sender_jid_row_id != -1:
                    cur3 = conn.execute("SELECT raw_string FROM jid WHERE _id=?", (sender_jid_row_id,))
                    if cur3:
                        r = cur3.fetchone()
                        if r:
                            sender_jid = r[0] or ""
                        cur3.close()
                is_group = "@g.us" in (chat_jid or "")
                phone = (sender_jid or chat_jid or "").split("@")[0] if (sender_jid or chat_jid) else ""
                if local_wa:
                    try:
                        cur4 = conn.execute(
                            "SELECT wa_name FROM wa_db.wa_contacts WHERE jid=?",
                            (sender_jid or chat_jid,),
                        )
                        if cur4:
                            r = cur4.fetchone()
                            if r:
                                sender_name = r[0] or ""
                            cur4.close()
                    except Exception:
                        pass
                if is_group:
                    try:
                        cur5 = conn.execute(
                            "SELECT subject FROM chat WHERE _id=?",
                            (chat_row_id,),
                        )
                        if cur5:
                            r = cur5.fetchone()
                            if r:
                                chat_name = r[0] or ""
                            cur5.close()
                    except Exception:
                        pass
                encoded = base64.b64encode((text_data or "").encode("utf-8")).decode("ascii")
                payload_obj = {
                    "type": "INCOMING",
                    "is_group": is_group,
                    "chat": {"uuid": chat_jid, "name": chat_name, "type": "group" if is_group else "chat"},
                    "user_info": {"uuid": sender_jid, "username": sender_name, "phone": phone},
                    "content": encoded,
                    "time": datetime.fromtimestamp((timestamp or 0) / 1000).isoformat() if timestamp else "",
                }
                incoming_queue.put({
                    "device_id": device_id,
                    "package": package,
                    "payload": payload_obj,
                })
            except Exception as e:
                logger.debug(f"[{device_id}] [WaMonitor] Row parse error: {e}")
        initialized[0] = True
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            try:
                cur2 = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [r[0] for r in cur2.fetchall()]
                logger.warning(f"[{device_id}] [WaMonitor] Table {TABLE} not found. Available: {tables[:10]}")
            except Exception:
                pass
        else:
            logger.warning(f"[{device_id}] [WaMonitor] DB error: {e}")
    except Exception as e:
        logger.warning(f"[{device_id}] [WaMonitor] Poll error: {e}")
    finally:
        try:
            os.unlink(local_msg)
        except OSError:
            pass
        if local_wa:
            try:
                os.unlink(local_wa)
            except OSError:
                pass


def run_monitor(
    device_id: Optional[str],
    incoming_queue: Queue,
    stop_event: threading.Event,
    package: str = "com.whatsapp",
) -> None:
    """Poll WhatsApp DB for new INCOMING messages."""
    seen: Set[tuple] = set()
    initialized = [False]
    fail_count = [0]
    logger.info(f"[{device_id or 'device'}] [WaMonitor] Started for {package} (ADB poll, interval={POLL_INTERVAL}s)")
    while not stop_event.is_set():
        _poll_once(device_id, seen, incoming_queue, initialized, fail_count, package)
        stop_event.wait(POLL_INTERVAL)

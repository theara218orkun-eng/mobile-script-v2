"""
Messenger Database Monitor - Ported from frida-farm-for-pingtai.
Monitors reverb_db_*.db for new messages via ADB pull + SQLite.
Requires: root, SELinux permissive.
"""
import hashlib
import os
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from queue import Queue
from typing import Dict, List, Optional, Tuple

from aid_utils import logger

DB_BASE = "/data/data/com.facebook.orca/databases"
TABLE = "local_message_persistence_store"
POLL_INTERVAL = float(os.getenv("MESSENGER_MONITOR_INTERVAL", "2.0"))


def _run_adb_shell(device_id: Optional[str], command: str, use_root: bool = True) -> str:
    """Execute ADB shell command (matches frida-farm run_adb_command)."""
    if use_root:
        escaped = command.replace("'", "'\\''")
        command = f"su -c '{escaped}'"
    cmd = ["adb"]
    if device_id and device_id not in ("any", "default"):
        cmd.extend(["-s", device_id])
    cmd.extend(["shell", command])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return (r.stdout or "") + (r.stderr or "")
    except Exception:
        return ""


def _run_adb(device_id: Optional[str], *args) -> tuple[bool, str]:
    """Run adb with args (for pull, etc)."""
    cmd = ["adb"]
    if device_id and device_id not in ("any", "default"):
        cmd.extend(["-s", device_id])
    cmd.extend(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return False, str(e)


def _find_databases(device_id: Optional[str]) -> List[str]:
    """Find reverb_db_*.db (matches frida-farm find_databases)."""
    cmd = f"find {DB_BASE} -name 'reverb_db_*.db' 2>/dev/null"
    out = _run_adb_shell(device_id, cmd)
    databases = [db.strip() for db in out.split("\n") if db.strip()]
    databases = [db for db in databases if db.endswith(".db") and "-journal" not in db]
    return databases


def _pull_database(device_id: Optional[str], remote_path: str, local_path: str) -> bool:
    """Pull DB + WAL/SHM. Tries /data/local/tmp first (frida-farm), then /sdcard fallback."""
    files_to_pull = [(remote_path, "")]
    wal_path = remote_path + "-wal"
    shm_path = remote_path + "-shm"
    if "yes" in _run_adb_shell(device_id, f"test -f {wal_path} && echo yes"):
        files_to_pull.append((wal_path, "-wal"))
    if "yes" in _run_adb_shell(device_id, f"test -f {shm_path} && echo yes"):
        files_to_pull.append((shm_path, "-shm"))
    path_hash = hashlib.md5(remote_path.encode()).hexdigest()[:8]
    timestamp = int(time.time())
    for base in ["/data/local/tmp", "/sdcard"]:
        success = True
        for r_path, suffix in files_to_pull:
            temp_name = f"msgr_dump_{path_hash}_{timestamp}{suffix}"
            device_temp = f"{base}/{temp_name}"
            _run_adb_shell(device_id, f"cp {r_path} {device_temp}")
            _run_adb_shell(device_id, f"chmod 666 {device_temp}")
            ok, _ = _run_adb(device_id, "pull", device_temp, local_path + suffix)
            _run_adb_shell(device_id, f"rm {device_temp}")
            if not ok:
                success = False
        if success:
            return True
    return False


def _extract_text_from_blob(blob_data) -> str:
    """
    Extract readable text from Protobuf BLOB.
    - Filter out IDs: 9+ digit numbers (615704450, 7432265970858834800)
    - Filter out ID fragments: 5-8 digit numbers (36106) - often suffixes of thread IDs
    - Prefer: multi-token messages (contain spaces, e.g. "7373 7473 738382"), then text with letters, then 1-4 digit numbers
    """
    if not blob_data:
        return "Empty"
    try:
        if isinstance(blob_data, bytes):
            decoded = blob_data.decode("utf-8", errors="ignore")
            matches = re.findall(r"[a-zA-Z0-9\s\.,!\?\'\"\-=]{3,}", decoded)
            matches_short = re.findall(r"[0-9]{1,9}", decoded)
            all_matches = list(dict.fromkeys(matches + matches_short))
            if not all_matches:
                return "[Binary Data]"
            cleaned = [m.strip() for m in all_matches if m.strip()]
            if not cleaned:
                return "[Binary Data]"
            # Exclude digit-only IDs: 9+ digits
            filtered = [m for m in cleaned if not (m.isdigit() and len(m) >= 9)]
            if not filtered:
                filtered = cleaned
            # Exclude 5-8 digit ID fragments (36106, 61570445) - keep only 1-4 digit numbers as valid
            filtered = [m for m in filtered if not (m.isdigit() and 5 <= len(m) <= 8)]
            if not filtered:
                filtered = [m for m in cleaned if not (m.isdigit() and len(m) >= 9)]
            # Prefer multi-token messages (contain spaces) - e.g. "7373 7473 738382 37383" over just "7373"
            space_matches = [m for m in filtered if " " in m and len(m) > 8]
            if space_matches:
                return max(space_matches, key=len)
            numeric_1_4 = [m for m in filtered if m.isdigit() and len(m) <= 4]
            text_matches = [m for m in filtered if any(c.isalpha() for c in m)]
            # Prefer 4-digit numbers over short text noise (h,8d, uF from encryption)
            if numeric_1_4 and len(max(numeric_1_4, key=len)) >= 4:
                return max(numeric_1_4, key=len)
            if text_matches:
                return max(text_matches, key=len)
            if numeric_1_4:
                return max(numeric_1_4, key=len)
            def _score(s: str) -> tuple:
                return (len(s), s.isdigit())
            return max(filtered, key=_score)
        return str(blob_data)
    except Exception:
        pass
    return "[Extraction Failed]"


def _parse_rows(rows: List, columns: List) -> List[Dict]:
    """Parse DB rows into message dicts (matches frida-farm _parse_rows)."""
    messages = []
    try:
        idx_thread_id = columns.index("thread_id")
        idx_timestamp = columns.index("message_timestamp_ms")
        idx_local_only = columns.index("is_local_only_message")
        idx_payload = columns.index("message_payload")
    except ValueError:
        return []
    for row in rows:
        thread_id = row[idx_thread_id]
        timestamp_ms = row[idx_timestamp]
        is_local_only = row[idx_local_only]
        payload_blob = row[idx_payload]
        direction = "OUTGOING" if is_local_only == 1 else "INCOMING"
        content = _extract_text_from_blob(payload_blob)
        date_str = ""
        try:
            ts = int(timestamp_ms) / 1000.0
            local_offset = time.timezone if (time.daylight == 0) else time.altzone
            local_offset = -local_offset
            tz_hours = int(local_offset // 3600)
            tz_minutes = int((local_offset % 3600) // 60)
            tz_sign = "+" if local_offset >= 0 else "-"
            tz_str = f"{tz_sign}{abs(tz_hours):02d}{abs(tz_minutes):02d}"
            dt = datetime.fromtimestamp(ts)
            date_str = dt.strftime(f"%a %b %d %Y %H:%M:%S GMT{tz_str}")
        except Exception:
            pass
        messages.append({
            "type": direction,
            "user_info": {"uuid": str(thread_id), "username": "", "phone": ""},
            "time": date_str,
            "content": content,
        })
    return messages


def _get_table_info(local_db: str) -> Dict:
    """Get table info (matches frida-farm get_table_info)."""
    try:
        conn = sqlite3.connect(local_db)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (TABLE,))
        if not cur.fetchone():
            conn.close()
            return {}
        cur.execute(f"SELECT MAX(message_timestamp_ms) FROM {TABLE}")
        result = cur.fetchone()[0]
        last_timestamp = int(result) if result else 0
        conn.close()
        return {"last_timestamp": last_timestamp}
    except Exception:
        return {}


def _poll_once(
    device_id: Optional[str],
    db_states: Dict[str, Dict],
    incoming_queue: Queue,
    start_time: float,
    fail_count: list,
) -> None:
    """Single poll cycle (matches frida-farm check_database flow)."""
    databases = _find_databases(device_id)
    if not databases:
        fail_count[0] += 1
        if fail_count[0] == 1 or fail_count[0] % 30 == 0:
            logger.warning(f"[{device_id}] [MessengerMonitor] No reverb_db_*.db found")
        return
    for db_path in databases:
        temp_dir = tempfile.gettempdir()
        local_db = os.path.join(temp_dir, f"msgr_monitor_{int(time.time())}_{hashlib.md5(db_path.encode()).hexdigest()[:8]}.db")
        if db_path not in db_states:
            if not _pull_database(device_id, db_path, local_db):
                fail_count[0] += 1
                continue
            fail_count[0] = 0
            table_info = _get_table_info(local_db)
            if not table_info:
                for s in ["", "-wal", "-shm"]:
                    try:
                        if os.path.exists(local_db + s):
                            os.unlink(local_db + s)
                    except OSError:
                        pass
                continue
            db_states[db_path] = {"last_timestamp": table_info.get("last_timestamp", 0)}
            min_ts_ms = int(start_time * 1000)
            try:
                conn = sqlite3.connect(local_db)
                cur = conn.cursor()
                cur.execute(f"SELECT * FROM {TABLE} LIMIT 1")
                columns = [d[0] for d in cur.description]
                cur.execute(
                    f"SELECT * FROM {TABLE} WHERE message_timestamp_ms > {min_ts_ms} ORDER BY message_timestamp_ms ASC"
                )
                rows = cur.fetchall()
                if rows:
                    msgs = _parse_rows(rows, columns)
                    for msg in msgs:
                        _enqueue_message(device_id, msg, incoming_queue)
                    if msgs:
                        db_states[db_path]["last_timestamp"] = rows[-1][columns.index("message_timestamp_ms")]
                conn.close()
            except Exception as e:
                logger.warning(f"[{device_id}] [MessengerMonitor] Init error: {e}")
            for s in ["", "-wal", "-shm"]:
                try:
                    if os.path.exists(local_db + s):
                        os.unlink(local_db + s)
                except OSError:
                    pass
            continue
        last_ts = db_states[db_path].get("last_timestamp", 0)
        if not _pull_database(device_id, db_path, local_db):
            fail_count[0] += 1
            if fail_count[0] == 1 or fail_count[0] % 30 == 0:
                logger.warning(f"[{device_id}] [MessengerMonitor] DB pull failed")
            continue
        fail_count[0] = 0
        try:
            conn = sqlite3.connect(local_db)
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM {TABLE} LIMIT 1")
            columns = [d[0] for d in cur.description]
            cur.execute(
                f"SELECT * FROM {TABLE} WHERE message_timestamp_ms > {last_ts} ORDER BY message_timestamp_ms ASC"
            )
            rows = cur.fetchall()
            if rows:
                msgs = _parse_rows(rows, columns)
                for msg in msgs:
                    _enqueue_message(device_id, msg, incoming_queue)
                db_states[db_path]["last_timestamp"] = rows[-1][columns.index("message_timestamp_ms")]
            conn.close()
        except Exception as e:
            logger.warning(f"[{device_id}] [MessengerMonitor] Poll error: {e}")
        finally:
            for s in ["", "-wal", "-shm"]:
                try:
                    if os.path.exists(local_db + s):
                        os.unlink(local_db + s)
                except OSError:
                    pass


def _enqueue_message(device_id: Optional[str], msg: Dict, queue: Queue) -> None:
    """Convert frida-farm message format to line-imspw payload and put in queue."""
    if msg.get("type") != "INCOMING":
        return  # Skip our own OUTGOING messages (prevents echo / double reply)
    user_info = msg.get("user_info", {})
    if not user_info.get("uuid") or msg.get("content") is None:
        return
    content = msg.get("content", "")
    thread_id = user_info.get("uuid", "")
    # Skip echo: if we just sent this exact message to this thread, do not enqueue (prevents double send)
    try:
        from services.messenger_service import was_just_sent
        if was_just_sent(device_id, thread_id, content):
            return
    except Exception:
        pass
    import base64
    try:
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    except Exception:
        encoded = content
    payload_obj = {
        "type": msg.get("type", "INCOMING"),
        "is_group": False,
        "chat": {"uuid": thread_id, "name": "", "type": "chat"},
        "user_info": {"uuid": thread_id, "username": "", "phone": ""},
        "content": encoded,
        "time": msg.get("time", ""),
    }
    queue.put({
        "device_id": device_id,
        "package": "com.facebook.orca",
        "payload": payload_obj,
    })


def _configure_background_sync(device_id: Optional[str]) -> None:
    """Configure Android to allow Messenger to sync in the background."""
    commands = [
        "dumpsys deviceidle whitelist +com.facebook.orca",
        "am set-standby-bucket com.facebook.orca active",
        "cmd appops set com.facebook.orca RUN_IN_BACKGROUND allow",
        "cmd appops set com.facebook.orca RUN_ANY_IN_BACKGROUND allow",
    ]
    for cmd in commands:
        _run_adb_shell(device_id, cmd, use_root=True)


def run_monitor(device_id: Optional[str], incoming_queue: Queue, stop_event: threading.Event) -> None:
    """
    Poll Messenger DB and put new messages into incoming_queue.
    Matches frida-farm-for-pingtai flow: find reverb_db, pull+WAL/SHM, incremental by timestamp.
    """
    db_states: Dict[str, Dict] = {}
    start_time = time.time()
    fail_count = [0]
    
    # Configure battery optimizations and permissions once
    _configure_background_sync(device_id)
    
    logger.info(f"[{device_id or 'device'}] [MessengerMonitor] Started (frida-farm style, interval={POLL_INTERVAL}s)")
    while not stop_event.is_set():
        _poll_once(device_id, db_states, incoming_queue, start_time, fail_count)
        stop_event.wait(POLL_INTERVAL)

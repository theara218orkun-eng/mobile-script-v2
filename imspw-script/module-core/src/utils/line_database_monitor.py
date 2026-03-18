"""
LINE Database Monitor: ADB pull + poll for new messages.
Works when LINE is in background (unlike Frida attach which may miss when app is suspended).
Set LINE_USE_DB_POLL=1 to use this instead of Frida for LINE.
Requires: root, SELinux permissive.

Why DB has no new messages when LINE is in background:
- LINE often writes new messages to local SQLite only when the app is in foreground or just opened.
- In background, Android may restrict LINE (Doze/Standby), so push may not wake it, or LINE
  may not write to DB until user opens the app. So our poll only sees data that LINE has
  already written. Fix: set LINE_WAKE_FOREGROUND_INTERVAL=60 or 120 to bring LINE to
  foreground briefly every 1–2 min so it syncs and writes to DB, then we send HOME.

Size-change detection (LINE_USE_SIZE_TRIGGER=1):
- Instead of blindly pulling every poll, we first check if any DB file size changed.
- When size increases → new data likely written → pull and read. Otherwise skip pull (saves ADB).
- Monitors all *.db, *.db-wal, *.db-shm in LINE's databases folder.
"""
import base64
import hashlib
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from queue import Queue
from typing import Dict, Optional, Set, Tuple

from aid_utils import logger

# Content-based dedup: (chat_id, content_hash) -> timestamp. Prevents re-processing same message
# when device reconnects or FTS docids change. TTL 5 min.
_LINE_RECENT_EMITTED: Dict[Tuple[str, str], float] = {}
_LINE_EMITTED_LOCK = threading.Lock()
_LINE_EMITTED_TTL = 300  # seconds

DB_BASE = "/data/data/jp.naver.line.android/databases"
DB_FILES = ["naver_line", "naver_line.db"]
FTS_DB_FILE = "unencrypted_test_full_text_search_message.db"  # New LINE: FTS index has message text
CONTACT_DB_FILES = ["contact", "contact.db"]
TABLE = "chat_history"
POLL_INTERVAL = float(os.getenv("LINE_MONITOR_INTERVAL", "1.0"))
# Keep LINE alive in background: ping interval (seconds)
LINE_KEEPALIVE_INTERVAL = float(os.getenv("LINE_KEEPALIVE_INTERVAL", "15"))
# Re-apply battery whitelist every N seconds (0 = once at start)
LINE_BACKGROUND_CONFIG_INTERVAL = int(os.getenv("LINE_BACKGROUND_CONFIG_INTERVAL", "300"))
# Every N seconds bring LINE to foreground briefly then HOME so it can sync (0 = disabled)
LINE_WAKE_FOREGROUND_INTERVAL = int(os.getenv("LINE_WAKE_FOREGROUND_INTERVAL", "0"))
# Only pull DB when file size changed. 0=always poll (real-time, default). 1=skip when size unchanged (can miss short msgs).
LINE_USE_SIZE_TRIGGER = os.getenv("LINE_USE_SIZE_TRIGGER", "0").lower() in ("1", "true", "yes")
# Use FTS DB by default (1=default for new LINE). 0=naver_line only (older LINE).
LINE_USE_FTS_DB = os.getenv("LINE_USE_FTS_DB", "1").lower() in ("1", "true", "yes")
# Debug: log each FTS poll (rows, new, emitted, skipped). Set LINE_DEBUG=1
LINE_DEBUG = os.getenv("LINE_DEBUG", "0").lower() in ("1", "true", "yes")


_adb_root_active = False


def _ensure_adb_root(device_id: Optional[str]) -> bool:
    """Try adb root (emulator/userdebug). Returns True if root shell available."""
    global _adb_root_active
    cmd = ["adb"]
    if device_id and device_id not in ("any", "default"):
        cmd.extend(["-s", device_id])
    cmd.extend(["root"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0 and "root" in out.lower() and "cannot" not in out.lower():
            time.sleep(2)  # Wait for adbd restart
            _adb_root_active = True
            return True
    except Exception:
        pass
    return False


def _run_adb_shell(device_id: Optional[str], command: str, use_root: bool = True) -> str:
    """Execute ADB shell command. When adb root active, run directly without su."""
    if use_root and not _adb_root_active:
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


def _run_adb_shell_no_su(device_id: Optional[str], command: str) -> bool:
    """Run shell command without su (for am/input). Returns True if exit code 0."""
    cmd = ["adb"]
    if device_id and device_id not in ("any", "default"):
        cmd.extend(["-s", device_id])
    cmd.extend(["shell", command])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def _run_adb(device_id: Optional[str], *args) -> tuple[bool, str]:
    cmd = ["adb"]
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode == 0, (r.stdout or "").strip() + ((" " + (r.stderr or "").strip()) if r.stderr else "")
    except Exception as e:
        return False, str(e)


def _find_all_line_databases(device_id: Optional[str]) -> list[str]:
    """Find all *.db files in LINE's databases folder (like Messenger's reverb_db discovery)."""
    cmd = f"find {DB_BASE} -type f -name '*.db' 2>/dev/null"
    out = _run_adb_shell(device_id, cmd)
    databases = [p.strip() for p in out.split("\n") if p.strip() and p.strip().endswith(".db")]
    databases = [p for p in databases if "-journal" not in p]
    return databases


def _get_db_stats(device_id: Optional[str]) -> Dict[str, int]:
    """
    Get size for each DB file (*.db, *.db-wal, *.db-shm) in LINE's databases folder.
    Returns dict: path -> size. Used to detect when any file changed (new message written).
    """
    cmd = (
        f"find {DB_BASE} -type f \\( -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' \\) "
        "-exec du -b {} \\; 2>/dev/null"
    )
    out = _run_adb_shell(device_id, cmd)
    result: Dict[str, int] = {}
    for line in out.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) >= 2:
            try:
                size = int(parts[0])
                path = parts[1].strip()
                result[path] = size
            except ValueError:
                pass
    return result


def _pull_db(device_id: Optional[str]) -> tuple[Optional[str], str]:
    """
    Pull naver_line (+ -wal, -shm if exist) to temp file. Returns (local_path, error_message).
    Requires root. WAL/SHM like Messenger: ensures we read latest data when LINE uses WAL mode.
    """
    last_err = "unknown"
    for db_name in DB_FILES:
        remote = f"{DB_BASE}/{db_name}"
        tmp_remote = "/sdcard/line_monitor.db"
        # Copy main db
        ok, out = _run_adb(device_id, "shell", "su", "-c", f"cp \"{remote}\" {tmp_remote} 2>&1")
        if not ok:
            last_err = out or "su/cp failed"
            continue
        fd, local = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        ok, out = _run_adb(device_id, "pull", tmp_remote, local)
        _run_adb(device_id, "shell", "rm", "-f", tmp_remote)
        if not ok:
            last_err = out or "pull failed"
            try:
                os.unlink(local)
            except OSError:
                pass
            continue
        # Pull -wal and -shm if exist (WAL mode: uncommitted data may be in -wal)
        for suffix in ["-wal", "-shm"]:
            remote_extra = remote + suffix
            tmp_extra = tmp_remote + suffix
            if "yes" in _run_adb_shell(device_id, f"test -f \"{remote_extra}\" && echo yes"):
                _run_adb_shell(device_id, f"su -c 'cp \"{remote_extra}\" {tmp_extra} 2>/dev/null'")
                _run_adb(device_id, "pull", tmp_extra, local + suffix)
                _run_adb_shell(device_id, f"rm -f {tmp_extra}")
        return local, ""
    return None, last_err


def _pull_fts_db(device_id: Optional[str]) -> tuple[Optional[str], str]:
    """Pull FTS DB (new LINE versions without naver_line.db). Returns (local_path, error)."""
    remote = f"{DB_BASE}/{FTS_DB_FILE}"
    tmp_remote = "/sdcard/line_fts_monitor.db"
    ok = "yes" in _run_adb_shell(device_id, f"test -f \"{remote}\" && echo yes")
    if not ok:
        return None, "FTS DB not found"
    _run_adb_shell(device_id, f"cp \"{remote}\" {tmp_remote} 2>/dev/null")
    fd, local = tempfile.mkstemp(suffix="_fts.db")
    os.close(fd)
    ok, out = _run_adb(device_id, "pull", tmp_remote, local)
    _run_adb_shell(device_id, f"rm -f {tmp_remote}")
    if not ok:
        try:
            os.unlink(local)
        except OSError:
            pass
        return None, out or "FTS pull failed"
    for suffix in ["-wal", "-shm"]:
        if "yes" in _run_adb_shell(device_id, f"test -f \"{remote}{suffix}\" && echo yes"):
            _run_adb_shell(device_id, f"cp \"{remote}{suffix}\" {tmp_remote}{suffix} 2>/dev/null")
            _run_adb(device_id, "pull", tmp_remote + suffix, local + suffix)
            _run_adb_shell(device_id, f"rm -f {tmp_remote}{suffix}")
    return local, ""


def _pull_contact_db(device_id: Optional[str]) -> Optional[str]:
    """Pull contact DB to resolve mid -> display name. Requires root."""
    for db_name in CONTACT_DB_FILES:
        remote = f"{DB_BASE}/{db_name}"
        tmp_remote = "/sdcard/line_contact.db"
        ok, _ = _run_adb(device_id, "shell", "su", "-c", f"cp \"{remote}\" {tmp_remote} 2>/dev/null")
        if not ok:
            continue
        fd, local = tempfile.mkstemp(suffix="_contact.db")
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


def _build_name_cache(device_id: Optional[str], main_conn) -> dict:
    """Build mid -> display_name cache from contact DB + membership. Call once per poll."""
    cache: dict = {}
    local_contact = _pull_contact_db(device_id)
    if local_contact:
        try:
            conn = sqlite3.connect(local_contact)
            cur = conn.execute("SELECT mid, overridden_name, profile_name FROM contacts")
            for row in cur.fetchall():
                mid, overridden, profile = (row[0] or ""), (row[1] or ""), (row[2] or "")
                name = (overridden or profile).strip()
                if mid and name:
                    cache[mid] = name
            conn.close()
        except Exception:
            pass
        finally:
            try:
                os.unlink(local_contact)
            except OSError:
                pass
    if main_conn:
        try:
            cur = main_conn.execute("SELECT mid, display_name FROM membership")
            for row in cur.fetchall():
                mid, dname = (row[0] or ""), (row[1] or "").strip()
                if mid and dname and mid not in cache:
                    cache[mid] = dname
        except Exception:
            pass
    return cache


_fts_name_cache: Dict[str, Tuple[Dict[str, str], float]] = {}  # device_id -> (cache, timestamp)
FTS_NAME_CACHE_TTL = 30.0  # Refresh contact names every 30s


def _build_fts_name_cache(device_id: Optional[str]) -> Dict[str, str]:
    """Build chat_id (mid) -> display_name from contact.db. Cached 30s to reduce ADB pulls."""
    now = time.time()
    key = device_id or ""
    if key in _fts_name_cache:
        cached, ts = _fts_name_cache[key]
        if now - ts < FTS_NAME_CACHE_TTL:
            return cached
    cache: Dict[str, str] = {}
    local_contact = _pull_contact_db(device_id)
    if local_contact:
        try:
            conn = sqlite3.connect(local_contact)
            cur = conn.execute("SELECT mid, overridden_name, profile_name FROM contacts")
            for row in cur.fetchall():
                mid, overridden, profile = (row[0] or ""), (row[1] or ""), (row[2] or "")
                name = (overridden or profile).strip()
                if mid and name:
                    cache[mid] = name
            conn.close()
        except Exception:
            pass
        finally:
            try:
                os.unlink(local_contact)
            except OSError:
                pass
    _fts_name_cache[key] = (cache, now)
    return cache


def _poll_fts_once(
    device_id: Optional[str],
    local: str,
    fts_seen: Set[int],
    incoming_queue: Queue,
    initialized: list,
) -> None:
    """Poll FTS DB (unencrypted_test_full_text_search_message) for new messages."""
    try:
        name_cache = _build_fts_name_cache(device_id)
        conn = sqlite3.connect(local)
        cur = conn.execute(
            "SELECT c.docid, c.c0formatted_message, r.chat_id FROM fts_message_content c "
            "LEFT JOIN message_chat_relation r ON r.message_id = c.docid "
            "ORDER BY c.docid DESC LIMIT 500"
        )
        rows = cur.fetchall()
        new_count = 0
        emitted = 0
        skip_reason: Dict[str, int] = {}
        for row in rows:
            docid, content, chat_id = (row[0] or 0), (row[1] or ""), (row[2] or "")
            if docid in fts_seen:
                continue
            new_count += 1
            fts_seen.add(docid)
            if not initialized[0]:
                skip_reason["init"] = skip_reason.get("init", 0) + 1
                continue
            if not content:
                skip_reason["no_content"] = skip_reason.get("no_content", 0) + 1
                continue
            if not chat_id:
                skip_reason["no_chat_id"] = skip_reason.get("no_chat_id", 0) + 1
                continue
            try:
                from services.line_service import was_just_sent
                if was_just_sent(device_id, chat_id, content):
                    skip_reason["was_just_sent"] = skip_reason.get("was_just_sent", 0) + 1
                    if LINE_DEBUG:
                        logger.info(f"[{device_id}] [LineMonitor] Skipping message - was just sent by bot: {content[:50]}")
                    continue
                else:
                    # Log that we checked but it's not a recent send (good for troubleshooting)
                    if LINE_DEBUG:
                        logger.debug(f"[{device_id}] [LineMonitor] Message not in recent-sent cache, processing: {content[:50]}")
            except Exception as e:
                if LINE_DEBUG:
                    logger.warning(f"[{device_id}] [LineMonitor] was_just_sent check failed: {e}")
                pass
            # Content dedup: skip if we emitted same chat+content recently (device reconnect / FTS rebuild)
            content_hash = hashlib.sha256((content or "").encode()).hexdigest()[:16]
            emit_key = (chat_id or "", content_hash)
            now = time.time()
            with _LINE_EMITTED_LOCK:
                if emit_key in _LINE_RECENT_EMITTED and (now - _LINE_RECENT_EMITTED[emit_key]) < _LINE_EMITTED_TTL:
                    skip_reason["recent_emitted"] = skip_reason.get("recent_emitted", 0) + 1
                    continue
                _LINE_RECENT_EMITTED[emit_key] = now
                # Prune old entries
                cutoff = now - _LINE_EMITTED_TTL
                for k in list(_LINE_RECENT_EMITTED.keys()):
                    if _LINE_RECENT_EMITTED[k] < cutoff:
                        del _LINE_RECENT_EMITTED[k]
            display_name = name_cache.get(chat_id, chat_id)
            try:
                encoded = base64.b64encode((content or "").encode("utf-8")).decode("ascii")
            except Exception:
                encoded = content or ""
            payload_obj = {
                "type": "INCOMING",
                "is_group": False,
                "chat": {"uuid": chat_id, "name": display_name, "type": "chat"},
                "user_info": {"uuid": chat_id, "username": display_name, "phone": ""},
                "content": encoded,
                "time": datetime.now().isoformat(),
            }
            incoming_queue.put({
                "device_id": device_id,
                "package": "jp.naver.line.android",
                "payload": payload_obj,
            })
            emitted += 1
        initialized[0] = True
        conn.close()
        if LINE_DEBUG and (new_count > 0 or emitted > 0):
            logger.info(
                f"[{device_id}] [LineMonitor] FTS poll: rows={len(rows)} new={new_count} emitted={emitted} skip={skip_reason}"
            )
    except Exception as e:
        logger.warning(f"[{device_id}] [LineMonitor] FTS poll error: {e}")


def _poll_once(
    device_id: Optional[str],
    seen: Set[tuple],
    incoming_queue: Queue,
    initialized: list,
    fail_count: list,
    fts_seen: Optional[Set[int]] = None,
    use_fts_mode: Optional[list] = None,
) -> None:
    # Default: try FTS first (unencrypted_test_full_text_search_message). Fallback: naver_line for older LINE.
    if LINE_USE_FTS_DB and fts_seen is not None:
        fts_local, fts_err = _pull_fts_db(device_id)
        if fts_local:
            if use_fts_mode is not None and not use_fts_mode[0]:
                use_fts_mode[0] = True
                logger.info(f"[{device_id}] [LineMonitor] Using FTS DB (unencrypted_test_full_text_search_message)")
            try:
                _poll_fts_once(device_id, fts_local, fts_seen, incoming_queue, initialized)
            finally:
                for p in [fts_local, fts_local + "-wal", fts_local + "-shm"]:
                    try:
                        if os.path.exists(p):
                            os.unlink(p)
                    except OSError:
                        pass
            fail_count[0] = 0
            return
    # Fallback: naver_line (older LINE versions)
    local, pull_err = _pull_db(device_id)
    if not local:
        fail_count[0] += 1
        if fail_count[0] == 1 or fail_count[0] % 30 == 0:
            reason = (pull_err or "unknown").strip()[:200]
            logger.warning(f"[{device_id}] [LineMonitor] DB pull failed: {reason}")
        return
    fail_count[0] = 0
    try:
        conn = sqlite3.connect(local)
        name_cache = _build_name_cache(device_id, conn)
        cur = conn.execute(
            f"SELECT type, content, created_time, from_mid FROM {TABLE} "
            "WHERE type=1 ORDER BY created_time DESC LIMIT 500"
        )
        rows = cur.fetchall()
        for row in rows:
            msg_type, content, created_time, from_mid = row[0], row[1], row[2], row[3]
            key = (created_time or 0, from_mid or "", (content or "")[:100])
            if key in seen:
                continue
            seen.add(key)
            if not initialized[0]:
                continue
            direction = "INCOMING" if (from_mid and from_mid != "0" and from_mid != "") else "OUTGOING"
            if direction != "INCOMING":
                continue
            # Content dedup: skip if we emitted same chat+content recently
            chat_id_legacy = from_mid or ""
            content_hash = hashlib.sha256((content or "").encode()).hexdigest()[:16]
            emit_key = (chat_id_legacy, content_hash)
            now = time.time()
            with _LINE_EMITTED_LOCK:
                if emit_key in _LINE_RECENT_EMITTED and (now - _LINE_RECENT_EMITTED[emit_key]) < _LINE_EMITTED_TTL:
                    continue
                _LINE_RECENT_EMITTED[emit_key] = now
                cutoff = now - _LINE_EMITTED_TTL
                for k in list(_LINE_RECENT_EMITTED.keys()):
                    if _LINE_RECENT_EMITTED[k] < cutoff:
                        del _LINE_RECENT_EMITTED[k]
            display_name = name_cache.get(from_mid or "", "")
            try:
                encoded = base64.b64encode((content or "").encode("utf-8")).decode("ascii")
            except Exception:
                encoded = content or ""
            try:
                ts = int(created_time) if created_time else 0
                time_str = datetime.fromtimestamp(ts / 1000).isoformat() if ts else ""
            except (TypeError, ValueError):
                time_str = ""
            payload_obj = {
                "type": direction,
                "is_group": False,
                "chat": {"uuid": from_mid or "", "name": display_name, "type": "chat"},
                "user_info": {"uuid": from_mid or "", "username": display_name, "phone": ""},
                "content": encoded,
                "time": time_str,
            }
            incoming_queue.put({
                "device_id": device_id,
                "package": "jp.naver.line.android",
                "payload": payload_obj,
            })
        initialized[0] = True
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            try:
                cur2 = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [r[0] for r in cur2.fetchall()]
                logger.warning(f"[{device_id}] [LineMonitor] Table {TABLE} not found. Available: {tables[:10]}")
            except Exception:
                pass
        else:
            logger.warning(f"[{device_id}] [LineMonitor] DB error: {e}")
    except Exception as e:
        logger.warning(f"[{device_id}] [LineMonitor] Poll error: {e}")
    finally:
        for path in [local, local + "-wal", local + "-shm"]:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError:
                pass


def _configure_background_sync(device_id: Optional[str]) -> None:
    """Configure Android to allow LINE to sync in the background (battery whitelist, run-in-background)."""
    commands = [
        "dumpsys deviceidle whitelist +jp.naver.line.android",
        "am set-standby-bucket jp.naver.line.android active",
        "cmd appops set jp.naver.line.android RUN_IN_BACKGROUND allow",
        "cmd appops set jp.naver.line.android RUN_ANY_IN_BACKGROUND allow",
    ]
    for cmd in commands:
        _run_adb_shell(device_id, cmd, use_root=True)


def _keep_line_alive(device_id: Optional[str]) -> None:
    """Send broadcasts to keep LINE eligible for background sync (no UI)."""
    _run_adb_shell(device_id, "am broadcast -a android.net.conn.CONNECTIVITY_CHANGE -p jp.naver.line.android", use_root=True)
    _run_adb_shell(device_id, "am broadcast -a android.intent.action.USER_PRESENT -p jp.naver.line.android", use_root=True)


def _is_line_foreground(device_id: Optional[str]) -> bool:
    """True if LINE is the current foreground app (user is using it)."""
    out = _run_adb_shell(device_id, "dumpsys window 2>/dev/null | grep -i mCurrentFocus", use_root=False)
    return "jp.naver.line.android" in (out or "")


def _wake_line_foreground_briefly(device_id: Optional[str]) -> None:
    """
    Bring LINE to foreground for a few seconds so it can sync, then send HOME.
    If LINE is already in foreground (user is replying etc.), skip entirely - do NOT send HOME.
    This avoids interrupting the user when they are actively using LINE.
    """
    if _is_line_foreground(device_id):
        return  # User is using LINE, don't interrupt
    if _run_adb_shell_no_su(device_id, "am start -a android.intent.action.MAIN -p jp.naver.line.android"):
        time.sleep(3)
    _run_adb_shell_no_su(device_id, "input keyevent KEYCODE_HOME")


def _stats_changed(prev: Dict[str, int], curr: Dict[str, int]) -> bool:
    """True if any file size changed (new keys, removed keys, or size diff)."""
    all_paths = set(prev.keys()) | set(curr.keys())
    for p in all_paths:
        if prev.get(p, 0) != curr.get(p, 0):
            return True
    return False


def run_monitor(device_id: Optional[str], incoming_queue: Queue, stop_event: threading.Event) -> None:
    """
    Poll LINE DB for new INCOMING messages. Keeps LINE alive in background and can briefly wake it to sync.
    When LINE_USE_SIZE_TRIGGER=1: only pull when any DB file size changed (saves ADB, more responsive).
    """
    seen: Set[tuple] = set()
    fts_seen: Set[int] = set()
    use_fts_mode = [False]
    initialized = [False]
    fail_count = [0]
    last_keepalive = 0.0
    last_config = 0.0
    last_wake_foreground = 0.0
    last_db_stats: Dict[str, int] = {}
    polls_without_change = 0
    FORCE_POLL_EVERY_N = 5  # When size_trigger on: full poll every N cycles (short msgs may not change file size)

    # Try adb root first (emulator/userdebug) - avoids su permission issues
    if _ensure_adb_root(device_id):
        logger.info(f"[{device_id}] [LineMonitor] adb root active")

    logger.info(
        f"[{device_id or 'device'}] [LineMonitor] Started (ADB poll, interval={POLL_INTERVAL}s, keepalive={LINE_KEEPALIVE_INTERVAL}s"
        + (f", wake_foreground={LINE_WAKE_FOREGROUND_INTERVAL}s" if LINE_WAKE_FOREGROUND_INTERVAL else "")
        + (", size_trigger=on" if LINE_USE_SIZE_TRIGGER else "")
        + (", FTS=default" if LINE_USE_FTS_DB else ", naver_line=default")
        + ")"
    )

    while not stop_event.is_set():
        current_time = time.time()

        # Re-apply battery whitelist periodically (some systems reset it)
        if LINE_BACKGROUND_CONFIG_INTERVAL > 0 and (current_time - last_config >= LINE_BACKGROUND_CONFIG_INTERVAL):
            _configure_background_sync(device_id)
            last_config = current_time
        elif last_config == 0:
            _configure_background_sync(device_id)
            last_config = current_time

        # Ping LINE so it stays eligible for background sync
        if current_time - last_keepalive >= LINE_KEEPALIVE_INTERVAL:
            _keep_line_alive(device_id)
            last_keepalive = current_time

        # Optionally bring LINE to foreground briefly so it can sync, then HOME
        if LINE_WAKE_FOREGROUND_INTERVAL > 0 and (current_time - last_wake_foreground >= LINE_WAKE_FOREGROUND_INTERVAL):
            _wake_line_foreground_briefly(device_id)
            last_wake_foreground = current_time

        # Size-trigger: only pull when any DB file size changed (or first run, or fallback)
        # When LINE_DEBUG=1, always poll to see debug output
        should_poll = True
        if LINE_USE_SIZE_TRIGGER and not LINE_DEBUG:
            curr_stats = _get_db_stats(device_id)
            if last_db_stats:
                if not _stats_changed(last_db_stats, curr_stats):
                    polls_without_change += 1
                    should_poll = polls_without_change >= FORCE_POLL_EVERY_N
                else:
                    polls_without_change = 0
            if curr_stats:
                last_db_stats = curr_stats

        if should_poll:
            if LINE_USE_SIZE_TRIGGER and polls_without_change >= FORCE_POLL_EVERY_N:
                polls_without_change = 0
            _poll_once(device_id, seen, incoming_queue, initialized, fail_count, fts_seen, use_fts_mode)

        stop_event.wait(POLL_INTERVAL)

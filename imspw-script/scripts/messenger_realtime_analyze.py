#!/usr/bin/env python3
"""
Messenger 实时分析：持续监听 DB，发现新消息时打印原始 blob 与提取结果。
用法: uv run python scripts/messenger_realtime_analyze.py [DEVICE_ID]
发送消息后，脚本会实时显示 DB 中的内容和提取结果。

注：消息在屏幕上显示时来自内存（解密后），存入 DB 时可能是加密/编码格式。
若需在写入 DB 前拦截明文，需用 Frida hook Messenger 的消息接收/显示逻辑。
"""
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(project_root, "module-core", "src"))

DB_BASE = "/data/data/com.facebook.orca/databases"
TABLE = "local_message_persistence_store"
POLL_SEC = 1.5


def run_adb(device_id, *args):
    cmd = ["adb"]
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def run_shell(device_id, cmd):
    escaped = cmd.replace("'", "'\\''")
    return run_adb(device_id, "shell", f"su -c '{escaped}'")


def find_db(device_id):
    ok, out = run_shell(device_id, f"find {DB_BASE} -name 'reverb_db_*.db' 2>/dev/null")
    for line in out.split("\n"):
        line = line.strip()
        if line.endswith(".db") and "reverb_db" in line:
            return line
    return None


def pull_db(device_id, remote, local):
    ok, _ = run_shell(device_id, f"cp {remote} {local}")
    if not ok:
        return False
    ok, _ = run_adb(device_id, "pull", local, local)
    return ok


def analyze_blob(blob: bytes) -> dict:
    """Analyze blob: raw view, all matches, extracted result."""
    if not blob:
        return {"extracted": "", "matches": [], "raw_preview": "", "hex_preview": ""}
    decoded = blob.decode("utf-8", errors="ignore")
    matches_3 = re.findall(r"[a-zA-Z0-9\s\.,!\?\'\"\-=]{3,}", decoded)
    matches_num = re.findall(r"[0-9]{1,9}", decoded)
    all_matches = list(dict.fromkeys(matches_3 + matches_num))
    cleaned = [m.strip() for m in all_matches if m.strip()]
    raw_preview = decoded[:200].replace("\x00", "·")
    hex_preview = blob[:80].hex(" ") if len(blob) > 0 else ""
    from utils.messenger_database_monitor import _extract_text_from_blob
    extracted = _extract_text_from_blob(blob)
    return {
        "extracted": extracted,
        "matches": cleaned,
        "raw_preview": raw_preview,
        "hex_preview": hex_preview,
    }


def main():
    device_id = os.getenv("DEVICE_ID") or (sys.argv[1] if len(sys.argv) > 1 else None)
    print("=" * 60)
    print("Messenger Realtime DB Analyze - Send message, watch here")
    print("=" * 60)
    print(f"Device: {device_id or '(default)'} | Poll: {POLL_SEC}s")
    print("Ctrl+C to exit")
    print("-" * 60)

    db_path = find_db(device_id)
    if not db_path:
        print("[FAIL] reverb_db_*.db not found")
        return 1
    print(f"[OK] Using: {db_path}\n")

    seen = set()
    initialized = False
    tmp_remote = "/sdcard/msgr_realtime.db"
    print("First poll: seeding (skip old messages)...\n")
    while True:
        try:
            ok, _ = run_shell(device_id, f"cp \"{db_path}\" {tmp_remote}")
            if not ok:
                time.sleep(POLL_SEC)
                continue
            fd, local = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            ok, _ = run_adb(device_id, "pull", tmp_remote, local)
            run_shell(device_id, f"rm -f {tmp_remote}")
            if not ok:
                time.sleep(POLL_SEC)
                continue
            try:
                conn = sqlite3.connect(local)
                cur = conn.execute(
                    f"SELECT thread_id, message_timestamp_ms, is_local_only_message, message_payload "
                    f"FROM {TABLE} ORDER BY message_timestamp_ms DESC LIMIT 20"
                )
                rows = cur.fetchall()
                conn.close()
                for row in rows:
                    tid, ts, is_local, payload = row[0], row[1], row[2], row[3]
                    key = (str(tid), ts)
                    if key in seen:
                        continue
                    seen.add(key)
                    if not initialized:
                        continue
                    direction = "OUT" if is_local else "IN"
                    analysis = analyze_blob(payload) if payload else {"extracted": "(empty)", "matches": [], "raw_preview": "", "hex_preview": ""}
                    print(f"\n>>> NEW [{direction}] thread={tid} ts={ts}")
                    print(f"    Extracted: {analysis['extracted']}")
                    print(f"    All matches: {analysis['matches'][:15]}")
                    print(f"    Raw preview: {analysis['raw_preview'][:100]}...")
                    print(f"    HEX(first 80B): {analysis['hex_preview']}")
                    print()
            finally:
                try:
                    os.unlink(local)
                except OSError:
                    pass
            if not initialized:
                initialized = True
                print("Ready. Listening for new messages...\n")
        except KeyboardInterrupt:
            print("\nExiting")
            break
        except Exception as e:
            print(f"[ERR] {e}")
        time.sleep(POLL_SEC)
    return 0


if __name__ == "__main__":
    sys.exit(main())

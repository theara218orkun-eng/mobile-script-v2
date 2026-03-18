#!/usr/bin/env python3
"""Inspect unencrypted_test_full_text_search_message.db for message content."""
import os
import subprocess
import sys
import tempfile

DB_BASE = "/data/data/jp.naver.line.android/databases"
REMOTE = f"{DB_BASE}/unencrypted_test_full_text_search_message.db"


def run_adb(device_id, *args):
    cmd = ["adb"]
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def main():
    device_id = os.getenv("DEVICE_ID") or (sys.argv[1] if len(sys.argv) > 1 else None)
    run_adb(device_id, "root")
    import time
    time.sleep(1)
    tmp = "/sdcard/line_fts_inspect.db"
    run_adb(device_id, "shell", f"cp \"{REMOTE}\" {tmp}")
    fd, local = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    ok, _ = run_adb(device_id, "pull", tmp, local)
    run_adb(device_id, "shell", "rm", "-f", tmp)
    if not ok:
        print("Pull failed")
        return 1
    import sqlite3
    conn = sqlite3.connect(local)
    # fts_message_content: FTS virtual table content
    for table in ["fts_message", "fts_message_content", "message_chat_relation"]:
        try:
            cur = conn.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in cur.fetchall()]
            print(f"\n=== {table} columns: {cols}")
            cur = conn.execute(f"SELECT * FROM {table} LIMIT 5")
            rows = cur.fetchall()
            for i, row in enumerate(rows):
                print(f"  Row {i+1}: {str(row)[:200]}...")
            # Search for 1234
            cur = conn.execute(f"SELECT * FROM {table}")
            all_rows = cur.fetchall()
            for row in all_rows:
                if any("1234" in str(c) for c in row):
                    print(f"  >>> FOUND 1234 in {table}: {row}")
        except Exception as e:
            print(f"  Error: {e}")
    conn.close()
    os.unlink(local)
    return 0


if __name__ == "__main__":
    sys.exit(main())

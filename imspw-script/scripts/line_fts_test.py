#!/usr/bin/env python3
"""
Test FTS poll: pull DB, run same query as monitor, show what would be emitted.
Run: uv run python scripts/line_fts_test.py [DEVICE_ID]
"""
import os
import subprocess
import sys
import tempfile

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(project_root, "module-core", "src"))

DB_BASE = "/data/data/jp.naver.line.android/databases"
FTS_DB = f"{DB_BASE}/unencrypted_test_full_text_search_message.db"


def run_adb(device_id, *args):
    cmd = ["adb"]
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def main():
    device_id = os.getenv("DEVICE_ID") or (sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Device: {device_id or '(default)'}")
    run_adb(device_id, "root")
    import time
    time.sleep(1)

    tmp = "/sdcard/line_fts_test.db"
    ok = run_adb(device_id, "shell", f"cp \"{FTS_DB}\" {tmp}")[0]
    if not ok:
        print("[FAIL] Cannot copy FTS DB - need root?")
        return 1

    fd, local = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    ok, _ = run_adb(device_id, "pull", tmp, local)
    run_adb(device_id, "shell", "rm", "-f", tmp)
    if not ok:
        print("[FAIL] Pull failed")
        return 1

    import sqlite3
    conn = sqlite3.connect(local)
    cur = conn.execute(
        "SELECT c.docid, c.c0formatted_message, r.chat_id FROM fts_message_content c "
        "LEFT JOIN message_chat_relation r ON r.message_id = c.docid "
        "ORDER BY c.docid DESC LIMIT 20"
    )
    rows = cur.fetchall()
    print(f"\n[Query result] Last 20 rows (docid, content, chat_id):")
    print("-" * 70)
    for row in rows:
        docid, content, chat_id = row[0], (row[1] or "")[:50], row[2] or "NULL"
        skip = ""
        if not row[1]:
            skip = " [SKIP: no content]"
        elif not row[2]:
            skip = " [SKIP: no chat_id - NOT in message_chat_relation!]"
        print(f"  docid={docid:4} chat_id={chat_id or 'NULL':20} content={content!r}{skip}")
    conn.close()
    os.unlink(local)

    print("\n[Tip] If chat_id is NULL for new messages, they won't be sent to processor.")
    print("      Send a test message, run again, check if new row has chat_id.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

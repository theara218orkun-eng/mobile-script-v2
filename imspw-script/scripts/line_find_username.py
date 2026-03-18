#!/usr/bin/env python3
"""Find chat_id -> username mapping in LINE DBs."""
import os
import subprocess
import sys
import tempfile

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(project_root, "module-core", "src"))

DB_BASE = "/data/data/jp.naver.line.android/databases"
CHAT_ID = "u79328c62cfe897e471867cc6e8cf0598"  # From FTS


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

    # Try contact.db
    for db_name in ["contact", "contact.db"]:
        remote = f"{DB_BASE}/{db_name}"
        tmp = "/sdcard/line_contact.db"
        if not run_adb(device_id, "shell", f"cp \"{remote}\" {tmp}")[0]:
            continue
        fd, local = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        if not run_adb(device_id, "pull", tmp, local)[0]:
            continue
        run_adb(device_id, "shell", "rm", "-f", tmp)
        try:
            import sqlite3
            c = sqlite3.connect(local)
            cur = c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            print(f"contact DB tables: {tables}")
            for t in tables:
                try:
                    cur = c.execute(f"PRAGMA table_info({t})")
                    cols = [r[1] for r in cur.fetchall()]
                    cur = c.execute(f"SELECT * FROM {t} LIMIT 3")
                    rows = cur.fetchall()
                    print(f"  {t} cols={cols}, sample={rows}")
                    if "mid" in cols or "name" in cols or CHAT_ID[:10] in str(rows):
                        cur = c.execute(f"SELECT * FROM {t}")
                        for row in cur.fetchall():
                            if CHAT_ID in str(row):
                                print(f"    FOUND {CHAT_ID}: {row}")
                except Exception as e:
                    print(f"  {t} error: {e}")
            c.close()
        except Exception as e:
            print(f"Error: {e}")
        os.unlink(local)
        break

    # Check fixed_crypto - might have room/chat metadata
    for db_name in ["fixed_crypto_key_test_full_text_search_message_square.db", "unencrypted_test_full_text_search_message.db"]:
        remote = f"{DB_BASE}/{db_name}"
        tmp = "/sdcard/line_check.db"
        if not run_adb(device_id, "shell", f"cp \"{remote}\" {tmp}")[0]:
            continue
        fd, local = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        if not run_adb(device_id, "pull", tmp, local)[0]:
            continue
        run_adb(device_id, "shell", "rm", "-f", tmp)
        try:
            import sqlite3
            c = sqlite3.connect(local)
            for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                tname = t[0]
                if "room" in tname or "chat" in tname or "member" in tname:
                    cols = [r[1] for r in c.execute(f"PRAGMA table_info({tname})").fetchall()]
                    print(f"\n{db_name}.{tname}: {cols}")
                    cur = c.execute(f"SELECT * FROM {tname} LIMIT 5")
                    for row in cur.fetchall():
                        if CHAT_ID in str(row):
                            print(f"  FOUND: {row}")
            c.close()
        except Exception as e:
            print(f"Error: {e}")
        os.unlink(local)
    return 0


if __name__ == "__main__":
    main()

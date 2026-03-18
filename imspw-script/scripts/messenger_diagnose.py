#!/usr/bin/env python3
"""
Messenger DB 诊断脚本：测试 ADB 能否拉取 reverb_db，并列出表结构。
用法: uv run python scripts/messenger_diagnose.py [DEVICE_ID]
"""
import os
import subprocess
import sys
import tempfile

# Add module-core to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(project_root, "module-core", "src"))

DB_BASE = "/data/data/com.facebook.orca/databases"


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
    print("-" * 50)

    # 1. Check ADB
    ok, out = run_adb(device_id, "devices")
    if not ok:
        print("[FAIL] adb devices failed")
        return 1
    print("[OK] ADB connected")

    # 2. List DB dir (root)
    ok, out = run_adb(device_id, "shell", "su", "-c", f"ls -la {DB_BASE}/ 2>&1")
    print(f"\n[su] ls {DB_BASE}:")
    print(out[:800] if out else "(empty)")
    if not ok or "Permission denied" in (out or ""):
        print("\n[!] Need root. Try: setenforce 0 (SELinux permissive)")

    # 3. List all .db files (Messenger may use reverb_db or client_message_*)
    ok, out = run_adb(device_id, "shell", "su", "-c", f"ls {DB_BASE}/*.db 2>/dev/null")
    db_files = [l.strip() for l in (out or "").split("\n") if l.strip() and ".db" in l and "/" in l]
    if not db_files:
        db_files = [f"{DB_BASE}/{l.strip().split()[-1]}" for l in (out or "").split("\n") if l.strip() and ".db" in l]
    if not db_files:
        print(f"\n[FAIL] No .db files found. Output: {out[:300]}")
        return 1
    print(f"\n[OK] DB files: {db_files[:15]}")
    remote = db_files[0] if db_files[0].startswith("/") else f"{DB_BASE}/{db_files[0]}"

    # Prefer reverb_db for messages
    for p in db_files:
        if "reverb_db" in p:
            remote = p
            break
    print(f"Using: {remote}")

    # 4. Copy via su to /sdcard (adb can't read root-owned /data/local/tmp)
    tmp_remote = "/sdcard/messenger_diagnose.db"
    ok, err = run_adb(device_id, "shell", "su", "-c", f'cp "{remote}" {tmp_remote}')
    if not ok:
        print(f"[FAIL] su cp failed: {err[:300]}")
        return 1
    fd, local = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ok, err = run_adb(device_id, "pull", tmp_remote, local)
        run_adb(device_id, "shell", "rm", "-f", tmp_remote)
        if not ok:
            print(f"[FAIL] adb pull failed: {err[:300]}")
            return 1
        print(f"[OK] Pulled to {local}")

        import sqlite3
        conn = sqlite3.connect(local)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        print(f"\nTables ({len(tables)}): {tables[:20]}{'...' if len(tables) > 20 else ''}")

        target = "local_message_persistence_store"
        if target in tables:
            cur = conn.execute(f"PRAGMA table_info({target})")
            cols = [r[1] for r in cur.fetchall()]
            print(f"\n[OK] {target} columns: {cols}")
            cur = conn.execute(f"SELECT COUNT(*) FROM {target}")
            print(f"      Row count: {cur.fetchone()[0]}")
            # Sample last 3 messages
            cur = conn.execute(
                f"SELECT thread_id, message_timestamp_ms, is_local_only_message, message_payload "
                f"FROM {target} ORDER BY message_timestamp_ms DESC LIMIT 3"
            )
            rows = cur.fetchall()
            if rows:
                from utils.messenger_database_monitor import _extract_text_from_blob
                print(f"\n      Last 3 messages:")
                for idx, row in enumerate(rows):
                    tid, ts, is_local, payload = row[0], row[1], row[2], row[3]
                    direction = "OUT" if is_local else "IN"
                    text = _extract_text_from_blob(payload) if payload else "(empty)"
                    print(f"        {idx+1}. [{direction}] thread={tid} ts={ts}: {text[:60]}...")
        else:
            print(f"\n[!] Table '{target}' not found. Messenger may have changed schema.")
    finally:
        try:
            os.unlink(local)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
LINE Live Monitor: Poll DB file sizes every 1s, alert when ANY file changes.
Run this, then send a message to LINE - you'll see which files change in real-time.
Usage: uv run python scripts/line_live_monitor.py [DEVICE_ID]
"""
import os
import subprocess
import sys
import time

DB_BASE = "/data/data/jp.naver.line.android/databases"


def run_adb(device_id, *args):
    cmd = ["adb"]
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def get_db_stats(device_id, use_su=False):
    cmd = (
        f"find {DB_BASE} -type f \\( -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' \\) "
        "-exec du -b {} \\; 2>/dev/null"
    )
    if use_su:
        escaped = cmd.replace("'", "'\\''")
        cmd = f"su -c '{escaped}'"
    ok, out = run_adb(device_id, "shell", cmd)
    result = {}
    for line in (out or "").strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) >= 2:
            try:
                result[parts[1].strip()] = int(parts[0])
            except ValueError:
                pass
    return result


def main():
    device_id = os.getenv("DEVICE_ID") or (sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"LINE Live Monitor | Device: {device_id or '(default)'}")
    print("=" * 60)
    print("Polling every 1s. Send a message to LINE now - we'll detect which files change.")
    print("Press Ctrl+C to stop.\n")

    # adb root
    ok, out = run_adb(device_id, "root")
    use_su = True
    if ok and "root" in (out or "").lower() and "cannot" not in (out or "").lower():
        time.sleep(2)
        use_su = False
        print("[OK] adb root active\n")

    prev = {}
    poll_count = 0
    while True:
        try:
            curr = get_db_stats(device_id, use_su=use_su)
            poll_count += 1
            if not curr:
                if poll_count <= 3:
                    print("[!] No DB files found - need root?")
                continue
            if prev:
                changed = []
                all_paths = set(prev.keys()) | set(curr.keys())
                for p in sorted(all_paths):
                    old_sz = prev.get(p, 0)
                    new_sz = curr.get(p, 0)
                    if old_sz != new_sz:
                        delta = new_sz - old_sz
                        sign = "+" if delta > 0 else ""
                        changed.append((p, old_sz, new_sz, delta))
                if changed:
                    ts = time.strftime("%H:%M:%S", time.localtime())
                    print(f"\n>>> CHANGE DETECTED @ {ts} <<<")
                    for path, old_sz, new_sz, delta in changed:
                        name = os.path.basename(path)
                        print(f"  {name}")
                        print(f"    {old_sz} -> {new_sz} ({delta:+d} bytes)")
                    print()
            prev = curr
            time.sleep(1)
        except KeyboardInterrupt:
            print("\n[Stopped]")
            break


if __name__ == "__main__":
    main()

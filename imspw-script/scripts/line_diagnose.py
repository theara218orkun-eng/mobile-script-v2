#!/usr/bin/env python3
"""
LINE DB 诊断脚本：列出所有数据库、表结构、文件大小。
检查 LINE 后台/通知相关配置（我们的配置不会禁用通知，只做放宽）。
用法: uv run python scripts/line_diagnose.py [DEVICE_ID]
"""
import os
import subprocess
import sys
import tempfile

# Add module-core to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(project_root, "module-core", "src"))

DB_BASE = "/data/data/jp.naver.line.android/databases"


def run_adb(device_id, *args):
    cmd = ["adb"]
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def run_shell(device_id, cmd, use_su=True):
    """Run shell command. If use_su, wrap with su -c. Else run directly (after adb root)."""
    if use_su:
        escaped = cmd.replace("'", "'\\''")
        full_cmd = f"su -c '{escaped}'"
    else:
        full_cmd = cmd
    ok, out = run_adb(device_id, "shell", full_cmd)
    return ok, out


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

    # 1b. Try adb root (works on emulator / userdebug builds). If success, no need for su -c.
    use_su = True
    ok_root, out_root = run_adb(device_id, "root")
    if ok_root and "restarting" in (out_root or "").lower():
        import time
        time.sleep(2)  # Wait for adb daemon restart
    if ok_root and "root" in (out_root or "").lower() and "cannot" not in (out_root or "").lower():
        use_su = False
        print("[OK] adb root succeeded, using root shell")
    else:
        print("[*] adb root not available, will use su -c")

    # 2. LINE 通知/后台诊断（我们的配置只做放宽，不会禁用通知）
    print("\n" + "=" * 50)
    print("[LINE 通知/后台诊断] 我们的代码不会禁用 LINE 通知，只做放宽")
    print("=" * 50)
    pkg = "jp.naver.line.android"
    # 2a. Doze whitelist
    ok_w, out_w = run_adb(device_id, "shell", "dumpsys deviceidle whitelist 2>/dev/null")
    in_whitelist = pkg in (out_w or "")
    print(f"  Doze whitelist: {'[OK] 已加入' if in_whitelist else '[!] 未加入 (需 root 或 adb root)'}")
    # 2b. Standby bucket (5=RESTRICTED 限制最严，0=ACTIVE 正常)
    ok_s, out_s = run_adb(device_id, "shell", f"am get-standby-bucket {pkg} 2>/dev/null")
    bucket = (out_s or "").strip().lower()
    is_active = "active" in bucket or bucket == "0"
    print(f"  Standby bucket: {bucket or '(unknown)'} {'[OK] active' if is_active else '[!] 非 active (bucket 5=限制最严)'}")
    if not is_active:
        print("  [修复] 尝试设置 standby bucket 为 active...")
        run_adb(device_id, "shell", f"am set-standby-bucket {pkg} active")
        ok_s2, out_s2 = run_adb(device_id, "shell", f"am get-standby-bucket {pkg} 2>/dev/null")
        bucket2 = (out_s2 or "").strip().lower()
        is_active2 = "active" in bucket2 or bucket2 == "0"
        print(f"  Standby bucket (修复后): {bucket2 or '(unknown)'} {'[OK] 已修复' if is_active2 else '[!] 仍非 active'}")
        if not is_active2:
            print("  [手动] 正在打开手机上的「忽略电池优化」界面，请在手机上点「允许」...")
            run_adb(device_id, "shell", f"am start -a android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS -d package:{pkg}")
    # 2c. AppOps RUN_IN_BACKGROUND
    ok_o, out_o = run_adb(device_id, "shell", f"cmd appops get {pkg} RUN_IN_BACKGROUND 2>/dev/null")
    allow_bg = "allow" in (out_o or "").lower()
    print(f"  RUN_IN_BACKGROUND: {'[OK] allow' if allow_bg else '[!] 非 allow'}")
    print("\n  若 LINE 仍收不到通知，请手动检查（LINE 官方建议）：")
    print("  - 设置 > 应用 > LINE > 电池 > 选择「不限制」")
    print("  - 关闭省电模式、自适应电池")
    print("  - 设置 > 应用 > LINE > 移动数据与 Wi‑Fi > 开启后台数据")
    print("  - 勿强制关闭 LINE（会导致推送延迟）")

    # 4. List all DB files with sizes (find + du -b)
    cmd = (
        f"find {DB_BASE} -type f \\( -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' \\) "
        "-exec du -b {} \\; 2>/dev/null"
    )
    ok, out = run_shell(device_id, cmd, use_su=use_su)
    print(f"\n[DB files with sizes] (run again after new message to see which changed):")
    if not ok or "Permission denied" in (out or ""):
        print("  [!] Need root to read /data/data/jp.naver.line.android/")
        print("      Try: adb root  (emulator/userdebug)")
        print("      Or:  setenforce 0  (on rooted device, SELinux permissive)")
        print("      Or:  Magisk + su")
        return 1
    lines = [l.strip() for l in (out or "").split("\n") if l.strip()]
    for line in sorted(lines, key=lambda x: x.split()[-1] if len(x.split()) >= 2 else x):
        parts = line.split(None, 1)
        if len(parts) >= 2:
            size, path = int(parts[0]), parts[1]
            print(f"  {size:>12} {path}")

    # 5. Find all .db (main files only)
    ok, out = run_shell(device_id, f"find {DB_BASE} -type f -name '*.db' 2>/dev/null", use_su=use_su)
    db_files = [p.strip() for p in (out or "").split("\n") if p.strip() and p.strip().endswith(".db")]
    db_files = [p for p in db_files if "-journal" not in p]
    if not db_files:
        print(f"\n[FAIL] No .db files found")
        return 1
    print(f"\n[OK] Main DB files: {db_files}")

    # 6. For each DB, list tables
    for remote in db_files[:10]:  # Limit to first 10
        basename = os.path.basename(remote)
        tmp_remote = f"/sdcard/line_diag_{basename.replace('.', '_')}.db"
        ok, _ = run_shell(device_id, f'cp "{remote}" {tmp_remote} 2>/dev/null', use_su=use_su)
        if not ok:
            continue
        fd, local = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ok, _ = run_adb(device_id, "pull", tmp_remote, local)
            run_adb(device_id, "shell", "rm", "-f", tmp_remote)
            if not ok:
                continue
            import sqlite3
            conn = sqlite3.connect(local)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [r[0] for r in cur.fetchall()]
            print(f"\n--- {basename} ---")
            print(f"  Tables: {tables[:25]}{'...' if len(tables) > 25 else ''}")

            # chat_history in naver_line
            if "chat_history" in tables and "naver_line" in basename:
                cur = conn.execute("PRAGMA table_info(chat_history)")
                cols = [r[1] for r in cur.fetchall()]
                print(f"  [chat_history] columns: {cols}")
                cur = conn.execute("SELECT COUNT(*) FROM chat_history")
                print(f"  [chat_history] row count: {cur.fetchone()[0]}")
                cur = conn.execute(
                    "SELECT type, content, created_time, from_mid FROM chat_history "
                    "WHERE type=1 ORDER BY created_time DESC LIMIT 3"
                )
                rows = cur.fetchall()
                if rows:
                    print(f"  Last 3 (type=1):")
                    for idx, row in enumerate(rows):
                        t, content, ts, from_mid = row[0], row[1], row[2], row[3]
                        direction = "IN" if (from_mid and from_mid != "0") else "OUT"
                        print(f"    {idx+1}. [{direction}] from={from_mid} ts={ts}: {(content or '')[:50]}...")

            # Tables that might contain "message" or "notification" (candidate for push-first-write)
            msg_like = [t for t in tables if any(x in t.lower() for x in ["message", "chat", "notif", "push", "sync"])]
            if msg_like:
                print(f"  [Candidate tables for message data]: {msg_like}")
            conn.close()
        except Exception as e:
            print(f"  Error: {e}")
        finally:
            try:
                os.unlink(local)
            except OSError:
                pass

    print("\n[Tip] Send a test message to LINE, then run this script again to see which file size changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

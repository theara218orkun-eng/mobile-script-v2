"""
Scheduled phone restart + frida-server auto-start.
Runs at configured time (e.g. 00:00 daily), reboots device, waits for boot, starts frida-server.
"""
import os
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional

from aid_utils import logger

# Config from env
PHONE_RESTART_HOUR = int(os.getenv("PHONE_RESTART_HOUR", "0"))  # 0=midnight, 12=noon
PHONE_RESTART_MINUTE = int(os.getenv("PHONE_RESTART_MINUTE", "0"))
FRIDA_SERVER_PATH = os.getenv("FRIDA_SERVER_PATH", "/data/local/tmp/frida-server")
BOOT_WAIT_SEC = int(os.getenv("PHONE_BOOT_WAIT_SEC", "90"))  # Wait after reboot before starting frida


def _run_adb(device_id: Optional[str], *args) -> tuple[bool, str]:
    """Run adb command. Returns (success, output)."""
    cmd = ["adb"]
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        out = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, out.strip()
    except Exception as e:
        return False, str(e)


def _start_frida_server(device_id: Optional[str]) -> bool:
    """Start frida-server on device via adb."""
    # Try: su -c 'frida-server -D' (-D = daemon mode, backgrounds automatically)
    ok, out = _run_adb(device_id, "shell", f"su -c '{FRIDA_SERVER_PATH} -D'")
    if ok:
        logger.info(f"[RestartScheduler] Frida-server started on {device_id or 'device'}")
        return True
    # Fallback: without su (if adb root available)
    ok2, _ = _run_adb(device_id, "shell", f"{FRIDA_SERVER_PATH} -D")
    if ok2:
        logger.info("[RestartScheduler] Frida-server started (no su)")
        return True
    logger.error(f"[RestartScheduler] Failed to start frida-server: {out}")
    return False


def _do_restart_and_frida(device_id: Optional[str]) -> None:
    """Reboot device, wait for boot, start frida-server."""
    logger.info(f"[RestartScheduler] Initiating phone restart at {datetime.now().isoformat()}")
    ok, out = _run_adb(device_id, "reboot")
    if not ok:
        logger.error(f"[RestartScheduler] Reboot failed: {out}")
        return
    logger.info(f"[RestartScheduler] Reboot sent. Waiting {BOOT_WAIT_SEC}s for boot...")
    time.sleep(BOOT_WAIT_SEC)
    # Wait for device
    _run_adb(device_id, "wait-for-device")
    time.sleep(15)  # Extra for system init
    _start_frida_server(device_id)
    logger.info("[RestartScheduler] Done. DeviceSupervisor will reconnect automatically.")


def run_scheduler(device_id: Optional[str], stop_event: threading.Event) -> None:
    """
    Background loop: at PHONE_RESTART_HOUR:PHONE_RESTART_MINUTE daily, reboot + start frida.
    """
    if PHONE_RESTART_HOUR < 0 or PHONE_RESTART_HOUR > 23:
        logger.warning(f"[RestartScheduler] PHONE_RESTART_HOUR={PHONE_RESTART_HOUR} invalid, disabled")
        return
    logger.info(f"[RestartScheduler] Scheduled daily at {PHONE_RESTART_HOUR:02d}:{PHONE_RESTART_MINUTE:02d}")
    last_run_date = None
    while not stop_event.is_set():
        now = datetime.now()
        if now.hour == PHONE_RESTART_HOUR and now.minute == PHONE_RESTART_MINUTE:
            if last_run_date != now.date():
                last_run_date = now.date()
                _do_restart_and_frida(device_id)
        stop_event.wait(30)  # Check every 30s

"""
DeviceWorker: Frida script injection for multiple IM apps (WhatsApp, LINE, Messenger, etc.)
Based on reference: spawn -> attach -> load -> resume. Each worker handles one package.
Multiple workers on same device: use device-level lock to serialize Frida operations (spawn/attach).
"""
import os
import subprocess
import threading
import time
import base64
from typing import Any, Optional, Dict, Set
from queue import Queue

import frida

from aid_utils import logger
from processor.device_processor import get_device_processor
import uiautomator2 as u2
from services.whatsapp_service import whatsapp_service
from services.line_service import line_service
from services.messenger_service import messenger_service

# Attach-only: LINE detects ptrace and exits. Use Frida Gadget (see scripts/patch_line_for_spawn.md) for spawn.
_DEFAULT_ATTACH_ONLY: Set[str] = {"jp.naver.line.android"}
_ATTACH_ONLY_ENV = os.getenv("FRIDA_ATTACH_ONLY_PACKAGES", "")
_ATTACH_ONLY_PACKAGES: Set[str] = (
    {p.strip() for p in _ATTACH_ONLY_ENV.split(",") if p.strip()}
    if _ATTACH_ONLY_ENV
    else _DEFAULT_ATTACH_ONLY
)

ATTACH_ONLY_GLOBAL = os.getenv("frida_attach_only", "").lower() in ("1", "true", "yes")
ATTACH_WAIT_RETRY = 8
SPAWN_WAIT_SECONDS = int(os.getenv("frida_spawn_wait_seconds", "8")) # Spawn: wait after resume before attach (WhatsApp needs time to init)
DEVICE_GONE_SLEEP = int(os.getenv("frida_device_gone_sleep", "30")) # When device is disconnected, back off longer and throttle log spam
DEVICE_GONE_LOG_INTERVAL = int(os.getenv("frida_device_gone_log_interval", "60"))

# Per-device lock: Frida Device is not thread-safe for concurrent spawn/attach
_DEVICE_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()
# Throttle "Process enumeration failed" when device is gone (avoid log spam)
_LAST_ENUM_WARNING: Dict[str, float] = {}
_ENUM_WARNING_LOCK = threading.Lock()


def _sleep_interruptible(stop_event: threading.Event, seconds: float) -> bool:
    """Sleep for up to seconds, return True if stop was requested (caller should exit)."""
    for _ in range(int(seconds)):
        if stop_event.wait(1):
            return True
    return False


def _get_device_lock(device_id: str) -> threading.Lock:
    with _LOCKS_LOCK:
        if device_id not in _DEVICE_LOCKS:
            _DEVICE_LOCKS[device_id] = threading.Lock()
        return _DEVICE_LOCKS[device_id]


def _needs_attach_only(package: str) -> bool:
    return ATTACH_ONLY_GLOBAL or package in _ATTACH_ONLY_PACKAGES


def _find_process(device: Any, package: str) -> Optional[int]:
    """Find PID by package name. On Android, use enumerate_applications (identifier)
    since enumerate_processes returns display name, not package name."""
    try:
        # Method 1: enumerate_applications - identifier = package name, pid when running
        for app in device.enumerate_applications():
            if getattr(app, "identifier", None) == package and getattr(app, "pid", None):
                return app.pid
        # Method 2: Fallback - enumerate_processes (main process name may equal package on some devices)
        for p in device.enumerate_processes():
            if p.name == package or p.name.startswith(package + ":"):
                return p.pid
    except Exception as e:
        err_msg = str(e).lower()
        is_device_gone = any(
            p in err_msg for p in ("device is gone", "unable to connect", "connection refused", "device disconnected")
        )
        do_log = True
        if is_device_gone:
            key = getattr(device, "id", id(device))
            with _ENUM_WARNING_LOCK:
                now = time.time()
                if key in _LAST_ENUM_WARNING and (now - _LAST_ENUM_WARNING[key]) < DEVICE_GONE_LOG_INTERVAL:
                    do_log = False
                else:
                    _LAST_ENUM_WARNING[key] = now
        if do_log:
            logger.warning(f"Process enumeration failed: {e}")
    return None


def decode_message(content: Optional[str]) -> Optional[str]:
    if not content:
        return None
    try:
        return base64.b64decode(content).decode('utf-8')
    except Exception:
        return content


class DeviceWorker(threading.Thread):
    """
    Worker: one thread per device:package. Reference flow: spawn -> attach -> load -> resume.
    """
    def __init__(
        self,
        device: Any,
        bundle: str,
        target_package: str,
        incoming_queue: Queue,
        whatsapp_package_name: str = "com.whatsapp",
        pb_client: Any = None,
        device_id_override: str = None,
    ):
        super().__init__(daemon=True)
        self.device = device
        self.bundle = bundle
        self.target_package = target_package
        self.whatsapp_package_name = whatsapp_package_name
        self.line_package_name = "jp.naver.line.android"
        self.messenger_package_name = "com.facebook.orca"
        self.stop_event = threading.Event()
        self.script: Any = None
        self.session: Any = None
        self.is_ready = False
        self.incoming_queue = incoming_queue
        self.pb_client = pb_client

        processor_id = device_id_override or self.device.id
        self.processor = get_device_processor(processor_id)
        self.outgoing_event = threading.Event()
        self.u2_device = None
        self._last_device_gone_log = 0.0
        self._recovered_from_device_gone = False

        if self.target_package == self.whatsapp_package_name:
            logger.info(f"[{self.device.id}] Initialized worker for WhatsApp")
            self.processor.register_handler("REPLY_WHATSAPP", self._handle_whatsapp_reply_task)
            self.processor.register_handler("REPLY_WHATSAPP_GROUP", self._handle_whatsapp_group_reply_task)
            self.processor.register_handler("REPLY_WHATSAPP_GROUP_BATCH", self._handle_whatsapp_group_reply_batch_task)
        elif self.target_package == self.line_package_name:
            logger.info(f"[{self.device.id}] Initialized worker for LINE")
            self.processor.register_handler("REPLY_LINE", self._handle_line_reply_task)
        elif self.target_package == self.messenger_package_name:
            logger.info(f"[{self.device.id}] Initialized worker for Messenger")
            self.processor.register_handler("REPLY_MESSENGER", self._handle_messenger_reply_task)

    def run(self) -> None:
        worker_node = f"{self.device.id}:{self.target_package}"
        logger.info(f"[{worker_node}] Worker started for {self.device.name} targeting {self.target_package}")

        while not self.stop_event.is_set():
            self.session = None
            self.script = None
            self.is_ready = False

            try:
                spawned_pid = None  # Set only when we spawn (need to resume)
                device_lock = _get_device_lock(self.device.id)
                with device_lock:
                    if _needs_attach_only(self.target_package):
                        pid = _find_process(self.device, self.target_package)
                        if not pid:
                            logger.info(f"[{worker_node}] Attach-only: {self.target_package} not running. Retrying in {ATTACH_WAIT_RETRY}s...")
                            if _sleep_interruptible(self.stop_event, ATTACH_WAIT_RETRY):
                                break
                            continue
                        logger.info(f"[{worker_node}] Found {self.target_package} (pid={pid}). Attaching...")
                        self.session = self.device.attach(pid)
                    else:
                        # Spawn path: spawn -> resume first -> wait -> attach -> load hook
                        # (attach before resume can trigger app anti-tamper; hook after app starts)
                        existing = _find_process(self.device, self.target_package)
                        if existing:
                            try:
                                self.device.kill(existing)
                                if _sleep_interruptible(self.stop_event, 2):
                                    continue
                            except Exception:
                                pass
                        spawned_pid = self.device.spawn([self.target_package])
                        self.device.resume(spawned_pid)
                        logger.info(f"[{worker_node}] Spawned and resumed (pid={spawned_pid}), waiting {SPAWN_WAIT_SECONDS}s for app to start...")
                        if _sleep_interruptible(self.stop_event, SPAWN_WAIT_SECONDS):
                            continue
                        pid = _find_process(self.device, self.target_package)
                        for retry in range(3):
                            if pid:
                                break
                            if self.stop_event.is_set():
                                break
                            logger.info(f"[{worker_node}] Process not ready, retry {retry + 1}/3 in 3s...")
                            if _sleep_interruptible(self.stop_event, 3):
                                break
                            pid = _find_process(self.device, self.target_package)
                        if not pid:
                            raise RuntimeError(f"Process {self.target_package} not found after spawn")
                        self.session = self.device.attach(pid)

                    self.script = self.session.create_script(self.bundle, runtime='v8')
                    self.script.on('message', self.on_message)
                    self.script.load()

                    try:
                        self.script.exports.set_target_package(self.target_package)
                        logger.info(f"[{worker_node}] Script configured for {self.target_package}")
                    except Exception as e:
                        logger.warning(f"[{worker_node}] set_target_package: {e}")

                    self.is_ready = True
                    self.processor.start()

                # After successful respawn from device gone: bring LINE to foreground
                if self._recovered_from_device_gone:
                    self._recovered_from_device_gone = False
                    try:
                        d = self._connect_u2()
                        if d:
                            d.app_start(self.line_package_name, stop=False)
                            logger.info(f"[{worker_node}] LINE brought to foreground after reconnect")
                    except Exception as ex:
                        logger.warning(f"[{worker_node}] Could not bring LINE to foreground: {ex}")

                # Monitor
                while not self.stop_event.is_set():
                    if self.session.is_detached:
                        logger.warning(f"[{worker_node}] Session detached, will re-spawn")
                        break
                    if self.stop_event.wait(1):
                        break

            except Exception as e:
                err_msg = str(e).lower()
                is_device_gone = any(
                    p in err_msg for p in ("device is gone", "unable to connect", "connection refused", "device disconnected")
                )
                if is_device_gone:
                    now = time.time()
                    if now - self._last_device_gone_log >= DEVICE_GONE_LOG_INTERVAL:
                        logger.warning(
                            f"[{worker_node}] Device unavailable ({e}), retrying in {DEVICE_GONE_SLEEP}s..."
                        )
                        self._last_device_gone_log = now
                    if _sleep_interruptible(self.stop_event, DEVICE_GONE_SLEEP):
                        break
                    # Try to get fresh device; if still gone, exit so Supervisor restarts
                    try:
                        self.device = frida.get_device(self.device.id)
                        self._recovered_from_device_gone = True
                        logger.info(f"[{worker_node}] Device reconnected, retrying...")
                    except Exception:
                        logger.warning(f"[{worker_node}] Device still unavailable, exiting for Supervisor restart...")
                        break
                else:
                    logger.error(f"[{worker_node}] [Worker Error] {e}")
                    if not _needs_attach_only(self.target_package):
                        try:
                            self.device.kill(self.target_package)
                        except Exception:
                            pass
                        # "spawn already in progress": Frida needs time to clear state
                        err_lower = str(e).lower()
                        if "spawn already in progress" in err_lower:
                            logger.info(f"[{worker_node}] Waiting 8s for spawn state to clear...")
                            if _sleep_interruptible(self.stop_event, 8):
                                break
                        else:
                            if _sleep_interruptible(self.stop_event, 2):
                                break
                    else:
                        if _sleep_interruptible(self.stop_event, 2):
                            break
            finally:
                if self.session:
                    try:
                        self.session.detach()
                    except Exception:
                        pass

        logger.info(f"[{worker_node}] Worker stopped.")

    def on_message(self, message: Dict[str, Any], data: Any) -> None:
        if message['type'] == 'send':
            payload = message['payload']
            logger.debug(f"[{self.device.id}] [{self.target_package}] {payload}")
            if isinstance(payload, dict):
                msg_type = payload.get('type')
                if msg_type == 'INCOMING':
                    self._handle_incoming(payload)
                elif msg_type == 'OUTGOING':
                    self.outgoing_event.set()
        elif message['type'] == 'error':
            logger.error(f"[{self.device.id}] [ERR] {message.get('stack', 'Unknown error')}")
        else:
            logger.debug(f"[{self.device.id}] [FRIDA] {message.get('payload', message)}")

    def _handle_incoming(self, payload: Dict[str, Any]) -> None:
        try:
            content = payload.get('content')
            if content:
                self.incoming_queue.put({
                    "device_id": self.device.id,
                    "package": self.target_package,
                    "task": lambda: None,
                    "desc": f"Incoming from {self.target_package}",
                    "payload": payload,
                })
        except Exception as e:
            logger.error(f"[{self.device.id}] [Decode Error] {e}")

    def _connect_u2(self):
        if self.u2_device:
            return self.u2_device
        try:
            self.u2_device = u2.connect(self.processor.device_id)
            return self.u2_device
        except Exception as e:
            logger.error(f"[{self.device.id}] [U2] Connection failed: {e}")
            self.u2_device = None
            return None

    def _handle_whatsapp_reply_task(self, payload: Dict[str, Any]) -> None:
        try:
            phone = payload.get("phone")
            message = payload.get("message")
            logger.info(f"[{self.device.id}] [Task] Sending WhatsApp to {phone}")
            # Launch WhatsApp via intent first (ensures app in foreground)
            try:
                cmd = ["adb", "-s", self.processor.device_id, "shell", "am", "start", "-n", "com.whatsapp/.Main"]
                subprocess.run(cmd, capture_output=True, timeout=5)
                time.sleep(2)
            except Exception as e:
                logger.warning(f"[{self.device.id}] Intent launch: {e}")
            if self.script and self.is_ready:
                self.outgoing_event.clear()
                if hasattr(self.script, 'exports_sync'):
                    self.script.exports_sync.wa_send(phone, message)
                else:
                    self.script.exports.wa_send(phone, message)
                if not self.outgoing_event.wait(timeout=10):
                    logger.warning(f"[{self.device.id}] [Task] OUTGOING timeout")
            else:
                raise RuntimeError("Script not ready")
        except Exception as e:
            logger.error(f"[{self.device.id}] Handler Error: {e}")
            raise

    def _handle_whatsapp_group_reply_task(self, payload: Dict[str, Any]) -> None:
        try:
            # Launch WhatsApp via intent first
            try:
                subprocess.run(
                    ["adb", "-s", self.processor.device_id, "shell", "am", "start", "-n", "com.whatsapp/.Main"],
                    capture_output=True, timeout=5,
                )
                time.sleep(2)
            except Exception as e:
                logger.warning(f"[{self.device.id}] Intent launch: {e}")
            d = self._connect_u2()
            whatsapp_service.send_message(
                device_ip=self.processor.device_id,
                group_name=payload.get("group_name"),
                message=payload.get("message"),
                d=d,
            )
        except Exception as e:
            logger.error(f"[{self.device.id}] Group Handler Error: {e}")
            self.u2_device = None
            raise

    def _handle_whatsapp_group_reply_batch_task(self, payload: Dict[str, Any]) -> None:
        try:
            d = self._connect_u2()
            whatsapp_service.send_messages(
                device_ip=self.processor.device_id,
                group_name=payload.get("group_name"),
                messages=payload.get("messages", []),
                d=d,
            )
        except Exception as e:
            logger.error(f"[{self.device.id}] Batch Handler Error: {e}")
            self.u2_device = None
            raise

    def _handle_messenger_reply_task(self, payload: Dict[str, Any]) -> None:
        try:
            messenger_service.send_message(
                device_ip=self.processor.device_id,
                group_name=payload.get("group_name"),
                message=payload.get("message"),
            )
        except Exception as e:
            logger.error(f"[{self.device.id}] Messenger Handler Error: {e}")
            raise

    def _handle_line_reply_task(self, payload: Dict[str, Any]) -> None:
        try:
            # Launch LINE via intent first (use line_service from core, not Frida)
            try:
                subprocess.run(
                    ["adb", "-s", self.processor.device_id, "shell", "am", "start", "-n", "jp.naver.line.android/.SplashActivity"],
                    capture_output=True, timeout=5,
                )
                time.sleep(2)
            except Exception as e:
                logger.warning(f"[{self.device.id}] LINE intent launch: {e}")
            d = self._connect_u2()
            line_service.send_message(
                device_ip=self.processor.device_id,
                group_name=payload.get("group_name"),
                message=payload.get("message"),
                d=d,
            )
        except Exception as e:
            logger.error(f"[{self.device.id}] LINE Handler Error: {e}")
            self.u2_device = None
            raise

    def stop(self) -> None:
        self.stop_event.set()

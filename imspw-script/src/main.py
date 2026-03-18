import sys
import os
import time
import queue
import threading
import base64
import hashlib
from pydantic import BaseModel, Field
from typing import Optional
from dotenv import load_dotenv

# Dedup: (key -> timestamp). Same message within DEDUP_SECONDS = skip (prevents queue flood).
_DEDUP_SECONDS = 10
_dedup_cache: dict = {}
_dedup_lock = threading.Lock()

# Recent replies: (device_id, platform, chat_uuid, content_hash) -> timestamp. Prevent reply loops.
_recent_replies: dict = {}
_recent_replies_lock = threading.Lock()
_recent_replies_TTL = 120  # seconds

# Load environment variables
load_dotenv()

# Add module-core/src to sys.path to allow direct imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# Ensure tasks.db uses project root (same as truncate script)
os.environ.setdefault("TASKS_DB_PATH", os.path.join(project_root, "tasks.db"))
os.environ.setdefault("CONTACTS_DB_PATH", os.path.join(project_root, "contacts.db"))
module_core_path = os.path.join(project_root, 'module-core', 'src')
if module_core_path not in sys.path:
    sys.path.append(module_core_path)

try:
    from frida_core.device_worker import _ATTACH_ONLY_PACKAGES, ATTACH_ONLY_GLOBAL
    from frida_core.device_supervisor import DeviceSupervisor
    from clients.processor_client import ProcessorClient
    from processor.device_processor import get_device_processor
    from services.messenger_service import messenger_service
    from services.line_service import line_service
    from services.whatsapp_service import whatsapp_service
    from services.telegram_service import telegram_service, run_monitor as run_telegram_monitor
    from utils.phone_restart_scheduler import run_scheduler
    from utils.messenger_database_monitor import run_monitor as run_messenger_monitor
    from utils.line_database_monitor import run_monitor as run_line_monitor
    import uiautomator2 as u2
    from aid_utils import logger
except ImportError as e:
    print(f"Could NOT import from module-core: {e}")
    sys.exit(1)

# 可选：callback_server 和 contact_core（module-core 可能尚未包含）
try:
    from server.callback_server import start_callback_server_thread
except ImportError:
    start_callback_server_thread = None  # 无 callback 接收能力

try:
    from db.contact_core import save_incoming_contact
except ImportError:
    def save_incoming_contact(*args, **kwargs):
        pass  # 无联系人持久化

class AppConfig(BaseModel):
    app_name: str = Field(default_factory=lambda: os.getenv("APP_NAME", "Line IMSPW"), description="IMSPW Application")
    version: str = Field(default_factory=lambda: os.getenv("APP_VERSION", "0.1.0"), description="Version of the application")
    target_packages: str = Field(default_factory=lambda: os.getenv("TARGET_PACKAGES", "jp.naver.line.android"), description="Comma-separated list of packages or app names (line, whatsapp, etc.)")
    device_id: Optional[str] = Field(default_factory=lambda: os.getenv("DEVICE_ID"), description="Device serial/IP. If None, uses first USB device.")
    processor_url: str = Field(default_factory=lambda: os.getenv("PROCESSOR_URL") or os.getenv("processor_url") or "", description="URL to post incoming messages to")
    processor_api_secret: Optional[str] = Field(default_factory=lambda: os.getenv("PROCESSOR_API_SECRET") or os.getenv("processor_api_secret"), description="API Secret for processor authentication")
    phone_restart_hour: int = Field(default_factory=lambda: int(os.getenv("PHONE_RESTART_HOUR", "-1")), description="Daily restart hour (0-23, -1=disabled)")

# App name -> package mapping for TARGET_APPS config (e.g. TARGET_APPS=line,whatsapp)
APPS = {
    "line": "jp.naver.line.android",
    "whatsapp": "com.whatsapp",
    "messenger": "com.facebook.orca",
    "zalo": "com.zing.zalo",
    "telegram": "org.telegram.messenger",
}


def get_platform_name(package_name: str) -> str:
    """Maps package name to simplified platform name."""
    if package_name == "jp.naver.line.android":
        return "line"
    elif package_name == "com.whatsapp":
        return "whatsapp"
    elif package_name == "com.facebook.orca":
        return "facebook"
    elif package_name == "com.zing.zalo":
        return "zalo"
    elif package_name == "org.telegram.messenger":
        return "telegram"
    return package_name


def resolve_packages(config_value: str) -> list[str]:
    """Resolve TARGET_APPS or TARGET_PACKAGES to list of package names."""
    items = [x.strip() for x in config_value.split(",") if x.strip()]
    packages = []
    for item in items:
        if item in APPS:
            packages.append(APPS[item])
        else:
            packages.append(item)  # Assume it's already a package name
    return packages

def message_processor(msg_queue: queue.Queue, processor_client: ProcessorClient):
    """
    Processes incoming messages: send to processor, if response has 'message' send back to user.
    Uses processor queue (add_task) - lock ensures one reply at a time, queue handles ordering.
    """
    logger.info("[*] Message Processor Started")

    while True:
        try:
            item = msg_queue.get()
            if item is None:
                break

            payload = item.get("payload", {})
            device_id = item.get("device_id")
            package = item.get("package")

            if payload.get("type") == "INCOMING":
                user_info = payload.get("user_info", {})
                chat = payload.get("chat", {})
                content = payload.get("content", "")
                username = user_info.get("username", "") or user_info.get("phone", "")
                is_group = payload.get("is_group", False)
                media_type = payload.get("media_type", "")
                media_url = payload.get("media_url", "")
                
                # Check if this is an image message
                is_incoming_image = (media_type == "image") or (media_url and media_url.strip() != "")
                
                try:
                    if is_incoming_image:
                        display_content = f"[Image] {media_url[:50] if media_url else ''}"
                    else:
                        display_content = base64.b64decode(content).decode("utf-8") if content else "(empty)"
                except Exception:
                    display_content = str(content)[:80] + ("..." if len(str(content)) > 80 else "")
                display_content = display_content.replace("\n", " ").replace("\r", " ").strip()

                # Dedup: same chat+content within DEDUP_SECONDS = skip (prevents queue flood)
                chat_id = chat.get("uuid") or user_info.get("phone", "") or user_info.get("uuid", "")
                dedup_key = (device_id or "", package or "", chat_id, hashlib.sha256((content or "").encode()).hexdigest())
                now = time.time()
                with _dedup_lock:
                    if dedup_key in _dedup_cache and (now - _dedup_cache[dedup_key]) < _DEDUP_SECONDS:
                        continue
                    _dedup_cache[dedup_key] = now
                    if len(_dedup_cache) > 500:
                        cutoff = now - _DEDUP_SECONDS
                        for k in list(_dedup_cache.keys()):
                            if _dedup_cache[k] <= cutoff:
                                del _dedup_cache[k]

                try:
                    save_incoming_contact(package, payload)
                except Exception as e:
                    logger.debug(f"[contact_core] save skipped: {e}")

                if is_incoming_image:
                    print(f"[INCOMING IMAGE] {package} | {username}: {media_url[:60]}{'...' if len(media_url or '') > 60 else ''}")
                else:
                    print(f"[INCOMING] {package} | {username}: {display_content[:80]}{'...' if len(display_content) > 80 else ''}")

                payload["platform"] = get_platform_name(package)
                payload["service"] = os.getenv("service_name")
                payload["device_id"] = device_id

                # Send to processor
                resp = processor_client.send_message(payload)

                if resp:
                    reply_msg = resp.get("message")
                    reply_image = resp.get("image")
                    
                    # Skip if no reply (backend may have skipped due to loop prevention)
                    if not reply_msg and not reply_image:
                        logger.debug(f"[{device_id}] [Reply skipped] Backend returned no reply")
                        continue

                    # Auto-reply with image for incoming images (if no explicit reply_image, use default)
                    auto_reply_image_for_images = os.getenv("AUTO_REPLY_IMAGE_FOR_IMAGES", "0").lower() in ("1", "true", "yes")
                    default_reply_image_url = os.getenv("DEFAULT_REPLY_IMAGE_URL", "")

                    if is_incoming_image and auto_reply_image_for_images and not reply_image and default_reply_image_url:
                        reply_image = default_reply_image_url
                        if not reply_msg:
                            reply_msg = resp.get("image_caption", "Thanks for the image!")

                    proc = get_device_processor(device_id)
                    proc.start()

                    if package == "com.whatsapp":
                        target = chat.get("name") or username
                        phone = user_info.get("phone", "")

                        if reply_image:
                            proc.add_task("REPLY_WHATSAPP_IMAGE", {
                                "target": target,
                                "phone": phone,
                                "image_url": reply_image,
                                "caption": reply_msg or ""
                            })
                            logger.info(f"[{device_id}] [Image reply queued] WhatsApp: {reply_image}")
                        elif reply_msg:
                            if is_group:
                                proc.add_task("REPLY_WHATSAPP_GROUP", {"group_name": target, "message": reply_msg})
                            else:
                                proc.add_task("REPLY_WHATSAPP", {"phone": phone, "message": reply_msg})
                            logger.info(f"[{device_id}] [Reply queued] WhatsApp: {reply_msg[:50]}...")
                    elif package == "jp.naver.line.android":
                        group_name = chat.get("name") or username or chat.get("uuid", "")
                        chat_id = chat.get("uuid", "")

                        if reply_image:
                            proc.add_task("REPLY_LINE_IMAGE", {
                                "group_name": group_name,
                                "chat_id": chat_id,
                                "image_url": reply_image,
                                "caption": reply_msg or ""
                            })
                            logger.info(f"[{device_id}] [Image reply queued] LINE: {reply_image}")
                        elif reply_msg:
                            proc.add_task("REPLY_LINE", {"group_name": group_name, "chat_id": chat_id, "message": reply_msg})
                            logger.info(f"[{device_id}] [Reply queued] LINE: {reply_msg[:50]}...")
                    elif package == "com.facebook.orca":
                        thread_id = chat.get("uuid") or user_info.get("uuid", "")

                        if reply_image:
                            proc.add_task("REPLY_MESSENGER_IMAGE", {
                                "group_name": thread_id,
                                "image_url": reply_image,
                                "caption": reply_msg or ""
                            })
                            logger.info(f"[{device_id}] [Image reply queued] Messenger: {reply_image}")
                        elif reply_msg:
                            proc.add_task("REPLY_MESSENGER", {"group_name": thread_id, "message": reply_msg})
                            logger.info(f"[{device_id}] [Reply queued] Messenger: {reply_msg[:50]}...")
                    elif package == "org.telegram.messenger":
                        chat_uuid = chat.get("uuid") or user_info.get("uuid", "")

                        if reply_image:
                            proc.add_task("REPLY_TELEGRAM_IMAGE", {
                                "entity": chat_uuid,
                                "image_url": reply_image,
                                "caption": reply_msg or ""
                            })
                            logger.info(f"[{device_id}] [Image reply queued] Telegram: {reply_image}")
                        elif reply_msg:
                            proc.add_task("REPLY_TELEGRAM", {"entity": chat_uuid, "message": reply_msg})
                            logger.info(f"[{device_id}] [Reply queued] Telegram: {reply_msg[:50]}...")
                    else:
                        logger.warning(f"Unknown package {package} for reply")

        except Exception as e:
            logger.error(f"Error in message processor: {e}")
        finally:
            msg_queue.task_done()

import requests

def download_and_push_image(device_id: str, image_url: str) -> Optional[str]:
    """Downloads an image from a URL and pushes it to the device's temporary storage."""
    try:
        response = requests.get(image_url, timeout=15)
        if response.status_code == 200:
            local_tmp = os.path.join(project_root, "tmp_reply_image.jpg")
            with open(local_tmp, "wb") as f:
                f.write(response.content)
            
            # Push to phone
            device = u2.connect(device_id)
            remote_path = "/sdcard/Download/tmp_reply_image.jpg"
            device.push(local_tmp, remote_path)
            return remote_path
    except Exception as e:
        logger.error(f"Failed to download/push image: {e}")
    return None

def main():
    config = AppConfig()
    package_list = resolve_packages(config.target_packages)

    print(f"Starting {config.app_name} v{config.version}")
    print(f"Target Packages: {', '.join(package_list)}")

    attach_only_pkgs = [p for p in package_list if ATTACH_ONLY_GLOBAL or p in _ATTACH_ONLY_PACKAGES]
    if attach_only_pkgs:
        print(f"  [Attach-only] {', '.join(attach_only_pkgs)} - open these apps first, then run.")
    print(f"  [Mode] LINE + Messenger: DB monitor. WhatsApp: Frida.")

    try:
        if config.device_id:
            logger.info(f"Connecting to device {config.device_id}...")
            device = u2.connect(config.device_id)
            frida_device_id = config.device_id
        else:
            logger.info("Connecting to first available USB device...")
            device = u2.connect_usb()
            frida_device_id = device.serial
            logger.info(f"Using device serial for Frida: {frida_device_id}")
            
        logger.info(f"Connected to {device.info.get('marketingName', 'Device')} ({device.serial})")
    except Exception as e:
        logger.error(f"Failed to connect to device: {e}")
        return

    incoming_queue = queue.Queue()
    
    # Initialize Processor Client
    processor_client = ProcessorClient(
        api_url=config.processor_url,
        api_secret=config.processor_api_secret
    )
    
    processor_thread = threading.Thread(target=message_processor, args=(incoming_queue, processor_client), daemon=True)
    processor_thread.start()

    # LINE + Messenger: DB monitor. WhatsApp: Frida only.
    line_use_db_poll = os.getenv("LINE_USE_DB_POLL", "1").lower() in ("1", "true", "yes")
    messenger_use_db_poll = os.getenv("MESSENGER_USE_DB_POLL", "1").lower() in ("1", "true", "yes")

    line_stop = threading.Event()
    messenger_stop = threading.Event()
    telegram_stop = threading.Event()

    proc = get_device_processor(frida_device_id)
    proc.start()

    # LINE: DB monitor only
    if "jp.naver.line.android" in package_list and line_use_db_poll:
        proc.register_handler("REPLY_LINE", lambda p: line_service.send_message(
            frida_device_id, p.get("group_name", ""), p.get("message", ""), chat_id=p.get("chat_id")
        ))
        
        def handle_line_image(p):
            remote_path = download_and_push_image(frida_device_id, p.get("image_url"))
            if remote_path:
                line_service.send_image(
                    frida_device_id, 
                    p.get("group_name", ""), 
                    remote_path, 
                    p.get("caption", "")
                )
        proc.register_handler("REPLY_LINE_IMAGE", handle_line_image)

        threading.Thread(
            target=run_line_monitor,
            args=(frida_device_id, incoming_queue, line_stop),
            daemon=True,
            name="LineDBMonitor",
        ).start()
        logger.info("[*] LINE DB Monitor started")

    # Messenger: DB monitor only
    if "com.facebook.orca" in package_list and messenger_use_db_poll:
        proc.register_handler("REPLY_MESSENGER", lambda p: messenger_service.send_message(
            frida_device_id, p.get("group_name", ""), p.get("message", "")
        ))
        
        def handle_messenger_image(p):
            remote_path = download_and_push_image(frida_device_id, p.get("image_url"))
            if remote_path:
                messenger_service.send_image(
                    frida_device_id, 
                    p.get("group_name", ""), 
                    remote_path, 
                    p.get("caption", "")
                )
        proc.register_handler("REPLY_MESSENGER_IMAGE", handle_messenger_image)

        mon_thread = threading.Thread(
            target=run_messenger_monitor,
            args=(frida_device_id, incoming_queue, messenger_stop),
            daemon=True,
            name="MessengerDBMonitor",
        )
        mon_thread.start()
        logger.info("[*] Messenger DB Monitor started")

    # Telegram: MTProto monitor only
    if "org.telegram.messenger" in package_list:
        proc.register_handler("REPLY_TELEGRAM", lambda p: telegram_service.send_message(
            p.get("entity", ""), p.get("message", "")
        ))

        def handle_tg_image(p):
            # For Telegram, we don't need to push to phone, just download locally
            try:
                response = requests.get(p.get("image_url"), timeout=15)
                if response.status_code == 200:
                    local_path = os.path.join(project_root, f"tg_reply_{int(time.time())}.jpg")
                    with open(local_path, "wb") as f:
                        f.write(response.content)
                    telegram_service.send_image(p.get("entity"), local_path, caption=p.get("caption", ""))
                    os.unlink(local_path)
            except Exception as e:
                logger.error(f"Failed to send Telegram image: {e}")
        proc.register_handler("REPLY_TELEGRAM_IMAGE", handle_tg_image)

        threading.Thread(
            target=run_telegram_monitor,
            args=(frida_device_id, incoming_queue, telegram_stop),
            daemon=True,
            name="TelegramMonitor",
        ).start()
        logger.info("[*] Telegram MTProto Monitor started")

    # WhatsApp Reply Handlers
    if "com.whatsapp" in package_list:
        proc.register_handler("REPLY_WHATSAPP", lambda p: whatsapp_service.send_message(
            frida_device_id, p.get("phone", ""), p.get("message", "")
        ))
        proc.register_handler("REPLY_WHATSAPP_GROUP", lambda p: whatsapp_service.send_message(
            frida_device_id, p.get("group_name", ""), p.get("message", "")
        ))
        def handle_wa_image(p):
            remote_path = download_and_push_image(frida_device_id, p.get("image_url"))
            if remote_path:
                whatsapp_service.send_image(
                    frida_device_id, 
                    p.get("target") or p.get("phone"), 
                    remote_path, 
                    p.get("caption", "")
                )
        proc.register_handler("REPLY_WHATSAPP_IMAGE", handle_wa_image)

    # Create group: runs in background thread per device_id (callback_server), not via processor queue

    # Frida: WhatsApp only (LINE + Messenger use DB monitor)
    frida_packages = [p for p in package_list if p == "com.whatsapp"]

    bundle_content = ""
    if frida_packages:
        script_path = os.path.join(module_core_path, 'hooks', 'agent_bundled.js')
        if not os.path.exists(script_path):
            logger.error(f"Frida script not found at {script_path}")
            return
        with open(script_path, 'r', encoding='utf-8') as f:
            bundle_content = f.read()
    supervisors = []
    restart_stop = threading.Event()
    try:
        for pkg in frida_packages or []:
            logger.info(f"Starting supervisor for {pkg}...")
            supervisor = DeviceSupervisor(
                device_id=frida_device_id,
                package_name=pkg,
                bundle_content=bundle_content,
                incoming_queue=incoming_queue
            )
            supervisor.start()
            supervisors.append(supervisor)
            time.sleep(2)  # Stagger: let first worker finish spawn/attach before next (device lock + init time)
        
        if supervisors:
            logger.info(f"Frida supervisors started ({len(supervisors)}). Press Ctrl+C to stop.")
        elif line_use_db_poll or messenger_use_db_poll:
            logger.info("Running in DB poll mode (no Frida). Press Ctrl+C to stop.")

        # Bring LINE to foreground on first start (Frida may have spawned WhatsApp)
        if "jp.naver.line.android" in package_list:
            time.sleep(3)  # Let Frida spawn finish
            try:
                device.app_start("jp.naver.line.android", stop=False)
                logger.info("[*] LINE brought to foreground")
            except Exception as e:
                logger.warning(f"[*] Could not bring LINE to foreground: {e}")

        # Callback message receiver server (接收外部 POST 回调并转发消息)
        if os.getenv("CALLBACK_SERVER_ENABLED", "1").lower() not in ("0", "false", "no"):
            if start_callback_server_thread:
                start_callback_server_thread()
                logger.info("[*] Callback server started (port from CALLBACK_SERVER_PORT)")
            else:
                logger.warning("[*] Callback server skipped: module-core lacks server.callback_server")

        # Optional: daily phone restart + frida-server auto-start
        restart_stop = threading.Event()
        if config.phone_restart_hour >= 0:
            restart_thread = threading.Thread(
                target=run_scheduler,
                args=(frida_device_id, restart_stop),
                daemon=True,
                name="PhoneRestartScheduler",
            )
            restart_thread.start()
        
        while True:
            time.sleep(1)
            # Monitor supervisors
            all_dead = True
            for s in supervisors:
                if s.is_alive():
                    all_dead = False
                else:
                     logger.warning(f"Supervisor for {s.package_name} is dead.")
            
            if all_dead and len(supervisors) > 0:
                logger.error("All supervisors are dead. Exiting.")
                break
                
    except KeyboardInterrupt:
        logger.info("Stopping...")
        restart_stop.set()
        line_stop.set()
        messenger_stop.set()
        telegram_stop.set()
        for s in supervisors:
            s.stop()
        for s in supervisors:
            s.join()
            
    except Exception as e:
        logger.error(f"Error in main: {e}")
        for s in supervisors:
            s.stop()
            s.join()

if __name__ == "__main__":
    main()

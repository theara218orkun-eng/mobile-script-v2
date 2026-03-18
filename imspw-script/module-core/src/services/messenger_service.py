"""
MessengerService: send messages via Deep Link + uiautomator2.
Uses fb-messenger://user-thread/{userId} to open chat, then u2 for input and send.
"""
import subprocess
import time
import threading
import logging
from typing import Optional

import uiautomator2 as u2

from services.im_service import IMService

logger = logging.getLogger(__name__)

# Recent-sent cache: (device_id, thread_id, content) -> timestamp. Used to skip echo in DB monitor.
_RECENT_SENT: dict = {}
_RECENT_SENT_LOCK = threading.Lock()
_RECENT_SENT_TTL = 90  # seconds


def record_sent(device_id: Optional[str], thread_id: str, content: str) -> None:
    """Record that we just sent this message (so monitor can skip it as echo)."""
    key = (device_id or "", thread_id, content)
    with _RECENT_SENT_LOCK:
        _RECENT_SENT[key] = time.time()
        # Prune old entries
        cutoff = time.time() - _RECENT_SENT_TTL
        for k in list(_RECENT_SENT.keys()):
            if _RECENT_SENT[k] < cutoff:
                del _RECENT_SENT[k]


def was_just_sent(device_id: Optional[str], thread_id: str, content: str) -> bool:
    """True if we sent this exact message to this thread recently (within TTL)."""
    key = (device_id or "", thread_id, content)
    with _RECENT_SENT_LOCK:
        ts = _RECENT_SENT.get(key)
        if ts is None:
            return False
        if time.time() - ts > _RECENT_SENT_TTL:
            del _RECENT_SENT[key]
            return False
        return True


def _open_messenger_chat(device_id: Optional[str], user_id: str) -> bool:
    """Open Messenger chat via Deep Link."""
    cmd = ["adb"]
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", f"fb-messenger://user-thread/{user_id}"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            logger.warning(f"[{device_id}] Deep Link failed: {r.stderr}")
            return False
        time.sleep(3)
        return True
    except Exception as e:
        logger.warning(f"[{device_id}] Deep Link error: {e}")
        return False


def _dismiss_accept_popup(d, wait_after_open: float = 1.5) -> None:
    """
    Dismiss 'Accept' / 'Accept request' popup if present, so message input is visible.
    Block/delete the popup: click Accept, then Accept request if shown; only then paste & send.
    """
    time.sleep(wait_after_open)
    # 1) Click "Accept" if exists (exact text, common button label)
    for sel in [{"text": "Accept"}, {"textContains": "Accept"}, {"description": "Accept"}]:
        try:
            el = d(**sel)
            if el.exists and el.wait(timeout=2):
                logger.info("[MessengerService] Clicking Accept popup")
                el.click()
                time.sleep(1)
                break
        except Exception:
            pass
    # 2) Click "Accept request" if exists
    for sel in [
        {"text": "Accept request"},
        {"textContains": "Accept request"},
        {"description": "Accept request"},
    ]:
        try:
            el = d(**sel)
            if el.exists and el.wait(timeout=2):
                logger.info("[MessengerService] Clicking Accept request")
                el.click()
                time.sleep(1)
                break
        except Exception:
            pass
    time.sleep(0.5)


def _send_text_u2(d, text: str) -> bool:
    """Type and send text using uiautomator2."""
    _dismiss_accept_popup(d)
    input_selectors = [
        {"resourceId": "com.facebook.orca:id/input"},
        {"resourceId": "com.facebook.orca:id/input_text"},
        {"className": "android.widget.EditText"},
    ]
    message_input = None
    for sel in input_selectors:
        if d(**sel).exists:
            message_input = d(**sel)
            break
    if not message_input or not message_input.wait(timeout=5):
        logger.warning("[MessengerService] Message input not found")
        return False
    message_input.click()
    time.sleep(0.5)
    message_input.set_text(text)
    time.sleep(0.5)
    send_btn = None
    for sel in [{"description": "Send"}, {"description": "Send message"}, {"text": "Send"}, {"resourceId": "com.facebook.orca:id/send_button"}]:
        btn = d(**sel)
        if btn.exists:
            send_btn = btn
            break
    if not send_btn:
        time.sleep(1)
        for sel in [{"description": "Send"}, {"description": "Send message"}, {"text": "Send"}]:
            btn = d(**sel)
            if btn.exists:
                send_btn = btn
                break
    if send_btn and send_btn.exists:
        send_btn.click()
        return True
    logger.warning("[MessengerService] Send button not found")
    return False


class MessengerService(IMService):
    def __init__(self):
        self.package_name = "com.facebook.orca"

    def connect_device(self, device_ip: str):
        try:
            logger.info(f"[{device_ip}] [MessengerService] Connecting to u2...")
            return u2.connect(device_ip)
        except Exception as e:
            logger.error(f"[{device_ip}] [MessengerService] Connect failed: {e}")
            raise

    def send_message(self, device_ip: str, group_name: str, message: str, d=None):
        """group_name = thread_id (user_id) for Messenger."""
        self.send_messages(device_ip, group_name, [message], d=d)

    def send_messages(self, device_ip: str, group_name: str, messages: list[str], d=None):
        """
        Send messages to Messenger thread.
        group_name = thread_id (user_id from user_info.uuid).
        """
        thread_id = group_name
        logger.info(f"[{device_ip}] [MessengerService] Sending to thread {thread_id}")
        if not _open_messenger_chat(device_ip, thread_id):
            raise RuntimeError("Failed to open Messenger chat")
        if d is None:
            d = self.connect_device(device_ip)
        time.sleep(1)
        for msg in messages:
            if not _send_text_u2(d, msg):
                raise RuntimeError(f"Failed to send message to {thread_id}")
            record_sent(device_ip, thread_id, msg)
            time.sleep(0.5)
        logger.info(f"[{device_ip}] [MessengerService] Sent to {thread_id}")
        d.app_start("jp.naver.line.android", stop=False)  # Switch to LINE after send

    def send_messages_to_groups(self, device_ip: str, group_names: list[str], messages: list[str]):
        for name in group_names:
            self.send_messages(device_ip, name, messages)

    def create_group(self, device_ip: str, group_name: str, accounts: list[str]):
        pass

    def promote_admin(self, device_ip: str, group_name: str, admin_names: list[str]):
        pass

    def inspect_group(self, device_ip: str, group_name: str):
        pass

    def get_invite_link(self, device_ip: str, group_name: str) -> str:
        return ""


messenger_service = MessengerService()

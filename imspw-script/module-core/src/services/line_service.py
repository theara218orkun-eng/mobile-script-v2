import logging
import threading
import time
from typing import Optional

import uiautomator2 as u2

from services.im_service import IMService

logger = logging.getLogger(__name__)

# Recent-sent cache: (device_id, chat_id, content) -> timestamp. Skip echo in DB monitor.
_LINE_RECENT_SENT: dict = {}
_LINE_RECENT_SENT_LOCK = threading.Lock()
_LINE_RECENT_SENT_TTL = 90  # seconds


def record_sent(device_id: Optional[str], chat_id: str, content: str) -> None:
    """Record that we just sent this message (so monitor can skip it as echo)."""
    key = (device_id or "", chat_id, content)
    with _LINE_RECENT_SENT_LOCK:
        _LINE_RECENT_SENT[key] = time.time()
        cutoff = time.time() - _LINE_RECENT_SENT_TTL
        for k in list(_LINE_RECENT_SENT.keys()):
            if _LINE_RECENT_SENT[k] < cutoff:
                del _LINE_RECENT_SENT[k]


def was_just_sent(device_id: Optional[str], chat_id: str, content: str) -> bool:
    """True if we sent this exact message to this chat recently (within TTL)."""
    key = (device_id or "", chat_id, content)
    with _LINE_RECENT_SENT_LOCK:
        ts = _LINE_RECENT_SENT.get(key)
        if ts is None:
            return False
        if time.time() - ts > _LINE_RECENT_SENT_TTL:
            del _LINE_RECENT_SENT[key]
            return False
        return True


class LineService(IMService):
    def __init__(self):
        self.package_name = "jp.naver.line.android"

    def connect_device(self, device_ip: str):
        """Standardized connection to device via u2."""
        try:
            logger.info(f"[{device_ip}] [LineService] Connecting to u2...")
            d = u2.connect(device_ip)
            return d
        except Exception as e:
            logger.error(f"[{device_ip}] [LineService] Failed to connect to device via u2: {e}")
            raise

    def send_message(self, device_ip: str, group_name: str, message: str, d=None, chat_id: Optional[str] = None):
        """
        Sends a message to a LINE group (or user).
        group_name: used for search (username/display name).
        chat_id: used for record_sent dedup (uuid). If None, uses group_name.
        """
        self.send_messages(device_ip, group_name, [message], d=d, chat_id=chat_id)

    def send_messages(self, device_ip: str, group_name: str, messages: list[str], d=None, chat_id: Optional[str] = None):
        """
        Sends multiple messages to a group in a single session.
        group_name: used for search in LINE (username/display name).
        chat_id: used for record_sent dedup. If None, uses group_name.
        """
        if d is None:
            d = self.connect_device(device_ip)

        dedup_key = chat_id or group_name
        logger.info(f"[{device_ip}] [LineService] Sending {len(messages)} messages to '{group_name}'")
        
        try:
            d.app_start(self.package_name, stop=True)
            time.sleep(5)  # Wait for cold start
            
            if self._navigate_to_chat(d, group_name):
                time.sleep(1)
                for msg in messages:
                    if self._send_text(d, msg):
                        record_sent(device_ip, dedup_key, msg)
                        time.sleep(0.5)
                    else:
                        logger.error(f"[{device_ip}] Failed to send message: {msg[:20]}...")
            else:
                logger.error(f"[{device_ip}] Failed to navigate to chat '{group_name}'")
                
        except Exception as e:
            logger.error(f"[{device_ip}] Error in send_messages: {e}")
        finally:
            # Keep LINE in foreground after job (don't close) so it can sync and receive notifications
            logger.info(f"[{device_ip}] Bringing LINE to foreground...")
            d.app_start(self.package_name, stop=False)

    def _navigate_to_chat(self, d, name: str) -> bool:
        """Helper to navigate to a specific chat."""
        logger.debug(f"Navigating to chat: {name}")

        # 1. Wait for 'Chats' tab
        if d(text="Chats").wait(timeout=30):
            d(text="Chats").click()
        else:
            logger.warning("Could not find 'Chats' tab (timed out)")
            return False
        
        time.sleep(1)

        # 2. Click Search
        search_icon = d(resourceId=f"{self.package_name}:id/header_search_button")
        if not search_icon.exists:
            search_icon = d(description="Search")
            
        if search_icon.exists:
            search_icon.click()
        else:
            logger.warning("Search icon not found")
            return False
        time.sleep(1)

        # 3. Input Name
        search_input = d(resourceId=f"{self.package_name}:id/search_query_edit_text")
        if not search_input.exists:
            search_input = d(className="android.widget.EditText")
            
        if search_input.wait(timeout=5):
            search_input.set_text(name)
        else:
            logger.warning("Search input not found")
            return False
            
        time.sleep(2)

        # 4. Select 'Chats' filter if available
        chats_filter = d(text="Chats")
        if chats_filter.exists:
            chats_filter.click()
            time.sleep(1)
        
        # 5. Match and Select
        # Prioritize exact title match
        target_chat = d(resourceId=f"{self.package_name}:id/title", text=name)
        
        if not target_chat.exists:
            target_chat = d(className="android.widget.TextView", text=name)
        
        if target_chat.exists:
            target_chat[0].click()
            
            if d(resourceId=f"{self.package_name}:id/chathistory_message_edit").wait(timeout=5) or \
               d(description="More options").exists or \
               d(resourceId=f"{self.package_name}:id/header_title", text=name).exists:
                return True
                
        return False

    def _send_text(self, d, text: str) -> bool:
        """Helper to type and send text."""
        message_input = d(resourceId=f"{self.package_name}:id/chathistory_message_edit")
        if not message_input.exists:
            message_input = d(className="android.widget.EditText")
        
        if message_input.wait(timeout=5):
            message_input.set_text(text)
            time.sleep(1)
            # Check for send button (icon or text)
            # 1. Try resource ID (icon)
            send_btn = d(resourceId=f"{self.package_name}:id/send_button_icon")
            
            # 2. Try description (accessibility text)
            if not send_btn.exists:
                send_btn = d(description="Send")
                
            # 3. Try text "Send" (rare in mobile app, but possible)
            if not send_btn.exists:
                send_btn = d(text="Send")
            
            # If not immediately visible, wait a bit (animating or enabled state)
            if not send_btn.exists:
                time.sleep(1) 
                
            if send_btn.exists:
                send_btn.click()
                return True
            
            logger.warning("Send button (icon/text) not found.")
            return False
            
        return False

    def send_messages_to_groups(self, device_ip: str, group_names: list[str], messages: list[str]):
        pass

    def create_group(self, device_ip: str, group_name: str, accounts: list[str]):
        pass

    def promote_admin(self, device_ip: str, group_name: str, admin_names: list[str]):
        pass

    def inspect_group(self, device_ip: str, group_name: str):
        pass

    def get_invite_link(self, device_ip: str, group_name: str) -> str:
        return ""

line_service = LineService()

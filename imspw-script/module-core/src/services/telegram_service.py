import asyncio
import base64
import os
import threading
from datetime import datetime
from queue import Queue
from typing import Dict, Optional, Any

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User, Chat, Channel
from aid_utils import logger

# Retrieve Telegram API credentials from environment variables
TG_API_ID = os.getenv("TELEGRAM_API_ID", "")
TG_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TG_SESSION_STRING = os.getenv("TG_SESSION_STRING", "")

class TelegramService:
    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    def start_client(self):
        """Initializes and starts the Telethon client synchronously."""
        if not TG_API_ID or not TG_API_HASH:
            logger.error("TELEGRAM_API_ID or TELEGRAM_API_HASH not set in .env")
            return
        
        if not TG_SESSION_STRING:
            logger.error("TG_SESSION_STRING not set in .env. Please run telegram_login.py first.")
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        self.client = TelegramClient(StringSession(TG_SESSION_STRING), int(TG_API_ID), TG_API_HASH)
        
        # Start client
        logger.info("[TelegramService] Starting MTProto Client...")
        self._loop.run_until_complete(self.client.connect())
        if not self._loop.run_until_complete(self.client.is_user_authorized()):
            logger.error("[TelegramService] Provided TG_SESSION_STRING is not authorized or expired!")
            return
            
        logger.info("[TelegramService] MTProto Client Started successfully!")

    def send_message(self, entity: str, message: str) -> bool:
        """Sends a message to a user, group, or channel."""
        if not self.client or not self._loop:
            logger.error("[TelegramService] Client not initialized.")
            return False

        # If entity is purely digits (or starts with - for groups), convert to int.
        # Telethon requires integer IDs for direct user/chat IDs, strings are treated as usernames.
        target_entity = entity
        if isinstance(target_entity, str):
            if target_entity.isdigit() or (target_entity.startswith("-") and target_entity[1:].isdigit()):
                target_entity = int(target_entity)

        try:
            future = asyncio.run_coroutine_threadsafe(self.client.send_message(target_entity, message), self._loop)
            future.result(timeout=10)
            logger.info(f"[TelegramService] Sent message to {entity}: {message[:50]}...")
            return True
        except Exception as e:
            logger.error(f"[TelegramService] Error sending message: {e}")
            return False

# Global instance for replying
telegram_service = TelegramService()


async def _format_message_event(event: events.NewMessage.Event) -> Optional[Dict[str, Any]]:
    """Formats a Telethon NewMessage event into the standard IMSPW payload."""
    try:
        sender = await event.get_sender()
        chat = await event.get_chat()

        # Skip our own outgoing messages to avoid echo
        if event.out:
            return None

        # Determine if it's a group
        is_group = isinstance(chat, (Chat, Channel)) and getattr(chat, 'megagroup', True)
        
        sender_uuid = str(sender.id) if sender else str(event.sender_id) if event.sender_id else ""
        sender_username = getattr(sender, 'username', "") or getattr(sender, 'first_name', "")
        sender_phone = getattr(sender, 'phone', "")
        
        chat_uuid = str(chat.id) if chat else str(event.chat_id) if event.chat_id else sender_uuid
        chat_name = getattr(chat, 'title', "") or sender_username
        
        if not sender_uuid:
            sender_uuid = chat_uuid

        content = event.raw_text or ""
        
        # Base64 encode content for consistency with other monitors
        try:
            encoded_content = base64.b64encode(content.encode("utf-8")).decode("ascii")
        except Exception:
            encoded_content = content
            
        time_str = event.date.isoformat() if event.date else datetime.now().isoformat()

        payload_obj = {
            "type": "INCOMING",
            "is_group": is_group,
            "chat": {
                "uuid": chat_uuid,
                "name": chat_name,
                "type": "group" if is_group else "chat"
            },
            "user_info": {
                "uuid": sender_uuid,
                "username": sender_username,
                "phone": sender_phone
            },
            "content": encoded_content,
            "time": time_str,
        }
        return payload_obj
    except Exception as e:
        logger.error(f"[TelegramService] Error formatting event: {e}")
        return None


def run_monitor(device_id: Optional[str], incoming_queue: Queue, stop_event: threading.Event) -> None:
    """
    Frida-farm pingtai style monitor for Telegram, but using MTProto (Telethon) instead of ADB.
    Runs asynchronously and places messages into the incoming_queue.
    """
    if not TG_API_ID or not TG_API_HASH:
        logger.warning("[TelegramMonitor] Missing TELEGRAM_API_ID/HASH in .env, skipping Telegram monitor.")
        return

    logger.info(f"[{device_id or 'telethon'}] [TelegramMonitor] Started (MTProto style)")
    
    # Use the global service to ensure we share the same client for incoming and outgoing
    if not telegram_service.client:
        try:
            telegram_service.start_client()
        except Exception as e:
            logger.error(f"[TelegramMonitor] Failed to start client: {e}")
            return

    client = telegram_service.client
    loop = telegram_service._loop

    @client.on(events.NewMessage)
    async def message_handler(event: events.NewMessage.Event):
        if stop_event.is_set():
            return
            
        payload = await _format_message_event(event)
        if payload:
            incoming_queue.put({
                "device_id": device_id or "telethon",
                "package": "org.telegram.messenger",
                "payload": payload,
            })

    # Run the event loop until the stop event is set
    async def _run_until_stopped():
        while not stop_event.is_set():
            await asyncio.sleep(1)
        await client.disconnect()

    try:
        if loop and not loop.is_closed():
            loop.run_until_complete(_run_until_stopped())
    except Exception as e:
        logger.error(f"[TelegramMonitor] Loop stopped: {e}")
    finally:
        logger.info(f"[{device_id or 'telethon'}] [TelegramMonitor] Stopped.")
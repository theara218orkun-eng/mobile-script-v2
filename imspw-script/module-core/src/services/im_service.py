from abc import ABC, abstractmethod
import uiautomator2 as u2
import logging

logger = logging.getLogger(__name__)

class IMService(ABC):
    """
    Abstract base class for Instant Messaging Services (WhatsApp, Telegram, Line, etc.).
    Defines the standard interface for UI automation tasks.
    """

    def connect_device(self, device_ip: str):
        """Standardized connection to device via uiautomator2."""
        try:
            logger.info(f"[{device_ip}] Connecting to u2...")
            d = u2.connect(device_ip)
            return d
        except Exception as e:
            logger.error(f"[{device_ip}] Failed to connect to device via u2: {e}")
            raise

    @abstractmethod
    def send_message(self, device_ip: str, group_name: str, message: str):
        """
        Sends a message to a group.
        Must handle app launch (cold start), navigation/search, and sending.
        """
        pass

    @abstractmethod
    def send_messages(self, device_ip: str, group_name: str, messages: list[str]):
        """
        Sends multiple messages to a group in a single session.
        """
        pass

    @abstractmethod
    def send_messages_to_groups(self, device_ip: str, group_names: list[str], messages: list[str]):
        """
        Sends multiple messages to multiple groups in a single app session.
        Optimized for bulk sending to many groups from one admin.
        """
        pass

    @abstractmethod
    def create_group(self, device_ip: str, group_name: str, accounts: list[str]):
        """
        Creates a new group with the specified accounts.
        Returns a dict with status and invite link.
        """
        pass

    @abstractmethod
    def promote_admin(self, device_ip: str, group_name: str, admin_names: list[str]):
        """
        Promotes specified participants to admin.
        """
        pass

    @abstractmethod
    def inspect_group(self, device_ip: str, group_name: str):
        """
        Inspects a group (specific logic depends on implementation).
        """
        pass

    @abstractmethod
    def get_invite_link(self, device_ip: str, group_name: str) -> str:
        """
        Retrieves the invite link for a group.
        """
        pass

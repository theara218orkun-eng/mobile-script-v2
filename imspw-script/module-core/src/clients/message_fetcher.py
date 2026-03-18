import requests
import os
from typing import List, Dict, Any, Optional

class MessageFetcherClient:
    def __init__(self, service_url: Optional[str] = None, auth_token: Optional[str] = None):
        self.service_url = service_url or os.getenv("MESSAGE_FETCHER_URL", "http://localhost:3000")
        self.auth_token = auth_token or os.getenv("MESSAGE_FETCHER_TOKEN", "")
        
        if not self.auth_token:
            print("[!] Warning: MESSAGE_FETCHER_TOKEN is not set.")

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json"
        }

    def fetch_messages(self, target: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Fetch new messages from the microservice.
        POST /tg/fetch
        """
        url = f"{self.service_url}/tg/fetch"
        payload = {"target": target, "limit": limit}
        
        try:
            response = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            response.raise_for_status()
            data = response.json()
            return data if data is not None else []
        except requests.exceptions.RequestException as e:
            print(f"[-] Error fetching messages: {e}")
            raise e

    def get_message(self, target: str, msg_id: int) -> Optional[str]:
        """
        Fetch a single message text by ID.
        GET /tg/{target}/{id}
        """
        url = f"{self.service_url}/tg/{target}/{msg_id}"
        
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=10)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            return data.get("message") if data else None
        except requests.exceptions.RequestException as e:
            print(f"[-] Error fetching message {msg_id}: {e}")
            raise e

    def sync_dialogs(self) -> bool:
        """
        Force the service to refresh its dialog cache.
        POST /tg/sync
        """
        url = f"{self.service_url}/tg/sync"
        try:
            response = requests.post(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"[-] Error syncing dialogs: {e}")
            return False

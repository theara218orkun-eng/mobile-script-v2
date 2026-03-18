import requests
import logging
import time
import jwt
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ProcessorClient:
    def __init__(self, api_url: str, api_secret: Optional[str] = None):
        self.api_url = api_url
        self.api_secret = api_secret

    def _generate_token(self) -> Optional[str]:
        """Generates a JWT token signed with the API secret."""
        if not self.api_secret:
            return None
        
        try:
            payload = {
                'iat': int(time.time()),
                'exp': int(time.time()) + 60
            }
            token = jwt.encode(payload, self.api_secret, algorithm='HS256')
            return token
        except Exception as e:
            logger.error(f"Failed to generate JWT token: {e}")
            return None

    def send_message(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Sends the message payload to the processor API.
        
        Args:
            payload: Dictionary containing message data
                     {'type': 'INCOMING', 'user_info': {...}, 'time': ..., 'content': ...}
        
        Returns:
            Response body dict if 200/201, None otherwise
        """
        if not self.api_url:
            logger.warning("Processor URL not configured. Skipping message send.")
            return None

        try:
            headers = {'Content-Type': 'application/json'}
            token = self._generate_token()
            if token:
                headers['Authorization'] = f"Bearer {token}"
            
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=10)
            
            if response.status_code in [200, 201]:
                try:
                    resp_body = response.json()
                    logger.info(f"Processor response [{response.status_code}]: {resp_body}")
                    return resp_body
                except Exception:
                    text = (response.text or "").strip()
                    if text and text.upper() not in ("OK", "SUCCESS"):
                        logger.info(f"Processor response [{response.status_code}]: {text[:500]}")
                        return {"message": text, "status": response.status_code}
                    else:
                        logger.info(f"Processor accepted message [{response.status_code}]")
                    return {"status": response.status_code}
            else:
                logger.error(f"Failed to send message to processor. Status: {response.status_code}, Response: {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending message to processor: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error in ProcessorClient: {e}")
            return None

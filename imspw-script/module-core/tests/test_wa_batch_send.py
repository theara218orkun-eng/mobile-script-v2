import sys
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
module_core_src = os.path.abspath(os.path.join(script_dir, "../src"))
if module_core_src not in sys.path:
    sys.path.insert(0, module_core_src)

from aid_core.services.whatsapp_service import whatsapp_service
from aid_core.utils import logger

def main():
    device_ip = "100.77.197.88:5555"
    target_group = "微博马经HK85570683646"
    messages = [
        "hello", 
        "how are you", 
        "I am fine"
    ]
    
    logger.info("--- Batch Send Verification Script ---")
    
    logger.info(f"Target Device: {device_ip}")
    logger.info(f"Target Group: {target_group}")
    logger.info(f"Messages: {messages}")
    
    try:
        logger.info("\nSending messages...")
        whatsapp_service.send_messages(
            device_ip=device_ip,
            group_name=target_group,
            messages=messages
        )
        logger.info("\n[SUCCESS] Batch send completed.")
        
    except Exception as e:
        logger.error(f"\n[ERROR] Failed to send messages: {e}")

if __name__ == "__main__":
    main()

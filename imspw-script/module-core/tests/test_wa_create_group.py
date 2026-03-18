import sys
import os
import time

# Ensure src is in path
script_dir = os.path.dirname(os.path.abspath(__file__))
module_core_src = os.path.abspath(os.path.join(script_dir, "../src"))
if module_core_src not in sys.path:
    sys.path.insert(0, module_core_src)

from aid_core.services.whatsapp_service import whatsapp_service
from aid_core.utils import logger

print(f"DEBUG: whatsapp_service loaded from: {whatsapp_service.__class__.__module__}")
import aid_core.services.whatsapp_service
print(f"DEBUG: whatsapp_service file: {aid_core.services.whatsapp_service.__file__}")
print(f"DEBUG: sys.path: {sys.path[:3]}")

def main():
    device_ip = "100.118.208.104" # Admin 01
    group_name = f"TestGroup_{int(time.time())}"
    accounts_to_add = ["Qk3", "Qk1"] 
    
    logger.info("--- WhatsApp Group Creation Verification Script ---")
    logger.info(f"Target Device: {device_ip}")
    logger.info(f"New Group Name: {group_name}")
    logger.info(f"Accounts to Add: {accounts_to_add}")
    
    try:
        logger.info("\nStarting group creation automation...")
        result = whatsapp_service.create_group(
            device_ip=device_ip,
            group_name=group_name,
            accounts=accounts_to_add
        )
        
        if result and result.get("status") == "success":
            logger.info("\n[SUCCESS] Group created!")
            logger.info(f"Invite Link: {result.get('invite_link')}")
        else:
            logger.error(f"\n[FAILED] Service returned: {result}")
            
    except Exception as e:
        logger.error(f"\n[ERROR] Exception during group creation: {e}")

if __name__ == "__main__":
    main()

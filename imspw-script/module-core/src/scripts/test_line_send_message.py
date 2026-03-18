import argparse
import sys
import os
from dotenv import load_dotenv

# Add parent directory to path to allow imports if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Add module-core/src to sys.path
module_core_src = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if module_core_src not in sys.path:
    sys.path.append(module_core_src)

from services.line_service import line_service

def main():
    parser = argparse.ArgumentParser(description="Test LINE Send Message via LineService")
    parser.add_argument("--device", help="Device Serial/IP")
    parser.add_argument("--name", default="Momo", help="Target User/Group Name")
    parser.add_argument("--text", default="Hello world", help="Message Text")
    args = parser.parse_args()

    # Load env for default device
    load_dotenv()
    device_id = args.device or os.getenv("DEVICE_ID")

    print(f"Testing LineService.send_message on {device_id}...")
    print(f"Target: {args.name}")
    print(f"Message: {args.text}")
    
    try:
        line_service.send_message(device_id, args.name, args.text)
        print("Test passed (check device/logs for actual send status).")
    except Exception as e:
        print(f"Test failed with exception: {e}")

if __name__ == "__main__":
    main()

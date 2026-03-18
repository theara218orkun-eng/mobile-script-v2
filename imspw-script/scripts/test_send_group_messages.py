#!/usr/bin/env python3
"""
Test WhatsApp service send_messages_to_groups directly.

Usage:
  DEVICE_ID=d56ff29b python scripts/test_send_group_messages.py
  python scripts/test_send_group_messages.py d56ff29b
"""
import os
import sys

# Add module-core/src to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
module_core = os.path.join(project_root, "module-core", "src")
if module_core not in sys.path:
    sys.path.insert(0, module_core)

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(project_root, ".env"))
except Exception:
    pass

# Mock data
TARGETS = ["微博马经67052lso"]
MESSAGES = ["Hello", "Second message", "Third"]


def main():
    args = sys.argv[1:]
    device_id = os.getenv("DEVICE_ID") or (args[0] if args else None)

    if not device_id:
        print("Usage: DEVICE_ID=xxx python scripts/test_send_group_messages.py")
        print("   or: python scripts/test_send_group_messages.py <device_id>")
        sys.exit(1)

    print(f"\n=== Test WhatsApp send_messages_to_groups ===\n")
    print(f"Device: {device_id}")
    print(f"Targets: {TARGETS}")
    print(f"Messages: {MESSAGES}\n")

    from services.whatsapp_service import whatsapp_service

    try:
        whatsapp_service.send_messages_to_groups(device_id, TARGETS, MESSAGES)
        print(f"\n[SUCCESS] Bulk send complete.")
    except Exception as e:
        print(f"\n[FAILED] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

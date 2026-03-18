#!/usr/bin/env python3
"""
Test full create_group flow.

Creates a WhatsApp group with participant "momo".

Usage:
  DEVICE_ID=d56ff29b python scripts/test_create_group.py
  python scripts/test_create_group.py d56ff29b
  python scripts/test_create_group.py d56ff29b "My Test Group" momo,user2
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


def main():
    args = sys.argv[1:]
    device_id = os.getenv("DEVICE_ID") or (args[0] if args else None)
    group_name = args[1] if len(args) > 1 else "TestGroup"
    participants = (args[2] if len(args) > 2 else "momo").split(",")

    if not device_id:
        print("Usage: DEVICE_ID=xxx python scripts/test_create_group.py")
        print("   or: python scripts/test_create_group.py <device_id> [group_name] [participant1,participant2]")
        print("\nExample: python scripts/test_create_group.py d56ff29b \"My Group\" momo")
        sys.exit(1)

    print(f"\n=== Full Create Group Test ===\n")
    print(f"Device: {device_id}")
    print(f"Group name: {group_name}")
    print(f"Participants: {participants}\n")

    from services.whatsapp_service import whatsapp_service

    try:
        result = whatsapp_service.create_group(device_id, group_name, participants)
        print(f"\n[SUCCESS] Result: {result}")
        if result.get("invite_link"):
            print(f"Invite link: {result['invite_link']}")
        else:
            print("(No invite link returned)")
    except Exception as e:
        print(f"\n[FAILED] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

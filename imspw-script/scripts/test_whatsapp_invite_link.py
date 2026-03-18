#!/usr/bin/env python3
"""
Test script to debug WhatsApp group invite link extraction.

Walk-through:
  Mode A (from Group Info screen):
    1. Manually open WhatsApp, go to a group chat
    2. Tap the group name at top to open Group Info
    3. Run: python scripts/test_whatsapp_invite_link.py

  Mode B (from Group chat, auto-open info):
    1. Open WhatsApp, go to a group chat (stay in the chat)
    2. Run: python scripts/test_whatsapp_invite_link.py --from-chat

Usage:
  DEVICE_ID=d56ff29b python scripts/test_whatsapp_invite_link.py
  python scripts/test_whatsapp_invite_link.py d56ff29b [--from-chat]
"""
import os
import sys
import time

# Add module-core/src to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
module_core = os.path.join(project_root, "module-core", "src")
if module_core not in sys.path:
    sys.path.insert(0, module_core)

import uiautomator2 as u2


def dump_ui(d, label: str = ""):
    """Dump current UI hierarchy to file for inspection."""
    try:
        xml = d.dump_hierarchy()
        fname = f"wa_ui_dump_{label}_{int(time.time())}.xml" if label else f"wa_ui_dump_{int(time.time())}.xml"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(xml)
        print(f"[OK] Dumped UI to {fname}")
        return xml
    except Exception as e:
        print(f"[ERR] Dump failed: {e}")
        return None


def find_elements_with_text(xml: str, keywords: list):
    """Find lines in XML that contain any of the keywords."""
    results = []
    for line in xml.split("\n"):
        lower = line.lower()
        for kw in keywords:
            if kw.lower() in lower and ("resource-id" in lower or 'text="' in lower or "content-desc" in lower):
                results.append((kw, line.strip()[:250]))
                break
    return results


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    from_chat = "--from-chat" in sys.argv
    device_id = os.getenv("DEVICE_ID") or (args[0] if args else None)
    if not device_id:
        print("Usage: DEVICE_ID=xxx python scripts/test_whatsapp_invite_link.py [--from-chat]")
        print("   or: python scripts/test_whatsapp_invite_link.py <device_id> [--from-chat]")
        sys.exit(1)

    print(f"\n=== WhatsApp Invite Link Test ===\n")
    print(f"Device: {device_id}")
    if from_chat:
        print("Mode: from-chat (will click conversation_contact_name to open Group Info)")
        print("Prerequisite: WhatsApp open, inside a group chat\n")
    else:
        print("Prerequisite: WhatsApp open, Group Info screen visible")
        print("  (Group chat -> tap group name at top -> Group Info)\n")

    d = u2.connect(device_id)
    pkg = "com.whatsapp"

    # Step 0: If from-chat, click to open Group Info
    if from_chat:
        print("[Step 0] Opening Group Info from chat...")
        conv = d(resourceId=f"{pkg}:id/conversation_contact_name")
        if conv.exists:
            conv.click()
            time.sleep(2)
            print("  Clicked conversation_contact_name")
        else:
            print("  [WARN] conversation_contact_name not found. Are you in a group chat?")

    # Step 1: Dump UI (initial state)
    print("\n[Step 1] Dumping current UI...")
    xml = dump_ui(d, "initial")
    if not xml:
        sys.exit(1)

    # Step 2: Search for Invite-related elements
    print("\n[Step 2] Searching for Invite / Link elements...")
    keywords = ["Invite", "invite", "邀请", "link", "invitation", "Group invite"]
    found = find_elements_with_text(xml, keywords)
    for kw, line in found:
        print(f"  '{kw}': {line}")

    # Step 3: Try common selectors
    print("\n[Step 3] Trying selectors...")
    selectors = [
        ("description=Invite", d(description="Invite")),
        ("description=invite", d(description="invite")),
        ("description=邀请", d(description="邀请")),
        ("resourceId=com.whatsapp:id/link", d(resourceId="com.whatsapp:id/link")),
        ("resourceId=com.whatsapp:id/invite_link", d(resourceId="com.whatsapp:id/invite_link")),
        ("text=Invite", d(text="Invite")),
        ("text=invite", d(text="invite")),
        ("text=邀请", d(text="邀请")),
        ("textContains=chat.whatsapp", d(textContains="chat.whatsapp")),
    ]

    for name, sel in selectors:
        if sel.exists:
            txt = sel.get_text() if hasattr(sel, "get_text") else "(no get_text)"
            print(f"  [EXISTS] {name} -> text={txt}")
        else:
            print(f"  [--] {name} not found")

    # Step 4: Try clicking Invite and dump again
    print("\n[Step 4] Attempting to click 'Invite' and re-dump...")
    clicked = False
    for desc in ["Invite", "invite", "邀请", "Group invite link"]:
        if d(description=desc).exists:
            d(description=desc).click()
            print(f"  Clicked description={desc}")
            clicked = True
            time.sleep(1.5)
            break
    if not clicked:
        for txt in ["Invite", "邀请"]:
            if d(text=txt).exists:
                d(text=txt).click()
                print(f"  Clicked text={txt}")
                clicked = True
                time.sleep(1.5)
                break
    if clicked:
        dump_ui(d, "after_invite_click")
        # Now look for link
        if d(resourceId="com.whatsapp:id/link").exists:
            link = d(resourceId="com.whatsapp:id/link").get_text()
            print(f"\n  [SUCCESS] Link via id/link: {link}")
        elif d(textContains="chat.whatsapp").exists:
            link = d(textContains="chat.whatsapp").get_text()
            print(f"\n  [SUCCESS] Link via textContains: {link}")
        else:
            print("\n  [--] No link element found after Invite click. Check wa_ui_dump_after_invite_click_*.xml")
    else:
        print("  Could not find Invite button to click. Check UI dump.")

    print("\n=== Done. Check wa_ui_dump_*.xml for full hierarchy ===\n")


if __name__ == "__main__":
    main()

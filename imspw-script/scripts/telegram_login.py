import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

# Load environment variables
load_dotenv()

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")

if not API_ID or not API_HASH:
    print("Error: TELEGRAM_API_ID or TELEGRAM_API_HASH not found in .env")
    print("Please set them before running this script.")
    exit(1)

print("Starting Telegram login process...")
print(f"Using API ID: {API_ID}")

async def main():
    client = TelegramClient(StringSession(), int(API_ID), API_HASH)
    await client.start()
    session_string = client.session.save()
    print("\n" + "="*50)
    print("Login successful! Here is your TG_SESSION_STRING:")
    print("="*50)
    print(session_string)
    print("="*50)
    print("\nPlease copy the string above and paste it into your .env file as:")
    print(f"TG_SESSION_STRING={session_string}")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
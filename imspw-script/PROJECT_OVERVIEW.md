# Line IMSPW - IM Message Interception System

## 📖 Overview

**Line IMSPW** is a Frida-based interception system that monitors and captures messages from popular instant messaging apps including **LINE**, **WhatsApp**, **Messenger**, and **Telegram**. It supports both message interception and automated replies.

### Key Features

- 📱 **Multi-Platform Support**: LINE, WhatsApp, Messenger, Telegram
- 🔍 **Dual Monitoring Modes**: 
  - **Frida hooks** for real-time interception (WhatsApp)
  - **Database polling** for LINE & Messenger (more stable)
- 🤖 **Auto-Reply**: Process incoming messages and send automated responses
- 📞 **Background Keepalive**: Maintains app activity for continuous message reception
- 🔄 **Callback Server**: Accept external message submissions via HTTP POST
- 💾 **Persistent Queue**: SQLite-based task queue prevents message loss

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Mobile Device (Root + ADB)                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │    LINE     │  │  WhatsApp   │  │  Telegram   │              │
│  │  (DB Poll)  │  │  (Frida)    │  │  (MTProto)  │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
│         └────────────────┴────────────────┘                      │
│                          │                                       │
│                    ┌─────▼─────┐                                 │
│                    │   ADB     │                                 │
│                    └─────┬─────┘                                 │
└──────────────────────────┼───────────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  Host PC    │
                    │  (This App) │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──────┐ ┌───▼────┐ ┌────▼─────┐
       │  Processor  │ │ Queue  │ │ Callback │
       │   Client    │ │ (SQLite)│ │  Server  │
       └──────┬──────┘ └────────┘ └──────────┘
              │
       ┌──────▼──────┐
       │   Backend   │
       │  (Your API) │
       └─────────────┘
```

---

## 📁 Project Structure

```
mobile-script/
├── src/
│   └── main.py              # Main entry point
├── module-core/src/
│   ├── frida_core/          # Frida device management
│   │   ├── device_supervisor.py
│   │   └── device_worker.py
│   ├── hooks/               # Frida injection scripts
│   │   └── agent_bundled.js
│   ├── services/            # Platform-specific services
│   │   ├── line_service.py
│   │   ├── whatsapp_service.py
│   │   ├── messenger_service.py
│   │   └── telegram_service.py
│   ├── utils/               # Database monitors
│   │   ├── line_database_monitor.py
│   │   ├── messenger_database_monitor.py
│   │   └── whatsapp_database_monitor.py
│   ├── processor/           # Task processing
│   │   └── device_processor.py
│   ├── clients/             # API clients
│   │   └── processor_client.py
│   ├── infrastructure/      # Queue & Lock
│   │   ├── queue.py
│   │   └── lock.py
│   └── db/                  # Database models
├── scripts/                 # Utility scripts
└── .env                     # Configuration
```

---

## 🚀 Quick Start

### Prerequisites

1. **Rooted Android device** or emulator with **frida-server** running
2. **ADB** installed and device connected
3. **Python 3.14+** with **uv** package manager

### Setup

```bash
# Install dependencies
uv sync

# Copy and configure environment
cp .env.example .env

# Edit .env with your settings
# DEVICE_ID=4d0a4baf
# TARGET_PACKAGES=jp.naver.line.android,com.whatsapp
# PROCESSOR_URL=http://localhost:8000/api/webhook
# PROCESSOR_API_SECRET=your_secret_key

# Run
uv run src/main.py
```

---

## ⚙️ Configuration (.env)

| Variable | Description | Default |
|----------|-------------|---------|
| `DEVICE_ID` | ADB device serial or IP:5555 | - |
| `TARGET_PACKAGES` | Apps to monitor (comma-separated) | `jp.naver.line.android` |
| `PROCESSOR_URL` | Backend webhook URL | - |
| `PROCESSOR_API_SECRET` | JWT signing secret | - |
| `LINE_USE_DB_POLL` | Use DB polling for LINE | `1` |
| `MESSENGER_USE_DB_POLL` | Use DB polling for Messenger | `1` |
| `LINE_MONITOR_INTERVAL` | LINE DB poll interval (seconds) | `1.0` |
| `CALLBACK_SERVER_PORT` | Callback server port | `8091` |
| `PHONE_RESTART_HOUR` | Daily restart hour (-1=disabled) | `-1` |

---

## 📡 Message Flow

### Incoming Message

```
1. App receives message
2. Frida hook / DB monitor captures it
3. Message → incoming_queue
4. message_processor() picks it up
5. POST to PROCESSOR_URL with JWT auth
6. Backend responds with optional reply
7. Reply queued → DeviceProcessor → Service → Send
```

### Payload Format

```json
POST /api/webhook
Authorization: Bearer <JWT>

{
  "type": "INCOMING",
  "device_id": "4d0a4baf",
  "package": "jp.naver.line.android",
  "platform": "line",
  "user_info": {
    "username": "John Doe",
    "phone": "+1234567890",
    "uuid": "user-uuid"
  },
  "chat": {
    "uuid": "chat-uuid",
    "name": "Group Name"
  },
  "content": "SGVsbG8gV29ybGQ=",  // Base64 encoded
  "time": 1710756123,
  "is_group": false
}
```

### Response Format

```json
// Auto-reply
{ "message": "Thanks for your message!" }

// Or acknowledge only
{ "status": "ok" }
```

---

## 🔧 Platform-Specific Notes

### LINE

- Uses **database polling** by default (more stable)
- Requires app to be opened first (attach-only mode)
- FTS (Full Text Search) table for message detection
- Background keepalive prevents message delays

### WhatsApp

- Uses **Frida hooks** for real-time interception
- May require **Frida Gadget** on jailed Android
- Supports both individual and group messages

### Messenger

- Uses **database polling** from `/data/data/com.facebook.orca/databases/`
- Monitors `messages` table for new entries
- Thread-based conversation tracking

### Telegram

- Uses **MTProto (Telethon)** - no root required for monitoring
- Requires API credentials from [my.telegram.org](https://my.telegram.org)
- Session string authentication (one-time setup)

```bash
# Telegram setup
uv run python scripts/telegram_login.py
# Copy TG_SESSION_STRING to .env
```

---

## 🛠️ Backend Implementation

Your backend needs to:

1. **Accept POST** at `/api/webhook`
2. **Verify JWT token** (HS256, signed with `PROCESSOR_API_SECRET`)
3. **Decode Base64** message content
4. **Return reply** (optional)

### Minimal Example (FastAPI)

```python
from fastapi import FastAPI, Header, HTTPException
import jwt, base64

app = FastAPI()
SECRET = "your_secret"

@app.post("/api/webhook")
async def webhook(payload: dict, authorization: str = Header(None)):
    # Verify JWT
    token = authorization.replace("Bearer ", "")
    jwt.decode(token, SECRET, algorithms=["HS256"])
    
    # Decode message
    content = base64.b64decode(payload["content"]).decode()
    print(f"Message: {content}")
    
    # Auto-reply
    return {"message": "Auto-reply here"}
```

---

## 🔍 Troubleshooting

| Issue | Solution |
|-------|----------|
| `need Gadget to attach on jailed Android` | Use attach-only mode or patch with Frida Gadget |
| `Connection refused` to processor | Start backend or set `PROCESSOR_URL=` empty |
| LINE not receiving | Set `LINE_DEBUG=1`, check FTS DB with `scripts/line_fts_test.py` |
| `adbd is not running as root` | Run `adb root` (userdebug devices only) |

---

## 📝 License

Private project - Internal use only

---

## 🤝 Contributing

This is a private project. For questions or issues, contact the development team.

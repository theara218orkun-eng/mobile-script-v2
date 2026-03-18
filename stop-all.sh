#!/bin/bash
# Stop All IMSPW Services

echo "Stopping all IMSPW services..."

# Kill backend and script processes
pkill -f "uvicorn main:app" 2>/dev/null
pkill -f "uv run src/main.py" 2>/dev/null

# Stop frida-server on emulator
adb shell "pkill -f frida-server" 2>/dev/null

echo "✅ All services stopped"

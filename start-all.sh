#!/bin/bash
# Start All IMSPW Services
# This script starts: Backend, Frida Server, and IMSPW Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/imspw-backend"
SCRIPT_PROJECT_DIR="$SCRIPT_DIR/imspw-script"

echo "========================================"
echo "  IMSPW - Starting All Services"
echo "========================================"
echo ""

# Check if emulator is running
echo "[1/4] Checking emulator..."
if ! adb devices | grep -q "emulator-5554"; then
    echo "❌ Emulator not found! Please start Android Emulator first."
    exit 1
fi
echo "✅ Emulator detected: emulator-5554"
echo ""

# Start Frida Server on emulator
echo "[2/4] Starting Frida Server on emulator..."
adb root
sleep 2
adb shell "/data/local/tmp/frida-server &"
sleep 2

if frida-ps -U >/dev/null 2>&1; then
    echo "✅ Frida Server started"
else
    echo "❌ Failed to start Frida Server"
    exit 1
fi
echo ""

# Start Backend Server in background
echo "[3/4] Starting Backend Server..."
cd "$BACKEND_DIR"
source .venv/bin/activate
nohup uvicorn main:app --reload > /tmp/imspw-backend.log 2>&1 &
BACKEND_PID=$!
deactivate
sleep 3

if ps -p $BACKEND_PID >/dev/null 2>&1; then
    echo "✅ Backend Server started (PID: $BACKEND_PID)"
else
    echo "❌ Failed to start Backend Server"
    cat /tmp/imspw-backend.log
    exit 1
fi
echo ""

# Start IMSPW Script in background
echo "[4/4] Starting IMSPW Script..."
cd "$SCRIPT_PROJECT_DIR"
source .venv/bin/activate
nohup uv run src/main.py > /tmp/imspw-script.log 2>&1 &
SCRIPT_PID=$!
deactivate
sleep 3

if ps -p $SCRIPT_PID >/dev/null 2>&1; then
    echo "✅ IMSPW Script started (PID: $SCRIPT_PID)"
else
    echo "❌ Failed to start IMSPW Script"
    cat /tmp/imspw-script.log
    exit 1
fi
echo ""

echo "========================================"
echo "  ✅ All Services Started Successfully!"
echo "========================================"
echo ""
echo "PIDs:"
echo "  Backend: $BACKEND_PID"
echo "  Script:  $SCRIPT_PID"
echo ""
echo "To view logs:"
echo "  Backend: tail -f /tmp/imspw-backend.log"
echo "  Script:  tail -f /tmp/imspw-script.log"
echo ""
echo "To stop all services:"
echo "  kill $BACKEND_PID $SCRIPT_PID"
echo "  adb shell 'pkill -f frida-server'"
echo ""

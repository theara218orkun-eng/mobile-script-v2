#!/bin/bash
# Start frida-server on Android emulator

echo "Starting frida-server on emulator..."

# Restart adbd as root (for emulator)
adb root

# Wait for adbd to restart
sleep 2

# Start frida-server in background
adb shell "/data/local/tmp/frida-server &"

# Wait for frida-server to start
sleep 2

# Verify it's working
echo "Verifying Frida..."
frida-ps -U | head -5

echo "Done! You can now run: uv run src/main.py"

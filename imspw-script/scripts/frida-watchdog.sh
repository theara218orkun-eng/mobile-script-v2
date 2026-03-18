#!/bin/bash
# Frida Server Watchdog - keeps frida-server running on emulator

DEVICE="emulator-5554"
FRIDA_PATH="/data/local/tmp/frida-server"

echo "Starting Frida Server Watchdog..."
echo "Monitoring: $DEVICE"

while true; do
    # Check if frida-server is responding
    if ! frida-ps -U >/dev/null 2>&1; then
        echo "[$(date '+%H:%M:%S')] Frida not responding, restarting..."
        
        # Restart adbd as root (emulator)
        adb root
        sleep 2
        
        # Start frida-server
        adb shell "$FRIDA_PATH &"
        sleep 2
        
        # Verify
        if frida-ps -U >/dev/null 2>&1; then
            echo "[$(date '+%H:%M:%S')] Frida restarted successfully"
        else
            echo "[$(date '+%H:%M:%S')] Failed to restart Frida"
        fi
    fi
    
    # Check every 10 seconds
    sleep 10
done

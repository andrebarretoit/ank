#!/system/bin/sh
# ANK - WiFi Auto-Reconnect
# Monitors WiFi and reconnects if disconnected
# Run as daemon via service.sh or manually: sh wifi-watchdog.sh &

ANK_DIR="${ANK_DIR:-/data/local/ank}"
ANK_SDCARD="/sdcard/AndroidKonteiner"
LOG="$ANK_DIR/logs/wifi-watchdog.log"
CONFIG="$ANK_DIR/config.json"
CHECK_INTERVAL=10
MAX_RETRIES=5
RETRY_DELAY=5

# WiFi interface
WLAN="wlan0"

# Known networks - scans from /data/misc/wifi/WifiConfigStore.xml
# Falls back to last connected network

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

get_ssid() {
    # Try to get current SSID
    local ssid=$(/system/bin/dumpsys wifi 2>/dev/null | grep "mWifiInfo" | grep -o 'SSID: "[^"]*"' | head -1 | cut -d'"' -f2)
    if [ -n "$ssid" ]; then
        echo "$ssid"
        return 0
    fi

    # Fallback: check wpa_supplicant
    ssid=$(/system/bin/wpa_cli -i "$WLAN" status 2>/dev/null | grep "ssid=" | head -1 | cut -d= -f2)
    if [ -n "$ssid" ]; then
        echo "$ssid"
        return 0
    fi

    # Fallback: read from WifiConfigStore
    ssid=$(grep -o 'SSID="[^"]*"' /data/misc/wifi/WifiConfigStore.xml 2>/dev/null | head -1 | cut -d'"' -f2)
    echo "$ssid"
}

is_wifi_connected() {
    # Check if wlan0 has an IP address
    local ip=$(/system/bin/ip -4 -o addr show "$WLAN" 2>/dev/null | cut -d' ' -f7 | cut -d/ -f1)
    if [ -n "$ip" ]; then
        echo "$ip"
        return 0
    fi
    return 1
}

is_internet_available() {
    # Quick ping test
    ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1
    return $?
}

toggle_wifi() {
    log "Toggling WiFi..."
    /system/bin/cmd wifi set-wifi-enabled disabled 2>/dev/null
    sleep 2
    /system/bin/cmd wifi set-wifi-enabled enabled 2>/dev/null
    sleep 5
}

force_reconnect() {
    local ssid="$1"
    log "Force reconnecting to: $ssid"

    # Method 1: disconnect + reconnect via wpa_cli
    /system/bin/wpa_cli -i "$WLAN" disconnect 2>/dev/null
    sleep 2
    /system/bin/wpa_cli -i "$WLAN" reconnect 2>/dev/null
    sleep 5

    # Check if it worked
    if is_wifi_connected; then
        log "Reconnected via wpa_cli"
        return 0
    fi

    # Method 2: toggle WiFi
    toggle_wifi

    if is_wifi_connected; then
        log "Reconnected via WiFi toggle"
        return 0
    fi

    # Method 3: reset interface
    log "Resetting network interface..."
    /system/bin/ip link set "$WLAN" down 2>/dev/null
    sleep 2
    /system/bin/ip link set "$WLAN" up 2>/dev/null
    sleep 5

    if is_wifi_connected; then
        log "Reconnected via interface reset"
        return 0
    fi

    return 1
}

ensure_services() {
    # Make sure ANK server is running
    local pid_file="$ANK_DIR/logs/server.pid"
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ! kill -0 "$pid" 2>/dev/null; then
            log "ANK server died (PID $pid), restarting..."
            # Try known restart-script locations
            local restart_sh=""
            for candidate in \
                "$ANK_DIR/scripts/restart-server.sh" \
                "$ANK_DIR/core/restart-server.sh" \
                "/data/adb/modules/ank/scripts/restart-server.sh" \
                "$ANK_DIR/ankfs/opt/ank/restart-server.sh"; do
                if [ -f "$candidate" ]; then
                    restart_sh="$candidate"
                    break
                fi
            done
            if [ -n "$restart_sh" ]; then
                sh "$restart_sh" 2>/dev/null
            fi
            # Manual restart fallback (arch-aware musl linker)
            local ROOTFS="$ANK_DIR/ankfs"
            local MUSL=""
            local arch
            arch=$(uname -m 2>/dev/null)
            case "$arch" in
                aarch64|arm64) MUSL="$ROOTFS/lib/ld-musl-aarch64.so.1" ;;
                x86_64)        MUSL="$ROOTFS/lib/ld-musl-x86_64.so.1" ;;
                armv7*|armhf)  MUSL="$ROOTFS/lib/ld-musl-armhf.so.1" ;;
                *)             MUSL="$ROOTFS/lib/ld-musl-armhf.so.1" ;;
            esac
            if [ -f "$MUSL" ]; then
                export LD_LIBRARY_PATH="$ROOTFS/usr/lib:$ROOTFS/lib"
                nohup "$MUSL" "$ROOTFS/usr/bin/python3" "$ROOTFS/opt/ank/server.py" > "$ANK_DIR/logs/server.log" 2>&1 &
                echo $! > "$pid_file"
                log "ANK server restarted (PID: $!)"
            fi
        fi
    fi
}

# ============================================================
# Main loop
# ============================================================
log "=== WiFi Watchdog started ==="
log "Interface: $WLAN"
log "Check interval: ${CHECK_INTERVAL}s"

consecutive_failures=0

while true; do
    sleep "$CHECK_INTERVAL"

    # Check WiFi connection
    if is_wifi_connected >/dev/null 2>&1; then
        # WiFi is up, check internet
        if ! is_internet_available; then
            log "WARN: WiFi connected but no internet"
            consecutive_failures=$((consecutive_failures + 1))
        else
            consecutive_failures=0
        fi
    else
        log "ERROR: WiFi disconnected!"
        consecutive_failures=$((consecutive_failures + 1))

        if [ "$consecutive_failures" -ge 3 ]; then
            log "Attempting reconnection (attempt $consecutive_failures)..."

            ssid=$(get_ssid)
            if [ -n "$ssid" ]; then
                force_reconnect "$ssid"
            else
                toggle_wifi
            fi

            # Check ANK server too
            ensure_services
        fi

        # Nuclear option: too many failures, reboot
        if [ "$consecutive_failures" -ge "$MAX_RETRIES" ]; then
            log "CRITICAL: $consecutive_failures consecutive failures. Last resort: restarting network stack..."
            /system/bin/cmd connectivity airplane-mode enable 2>/dev/null
            sleep 5
            /system/bin/cmd connectivity airplane-mode disable 2>/dev/null
            sleep 15
            consecutive_failures=0
        fi
    fi

    # Ensure ANK server is alive
    ensure_services
done

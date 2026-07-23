#!/system/bin/sh
# ============================================================
# ANK - Android Konteiner
# action.sh > Magisk Manager Action button
# Toggle: running -> stop, stopped -> start
# ============================================================

# ui_print is only available inside Magisk Manager
command -v ui_print >/dev/null 2>&1 || ui_print() { echo "$@"; }

ANK_DIR="/data/local/ank"
ANK_SDCARD="/sdcard/AndroidKonteiner"
ROOTFS="$ANK_DIR/ankfs"
SERVER_PID_FILE="$ANK_DIR/logs/server.pid"
PORT=8001

mkdir -p "$ANK_DIR/logs"

# Detect musl linker
ARCH=$(uname -m)
case "$ARCH" in
    aarch64|arm64)  MUSL="$ROOTFS/lib/ld-musl-aarch64.so.1" ;;
    armv7*|armhf)   MUSL="$ROOTFS/lib/ld-musl-armhf.so.1" ;;
    x86_64)         MUSL="$ROOTFS/lib/ld-musl-x86_64.so.1" ;;
    *)              MUSL=$(find "$ROOTFS/lib" -name "ld-musl-*.so.*" 2>/dev/null | head -1) ;;
esac

# Get device IP
get_ip() {
    local ip=""
    for iface in wlan0 eth0 rmnet_data0; do
        ip=$(ip addr show "$iface" 2>/dev/null | grep -o 'inet [0-9.]*' | head -1 | cut -d' ' -f2)
        [ -n "$ip" ] && break
    done
    [ -z "$ip" ] && ip="localhost"
    echo "$ip"
}

# Check if running
RUNNING=0
PID=""
if [ -f "$SERVER_PID_FILE" ]; then
    PID=$(cat "$SERVER_PID_FILE")
    kill -0 "$PID" 2>/dev/null && RUNNING=1
fi

IP=$(get_ip)

if [ "$RUNNING" -eq 1 ]; then
    ui_print ""
    ui_print "  ANK: Server running, shutting down..."
    kill "$PID" 2>/dev/null
    pkill -f "ld-musl-.*python3.*server.py" 2>/dev/null
    sleep 1
    rm -f "$SERVER_PID_FILE"
    ui_print "  ANK: Server stopped."
    ui_print ""
else
    [ ! -f "$ROOTFS/usr/bin/python3" ] && { ui_print "  ANK: ERROR - python3 missing!"; exit 1; }
    [ ! -f "$MUSL" ] && { ui_print "  ANK: ERROR - musl linker missing!"; exit 1; }

    export LD_LIBRARY_PATH="$ROOTFS/usr/lib:$ROOTFS/lib"
    cd "$ROOTFS"
    nohup "$MUSL" "$ROOTFS/usr/bin/python3" "$ROOTFS/opt/ank/server.py" > "$ANK_DIR/logs/server.log" 2>&1 &
    echo $! > "$SERVER_PID_FILE"
    sleep 1

    if kill -0 "$!" 2>/dev/null; then
        ui_print ""
        ui_print "  ANK: Server started!"
        ui_print "  Panel: http://$IP:$PORT"
        ui_print "  Login: admin / admin123"
        ui_print ""
    else
        ui_print ""
        ui_print "  ANK: Server failed to start."
        ui_print "  Log: $ANK_DIR/logs/server.log"
        ui_print ""
    fi
fi

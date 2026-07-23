#!/system/bin/sh
# ============================================================
# ANK - Android Konteiner
# service.d/ank.sh - fallback boot auto-start
# Runs AFTER service.sh as a safety net
# Only starts server if service.sh didn't (no PID file or dead)
# ============================================================

ANK_DIR="/data/local/ank"
ANK_SDCARD="/sdcard/AndroidKonteiner"
ROOTFS="$ANK_DIR/ankfs"
SERVER_PID_FILE="$ANK_DIR/logs/server.pid"
CONFIG="$ANK_DIR/config.json"
LOG="$ANK_DIR/logs/service.log"

mkdir -p "$ANK_DIR/logs"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [service.d] $1" >> "$LOG"
}

# Check autostart setting (default: enabled)
AUTOSTART="1"
if [ -f "$CONFIG" ]; then
    AS=$(grep -o '"autostart_on_boot"[[:space:]]*:[[:space:]]*[a-z]*' "$CONFIG" 2>/dev/null | grep -o '[a-z]*$')
    [ "$AS" = "false" ] && AUTOSTART="0"
fi

if [ "$AUTOSTART" = "0" ]; then
    log "Autostart disabled, skipping"
    exit 0
fi

# Wait for boot to complete
count=0
while [ "$(getprop sys.boot_completed)" != "1" ]; do
    sleep 3
    count=$((count + 1))
    [ "$count" -gt 40 ] && break
done

# Extra wait
sleep 10

# Check if server is already running (from service.sh)
if [ -f "$SERVER_PID_FILE" ]; then
    PID=$(cat "$SERVER_PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        log "Server already running (PID $PID), skipping fallback"
        exit 0
    fi
fi

# Also check by process name
if pgrep -f "ld-musl-.*python3.*server.py" >/dev/null 2>&1; then
    log "Server process found, skipping fallback"
    exit 0
fi

log "service.d fallback: server not running, starting..."

# Detect architecture
ARCH=$(uname -m)
case "$ARCH" in
    aarch64|arm64)  MUSL="$ROOTFS/lib/ld-musl-aarch64.so.1" ;;
    armv7*|armhf)   MUSL="$ROOTFS/lib/ld-musl-armhf.so.1" ;;
    x86_64)         MUSL="$ROOTFS/lib/ld-musl-x86_64.so.1" ;;
    *)              MUSL="$ROOTFS/lib/ld-musl-$ARCH.so.1" ;;
esac

if [ ! -f "$MUSL" ]; then
    MUSL=$(find "$ROOTFS/lib" -name "ld-musl-*.so.*" 2>/dev/null | head -1)
fi

if [ ! -f "$MUSL" ] || [ ! -f "$ROOTFS/usr/bin/python3" ]; then
    log "ERROR: Required files missing (musl or python3)"
    exit 1
fi

PYLIB="$ROOTFS/usr/lib:$ROOTFS/lib"
SERVER="$ROOTFS/opt/ank/server.py"

export LD_LIBRARY_PATH="$PYLIB"
cd "$ROOTFS"
nohup "$MUSL" "$ROOTFS/usr/bin/python3" "$SERVER" > "$ANK_DIR/logs/server.log" 2>&1 &
echo $! > "$SERVER_PID_FILE"

log "Fallback server started (PID: $(cat $SERVER_PID_FILE))"
log "Panel: http://localhost:8001"

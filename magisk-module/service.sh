#!/system/bin/sh
# ============================================================
# ANK - Android Konteiner
# service.sh - starts server on boot (post-boot)
# ============================================================

ANK_DIR="/data/local/ank"
ANK_SDCARD="/sdcard/AndroidKonteiner"
ROOTFS="$ANK_DIR/ankfs"
LOG="$ANK_DIR/logs/service.log"
SERVER_PID_FILE="$ANK_DIR/logs/server.pid"
CONFIG="$ANK_DIR/config.json"
MODE_FILE="$ANK_DIR/mode"

mkdir -p "$ANK_DIR/logs"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

log "=== service.sh started ==="

# Detect architecture and find correct musl linker
ARCH=$(uname -m)
case "$ARCH" in
    aarch64|arm64)  MUSL="$ROOTFS/lib/ld-musl-aarch64.so.1" ;;
    armv7*|armhf)   MUSL="$ROOTFS/lib/ld-musl-armhf.so.1" ;;
    x86_64)         MUSL="$ROOTFS/lib/ld-musl-x86_64.so.1" ;;
    *)              MUSL="$ROOTFS/lib/ld-musl-$ARCH.so.1" ;;
esac

# Fallback: find any musl linker
if [ ! -f "$MUSL" ]; then
    MUSL=$(find "$ROOTFS/lib" -name "ld-musl-*.so.*" 2>/dev/null | head -1)
fi

PYLIB="$ROOTFS/usr/lib:$ROOTFS/lib"
SERVER="$ROOTFS/opt/ank/server.py"

# Check autostart setting (default: enabled for first boot)
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
    sleep 2
    count=$((count + 1))
    [ "$count" -gt 60 ] && break
done
log "Boot completed"

# Extra wait for system to stabilize
sleep 5

# Kill old server if running
if [ -f "$SERVER_PID_FILE" ]; then
    OLD_PID=$(cat "$SERVER_PID_FILE")
    kill "$OLD_PID" 2>/dev/null
    sleep 1
fi
pkill -f "ld-musl-" 2>/dev/null
sleep 1

# Verify Python exists
if [ ! -f "$ROOTFS/usr/bin/python3" ]; then
    log "ERROR: Python not found at $ROOTFS/usr/bin/python3"
    exit 1
fi

if [ ! -f "$MUSL" ]; then
    log "ERROR: musl linker not found"
    exit 1
fi

# Restore host hostname
/system/bin/sh -c "echo $(getprop ro.product.model 2>/dev/null || echo Android) > /proc/sys/kernel/hostname" 2>/dev/null

# Start server on HOST using musl linker
cd "$ROOTFS"
env LD_LIBRARY_PATH="$PYLIB" nohup "$MUSL" "$ROOTFS/usr/bin/python3" "$SERVER" > "$ANK_DIR/logs/server.log" 2>&1 &
echo $! > "$SERVER_PID_FILE"

log "Server started (PID: $(cat $SERVER_PID_FILE)) | Arch: $ARCH | Musl: $MUSL"
log "Panel: http://localhost:8001"

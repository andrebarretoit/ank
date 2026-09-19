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

log "[ANK-Engine] Server Started"

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

# Ensure /dev nodes exist in ankfs for Python/PTY
mkdir -p "$ROOTFS/dev"
# Bind-mount host /dev nodes — mknod on Android creates regular files (SELinux)
for _dn in null urandom random tty ptmx console; do
    [ -e "/dev/$_dn" ] && mount --bind "/dev/$_dn" "$ROOTFS/dev/$_dn" 2>/dev/null
    [ -e "$ROOTFS/dev/$_dn" ] || mknod "$ROOTFS/dev/$_dn" c 1 3 2>/dev/null
    chmod 666 "$ROOTFS/dev/$_dn" 2>/dev/null
done

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

# Kernel 3.10 has no devtmpfs, and /data is mounted with nodev
# Mount tmpfs on /dev so pty.fork() and /dev/null work for server.py (WebSocket terminal)
# Check if devpts is mounted (not just /dev) - /dev may be tmpfs from manual mount but missing devpts
if ! mountpoint -q "$ROOTFS/dev/pts" 2>/dev/null; then
    umount "$ROOTFS/dev" 2>/dev/null
    mount -t tmpfs -o size=16m tmpfs "$ROOTFS/dev" 2>/dev/null
    # Bind-mount host /dev nodes — mknod on Android creates regular files (SELinux)
    for _dn in null zero random urandom tty ptmx console; do
        [ -e "/dev/$_dn" ] && mount --bind "/dev/$_dn" "$ROOTFS/dev/$_dn" 2>/dev/null
        [ -e "$ROOTFS/dev/$_dn" ] || mknod "$ROOTFS/dev/$_dn" c 1 3 2>/dev/null
        chmod 666 "$ROOTFS/dev/$_dn" 2>/dev/null
    done
    mkdir -p "$ROOTFS/dev/pts" "$ROOTFS/dev/shm" 2>/dev/null
    mount -t devpts devpts "$ROOTFS/dev/pts" 2>/dev/null
    log "Mounted tmpfs on /dev (kernel 3.10 workaround)"
fi

# Start server on HOST using musl linker
cd "$ROOTFS"
env LD_LIBRARY_PATH="$PYLIB" nohup "$MUSL" "$ROOTFS/usr/bin/python3" "$SERVER" > "$ANK_DIR/logs/server.log" 2>&1 &
echo $! > "$SERVER_PID_FILE"

log "Server started (PID: $(cat $SERVER_PID_FILE)) | Arch: $ARCH | Musl: $MUSL"
log "Panel: http://localhost:8001"

# Start sshd in ankfs (SSH access to ANK shell)
SSH_ENABLED="1"
SSH_PORT="2200"
if [ -f "$CONFIG" ]; then
    SE=$(grep -o '"ssh_enabled"[[:space:]]*:[[:space:]]*[a-z]*' "$CONFIG" 2>/dev/null | grep -o '[a-z]*$')
    [ "$SE" = "false" ] && SSH_ENABLED="0"
    SP=$(grep -o '"ssh_port"[[:space:]]*:[[:space:]]*[0-9]*' "$CONFIG" 2>/dev/null | grep -o '[0-9]*$')
    [ -n "$SP" ] && SSH_PORT="$SP"
fi

if [ "$SSH_ENABLED" = "1" ] && [ -f "$ROOTFS/usr/sbin/sshd" ]; then
    mkdir -p "$ROOTFS/run/ankd" 2>/dev/null
    mkdir -p "$ROOTFS/dev/pts" "$ROOTFS/dev/shm" 2>/dev/null
    mount -t devpts devpts "$ROOTFS/dev/pts" 2>/dev/null
    mount -t proc proc "$ROOTFS/proc" 2>/dev/null
    # Start sshd (no -D: sshd daemonizes itself via fork, survives parent exit)
    log "sshd config: port=$SSH_PORT rootfs=$ROOTFS"
    log "  sshd binary: $(ls -la "$ROOTFS/usr/sbin/sshd" 2>/dev/null || echo 'MISSING')"
    log "  host keys: rsa=$(ls "$ROOTFS/etc/ssh/ssh_host_rsa_key" 2>/dev/null || echo 'no') ed25519=$(ls "$ROOTFS/etc/ssh/ssh_host_ed25519_key" 2>/dev/null || echo 'no')"
    log "  dev/urandom: $(ls -la "$ROOTFS/dev/urandom" 2>/dev/null || echo 'MISSING')"
    log "  shadow: $(head -1 "$ROOTFS/etc/shadow" 2>/dev/null | cut -d: -f1 || echo 'MISSING')"
    chroot "$ROOTFS" /usr/sbin/sshd -t 2>&1 | while IFS= read -r line; do log "  sshd -t: $line"; done || true
    nohup chroot "$ROOTFS" /usr/sbin/sshd \
        -p "$SSH_PORT" \
        -o "PidFile=/run/ankd/sshd.pid" \
        -o "PasswordAuthentication=yes" \
        -o "PermitRootLogin=yes" \
        -o "ChallengeResponseAuthentication=no" \
        -e 2>&1 | while IFS= read -r line; do log "  sshd: $line"; done &
    sleep 2
    SSHD_PID=$(cat "$ROOTFS/run/ankd/sshd.pid" 2>/dev/null)
    if [ -n "$SSHD_PID" ] && kill -0 "$SSHD_PID" 2>/dev/null; then
        log "sshd started on port $SSH_PORT (PID: $SSHD_PID)"
    else
        log "ERROR: sshd failed to start on port $SSH_PORT"
        log "  sshd -t (config test):"
        chroot "$ROOTFS" /usr/sbin/sshd -t 2>&1 | while IFS= read -r line; do log "    $line"; done || true
    fi
else
    log "sshd disabled or sshd not found"
fi

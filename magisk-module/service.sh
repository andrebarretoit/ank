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
# Target file must exist before bind-mount; mknod fallback uses correct major/minor
for _dn in "null:1:3" "urandom:1:9" "random:1:8" "tty:5:0" "ptmx:5:2" "console:5:1"; do
    _name="${_dn%%:*}"; _rest="${_dn#*:}"; _maj="${_rest%%:*}"; _min="${_rest##*:}"
    [ -e "$ROOTFS/dev/$_name" ] || touch "$ROOTFS/dev/$_name" 2>/dev/null
    [ -e "/dev/$_name" ] && mount --bind "/dev/$_name" "$ROOTFS/dev/$_name" 2>/dev/null
    if [ ! -c "$ROOTFS/dev/$_name" ]; then
        rm -f "$ROOTFS/dev/$_name" 2>/dev/null
        mknod "$ROOTFS/dev/$_name" c "$_maj" "$_min" 2>/dev/null
    fi
    chmod 666 "$ROOTFS/dev/$_name" 2>/dev/null
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
    # Target must exist before bind-mount (fresh tmpfs is empty); correct major/minor fallback
    for _dn in "null:1:3" "zero:1:5" "random:1:8" "urandom:1:9" "tty:5:0" "ptmx:5:2" "console:5:1"; do
        _name="${_dn%%:*}"; _rest="${_dn#*:}"; _maj="${_rest%%:*}"; _min="${_rest##*:}"
        [ -e "$ROOTFS/dev/$_name" ] || touch "$ROOTFS/dev/$_name" 2>/dev/null
        [ -e "/dev/$_name" ] && mount --bind "/dev/$_name" "$ROOTFS/dev/$_name" 2>/dev/null
        if [ ! -c "$ROOTFS/dev/$_name" ]; then
            rm -f "$ROOTFS/dev/$_name" 2>/dev/null
            mknod "$ROOTFS/dev/$_name" c "$_maj" "$_min" 2>/dev/null
        fi
        chmod 666 "$ROOTFS/dev/$_name" 2>/dev/null
    done
    mkdir -p "$ROOTFS/dev/pts" "$ROOTFS/dev/shm" 2>/dev/null
    mount -t devpts -o mode=0620,ptmxmode=0666 devpts "$ROOTFS/dev/pts" 2>/dev/null
    log "Mounted tmpfs on /dev (kernel 3.10 workaround)"
fi

# Start server on HOST using musl linker
cd "$ROOTFS"
env LD_LIBRARY_PATH="$PYLIB" nohup "$MUSL" "$ROOTFS/usr/bin/python3" "$SERVER" > "$ANK_DIR/logs/server.log" 2>&1 &
echo $! > "$SERVER_PID_FILE"

log "Server started (PID: $(cat $SERVER_PID_FILE)) | Arch: $ARCH"
log "Panel: http://localhost:8001"

# One-time password fix: if shadow has locked hash (* or !), regenerate via chroot
# (install.sh may fail to generate compatible hash in Magisk installer context)
if grep -q "^root:\*:" "$ROOTFS/etc/shadow" 2>/dev/null || grep -q "^root:!:" "$ROOTFS/etc/shadow" 2>/dev/null; then
    ANK_PASS=$(grep -o '"password":"[^"]*"' "$CONFIG" 2>/dev/null | head -1 | cut -d'"' -f4)
    [ -z "$ANK_PASS" ] && ANK_PASS="ank123"
    ENC_PASS=$(chroot "$ROOTFS" /usr/bin/openssl passwd -6 "$ANK_PASS" 2>/dev/null)
    if [ -n "$ENC_PASS" ]; then
        SP_CHG=$(( $(date +%s) / 86400 ))
        printf "root:%s:%s:0:99999:7:::\nadmin:%s:%s:0:99999:7:::\n" "$ENC_PASS" "$SP_CHG" "$ENC_PASS" "$SP_CHG" > "$ROOTFS/etc/shadow"
        chmod 644 "$ROOTFS/etc/shadow"
        log "Password configured"
    fi
fi
# Ensure admin user exists in passwd
if ! grep -q "^admin:" "$ROOTFS/etc/passwd" 2>/dev/null; then
    echo "admin:x:1000:1000::/root:/ankcoreshell.sh" >> "$ROOTFS/etc/passwd"
    log "Admin user created"
fi
# Fix admin home permissions (uid 1000 needs access to /root)
chmod 755 "$ROOTFS/root" 2>/dev/null
# Clear Alpine default MOTD
: > "$ROOTFS/etc/motd" 2>/dev/null
# Ensure ankcoreshell is in /etc/shells
if ! grep -q "ankcoreshell" "$ROOTFS/etc/shells" 2>/dev/null; then
    echo "/ankcoreshell.sh" >> "$ROOTFS/etc/shells" 2>/dev/null
fi

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
    # /var doesn't exist on Android — create in /data and symlink for sshd's /var/empty
    mkdir -p /data/local/ank/var/empty 2>/dev/null
    chmod 755 /data/local/ank/var/empty 2>/dev/null
    [ ! -e /var ] && ln -sf /data/local/ank/var /var 2>/dev/null
    mkdir -p "$ROOTFS/dev/pts" "$ROOTFS/dev/shm" 2>/dev/null
    # Mount devpts FIRST so ptmx is created by devpts (not bind-mounted from host)
    umount "$ROOTFS/dev/pts" 2>/dev/null
    mount -t devpts -o mode=0620,ptmxmode=0666 devpts "$ROOTFS/dev/pts" 2>/dev/null
    # Remove host bind-mounted ptmx, replace with devpts ptmx so PTY slave is in same namespace
    umount "$ROOTFS/dev/ptmx" 2>/dev/null
    rm -f "$ROOTFS/dev/ptmx" 2>/dev/null
    ln -sf pts/ptmx "$ROOTFS/dev/ptmx" 2>/dev/null
    chmod 666 "$ROOTFS/dev/pts/ptmx" 2>/dev/null
    mount -t proc proc "$ROOTFS/proc" 2>/dev/null
    # Ensure /dev/urandom is a real char device — sshd/OpenSSL PRNG needs it
    if [ ! -c "$ROOTFS/dev/urandom" ]; then
        rm -f "$ROOTFS/dev/urandom" 2>/dev/null
        touch "$ROOTFS/dev/urandom" 2>/dev/null
        mount --bind /dev/urandom "$ROOTFS/dev/urandom" 2>/dev/null
        [ ! -c "$ROOTFS/dev/urandom" ] && { rm -f "$ROOTFS/dev/urandom" 2>/dev/null; mknod "$ROOTFS/dev/urandom" c 1 9 2>/dev/null; }
        chmod 666 "$ROOTFS/dev/urandom" 2>/dev/null
        [ -c "$ROOTFS/dev/urandom" ] && log "Fixed /dev/urandom (was not a device node)" || log "WARN: /dev/urandom still not a device node"
    fi
    log "sshd starting on port $SSH_PORT"
    chroot "$ROOTFS" /usr/sbin/sshd -t 2>&1 | while IFS= read -r line; do log "  sshd config: $line"; done || true
    nohup chroot "$ROOTFS" /usr/sbin/sshd \
        -p "$SSH_PORT" \
        -o "PidFile=/run/ankd/sshd.pid" \
        -o "PasswordAuthentication=yes" \
        -o "PermitRootLogin=yes" \
        -o "PermitTTY=yes" \
        -o "ChallengeResponseAuthentication=no" \
        -e 2>&1 | while IFS= read -r line; do log "  sshd: $line"; done &
    sleep 2
    SSHD_PID=$(cat "$ROOTFS/run/ankd/sshd.pid" 2>/dev/null)
    if [ -n "$SSHD_PID" ] && kill -0 "$SSHD_PID" 2>/dev/null; then
        log "sshd running on port $SSH_PORT (PID: $SSHD_PID)"
    else
        log "ERROR: sshd failed to start on port $SSH_PORT"
    fi
else
    log "sshd disabled or sshd not found"
fi

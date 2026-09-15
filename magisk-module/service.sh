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

# Ensure /dev nodes exist in ankfs for Python/PTY
mkdir -p "$ROOTFS/dev"
[ -e "$ROOTFS/dev/null" ] || mknod "$ROOTFS/dev/null" c 1 3 2>/dev/null
[ -e "$ROOTFS/dev/urandom" ] || mknod "$ROOTFS/dev/urandom" c 1 9 2>/dev/null
[ -e "$ROOTFS/dev/random" ] || mknod "$ROOTFS/dev/random" c 1 8 2>/dev/null
[ -e "$ROOTFS/dev/tty" ] || mknod "$ROOTFS/dev/tty" c 5 0 2>/dev/null
[ -e "$ROOTFS/dev/ptmx" ] || mknod "$ROOTFS/dev/ptmx" c 5 2 2>/dev/null
[ -e "$ROOTFS/dev/console" ] || mknod "$ROOTFS/dev/console" c 5 1 2>/dev/null
chmod 666 "$ROOTFS/dev/null" "$ROOTFS/dev/urandom" "$ROOTFS/dev/random" "$ROOTFS/dev/tty" "$ROOTFS/dev/ptmx" "$ROOTFS/dev/console" 2>/dev/null

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
    mknod "$ROOTFS/dev/null" c 1 3 2>/dev/null; chmod 666 "$ROOTFS/dev/null" 2>/dev/null
    mknod "$ROOTFS/dev/zero" c 1 5 2>/dev/null; chmod 666 "$ROOTFS/dev/zero" 2>/dev/null
    mknod "$ROOTFS/dev/random" c 1 8 2>/dev/null; chmod 666 "$ROOTFS/dev/random" 2>/dev/null
    mknod "$ROOTFS/dev/urandom" c 1 9 2>/dev/null; chmod 666 "$ROOTFS/dev/urandom" 2>/dev/null
    mknod "$ROOTFS/dev/tty" c 5 0 2>/dev/null; chmod 666 "$ROOTFS/dev/tty" 2>/dev/null
    mknod "$ROOTFS/dev/ptmx" c 5 2 2>/dev/null; chmod 666 "$ROOTFS/dev/ptmx" 2>/dev/null
    mknod "$ROOTFS/dev/console" c 5 1 2>/dev/null; chmod 666 "$ROOTFS/dev/console" 2>/dev/null
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

# Install openssh if not present (tarball may not include it)
if [ ! -e "$ROOTFS/usr/sbin/sshd" ]; then
    log "sshd not found in ankfs, installing openssh..."
    mount -t proc proc "$ROOTFS/proc" 2>/dev/null
    mkdir -p "$ROOTFS/dev" 2>/dev/null
    if ! mountpoint -q "$ROOTFS/dev" 2>/dev/null; then
        mount -t tmpfs -o size=16m tmpfs "$ROOTFS/dev" 2>/dev/null
    fi
    [ -e "$ROOTFS/dev/null" ] || mknod "$ROOTFS/dev/null" c 1 3 2>/dev/null
    chmod 666 "$ROOTFS/dev/null" 2>/dev/null
    [ -e "$ROOTFS/dev/urandom" ] || mknod "$ROOTFS/dev/urandom" c 1 9 2>/dev/null
    chmod 666 "$ROOTFS/dev/urandom" 2>/dev/null
    echo "nameserver 8.8.8.8" > "$ROOTFS/etc/resolv.conf" 2>/dev/null
    echo "nameserver 8.8.4.4" >> "$ROOTFS/etc/resolv.conf" 2>/dev/null

    chroot "$ROOTFS" /sbin/apk add --no-cache openssh bash shadow 2>&1 | while IFS= read -r line; do
        log "  apk: $line"
    done

    # Configure sshd
    mkdir -p "$ROOTFS/etc/ssh" "$ROOTFS/run/sshd" 2>/dev/null
    cat > "$ROOTFS/etc/ssh/sshd_config" << 'SSHEOF'
Port 2200
PermitRootLogin yes
PasswordAuthentication yes
ChallengeResponseAuthentication no
UsePAM no
PidFile /run/sshd.pid
Subsystem sftp /usr/libexec/sftp-server
SSHEOF
    chroot "$ROOTFS" /usr/bin/ssh-keygen -A 2>/dev/null || true

    # Install ANK shell + MOTD
    cp "$ROOTFS/opt/ank/server/ank-shell.sh" "$ROOTFS/ank-shell.sh" 2>/dev/null
    chmod 755 "$ROOTFS/ank-shell.sh" 2>/dev/null
    sed -i '1s|#!/system/bin/sh|#!/bin/sh|' "$ROOTFS/ank-shell.sh" 2>/dev/null
    sed -i 's|^root:.*|root:/bin/sh|' "$ROOTFS/etc/passwd" 2>/dev/null

    mkdir -p "$ROOTFS/etc/profile.d" 2>/dev/null
    cat > "$ROOTFS/etc/profile.d/ank-motd.sh" << 'MOTDEOF'
ank_motd() {
    read _ u1 n1 s1 _ < /proc/stat
    sleep 1
    read _ u2 n2 s2 _ < /proc/stat
    total=$(( (u2+n2+s2) - (u1+n1+s1) ))
    idle=$(( u2 - u1 ))
    if [ "$total" -gt 0 ]; then
        cpu=$(( (total - idle) * 100 / total ))
    else
        cpu=0
    fi
    mem_total=$(awk '/^MemTotal/{print $2}' /proc/meminfo)
    mem_avail=$(awk '/^MemAvailable/{print $2}' /proc/meminfo)
    if [ -n "$mem_total" ] && [ "$mem_total" -gt 0 ] 2>/dev/null; then
        mem_used=$(( (mem_total - mem_avail) * 100 / mem_total ))
    else
        mem_used=0
    fi
    up=$(awk '{d=int($1/86400);h=int(($1%86400)/3600);m=int(($1%3600)/60);printf "%dd %dh %dm",d,h,m}' /proc/uptime)
    cat << 'ART'

          /$$$$$$  /$$   /$$ /$$   /$$
         /$$__  $$| $$$ | $$| $$  /$$/
        | $$  \ $$| $$$$| $$| $$ /$$/
        | $$$$$$$$| $$ $$ $$| $$$$$/
        | $$__  $$| $$  $$$$| $$  $$
        | $$  | $$| $$\  $$$| $$\  $$
        | $$  | $$| $$ \  $$| $$ \  $$
        |__/  |__/|__/  \__/|__/  \__/

         Android Konteiner | ANK CLI
ART
    printf "       CPU: %s%%  MEM: %s%%  UPTIME: %s\n" "$cpu" "$mem_used" "$up"
}
ank_motd
unset ank_motd
MOTDEOF

    umount "$ROOTFS/proc" 2>/dev/null
    umount "$ROOTFS/dev" 2>/dev/null
    log "openssh installed + ANK shell configured"
fi

# Ensure ANK shell + MOTD exist (for installs that already had openssh)
if [ -e "$ROOTFS/usr/sbin/sshd" ]; then
    # ANK shell
    if [ ! -e "$ROOTFS/ank-shell.sh" ] || ! grep -q "ANK Shell" "$ROOTFS/ank-shell.sh" 2>/dev/null; then
        cp "$ROOTFS/opt/ank/server/ank-shell.sh" "$ROOTFS/ank-shell.sh" 2>/dev/null
        chmod 755 "$ROOTFS/ank-shell.sh" 2>/dev/null
        sed -i '1s|#!/system/bin/sh|#!/bin/sh|' "$ROOTFS/ank-shell.sh" 2>/dev/null
    fi
    # Set root shell to ank-shell
    if ! grep -q "ank-shell" "$ROOTFS/etc/passwd" 2>/dev/null; then
        sed -i 's|^root:.*|root:/bin/sh|' "$ROOTFS/etc/passwd" 2>/dev/null
    fi
    # ANK MOTD (dynamic)
    if ! grep -q "ank_motd" "$ROOTFS/etc/profile.d/ank-motd.sh" 2>/dev/null; then
        mkdir -p "$ROOTFS/etc/profile.d" 2>/dev/null
        cat > "$ROOTFS/etc/profile.d/ank-motd.sh" << 'MOTDEOF'
ank_motd() {
    read _ u1 n1 s1 _ < /proc/stat
    sleep 1
    read _ u2 n2 s2 _ < /proc/stat
    total=$(( (u2+n2+s2) - (u1+n1+s1) ))
    idle=$(( u2 - u1 ))
    if [ "$total" -gt 0 ]; then
        cpu=$(( (total - idle) * 100 / total ))
    else
        cpu=0
    fi
    mem_total=$(awk '/^MemTotal/{print $2}' /proc/meminfo)
    mem_avail=$(awk '/^MemAvailable/{print $2}' /proc/meminfo)
    if [ -n "$mem_total" ] && [ "$mem_total" -gt 0 ] 2>/dev/null; then
        mem_used=$(( (mem_total - mem_avail) * 100 / mem_total ))
    else
        mem_used=0
    fi
    up=$(awk '{d=int($1/86400);h=int(($1%86400)/3600);m=int(($1%3600)/60);printf "%dd %dh %dm",d,h,m}' /proc/uptime)
    cat << 'ART'

          /$$$$$$  /$$   /$$ /$$   /$$
         /$$__  $$| $$$ | $$| $$  /$$/
        | $$  \ $$| $$$$| $$| $$ /$$/
        | $$$$$$$$| $$ $$ $$| $$$$$/
        | $$__  $$| $$  $$$$| $$  $$
        | $$  | $$| $$\  $$$| $$\  $$
        | $$  | $$| $$ \  $$| $$ \  $$
        |__/  |__/|__/  \__/|__/  \__/

         Android Konteiner | ANK CLI
ART
    printf "       CPU: %s%%  MEM: %s%%  UPTIME: %s\n" "$cpu" "$mem_used" "$up"
}
ank_motd
unset ank_motd
MOTDEOF
    fi
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
    mkdir -p "$ROOTFS/dev/pts" "$ROOTFS/dev/shm" 2>/dev/null
    mount -t devpts devpts "$ROOTFS/dev/pts" 2>/dev/null
    mount -t proc proc "$ROOTFS/proc" 2>/dev/null
    # Set root password from config
    ANK_PASS=$(grep -o '"password":"[^"]*"' "$CONFIG" 2>/dev/null | head -1 | cut -d'"' -f4)
    [ -z "$ANK_PASS" ] && ANK_PASS="ank123"
    # Generate hash and write to shadow directly
    if [ -f "$ROOTFS/usr/bin/openssl" ] || [ -f "$ROOTFS/usr/sbin/openssl" ]; then
        ENC_PASS=$(chroot "$ROOTFS" /usr/bin/openssl passwd -1 "$ANK_PASS" 2>/dev/null || \
                   chroot "$ROOTFS" /usr/sbin/openssl passwd -1 "$ANK_PASS" 2>/dev/null)
        if [ -n "$ENC_PASS" ] && [ -f "$ROOTFS/etc/shadow" ]; then
            sed -i "s|^root:[^:]*:|root:${ENC_PASS}:|" "$ROOTFS/etc/shadow" 2>/dev/null
            log "Password set via shadow (openssl)"
        fi
    fi
    # Generate host keys if missing
    [ ! -f "$ROOTFS/etc/ssh/ssh_host_rsa_key" ] && \
        chroot "$ROOTFS" /usr/bin/ssh-keygen -A 2>/dev/null || true
    # Start sshd
    chroot "$ROOTFS" /usr/sbin/sshd \
        -D -p "$SSH_PORT" \
        -o "PidFile=/run/ankd/sshd.pid" \
        -o "PasswordAuthentication=yes" \
        -o "PermitRootLogin=yes" \
        -o "ChallengeResponseAuthentication=no" \
        </dev/null >/dev/null 2>&1 &
    SSHD_PID=$!
    log "sshd started on port $SSH_PORT (PID: $SSHD_PID)"
else
    log "sshd disabled or sshd not found"
fi

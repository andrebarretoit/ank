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

# Ensure ANK shell + MOTD exist
if [ -e "$ROOTFS/usr/sbin/sshd" ]; then
    # ANK shell
    if [ ! -e "$ROOTFS/ank-shell.sh" ] || ! grep -q "ANK Shell" "$ROOTFS/ank-shell.sh" 2>/dev/null; then
        cp "$ROOTFS/opt/ank/server/ank-shell.sh" "$ROOTFS/ank-shell.sh" 2>/dev/null
        chmod 755 "$ROOTFS/ank-shell.sh" 2>/dev/null
        sed -i '1s|#!/system/bin/sh|#!/bin/sh|' "$ROOTFS/ank-shell.sh" 2>/dev/null
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
    # Generate SHA-512 hash and write to shadow directly
    if [ -f "$ROOTFS/usr/bin/openssl" ] || [ -f "$ROOTFS/usr/sbin/openssl" ]; then
        ENC_PASS=$(chroot "$ROOTFS" /usr/bin/openssl passwd -6 "$ANK_PASS" 2>/dev/null || \
                   chroot "$ROOTFS" /usr/sbin/openssl passwd -6 "$ANK_PASS" 2>/dev/null)
        if [ -n "$ENC_PASS" ] && [ -f "$ROOTFS/etc/shadow" ]; then
            sed -i "s|^root:[^:]*:|root:${ENC_PASS}:|" "$ROOTFS/etc/shadow" 2>/dev/null
            # Create admin user if missing (pfSense-style: admin = root uid 0)
            if ! grep -q "^admin:" "$ROOTFS/etc/passwd" 2>/dev/null; then
                echo "admin:x:0:0:Admin:/root:/bin/sh" >> "$ROOTFS/etc/passwd"
                echo "admin:${ENC_PASS}:19000:0:99999:7:::" >> "$ROOTFS/etc/shadow"
                log "Created admin user in passwd+shadow"
            else
                sed -i "s|^admin:[^:]*:|admin:${ENC_PASS}:|" "$ROOTFS/etc/shadow" 2>/dev/null
            fi
            log "Password set via shadow (openssl SHA-512)"
        fi
    fi
    # Generate host keys on the HOST (no chroot needed — avoids segfault)
    mkdir -p "$ROOTFS/etc/ssh" 2>/dev/null
    if [ ! -f "$ROOTFS/etc/ssh/ssh_host_rsa_key" ] || [ ! -f "$ROOTFS/etc/ssh/ssh_host_ed25519_key" ]; then
        KEYGEN_ERR=""
        # Strategy 1: openssl on host (most reliable — Android always has openssl)
        if command -v openssl >/dev/null 2>&1 || [ -x /system/bin/openssl ]; then
            OPENSSL=$(command -v openssl 2>/dev/null || echo /system/bin/openssl)
            log "Generating host keys with: $OPENSSL (openssl)"
            if [ ! -f "$ROOTFS/etc/ssh/ssh_host_rsa_key" ]; then
                $OPENSSL genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -outform PEM -out "$ROOTFS/etc/ssh/ssh_host_rsa_key" 2>"$ANK_DIR/logs/ssh-keygen-rsa.err" && \
                $OPENSSL rsa -in "$ROOTFS/etc/ssh/ssh_host_rsa_key" -pubout -out "$ROOTFS/etc/ssh/ssh_host_rsa_key.pub" 2>>"$ANK_DIR/logs/ssh-keygen-rsa.err"
                if [ -f "$ROOTFS/etc/ssh/ssh_host_rsa_key" ]; then
                    chmod 600 "$ROOTFS/etc/ssh/ssh_host_rsa_key"
                    chmod 644 "$ROOTFS/etc/ssh/ssh_host_rsa_key.pub"
                    log "RSA host key generated (openssl)"
                else
                    KEYGEN_ERR="rsa"
                    log "WARN: RSA key generation failed: $(cat "$ANK_DIR/logs/ssh-keygen-rsa.err" 2>/dev/null)"
                fi
            fi
            if [ ! -f "$ROOTFS/etc/ssh/ssh_host_ed25519_key" ]; then
                $OPENSSL genpkey -algorithm Ed25519 -outform PEM -out "$ROOTFS/etc/ssh/ssh_host_ed25519_key" 2>"$ANK_DIR/logs/ssh-keygen-ed25519.err" && \
                $OPENSSL pkey -in "$ROOTFS/etc/ssh/ssh_host_ed25519_key" -pubout -out "$ROOTFS/etc/ssh/ssh_host_ed25519_key.pub" 2>>"$ANK_DIR/logs/ssh-keygen-ed25519.err"
                if [ -f "$ROOTFS/etc/ssh/ssh_host_ed25519_key" ]; then
                    chmod 600 "$ROOTFS/etc/ssh/ssh_host_ed25519_key"
                    chmod 644 "$ROOTFS/etc/ssh/ssh_host_ed25519_key.pub"
                    log "Ed25519 host key generated (openssl)"
                else
                    KEYGEN_ERR="${KEYGEN_ERR:+$KEYGEN_ERR, }ed25519"
                    log "WARN: Ed25519 key generation failed: $(cat "$ANK_DIR/logs/ssh-keygen-ed25519.err" 2>/dev/null)"
                fi
            fi
        fi
        # Strategy 2: ssh-keygen on host (if openssl failed or not available)
        if [ ! -f "$ROOTFS/etc/ssh/ssh_host_rsa_key" ] || [ ! -f "$ROOTFS/etc/ssh/ssh_host_ed25519_key" ]; then
            KEYGEN=""
            if command -v ssh-keygen >/dev/null 2>&1; then
                KEYGEN="ssh-keygen"
            elif [ -x /system/bin/ssh-keygen ]; then
                KEYGEN="/system/bin/ssh-keygen"
            fi
            if [ -n "$KEYGEN" ]; then
                log "Generating host keys with: $KEYGEN (ssh-keygen)"
                if [ ! -f "$ROOTFS/etc/ssh/ssh_host_rsa_key" ]; then
                    eval $KEYGEN -t rsa -b 3072 -f "$ROOTFS/etc/ssh/ssh_host_rsa_key" -N "" -q 2>"$ANK_DIR/logs/ssh-keygen-rsa.err"
                    if [ -f "$ROOTFS/etc/ssh/ssh_host_rsa_key" ]; then
                        chmod 600 "$ROOTFS/etc/ssh/ssh_host_rsa_key"
                        chmod 644 "$ROOTFS/etc/ssh/ssh_host_rsa_key.pub"
                        log "RSA host key generated (ssh-keygen)"
                    else
                        KEYGEN_ERR="${KEYGEN_ERR:+$KEYGEN_ERR, }rsa"
                        log "WARN: RSA key generation failed: $(cat "$ANK_DIR/logs/ssh-keygen-rsa.err" 2>/dev/null)"
                    fi
                fi
                if [ ! -f "$ROOTFS/etc/ssh/ssh_host_ed25519_key" ]; then
                    eval $KEYGEN -t ed25519 -f "$ROOTFS/etc/ssh/ssh_host_ed25519_key" -N "" -q 2>"$ANK_DIR/logs/ssh-keygen-ed25519.err"
                    if [ -f "$ROOTFS/etc/ssh/ssh_host_ed25519_key" ]; then
                        chmod 600 "$ROOTFS/etc/ssh/ssh_host_ed25519_key"
                        chmod 644 "$ROOTFS/etc/ssh/ssh_host_ed25519_key.pub"
                        log "Ed25519 host key generated (ssh-keygen)"
                    else
                        KEYGEN_ERR="${KEYGEN_ERR:+$KEYGEN_ERR, }ed25519"
                        log "WARN: Ed25519 key generation failed: $(cat "$ANK_DIR/logs/ssh-keygen-ed25519.err" 2>/dev/null)"
                    fi
                fi
            fi
        fi
        # Strategy 3: chroot ssh-keygen with LD_LIBRARY_PATH (last resort)
        if [ ! -f "$ROOTFS/etc/ssh/ssh_host_rsa_key" ] || [ ! -f "$ROOTFS/etc/ssh/ssh_host_ed25519_key" ]; then
            if [ -f "$ROOTFS/usr/bin/ssh-keygen" ]; then
                log "Generating host keys with: chroot + LD_LIBRARY_PATH (last resort)"
                if [ ! -f "$ROOTFS/etc/ssh/ssh_host_rsa_key" ]; then
                    LD_LIBRARY_PATH="$ROOTFS/usr/lib:$ROOTFS/lib" chroot "$ROOTFS" /usr/bin/ssh-keygen -t rsa -b 3072 -f /etc/ssh/ssh_host_rsa_key -N "" -q 2>"$ANK_DIR/logs/ssh-keygen-rsa.err"
                    if [ -f "$ROOTFS/etc/ssh/ssh_host_rsa_key" ]; then
                        chmod 600 "$ROOTFS/etc/ssh/ssh_host_rsa_key"
                        chmod 644 "$ROOTFS/etc/ssh/ssh_host_rsa_key.pub"
                        log "RSA host key generated (chroot)"
                    else
                        KEYGEN_ERR="${KEYGEN_ERR:+$KEYGEN_ERR, }rsa"
                        log "WARN: RSA key generation failed: $(cat "$ANK_DIR/logs/ssh-keygen-rsa.err" 2>/dev/null)"
                    fi
                fi
                if [ ! -f "$ROOTFS/etc/ssh/ssh_host_ed25519_key" ]; then
                    LD_LIBRARY_PATH="$ROOTFS/usr/lib:$ROOTFS/lib" chroot "$ROOTFS" /usr/bin/ssh-keygen -t ed25519 -f /etc/ssh/ssh_host_ed25519_key -N "" -q 2>"$ANK_DIR/logs/ssh-keygen-ed25519.err"
                    if [ -f "$ROOTFS/etc/ssh/ssh_host_ed25519_key" ]; then
                        chmod 600 "$ROOTFS/etc/ssh/ssh_host_ed25519_key"
                        chmod 644 "$ROOTFS/etc/ssh/ssh_host_ed25519_key.pub"
                        log "Ed25519 host key generated (chroot)"
                    else
                        KEYGEN_ERR="${KEYGEN_ERR:+$KEYGEN_ERR, }ed25519"
                        log "WARN: Ed25519 key generation failed: $(cat "$ANK_DIR/logs/ssh-keygen-ed25519.err" 2>/dev/null)"
                    fi
                fi
            fi
        fi
        if [ -n "$KEYGEN_ERR" ]; then
            log "WARN: Host key generation failed for: $KEYGEN_ERR"
        fi
        if [ ! -f "$ROOTFS/etc/ssh/ssh_host_rsa_key" ] && [ ! -f "$ROOTFS/etc/ssh/ssh_host_ed25519_key" ]; then
            log "ERROR: No host keys available — sshd will fail to start"
        fi
    else
        # Keys already exist — ensure permissions are correct
        chmod 600 "$ROOTFS/etc/ssh/ssh_host_rsa_key" 2>/dev/null
        chmod 644 "$ROOTFS/etc/ssh/ssh_host_rsa_key.pub" 2>/dev/null
        chmod 600 "$ROOTFS/etc/ssh/ssh_host_ed25519_key" 2>/dev/null
        chmod 644 "$ROOTFS/etc/ssh/ssh_host_ed25519_key.pub" 2>/dev/null
    fi

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
    SSHD_PID=$!
    sleep 2
    if kill -0 "$SSHD_PID" 2>/dev/null; then
        log "sshd started on port $SSH_PORT (PID: $SSHD_PID)"
    else
        log "ERROR: sshd failed to start on port $SSH_PORT"
        log "  sshd -t (config test):"
        chroot "$ROOTFS" /usr/sbin/sshd -t 2>&1 | while IFS= read -r line; do log "    $line"; done || true
    fi
else
    log "sshd disabled or sshd not found"
fi

#!/system/bin/sh
ANK_DIR=/data/local/ank/ankfs
ANK_SDCARD="/sdcard/AndroidKonteiner"
ANK_LOG="$ANK_DIR/../logs/server.log"

# Detect architecture
ARCH=$(uname -m)
case "$ARCH" in
    aarch64|arm64)  MUSL="$ANK_DIR/lib/ld-musl-aarch64.so.1" ;;
    armv7*|armhf)   MUSL="$ANK_DIR/lib/ld-musl-armhf.so.1" ;;
    x86_64)         MUSL="$ANK_DIR/lib/ld-musl-x86_6.1" ;;
    *)              MUSL=$(find "$ANK_DIR/lib" -name "ld-musl-*.so.*" 2>/dev/null | head -1) ;;
esac

[ ! -f "$MUSL" ] && MUSL=$(find "$ANK_DIR/lib" -name "ld-musl-*.so.*" 2>/dev/null | head -1)

# Install openssh if not present (ankfs tarball may not include it)
if [ ! -e "$ANK_DIR/usr/sbin/sshd" ]; then
    echo "[START] sshd not found, installing openssh..."
    # Setup minimal chroot env for apk
    mount -t proc proc "$ANK_DIR/proc" 2>/dev/null
    mkdir -p "$ANK_DIR/dev" 2>/dev/null
    mount -t tmpfs -o size=16m tmpfs "$ANK_DIR/dev" 2>/dev/null
    [ -e "$ANK_DIR/dev/null" ] || mknod "$ANK_DIR/dev/null" c 1 3 2>/dev/null
    chmod 666 "$ANK_DIR/dev/null" 2>/dev/null
    [ -e "$ANK_DIR/dev/urandom" ] || mknod "$ANK_DIR/dev/urandom" c 1 9 2>/dev/null
    chmod 666 "$ANK_DIR/dev/urandom" 2>/dev/null
    echo "nameserver 8.8.8.8" > "$ANK_DIR/etc/resolv.conf" 2>/dev/null

    # Install via chroot + musl
    chroot "$ANK_DIR" /sbin/apk add --no-cache openssh bash shadow 2>&1 | tee -a "$ANK_LOG"

    # Configure sshd
    mkdir -p "$ANK_DIR/etc/ssh" "$ANK_DIR/run/sshd" 2>/dev/null
    cat > "$ANK_DIR/etc/ssh/sshd_config" << 'SSHEOF'
Port 8022
PermitRootLogin yes
PasswordAuthentication yes
ChallengeResponseAuthentication no
UsePAM no
PidFile /run/sshd.pid
SSHEOF
    chroot "$ANK_DIR" /usr/bin/ssh-keygen -A 2>/dev/null || true
    mkdir -p "$ANK_DIR/root/.ssh" 2>/dev/null
    chmod 700 "$ANK_DIR/root/.ssh" 2>/dev/null
    touch "$ANK_DIR/root/.ssh/authorized_keys" 2>/dev/null
    chmod 600 "$ANK_DIR/root/.ssh/authorized_keys" 2>/dev/null

    umount "$ANK_DIR/proc" 2>/dev/null
    umount "$ANK_DIR/dev" 2>/dev/null
    echo "[START] openssh installed"
fi

cd "$ANK_DIR"
env LD_LIBRARY_PATH="$ANK_DIR/usr/lib:$ANK_DIR/lib" setsid "$MUSL" "$ANK_DIR/usr/bin/python3" "$ANK_DIR/opt/ank/server.py" </dev/null >"$ANK_LOG" 2>&1 &

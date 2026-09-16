#!/system/bin/sh
# ============================================================
# ANK - Build & export ankcore tarball
# Packages existing ankfs into tarball and exports to
# /sdcard/Download/ank-exports/ank-prebuild-{ARCH}.tar.gz
#
# If called standalone (not from install.sh), installs ALL
# packages needed for offline use before packaging.
#
# Handshake protocol (called by install.sh):
#   1. install.sh creates .tarball_request
#   2. This script touches .tarball_ack (acknowledged)
#   3. This script does the work
#   4. This script touches .tarball_done (finished)
# ============================================================

ANK_DIR="/data/local/ank"
ANKFS="$ANK_DIR/ankfs"
ANKCORE_DIR="$ANK_DIR/cache"
EXPORT_DIR="/sdcard/Download/ank-exports"
LOG="$ANK_DIR/logs/build-tarball.log"

# Full list of packages needed for offline use
# Covers: ankfs (python3, openssh, bash, shadow) + container base image (sshpass, nginx)
OFFLINE_PKGS="python3 openssl openssh bash busybox shadow sshpass nginx"

mkdir -p "$ANKCORE_DIR" "$ANK_DIR/logs" "$EXPORT_DIR"

# ============================================================
# Handshake - respond to install.sh if it's waiting
# ============================================================
SIGNAL_DIR="$ANK_DIR/cache"
REQUEST="$SIGNAL_DIR/.tarball_request"
ACK="$SIGNAL_DIR/.tarball_ack"
DONE="$SIGNAL_DIR/.tarball_done"

if [ -f "$REQUEST" ]; then
    touch "$ACK"
    echo "Handshake: acknowledged install request"
fi

# ============================================================
# Detect architecture
# ============================================================
ARCH=$(uname -m)
case "$ARCH" in
    aarch64|arm64)       ARCH_NAME="aarch64" ;;
    armv7*|armhf|armv8*) ARCH_NAME="armv7" ;;
    x86_64)              ARCH_NAME="x86_64" ;;
    *)                   ARCH_NAME="$ARCH" ;;
esac

TARBALL="$ANKCORE_DIR/ankcore-${ARCH_NAME}.tar.gz"
OUT="$EXPORT_DIR/ank-prebuild-${ARCH_NAME}.tar.gz"

echo "=== ANK Build Tarball > $(date) ===" > "$LOG"
echo "Architecture: $ARCH_NAME" >> "$LOG"

# ============================================================
# Validate ankfs
# ============================================================
if [ ! -d "$ANKFS" ] || [ ! -f "$ANKFS/bin/sh" ]; then
    echo "ERROR: ankfs not found at $ANKFS" | tee -a "$LOG"
    [ -f "$REQUEST" ] && touch "$DONE"
    exit 1
fi

# ============================================================
# If called standalone (not from install.sh), ensure all
# offline packages are installed in ankfs before packaging
# ============================================================
if [ ! -f "$REQUEST" ]; then
    echo "Standalone mode: ensuring all offline packages are installed..." | tee -a "$LOG"
    # Setup DNS
    mkdir -p "$ANKFS/etc/apk" "$ANKFS/var/cache/apk" 2>/dev/null
    echo "nameserver 8.8.8.8" > "$ANKFS/etc/resolv.conf" 2>/dev/null
    echo "nameserver 8.8.4.4" >> "$ANKFS/etc/resolv.conf" 2>/dev/null
    echo "http://dl-cdn.alpinelinux.org/alpine/v3.20/main" > "$ANKFS/etc/apk/repositories" 2>/dev/null
    echo "http://dl-cdn.alpinelinux.org/alpine/v3.20/community" >> "$ANKFS/etc/apk/repositories" 2>/dev/null

    mount -t proc proc "$ANKFS/proc" 2>/dev/null
    if [ -f "$ANKFS/sbin/apk" ] || [ -f "$ANKFS/usr/bin/apk" ]; then
        echo "Installing $OFFLINE_PKGS..." | tee -a "$LOG"
        chroot "$ANKFS" /bin/sh -c "export PATH=/sbin:/usr/sbin:/bin:/usr/bin; apk update && apk add --no-cache $OFFLINE_PKGS" 2>>"$LOG"
        RET=$?
        umount "$ANKFS/proc" 2>/dev/null
        if [ $RET -ne 0 ]; then
            echo "WARN: Some packages may have failed (rc=$RET)" | tee -a "$LOG"
        fi
    else
        umount "$ANKFS/proc" 2>/dev/null
        echo "WARN: apk not found in ankfs, skipping package install" | tee -a "$LOG"
    fi

    # Setup busybox symlinks
    if [ -f "$ANKFS/bin/busybox" ]; then
        chroot "$ANKFS" /bin/busybox --install -s /bin 2>/dev/null
    fi

    # Configure sshd
    if [ -d "$ANKFS/etc/ssh" ]; then
        sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        sed -i '/^UsePAM/d' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        mkdir -p "$ANKFS/etc/ssh/sshd_config.d"
        cat > "$ANKFS/etc/ssh/ank-sshd.conf" << 'SSHEOF'
Port 2200
ListenAddress 0.0.0.0
PermitRootLogin yes
PasswordAuthentication yes
ChallengeResponseAuthentication no
X11Forwarding no
AllowTcpForwarding no
PidFile /run/ankd/sshd.pid
Subsystem sftp internal-sftp
SSHEOF
        if [ -f "$ANKFS/etc/ssh/sshd_config" ]; then
            grep -v "^Port \|^ListenAddress \|^PermitRootLogin \|^PasswordAuthentication \|^ChallengeResponse \|^X11Forwarding \|^AllowTcpForwarding \|^PidFile \|^Subsystem sftp" \
                "$ANKFS/etc/ssh/sshd_config" > "$ANKFS/etc/ssh/sshd_config.tmp" 2>/dev/null
            cat "$ANKFS/etc/ssh/ank-sshd.conf" >> "$ANKFS/etc/ssh/sshd_config.tmp"
            mv "$ANKFS/etc/ssh/sshd_config.tmp" "$ANKFS/etc/ssh/sshd_config"
        fi
    fi

    # Generate host keys
    if [ -f "$ANKFS/usr/bin/ssh-keygen" ]; then
        chroot "$ANKFS" /usr/bin/ssh-keygen -A 2>>"$LOG" || true
    fi

    # SSH dirs
    mkdir -p "$ANKFS/root/.ssh" "$ANKFS/run/sshd" "$ANKFS/run/ankd"
    chmod 700 "$ANKFS/root/.ssh"
    touch "$ANKFS/root/.ssh/authorized_keys"
    chmod 600 "$ANKFS/root/.ssh/authorized_keys"

    echo "Standalone: packages and config ready" | tee -a "$LOG"
fi

# ============================================================
# Verify all offline packages are present
# ============================================================
echo "Verifying offline packages in ankfs..." | tee -a "$LOG"
MISSING=""
for bin in python3 ssh sshd bash nginx chpasswd ssh-keygen; do
    FOUND=0
    for p in "$ANKFS/usr/bin/$bin" "$ANKFS/bin/$bin" "$ANKFS/usr/sbin/$bin" "$ANKFS/usr/local/bin/$bin"; do
        [ -f "$p" ] || [ -L "$p" ] && FOUND=1 && break
    done
    if [ $FOUND -eq 0 ]; then
        MISSING="$MISSING $bin"
        echo "WARN: $bin not found in ankfs" | tee -a "$LOG"
    fi
done
# Check libraries (libssl, libcrypto, libpython3)
for lib in libssl libcrypto libpython3 libz libffi; do
    FOUND=0
    for p in "$ANKFS/usr/lib/$lib"*.so* "$ANKFS/lib/$lib"*.so*; do
        [ -f "$p" ] || [ -L "$p" ] && FOUND=1 && break
    done
    if [ $FOUND -eq 0 ]; then
        MISSING="$MISSING lib:$lib"
        echo "WARN: $lib not found in ankfs" | tee -a "$LOG"
    fi
done
if [ -n "$MISSING" ]; then
    echo "WARN: Missing:$MISSING (containers may need network for these)" | tee -a "$LOG"
else
    echo "OK: All offline packages verified" | tee -a "$LOG"
fi

# ============================================================
# Package existing ankfs into tarball
# ============================================================
echo "Packaging ankfs from $ANKFS..." | tee -a "$LOG"
rm -f "$TARBALL"
cd "$ANKFS" && tar czf "$TARBALL" . 2>>"$LOG"; cd /
if [ ! -s "$TARBALL" ]; then
    echo "ERROR: Tarball creation failed" | tee -a "$LOG"
    [ -f "$REQUEST" ] && touch "$DONE"
    exit 1
fi
FSIZE=$(stat -c%s "$TARBALL" 2>/dev/null || echo 0)
echo "Tarball created: ${FSIZE} bytes" | tee -a "$LOG"

# ============================================================
# Export to Download/ank-exports/
# ============================================================
mkdir -p "$EXPORT_DIR"
cp "$TARBALL" "$OUT" 2>/dev/null
if [ -s "$OUT" ]; then
    OUT_SIZE=$(du -h "$OUT" | cut -f1)
    echo "Exported: $OUT ($OUT_SIZE)" | tee -a "$LOG"
else
    echo "WARN: Failed to export to sdcard, tarball at: $TARBALL" | tee -a "$LOG"
fi

echo "=== Done ===" | tee -a "$LOG"

# ============================================================
# Signal install.sh that we're done
# ============================================================
[ -f "$REQUEST" ] && touch "$DONE"

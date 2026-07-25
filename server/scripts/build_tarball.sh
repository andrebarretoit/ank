#!/system/bin/sh
# ============================================================
# ANK - Build ankcore tarball (temporary dev tool)
# Generates ankcore-{arch}.tar.gz and exports to /sdcard/Download
# Safe to add/remove - does not affect install flow
# ============================================================

ANK_DIR="/data/local/ank"
ANKCORE_DIR="$ANK_DIR/cache"
SDCARD="/sdcard/Download"
LOG="/data/local/ank/logs/build-tarball.log"

mkdir -p "$ANKCORE_DIR" "$ANK_DIR/logs"

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

ARCH=$(uname -m)
case "$ARCH" in
    aarch64|arm64)  ARCH_NAME="aarch64" ;;
    armv7*|armhf|armv8*) ARCH_NAME="armv7" ;;
    x86_64)         ARCH_NAME="x86_64" ;;
    *)              ARCH_NAME="$ARCH" ;;
esac

TARBALL="$ANKCORE_DIR/ankcore-${ARCH_NAME}.tar.gz"
OUT="$SDCARD/ankcore-${ARCH_NAME}.tar.gz"

echo "=== ANK Build Tarball > $(date) ===" > "$LOG"
echo "Architecture: $ARCH_NAME"

# Find download tool
DL=""
command -v wget >/dev/null 2>&1 && DL="wget -q -O"
if [ -z "$DL" ]; then
    command -v curl >/dev/null 2>&1 && DL="curl -sL -o"
fi
if [ -z "$DL" ]; then
    [ -f /system/bin/toybox ] && /system/bin/toybox wget --help >/dev/null 2>&1 && DL="/system/bin/toybox wget -q -O"
fi
[ -z "$DL" ] && { echo "ERROR: No download tool (wget/curl)"; exit 1; }

# Download Alpine minirootfs
ALPINE_TAR="$ANKCORE_DIR/alpine-minirootfs-build.tar.gz"
echo "Downloading Alpine minirootfs..."
OK=0
for VER in "3.20.2" "3.20.1" "3.20.0" "3.19.1"; do
    URL="https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/${ARCH_NAME}/alpine-minirootfs-${VER}-${ARCH_NAME}.tar.gz"
    echo "  Trying Alpine ${VER}..."
    rm -f "$ALPINE_TAR"
    $DL "$ALPINE_TAR" "$URL" 2>>"$LOG"
    if [ -s "$ALPINE_TAR" ]; then
        FSIZE=$(stat -c%s "$ALPINE_TAR" 2>/dev/null || echo 0)
        if [ "$FSIZE" -gt 100000 ]; then
            HEAD=$(dd if="$ALPINE_TAR" bs=1 count=2 2>/dev/null | od -A n -t x1 | tr -d ' ')
            if [ "$HEAD" = "1f8b" ]; then
                echo "  Downloaded: ${FSIZE} bytes"
                OK=1
                break
            fi
        fi
        rm -f "$ALPINE_TAR"
    fi
done
[ "$OK" -eq 0 ] && { echo "ERROR: Download failed"; exit 1; }

# Extract
BUILDROOT="$ANKCORE_DIR/.buildroot"
rm -rf "$BUILDROOT"
mkdir -p "$BUILDROOT"
cd "$BUILDROOT" && tar xzf "$ALPINE_TAR" 2>>"$LOG"
if [ $? -ne 0 ] || [ ! -f "$BUILDROOT/bin/sh" ]; then
    cd /; rm -rf "$BUILDROOT"
    echo "ERROR: Extraction failed"; exit 1
fi
cd /
echo "Alpine minirootfs extracted"

# Setup DNS + repos
mkdir -p "$BUILDROOT/etc" "$BUILDROOT/etc/apk" "$BUILDROOT/var/cache/apk"
echo "nameserver 8.8.8.8" > "$BUILDROOT/etc/resolv.conf"
echo "nameserver 8.8.4.4" >> "$BUILDROOT/etc/resolv.conf"
echo "127.0.0.1 localhost" > "$BUILDROOT/etc/hosts"
echo "https://dl-cdn.alpinelinux.org/alpine/v3.20/main" > "$BUILDROOT/etc/apk/repositories"
echo "https://dl-cdn.alpinelinux.org/alpine/v3.20/community" >> "$BUILDROOT/etc/apk/repositories"

# Install packages
echo "Installing python3, openssl, openssh..."
mount -t proc proc "$BUILDROOT/proc" 2>/dev/null
chroot "$BUILDROOT" /bin/sh -c "export PATH=/sbin:/usr/sbin:/bin:/usr/bin; apk update && apk add --no-cache python3 openssl openssh bash busybox shadow" 2>>"$LOG"
RET=$?
umount "$BUILDROOT/proc" 2>/dev/null
[ $RET -ne 0 ] && { echo "ERROR: Package install failed"; cd /; rm -rf "$BUILDROOT"; exit 1; }

# Setup busybox
if [ -f "$BUILDROOT/bin/busybox" ]; then
    chroot "$BUILDROOT" /bin/busybox --install -s /bin 2>/dev/null
fi
[ ! -f "$BUILDROOT/bin/sh" ] && ln -sf /bin/busybox "$BUILDROOT/bin/sh" 2>/dev/null
echo "Packages installed"

# Package tarball
echo "Packaging tarball..."
rm -f "$TARBALL"
cd "$BUILDROOT" && tar czf "$TARBALL" . 2>>"$LOG"; cd /
rm -rf "$BUILDROOT"
if [ ! -s "$TARBALL" ]; then
    echo "ERROR: Tarball creation failed"; exit 1
fi
FSIZE=$(stat -c%s "$TARBALL" 2>/dev/null || echo 0)
echo "Tarball created: ${FSIZE} bytes"

# Export to sdcard
mkdir -p "$SDCARD"
cp "$TARBALL" "$OUT" 2>/dev/null
if [ -s "$OUT" ]; then
    echo "Exported to: $OUT"
else
    echo "WARN: Failed to export to sdcard, tarball at: $TARBALL"
fi

# Cleanup
rm -f "$ALPINE_TAR"
echo "=== Done ==="

# Signal install.sh that we're done (if handshake was made)
[ -f "$REQUEST" ] && touch "$DONE"

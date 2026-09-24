#!/system/bin/sh
# ============================================================
# ANK - Download Alpine rootfs
# Usage: download-rootfs.sh <version>
# Example: download-rootfs.sh 3.20
# ============================================================

VERSION="${1:-3.20}"
ANK_DIR="${ANK_DIR:-/data/local/ank}"
ANK_SDCARD="/sdcard/AndroidKonteiner"
IMAGES_DIR="$ANK_DIR/images"
ROOTFS="$IMAGES_DIR/alpine-${VERSION}"
ARCH=$(uname -m)

case "$ARCH" in
    aarch64|arm64)        ARCH_NAME="aarch64" ;;
    armv7*|armv8*|armhf)  ARCH_NAME="armv7" ;;
    x86_64)               ARCH_NAME="x86_64" ;;
    *)                    ARCH_NAME="$ARCH" ;;
esac

TARBALL="$ANK_DIR/cache/alpine-minirootfs-${VERSION}-${ARCH_NAME}.tar.gz"
ALPINE_URL="https://dl-cdn.alpinelinux.org/alpine/v${VERSION}/releases/${ARCH_NAME}/alpine-minirootfs-${VERSION}.0-${ARCH_NAME}.tar.gz"

# Already downloaded?
if [ -e "$ROOTFS/usr/bin/sh" ] || [ -L "$ROOTFS/usr/bin/sh" ] || [ -e "$ROOTFS/bin/busybox" ] || [ -L "$ROOTFS/bin/busybox" ]; then
    echo "Image alpine-${VERSION} already exists"
    exit 0
fi

mkdir -p "$IMAGES_DIR" "$ANK_DIR/cache"

# Check cached Alpine minirootfs
if [ -s "$TARBALL" ]; then
    HEAD=$(dd if="$TARBALL" bs=1 count=2 2>/dev/null | od -A n -t x1 | tr -d ' ')
    if [ "$HEAD" = "1f8b" ]; then
        echo "Using cached Alpine tarball"
    else
        rm -f "$TARBALL"
    fi
fi

# Download Alpine minirootfs
echo "Downloading Alpine v${VERSION} for ${ARCH_NAME}..."
echo "Dest: $TARBALL"

# Multiple mirrors for faster download
MIRRORS="https://dl-cdn.alpinelinux.org/alpine/v${VERSION}/releases/${ARCH_NAME} https://dl-ftp.alpinelinux.org/alpine/v${VERSION}/releases/${ARCH_NAME} https://mirror.init7.net/alpine/v${VERSION}/releases/${ARCH_NAME} https://alpine.global.ssl.fastly.net/alpine/v${VERSION}/releases/${ARCH_NAME} https://uk.alpinelinux.org/alpine/v${VERSION}/releases/${ARCH_NAME}"

DOWNLOADED=0
for MIRROR_URL in $MIRRORS; do
    FULL_URL="${MIRROR_URL}/alpine-minirootfs-${VERSION}.0-${ARCH_NAME}.tar.gz"
    echo "Trying: $MIRROR_URL"
    if command -v curl >/dev/null 2>&1; then
        curl -L --connect-timeout 10 --max-time 300 --retry 2 --retry-delay 1 \
             -f -o "$TARBALL" "$FULL_URL" 2>&1
    elif command -v wget >/dev/null 2>&1; then
        wget --timeout=300 --tries=2 -q -O "$TARBALL" "$FULL_URL" 2>&1
    fi
    echo ""
    if [ -s "$TARBALL" ]; then
        HEAD=$(dd if="$TARBALL" bs=1 count=2 2>/dev/null | od -A n -t x1 | tr -d ' ')
        if [ "$HEAD" = "1f8b" ]; then
            echo "OK: Downloaded from $MIRROR_URL"
            DOWNLOADED=1
            break
        fi
    fi
    echo "WARN: Mirror failed, trying next..."
    rm -f "$TARBALL"
done

if [ "$DOWNLOADED" -ne 1 ]; then
    echo "ERROR: All mirrors failed"
    exit 1
fi

if [ ! -f "$TARBALL" ]; then
    echo "ERROR: Download failed"
    exit 1
fi

# Extract
echo "Extracting..."
mkdir -p "$ROOTFS"
TMPDIR="$ANK_DIR/.extract_tmp"
rm -rf "$TMPDIR"
mkdir -p "$TMPDIR"
cd "$TMPDIR" && tar xzf "$TARBALL" 2>/dev/null
cd /
rm -rf "$ROOTFS"/*
for item in "$TMPDIR"/*; do
    [ -e "$item" ] && mv "$item" "$ROOTFS/"
done
rm -rf "$TMPDIR"

# Configure repos + DNS
mkdir -p "$ROOTFS/etc/apk" "$ROOTFS/var/cache/apk" "$ROOTFS/etc/ssl/certs"
echo "http://dl-cdn.alpinelinux.org/alpine/v${VERSION}/main" > "$ROOTFS/etc/apk/repositories"
echo "http://dl-cdn.alpinelinux.org/alpine/v${VERSION}/community" >> "$ROOTFS/etc/apk/repositories"
echo "nameserver 8.8.8.8" > "$ROOTFS/etc/resolv.conf"
echo "nameserver 8.8.4.4" >> "$ROOTFS/etc/resolv.conf"
echo "127.0.0.1 localhost" > "$ROOTFS/etc/hosts"

if [ -e "$ROOTFS/bin/sh" ] || [ -L "$ROOTFS/bin/sh" ] || [ -e "$ROOTFS/bin/busybox" ] || [ -L "$ROOTFS/bin/busybox" ]; then
    echo "Image 'alpine-${VERSION}' downloaded and extracted"
    exit 0
else
    echo "ERROR: Extraction failed"
    exit 1
fi

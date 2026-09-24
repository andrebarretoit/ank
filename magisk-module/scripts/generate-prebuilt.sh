#!/system/bin/sh
# Generate pre-built ankfs tarball from current installation
# Output: /sdcard/Download/ankfs-v{VERSION}-{ARCH}.tar.xz

ANK_VERSION="2.0.0"
ANK_DIR="${ANK_DIR:-/data/local/ank}"
ANK_SDCARD="/sdcard/AndroidKonteiner"
ANKFS="$ANK_DIR/ankfs"

ARCH=$(uname -m)
case "$ARCH" in
    aarch64|arm64)  ARCH_NAME="aarch64" ;;
    armv7*|armhf)   ARCH_NAME="armv7" ;;
    x86_64)         ARCH_NAME="x86_64" ;;
    *)              ARCH_NAME="$ARCH" ;;
esac

OUT="/sdcard/Download/ankfs-v${ANK_VERSION}-${ARCH_NAME}.tar.xz"

if [ ! -f "$ANKFS/usr/bin/python3" ]; then
    echo "ERROR: python3 not found in ankfs"
    exit 1
fi

if [ ! -f "$ANKFS/opt/ank/server.py" ]; then
    echo "ERROR: server.py not found in ankfs"
    exit 1
fi

echo "Generating pre-built ankfs: $ARCH_NAME v$ANK_VERSION"
echo "  Source: $ANKFS"
echo "  Output: $OUT"

cd "$ANKFS" && tar cJf "$OUT" . 2>/dev/null
cd /

SIZE=$(du -h "$OUT" | cut -f1)
echo "Done: $OUT ($SIZE)"

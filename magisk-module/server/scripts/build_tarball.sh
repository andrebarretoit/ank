#!/system/bin/sh
# ============================================================
# ANK - Build ankcore tarball
# Packages existing ankfs into tarball and exports to /sdcard/Download
# Safe to add/remove - does not affect install flow
# ============================================================

ANK_DIR="/data/local/ank"
ANKFS="$ANK_DIR/ankfs"
ANKCORE_DIR="$ANK_DIR/cache"
SDCARD="/sdcard/Download"
LOG="$ANK_DIR/logs/build-tarball.log"

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

# ============================================================
# Package existing ankfs into tarball
# ============================================================
if [ ! -d "$ANKFS" ] || [ ! -f "$ANKFS/bin/sh" ]; then
    echo "ERROR: ankfs not found at $ANKFS"
    [ -f "$REQUEST" ] && touch "$DONE"
    exit 1
fi

echo "Packaging ankfs from $ANKFS..."
rm -f "$TARBALL"
cd "$ANKFS" && tar czf "$TARBALL" . 2>>"$LOG"; cd /
if [ ! -s "$TARBALL" ]; then
    echo "ERROR: Tarball creation failed"
    [ -f "$REQUEST" ] && touch "$DONE"
    exit 1
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

echo "=== Done ==="

# Signal install.sh that we're done (if handshake was made)
[ -f "$REQUEST" ] && touch "$DONE"

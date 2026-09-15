#!/system/bin/sh
ANK_DIR=/data/local/ank/ankfs
ANK_SDCARD="/sdcard/AndroidKonteiner"
ANK_LOG="$ANK_DIR/../logs/server.log"

# Detect architecture
ARCH=$(uname -m)
case "$ARCH" in
    aarch64|arm64)  MUSL="$ANK_DIR/lib/ld-musl-aarch64.so.1" ;;
    armv7*|armhf)   MUSL="$ANK_DIR/lib/ld-musl-armhf.so.1" ;;
    x86_64)         MUSL="$ANK_DIR/lib/ld-musl-x86_64.so.1" ;;
    *)              MUSL=$(find "$ANK_DIR/lib" -name "ld-musl-*.so.*" 2>/dev/null | head -1) ;;
esac

[ ! -f "$MUSL" ] && MUSL=$(find "$ANK_DIR/lib" -name "ld-musl-*.so.*" 2>/dev/null | head -1)

cd "$ANK_DIR"
env LD_LIBRARY_PATH="$ANK_DIR/usr/lib:$ANK_DIR/lib" setsid "$MUSL" "$ANK_DIR/usr/bin/python3" "$ANK_DIR/opt/ank/server.py" </dev/null >"$ANK_LOG" 2>&1 &

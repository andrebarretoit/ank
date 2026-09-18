#!/system/bin/sh
# ANK Lite Server Starter
# Starts the ANK server using PRoot (non-root mode)

ANK_DIR="/data/local/ank"
ROOTFS="$ANK_DIR/ankfs"
PROOT="$ANK_DIR/proot"

# Check prerequisites
if [ ! -e "$PROOT" ]; then
    echo "ERRO: PRoot nao encontrado em $PROOT"
    exit 1
fi

if [ ! -e "$ROOTFS/usr/bin/python3" ]; then
    echo "ERRO: Python3 nao encontrado no rootfs"
    exit 1
fi

# Check if already running
if pgrep -f "proot.*server.py" > /dev/null 2>&1; then
    echo "Servidor ANK ja esta rodando"
    pgrep -f "proot.*server.py"
    exit 0
fi

echo "Iniciando servidor ANK (Lite mode via PRoot)..."

# Create necessary directories
mkdir -p "$ANK_DIR/logs"
mkdir -p "$ANK_DIR/containers"
mkdir -p "$ANK_DIR/images"

# Write mode file
echo '{"mode":"lite"}' > "$ANK_DIR/mode"

# Setup DNS
echo "nameserver 8.8.8.8" > "$ROOTFS/etc/resolv.conf"
echo "nameserver 8.8.4.4" >> "$ROOTFS/etc/resolv.conf"

# Start server via PRoot
cd "$ROOTFS"
LD_LIBRARY_PATH="$ROOTFS/lib:$ROOTFS/usr/lib" \
"$PROOT" -0 -r "$ROOTFS" \
-b /dev -b /proc -b /sys \
-w /root \
/usr/bin/python3 /opt/ank/server.py &

SERVER_PID=$!
echo "Servidor ANK iniciado (PID: $SERVER_PID)"
echo "Acesse: http://localhost:8001"

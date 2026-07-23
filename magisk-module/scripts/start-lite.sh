#!/system/bin/sh
# ANK Lite Server Starter
# Starts the ANK server using PRoot (non-root mode)

ANK_DIR="/data/local/ank"
ANK_SDCARD="/sdcard/AndroidKonteiner"
ROOTFS="$ANK_DIR/ankfs"
PROOT="$ANK_DIR/proot"

# Check prerequisites
if [ ! -e "$PROOT" ]; then
    echo "ERRO: PRoot nao encontrado"
    exit 1
fi

if [ ! -e "$ROOTFS/usr/bin/python3" ]; then
    echo "ERRO: Python3 nao encontrado no rootfs"
    exit 1
fi

# Check if already running
if pgrep -f "ld-musl.*python3.*server.py" > /dev/null 2>&1; then
    echo "Servidor ANK ja esta rodando"
    exit 0
fi

echo "Iniciando servidor ANK (Lite mode)..."

# Start server via PRoot
cd "$ROOTFS"
LD_LIBRARY_PATH="$ROOTFS/lib:$ROOTFS/usr/lib" \
"$PROOT" -0 -r "$ROOTFS" \
/usr/bin/python3 /opt/ank/server.py &

SERVER_PID=$!
echo "Servidor ANK iniciado (PID: $SERVER_PID)"
echo "Acesse: https://localhost:8001"

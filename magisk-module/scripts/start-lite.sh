#!/system/bin/sh
# ANK Lite Server Starter (non-root, via PRoot)
# Validated flow: tested on SM-M127F / aarch64

ANK_DIR="/data/local/tmp/ank"
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

if [ ! -e "$ROOTFS/run_server.sh" ]; then
    echo "ERRO: run_server.sh nao encontrado no rootfs"
    exit 1
fi

# Check if already running
if pgrep -f "python3 server.py" > /dev/null 2>&1; then
    echo "Servidor ANK ja esta rodando"
    exit 0
fi

echo "Iniciando servidor ANK (Lite mode via PRoot)..."

# Create necessary directories
mkdir -p "$ANK_DIR/logs" "$ANK_DIR/tmp" "$ROOTFS/tmp"

# Write mode file
echo '{"mode":"lite"}' > "$ANK_DIR/mode" 2>/dev/null

# Start server via PRoot (validated command)
nohup sh -c "PROOT_TMP_DIR=$ANK_DIR/tmp \
$PROOT -0 -r $ROOTFS \
-b /dev -b /proc -b /sys \
-b $ANK_DIR:/ank \
-w /root \
/bin/sh /run_server.sh" > "$ANK_DIR/logs/server.log" 2>&1 &

echo "Servidor ANK iniciado"
echo "Acesse: http://localhost:8001"

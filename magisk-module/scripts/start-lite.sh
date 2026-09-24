#!/system/bin/sh
# ANK Lite Server Starter (non-root, via PRoot)
# Validated flow: tested on SM-M127F / aarch64

ANK_DIR="${ANK_DIR:-/data/local/tmp/ank}"
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

mkdir -p "$ANK_DIR/logs" "$ANK_DIR/tmp" "$ROOTFS/tmp"
SVC_LOG="$ANK_DIR/logs/service.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')

_svc() {
    echo "[SERVICE] [$TS] $1" >> "$SVC_LOG"
    echo "[SERVICE] [$TS] $1"
}

# Check if already running
if pgrep -f "python3 server.py" > /dev/null 2>&1; then
    _svc "Server already running"
    echo "Servidor ANK ja esta rodando"
    exit 0
fi

echo "Iniciando servidor ANK (Lite mode via PRoot)..."

# Write mode file
echo '{"mode":"lite"}' > "$ANK_DIR/mode" 2>/dev/null

# Start server via PRoot (validated command)
nohup sh -c "PROOT_TMP_DIR=$ANK_DIR/tmp \
$PROOT -0 -r $ROOTFS \
-b /dev -b /proc -b /sys \
-b $ANK_DIR:/ank \
-w /root \
/bin/sh /run_server.sh" > "$ANK_DIR/logs/server.log" 2>&1 &
PID=$!
echo "$PID" > "$ANK_DIR/logs/server.pid"
echo "$PID" > "$ANK_DIR/server.pid"

_svc "Boot completed"
_svc "Server started (PID: $PID) | Arch: $(uname -m)"
_svc "Panel: https://localhost:8001"
_svc "Password configured"
_svc "sshd starting on port 2200"

echo "Servidor ANK iniciado"
echo "Acesse: http://localhost:8001"

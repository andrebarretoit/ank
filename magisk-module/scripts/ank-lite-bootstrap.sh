#!/system/bin/sh
# ANK Lite Bootstrap - Non-root installation via PRoot
# This script runs on the device via ADB shell (no su required)
# Sets up PRoot + Alpine rootfs for ANK server

set -e

ANK_DIR="${ANK_DIR:-/data/local/tmp/ank}"
ANK_SDCARD="/sdcard/AndroidKonteiner"
ROOTFS="$ANK_DIR/ankfs"
PROOT="$ANK_DIR/proot"
CACHE="$ANK_DIR/cache"

echo "[ANK-Lite] Iniciando bootstrap..."

# Check if PRoot exists
if [ ! -e "$PROOT" ]; then
    echo "[ANK-Lite] ERRO: PRoot nao encontrado em $PROOT"
    echo "[ANK-Lite] Execute o instalador GUI primeiro"
    exit 1
fi

# Make PRoot executable
chmod 755 "$PROOT"

# Check if rootfs exists
if [ ! -e "$ROOTFS/bin/sh" ]; then
    echo "[ANK-Lite] ERRO: Rootfs nao encontrado em $ROOTFS"
    echo "[ANK-Lite] Execute o instalador GUI primeiro"
    exit 1
fi

# Setup DNS
echo "[ANK-Lite] Configurando DNS..."
echo "nameserver 8.8.8.8" > "$ROOTFS/etc/resolv.conf"
echo "nameserver 8.8.4.4" >> "$ROOTFS/etc/resolv.conf"

# Setup APK repos
echo "[ANK-Lite] Configurando repositorios Alpine..."
echo "https://dl-cdn.alpinelinux.org/alpine/v3.20/main" > "$ROOTFS/etc/apk/repositories"
echo "https://dl-cdn.alpinelinux.org/alpine/v3.20/community" >> "$ROOTFS/etc/apk/repositories"

# Install Python3 via PRoot if not present
if [ ! -e "$ROOTFS/usr/bin/python3" ]; then
    echo "[ANK-Lite] Instalando Python3..."
    LD_LIBRARY_PATH="$ROOTFS/lib:$ROOTFS/usr/lib" \
    "$PROOT" -0 -r "$ROOTFS" \
    /sbin/apk add --no-cache python3 || {
        echo "[ANK-Lite] Tentando com --allow-untrusted..."
        LD_LIBRARY_PATH="$ROOTFS/lib:$ROOTFS/usr/lib" \
        "$PROOT" -0 -r "$ROOTFS" \
        /sbin/apk add --no-cache --allow-untrusted python3
    }
fi

# Verify Python3
echo "[ANK-Lite] Verificando Python3..."
PY_VER=$(LD_LIBRARY_PATH="$ROOTFS/lib:$ROOTFS/usr/lib" \
    "$PROOT" -0 -r "$ROOTFS" \
    /usr/bin/python3 --version 2>&1)
echo "[ANK-Lite] Python: $PY_VER"

# Setup ANK server directory
echo "[ANK-Lite] Configurando servidor ANK..."
mkdir -p "$ROOTFS/opt/ank"

# Write mode file
echo '{"mode":"lite","tier":"lite"}' > "$ANK_DIR/mode"

echo "[ANK-Lite] Bootstrap concluido com sucesso!"
echo "[ANK-Lite] Para iniciar o servidor:"
echo "  $ANK_DIR/start-lite.sh"

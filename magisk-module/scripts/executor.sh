#!/system/bin/sh
# ANK - Command executor (runs on host, outside chroot)
# Watches FIFO for commands from server.py

ANK_DIR="${ANK_DIR:-/data/local/ank}"
ANK_SDCARD="/sdcard/AndroidKonteiner"
FIFO="$ANK_DIR/logs/exec.fifo"
LOG="$ANK_DIR/logs/service.log"

log() {
    echo "[$(date '+%H:%M:%S')] $1" >> "$LOG"
}

log "Executor iniciado"

# Create FIFO if not exists
mkfifo "$FIFO" 2>/dev/null

while true; do
    # Read command from FIFO
    CMD=$(cat "$FIFO" 2>/dev/null)
    if [ -n "$CMD" ]; then
        log "EXEC: $CMD"
        # Run command on host
        eval "$CMD" 2>&1
    fi
done

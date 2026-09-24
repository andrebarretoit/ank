#!/system/bin/sh
# ANK Server Restart Script
# Called by server.py when it receives SIGHUP
# Stops the server gracefully, waits, then starts it again

ANK_DIR="${ANK_DIR:-/data/local/ank}"
# Lite host without env: rooted default missing, lite install present
if [ "$ANK_DIR" = "/data/local/ank" ] && [ ! -d "$ANK_DIR" ] && [ -d "/data/local/tmp/ank" ]; then
    ANK_DIR="/data/local/tmp/ank"
fi
ANKFS="$ANK_DIR/ankfs"
LOG_DIR="$ANK_DIR/logs"
SERVER_LOG="$LOG_DIR/server.log"
START_SCRIPT="$ANKFS/opt/ank/start-server.sh"
# Canonical PID location (server.py writes logs/server.pid)
PID_FILE="$LOG_DIR/server.pid"
# Legacy fallback
LEGACY_PID_FILE="$ANK_DIR/server.pid"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restart.sh] Restart requested" >> "$SERVER_LOG"

# Find server PID
find_pid() {
    # Prefer canonical PID file
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return
        fi
    fi
    # Legacy PID file
    if [ -f "$LEGACY_PID_FILE" ]; then
        pid=$(cat "$LEGACY_PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return
        fi
    fi
    # Fallback: pgrep
    pid=$(pgrep -f 'python3.*server.py' 2>/dev/null | head -1)
    if [ -n "$pid" ]; then
        echo "$pid"
        return
    fi
    echo ""
}

# ── Step 1: Stop ─────────────────────────────────────────────────────────────
PID=$(find_pid)
if [ -n "$PID" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restart.sh] Stopping server (PID $PID)..." >> "$SERVER_LOG"
    kill "$PID" 2>/dev/null
    # Wait up to 10s for graceful shutdown
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if ! kill -0 "$PID" 2>/dev/null; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restart.sh] Server stopped" >> "$SERVER_LOG"
            break
        fi
        sleep 1
    done
    # Force kill if still alive
    if kill -0 "$PID" 2>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restart.sh] Force killing..." >> "$SERVER_LOG"
        kill -9 "$PID" 2>/dev/null
        sleep 2
    fi
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restart.sh] No running server found" >> "$SERVER_LOG"
fi

# ── Step 2: Wait ─────────────────────────────────────────────────────────────
echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restart.sh] Waiting 5s before restart..." >> "$SERVER_LOG"
sleep 5

# ── Step 3: Start ────────────────────────────────────────────────────────────
echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restart.sh] Starting server..." >> "$SERVER_LOG"

# Detect lite mode (proot + lite marker in mode file)
IS_LITE=0
if [ -f "$ANK_DIR/proot" ] && [ -f "$ANK_DIR/mode" ] && grep -q '"mode": *"lite"' "$ANK_DIR/mode" 2>/dev/null; then
    IS_LITE=1
fi

if [ "$IS_LITE" -eq 1 ]; then
    if [ -f "$ANK_DIR/start-lite.sh" ]; then
        # Lite: validated start script (binds host dir to /ank, writes server.pid)
        sh "$ANK_DIR/start-lite.sh" >> "$SERVER_LOG" 2>&1
    elif [ -f "$ANK_DIR/proot" ]; then
        # Lite fallback: proot + run_server.sh with host dir mounted at /ank
        mkdir -p "$ANK_DIR/logs" "$ANK_DIR/tmp" "$ANKFS/tmp" 2>/dev/null
        if [ -f "$ANKFS/run_server.sh" ]; then
            nohup sh -c "PROOT_TMP_DIR=$ANK_DIR/tmp \
$ANK_DIR/proot -0 -r $ANKFS \
-b /dev -b /proc -b $ANK_DIR:/ank \
-w /root \
/bin/sh /run_server.sh" >> "$SERVER_LOG" 2>&1 &
        else
            nohup env ANK_DIR=/ank PROOT_TMP_DIR="$ANK_DIR/tmp" \
            "$ANK_DIR/proot" -0 -r "$ANKFS" \
                -b /dev -b /proc -b "$ANK_DIR:/ank" -w /root \
                /usr/bin/python3 /opt/ank/server.py \
                >> "$SERVER_LOG" 2>&1 &
        fi
        echo "$!" > "$PID_FILE"
        echo "$!" > "$LEGACY_PID_FILE"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restart.sh] ERROR: Lite mode but no proot found" >> "$SERVER_LOG"
        exit 1
    fi
elif [ -x "$START_SCRIPT" ] || [ -f "$START_SCRIPT" ]; then
    sh "$START_SCRIPT" >> "$SERVER_LOG" 2>&1
elif [ -x "$ANKFS/opt/ank/start-lite.sh" ] || [ -f "$ANKFS/opt/ank/start-lite.sh" ]; then
    sh "$ANKFS/opt/ank/start-lite.sh" >> "$SERVER_LOG" 2>&1
elif [ -f "$ANKFS/usr/bin/python3" ] && ls "$ANKFS/lib/ld-musl-"* >/dev/null 2>&1; then
    # Rooted mode fallback
    cd "$ANKFS"
    LD_LIBRARY_PATH="$ANKFS/lib:$ANKFS/usr/lib" \
    nohup "$ANKFS/lib/ld-musl-"* "$ANKFS/usr/bin/python3" /opt/ank/server.py \
        >> "$SERVER_LOG" 2>&1 &
    echo "$!" > "$PID_FILE"
    echo "$!" > "$LEGACY_PID_FILE"
elif [ -f "$ANK_DIR/proot" ]; then
    # Generic PRoot fallback: bind host dir as /ank so guest ANK_DIR resolves
    cd "$ANKFS"
    nohup "$ANK_DIR/proot" -0 -r "$ANKFS" \
        -b /dev -b /proc -b "$ANK_DIR:/ank" -w /root \
        /usr/bin/python3 /opt/ank/server.py \
        >> "$SERVER_LOG" 2>&1 &
    echo "$!" > "$PID_FILE"
    echo "$!" > "$LEGACY_PID_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restart.sh] ERROR: No server binary found" >> "$SERVER_LOG"
    exit 1
fi

NEW_PID=""
for i in 1 2 3 4 5 6 7 8 9 10; do
    if [ -s "$PID_FILE" ]; then
        NEW_PID=$(cat "$PID_FILE" 2>/dev/null)
        [ -n "$NEW_PID" ] && kill -0 "$NEW_PID" 2>/dev/null && break
    fi
    NEW_PID=$(pgrep -f 'python3.*server.py' 2>/dev/null | head -1)
    [ -n "$NEW_PID" ] && kill -0 "$NEW_PID" 2>/dev/null && break
    sleep 1
    NEW_PID=""
done
if [ -n "$NEW_PID" ]; then
    echo "$NEW_PID" > "$PID_FILE"
    echo "$NEW_PID" > "$LEGACY_PID_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restart.sh] Server restarted (PID $NEW_PID)" >> "$SERVER_LOG"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restart.sh] WARNING: restart may have failed (no PID)" >> "$SERVER_LOG"
fi

exit 0

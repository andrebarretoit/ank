#!/system/bin/sh
# ANK Updater - download, verify and apply a module update zip.
# Usage: ank-updater.sh <zip_url> [sha256]
#
# Flow: download (retry once after 5s) -> sha256 -> extract -> swap module
#       -> resync runtime copies -> propagate ankd.sh to containers
#       -> DONE -> restart server.
# Log:  /sdcard/AndroidKonteiner/ank-update.log
# State: /sdcard/AndroidKonteiner/ank-update.state (RUNNING (...)/DONE (...)/FAILED: ...)

ZIP_URL="$1"
EXPECT_SHA="$2"

ANK_DIR="${ANK_DIR:-/data/local/ank}"
if [ ! -d "$ANK_DIR" ] && [ -d "/data/local/tmp/ank" ]; then
    ANK_DIR="/data/local/tmp/ank"
fi
ANKFS="$ANK_DIR/ankfs"
MODULE_DIR="/data/adb/modules/ank"
STAGING="/data/adb/modules/.ank-update-new"
BACKUP="/data/adb/modules/.ank-update-old"
TMP_DIR="$ANK_DIR/tmp"
SDCARD="/sdcard/AndroidKonteiner"
LOG="$SDCARD/ank-update.log"
STATE="$SDCARD/ank-update.state"
ZIP="$TMP_DIR/ank-update.zip"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG" 2>/dev/null
}

set_state() {
    echo "$1" > "$STATE" 2>/dev/null
    log "STATE -> $1"
}

fail() {
    set_state "FAILED: $*"
    rm -rf "$STAGING" 2>/dev/null
    rm -f "$ZIP" 2>/dev/null
    if [ ! -f "$MODULE_DIR/module.prop" ] && [ -d "$BACKUP" ]; then
        rm -rf "$MODULE_DIR" 2>/dev/null
        mv "$BACKUP" "$MODULE_DIR" 2>/dev/null
        log "ROLLBACK: previous module restored from backup"
    fi
    log "=== UPDATE FAILED ==="
    exit 1
}

# Atomic file replace: a running script keeps reading the old inode,
# new opens get the finished file. Never truncate a file in place.
sync_file() {
    if cp "$1" "$2.tmp" 2>/dev/null; then
        if mv -f "$2.tmp" "$2" 2>/dev/null; then
            return 0
        fi
        rm -f "$2.tmp" 2>/dev/null
        return 1
    fi
    rm -f "$2.tmp" 2>/dev/null
    return 1
}

mkdir -p "$SDCARD" "$TMP_DIR" 2>/dev/null
log "=== UPDATE START url=$ZIP_URL ==="

[ -n "$ZIP_URL" ] || fail "no zip url given"
[ -d "$MODULE_DIR" ] || fail "module dir $MODULE_DIR not found (root mode only)"

# ---- Download (curl first; on failure retry once after 5s) ----
set_state "RUNNING (download)"
DL_TOOL=""
if command -v curl >/dev/null 2>&1; then
    DL_TOOL="curl"
elif command -v wget >/dev/null 2>&1; then
    DL_TOOL="wget"
fi
[ -n "$DL_TOOL" ] || fail "neither curl nor wget available"

dl() {
    if [ "$DL_TOOL" = "curl" ]; then
        curl -fL --connect-timeout 15 --max-time 900 -o "$ZIP" "$ZIP_URL" 2>/dev/null
    else
        wget -q -T 30 -t 3 -O "$ZIP" "$ZIP_URL" 2>/dev/null
    fi
}

if dl; then
    log "download ok (attempt 1, tool=$DL_TOOL)"
else
    log "download failed, retrying in 5s..."
    sleep 5
    if dl; then
        log "download ok (attempt 2, tool=$DL_TOOL)"
    else
        fail "download failed after 2 attempts"
    fi
fi
[ -s "$ZIP" ] || fail "downloaded file is empty"

# ---- Verify sha256 (optional; verified only when provided) ----
set_state "RUNNING (verify)"
if [ -n "$EXPECT_SHA" ] && [ "$EXPECT_SHA" != "-" ]; then
    EXPECT_SHA=$(echo "$EXPECT_SHA" | tr 'A-Z' 'a-z')
    ACTUAL=""
    if command -v sha256sum >/dev/null 2>&1; then
        ACTUAL=$(sha256sum "$ZIP" 2>/dev/null | awk '{print $1}')
    elif [ -x "$ANKFS/usr/bin/sha256sum" ]; then
        ACTUAL=$("$ANKFS/usr/bin/sha256sum" "$ZIP" 2>/dev/null | awk '{print $1}')
    fi
    [ -n "$ACTUAL" ] || fail "sha256sum not available"
    [ "$ACTUAL" = "$EXPECT_SHA" ] || fail "sha256 mismatch (expected $EXPECT_SHA, got $ACTUAL)"
    log "sha256 verified"
else
    log "no sha256 provided, skipping verification"
fi

# ---- Extract to staging ----
set_state "RUNNING (extract)"
rm -rf "$STAGING"
mkdir -p "$STAGING" || fail "cannot create staging dir"
if command -v unzip >/dev/null 2>&1; then
    unzip -o -q "$ZIP" -d "$STAGING" 2>/dev/null || fail "unzip failed"
elif [ -x "$ANKFS/usr/bin/unzip" ]; then
    "$ANKFS/usr/bin/unzip" -o -q "$ZIP" -d "$STAGING" 2>/dev/null || fail "unzip failed"
else
    fail "unzip not available"
fi
[ -f "$STAGING/module.prop" ] || fail "zip has no module.prop"
[ -f "$STAGING/server/server.py" ] || fail "zip has no server/server.py"
[ -d "$STAGING/scripts" ] || fail "zip has no scripts/"

# ---- Swap module dir (mv = same-filesystem rename, instant) ----
set_state "RUNNING (swap)"
rm -rf "$BACKUP" 2>/dev/null
if [ -d "$MODULE_DIR" ]; then
    mv "$MODULE_DIR" "$BACKUP" || fail "cannot move current module aside"
fi
mv "$STAGING" "$MODULE_DIR" || fail "cannot move new module into place"
[ -f "$MODULE_DIR/module.prop" ] || fail "swapped module is invalid"

# ---- Resync runtime copies (same layout as install.sh) ----
set_state "RUNNING (resync)"
NEW_SCRIPTS="$MODULE_DIR/scripts"
NEW_SERVER="$MODULE_DIR/server"
mkdir -p "$ANK_DIR/core/ankd" "$ANK_DIR/core/static" "$ANKFS/opt/ank/scripts" "$ANKFS/opt/ank/static"

for f in "$NEW_SCRIPTS"/*.sh; do
    [ -f "$f" ] || continue
    sync_file "$f" "$ANK_DIR/core/$(basename "$f")" || log "WARN: core resync failed for $(basename "$f")"
    chmod 755 "$ANK_DIR/core/$(basename "$f")" 2>/dev/null
    cp "$f" "$ANKFS/opt/ank/scripts/$(basename "$f")" 2>/dev/null
done

if [ -d "$NEW_SERVER/ankd" ]; then
    for f in "$NEW_SERVER/ankd/"*.sh; do
        [ -f "$f" ] || continue
        sync_file "$f" "$ANK_DIR/core/ankd/$(basename "$f")" || log "WARN: ankd resync failed for $(basename "$f")"
        chmod 755 "$ANK_DIR/core/ankd/$(basename "$f")" 2>/dev/null
    done
fi

if [ -d "$NEW_SERVER/static" ]; then
    rm -rf "$ANK_DIR/core/static.new" 2>/dev/null
    if cp -r "$NEW_SERVER/static" "$ANK_DIR/core/static.new" 2>/dev/null; then
        rm -rf "$ANK_DIR/core/static" 2>/dev/null
        mv "$ANK_DIR/core/static.new" "$ANK_DIR/core/static" 2>/dev/null
    fi
    rm -rf "$ANKFS/opt/ank/static.new" 2>/dev/null
    if cp -r "$NEW_SERVER/static" "$ANKFS/opt/ank/static.new" 2>/dev/null; then
        rm -rf "$ANKFS/opt/ank/static" 2>/dev/null
        mv "$ANKFS/opt/ank/static.new" "$ANKFS/opt/ank/static" 2>/dev/null
    fi
fi

if [ -f "$NEW_SERVER/server.py" ]; then
    sync_file "$NEW_SERVER/server.py" "$ANKFS/opt/ank/server.py" || log "WARN: server.py resync failed"
    chmod 755 "$ANKFS/opt/ank/server.py" 2>/dev/null
fi
for f in "$NEW_SERVER"/*.py; do
    [ -f "$f" ] || continue
    sync_file "$f" "$ANKFS/opt/ank/$(basename "$f")" || log "WARN: module resync failed for $(basename "$f")"
done
log "runtime resync done"

# ---- Propagate ankd.sh to existing containers ----
set_state "RUNNING (propagate)"
if [ -f "$NEW_SERVER/ankd/ankd.sh" ]; then
    for cdir in "$ANK_DIR/containers"/*/; do
        [ -d "$cdir" ] || continue
        [ -d "$cdir/merged/usr/ankd/core" ] || continue
        if sync_file "$NEW_SERVER/ankd/ankd.sh" "$cdir/merged/usr/ankd/core/ankd.sh"; then
            chmod 755 "$cdir/merged/usr/ankd/core/ankd.sh" 2>/dev/null
            log "propagated ankd.sh -> $(basename "$cdir")"
        else
            log "WARN: propagate ankd.sh failed for $(basename "$cdir")"
        fi
    done
fi

# ---- Finish ----
rm -rf "$BACKUP" "$STAGING" 2>/dev/null
rm -f "$ZIP" 2>/dev/null
NEW_VC=$(grep '^versionCode=' "$MODULE_DIR/module.prop" 2>/dev/null | head -1 | cut -d= -f2)
set_state "DONE (versionCode=$NEW_VC)"
log "=== UPDATE DONE ==="

if [ -f "$ANK_DIR/core/restart-server.sh" ]; then
    log "restarting server..."
    nohup sh "$ANK_DIR/core/restart-server.sh" >/dev/null 2>&1 &
fi
exit 0

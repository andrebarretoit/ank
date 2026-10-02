#!/system/bin/sh
# ANK Updater - download, verify and apply a module update zip.
# Usage: ank-updater.sh <zip_url> [sha256]
#
# Flow: download (retry once after 5s) -> sha256 -> backup (module code copy
#       + runtime server tarball) -> extract OVER the current module (merge;
#       the module's ankfs/ payloads and the runtime rootfs are never touched)
#       -> validate -> resync runtime copies -> propagate ankd.sh to containers
#       -> DONE -> restart server.
# Rollback: any failure after extraction restores the module code from the
#           backup copy and, if the resync already started, the runtime server
#           (ankfs/opt/ank) from the tarball. The backup is kept after a
#           successful update until the next one starts.
# Log:  /sdcard/AndroidKonteiner/ank-update.log
# State: /sdcard/AndroidKonteiner/ank-update.state (RUNNING (...)/DONE (PatchFix=vc19-0210)/FAILED: ...)

ZIP_URL="$1"
EXPECT_SHA="$2"

ANK_DIR="${ANK_DIR:-/data/local/ank}"
if [ ! -d "$ANK_DIR" ] && [ -d "/data/local/tmp/ank" ]; then
    ANK_DIR="/data/local/tmp/ank"
fi
ANKFS="$ANK_DIR/ankfs"
MODULE_DIR="/data/adb/modules/ank"
BACKUP="/data/adb/modules/.ank-update-old"
TMP_DIR="$ANK_DIR/tmp"
SDCARD="/sdcard/AndroidKonteiner"
LOG="$SDCARD/ank-update.log"
STATE="$SDCARD/ank-update.state"
ZIP="$TMP_DIR/ank-update.zip"

EXTRACT_STARTED=0
RESYNC_STARTED=0

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG" 2>/dev/null
}

set_state() {
    echo "$1" > "$STATE" 2>/dev/null
    log "State: $1"
}

# Restore module code (everything except ankfs/) from the backup copy and,
# when the resync had already touched it, the runtime server from the tarball.
restore_backups() {
    if [ -f "$BACKUP/module/module.prop" ]; then
        mkdir -p "$MODULE_DIR" 2>/dev/null
        for e in "$MODULE_DIR"/*; do
            [ -e "$e" ] || continue
            [ "$(basename "$e")" = "ankfs" ] && continue
            rm -rf "$e" 2>/dev/null
        done
        R_OK=1
        for e in "$BACKUP/module"/*; do
            [ -e "$e" ] || continue
            cp -R "$e" "$MODULE_DIR/" 2>/dev/null || R_OK=0
        done
        if [ "$R_OK" = 1 ]; then
            log "ROLLBACK: module code restored from backup"
        else
            log "ROLLBACK FAILED: module code restore incomplete"
        fi
    fi
    if [ "$RESYNC_STARTED" = 1 ] && [ -f "$BACKUP/runtime-server.tgz" ] && [ -d "$ANKFS" ]; then
        if tar xzf "$BACKUP/runtime-server.tgz" -C "$ANKFS" 2>/dev/null; then
            log "ROLLBACK: runtime server restored from tarball"
        else
            log "ROLLBACK FAILED: runtime server restore"
        fi
    fi
}

fail() {
    set_state "FAILED: $*"
    rm -f "$ZIP" 2>/dev/null
    if [ "$EXTRACT_STARTED" = 1 ]; then
        restore_backups
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
log "=== UPDATE START ==="

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
    log "Download complete (attempt 1, $DL_TOOL)"
else
    log "Download failed, retrying in 5 seconds..."
    sleep 5
    if dl; then
        log "Download complete (attempt 2, $DL_TOOL)"
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
    log "Checksum verified (sha256)"
else
    log "No checksum provided, verification skipped"
fi

# ---- Backup: module code (without ankfs/) + runtime server tarball ----
# The ankfs payloads (~73 MB) are never copied, moved or touched: only the
# code that the update can actually change gets a backup (~3-4 MB), plus the
# runtime server dir (ankfs/opt/ank, ~5 MB) as a state tarball.
set_state "RUNNING (backup)"
rm -rf "$BACKUP" 2>/dev/null
mkdir -p "$BACKUP/module" || fail "cannot create backup dir"
for e in "$MODULE_DIR"/*; do
    [ -e "$e" ] || continue
    [ "$(basename "$e")" = "ankfs" ] && continue
    cp -R "$e" "$BACKUP/module/" 2>/dev/null || log "WARN: backup skipped $(basename "$e")"
done
[ -f "$BACKUP/module/module.prop" ] || fail "module code backup failed"
if [ -d "$ANKFS/opt/ank" ]; then
    if tar czf "$BACKUP/runtime-server.tgz" -C "$ANKFS" opt/ank 2>/dev/null; then
        log "Backup created (module code + runtime server)"
    else
        log "WARN: runtime server tarball failed (resync rollback unavailable)"
    fi
else
    log "WARN: no runtime server dir to back up"
fi

# ---- Extract OVER the current module (merge; ankfs/ stays untouched) ----
set_state "RUNNING (extract)"
UNZIP=""
if command -v unzip >/dev/null 2>&1; then
    UNZIP="unzip"
elif [ -x "$ANKFS/usr/bin/unzip" ]; then
    UNZIP="$ANKFS/usr/bin/unzip"
fi
[ -n "$UNZIP" ] || fail "unzip not available"

# Best-effort structural check before touching anything.
LIST=$($UNZIP -l "$ZIP" 2>/dev/null)
if [ -n "$LIST" ]; then
    echo "$LIST" | grep -q "module.prop" || fail "zip has no module.prop"
    echo "$LIST" | grep -q "server/server.py" || fail "zip has no server/server.py"
    echo "$LIST" | grep -q "scripts/ank-updater.sh" || fail "zip has no scripts/ank-updater.sh"
fi

EXTRACT_STARTED=1
$UNZIP -o -q "$ZIP" -d "$MODULE_DIR" 2>/dev/null || fail "unzip failed"

set_state "RUNNING (validate)"
[ -f "$MODULE_DIR/module.prop" ] || fail "module.prop missing after extract"
NEW_VC=$(grep '^versionCode=' "$MODULE_DIR/module.prop" 2>/dev/null | head -1 | cut -d= -f2)
[ -n "$NEW_VC" ] || fail "module.prop has no versionCode"
NEW_BUILDDATE=$(grep '^buildDate=' "$MODULE_DIR/module.prop" 2>/dev/null | head -1 | cut -d= -f2)
NEW_PF="vc${NEW_VC}${NEW_BUILDDATE:+-$NEW_BUILDDATE}"
[ -f "$MODULE_DIR/server/server.py" ] || fail "server/server.py missing after extract"
[ -f "$MODULE_DIR/scripts/ank-updater.sh" ] || fail "scripts/ank-updater.sh missing after extract"
log "Update extracted over current module ($NEW_PF)"

# ---- Resync runtime copies (same layout as install.sh) ----
set_state "RUNNING (resync)"
RESYNC_STARTED=1
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
log "Runtime resync complete"

# ---- Propagate ankd.sh to existing containers ----
set_state "RUNNING (propagate)"
if [ -f "$NEW_SERVER/ankd/ankd.sh" ]; then
    for cdir in "$ANK_DIR/containers"/*/; do
        [ -d "$cdir" ] || continue
        [ -d "$cdir/merged/usr/ankd/core" ] || continue
        if sync_file "$NEW_SERVER/ankd/ankd.sh" "$cdir/merged/usr/ankd/core/ankd.sh"; then
            chmod 755 "$cdir/merged/usr/ankd/core/ankd.sh" 2>/dev/null
            log "Propagated ankd.sh to container $(basename "$cdir")"
        else
            log "WARN: propagate ankd.sh failed for $(basename "$cdir")"
        fi
    done
fi

# ---- Finish ----
rm -f "$ZIP" 2>/dev/null
set_state "DONE ($NEW_PF)"
log "=== UPDATE DONE === (previous version preserved at $BACKUP)"

if [ -f "$ANK_DIR/core/restart-server.sh" ]; then
    log "Restarting ANK server..."
    nohup sh "$ANK_DIR/core/restart-server.sh" >/dev/null 2>&1 &
fi
exit 0

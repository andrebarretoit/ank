#!/system/bin/sh
ANK_VERSION="2.0.0"
ANK_DIR="/data/local/ank"
ANKFS="$ANK_DIR/ankfs"
ANK_SDCARD="/sdcard/AndroidKonteiner"
LOG_FILE="$ANK_DIR/logs/install.log"
REPO="http://dl-cdn.alpinelinux.org/alpine/v3.20"
BASE_IMAGE="alpine-3.20"

init_log() {
    mkdir -p "$ANK_DIR/logs"
    echo "=== ANK Install v${ANK_VERSION} > $(date) ===" > "$LOG_FILE"
}

log() {
    local level="$1"; shift
    echo "[$level] $*" >> "$LOG_FILE"
    [ "$level" != "INFO" ] && ui_print "[$level] $*"
}

die() {
    log FAIL "$*"
    mkdir -p "$ANK_SDCARD/logs"
    cp "$LOG_FILE" "$ANK_SDCARD/logs/install.log" 2>/dev/null
    ui_print "  INSTALL FAILED > see $ANK_SDCARD/logs/install.log"
    exit 1
}

cleanup() {
    # Kill ANK server
    pkill -9 -f "ld-musl.*python3.*server.py" 2>/dev/null
    pkill -9 -f "ld-musl.*server.py" 2>/dev/null

    # Kill ALL processes inside ALL container chroots
    for c in "$ANK_DIR/containers"/*/; do
        [ -d "$c" ] || continue
        local rootfs="$c/merged"
        for pid_dir in /proc/[0-9]*; do
            local pid=$(basename "$pid_dir")
            local exe=$(readlink "$pid_dir/exe" 2>/dev/null)
            local cwd_path=$(readlink "$pid_dir/cwd" 2>/dev/null)
            case "$exe" in ${rootfs}/*) kill -9 "$pid" 2>/dev/null ;; esac
            case "$cwd_path" in ${rootfs}/*) kill -9 "$pid" 2>/dev/null ;; esac
        done
    done

    # Also kill container init shells and sshd globally
    for cpid in $(pgrep -f "sh.*_ank_exit" 2>/dev/null); do kill -9 "$cpid" 2>/dev/null; done
    pkill -9 -f "sshd.*PidFile" 2>/dev/null
    pkill -9 -f "sshd.*-p.*22[0-9][0-9]" 2>/dev/null

    sleep 1

    # Unmount ALL container chroot mounts
    for c in "$ANK_DIR/containers"/*/; do
        [ -d "$c" ] || continue
        local rootfs="$c/merged"
        for m in dev/pts dev/shm dev proc sys run tmp; do
            umount "$rootfs/$m" 2>/dev/null
            umount -l "$rootfs/$m" 2>/dev/null
        done
        umount "$rootfs" 2>/dev/null
        umount -l "$rootfs" 2>/dev/null
    done

    # Unmount ankfs mounts
    for m in dev/pts dev/shm dev proc sys run tmp; do
        umount "$ANKFS/$m" 2>/dev/null
        umount -l "$ANKFS/$m" 2>/dev/null
    done

    # Clean iptables
    iptables -t nat -S 2>/dev/null | grep -i "ank" | sed 's/-A/-D/g' | while read rule; do
        iptables -t nat $rule 2>/dev/null
    done
    iptables -S 2>/dev/null | grep -i "ank" | sed 's/-A/-D/g' | while read rule; do
        iptables $rule 2>/dev/null
    done

    # Clean network
    ip link set ank0 down 2>/dev/null
    ip link delete ank0 2>/dev/null
    ip netns list 2>/dev/null | grep -i "netns_\|ank" | cut -d' ' -f1 | while read ns; do
        ip netns delete "$ns" 2>/dev/null
    done

    # Clean cgroups
    rm -rf "/sys/fs/cgroup/ank" 2>/dev/null

    # Remove ALL ANK data (fresh start)
    rm -rf "$ANK_DIR"
    rm -rf "/sdcard/AndroidKonteiner"

    # Recreate base dirs
    mkdir -p "$ANK_DIR/logs" "$ANK_DIR/cache"
}

cp_log_to_sdcard() { mkdir -p "$ANK_SDCARD/logs"; cp "$LOG_FILE" "$ANK_SDCARD/logs/install.log" 2>/dev/null; }

detect_arch() {
    ARCH_NAME=$(uname -m)
    # Map uname -m to Alpine repo arch for downloads
    case "$ARCH_NAME" in
        aarch64|arm64) ALPINE_ARCH="aarch64" ;;
        armv8*) ALPINE_ARCH="armhf" ;;
        armv7*|armhf) ALPINE_ARCH="armv7" ;;
        x86_64) ALPINE_ARCH="x86_64" ;;
        *) ALPINE_ARCH="$ARCH_NAME" ;;
    esac
}

# Universal chroot: host tools first, then rootfs fallbacks
_chroot_rootfs() {
    local ROOTFS="$1"; shift
    local CMD="$*"

    # Discover host tools dynamically via which/command -v
    local HOST_BUSYBOX=""
    local HOST_TOYBOX=""
    local HOST_CHROOT=""
    for b in $(command -v busybox 2>/dev/null) /system/xbin/busybox /system/bin/busybox; do
        [ -x "$b" ] && HOST_BUSYBOX="$b" && break
    done
    for t in $(command -v toybox 2>/dev/null) /system/bin/toybox /system/xbin/toybox; do
        [ -x "$t" ] && HOST_TOYBOX="$t" && break
    done
    for c in $(command -v chroot 2>/dev/null) /system/bin/chroot /system/xbin/chroot; do
        [ -x "$c" ] && HOST_CHROOT="$c" && break
    done

    log INFO "Host tools: busybox=${HOST_BUSYBOX:-none} toybox=${HOST_TOYBOX:-none} chroot=${HOST_CHROOT:-none}"

    # 1. Host busybox chroot
    if [ -n "$HOST_BUSYBOX" ]; then
        log INFO "Trying: $HOST_BUSYBOX chroot $ROOTFS /bin/sh -c ..."
        "$HOST_BUSYBOX" chroot "$ROOTFS" /bin/sh -c "$CMD" 2>>"$LOG_FILE" && return 0
        log WARN "Host busybox chroot failed"
    fi

    # 2. Host toybox chroot
    if [ -n "$HOST_TOYBOX" ]; then
        log INFO "Trying: $HOST_TOYBOX chroot $ROOTFS /bin/sh -c ..."
        "$HOST_TOYBOX" chroot "$ROOTFS" /bin/sh -c "$CMD" 2>>"$LOG_FILE" && return 0
        log WARN "Host toybox chroot failed"
    fi

    # 3. Host chroot (standalone)
    if [ -n "$HOST_CHROOT" ]; then
        log INFO "Trying: $HOST_CHROOT $ROOTFS /bin/sh -c ..."
        "$HOST_CHROOT" "$ROOTFS" /bin/sh -c "$CMD" 2>>"$LOG_FILE" && return 0
        log WARN "Host chroot failed"
    fi

    # 4. Host musl direct exec (no chroot, runs rootfs binaries via host linker)
    local MUSL=$(ls "$ROOTFS"/lib/ld-musl-*.so* 2>/dev/null | head -1)
    if [ -n "$MUSL" ] && [ -x "$MUSL" ]; then
        local SH=""
        for s in "$ROOTFS/bin/sh" "$ROOTFS/bin/busybox"; do
            [ -e "$s" ] || [ -L "$s" ] && { SH="$s"; break; }
        done
        [ -z "$SH" ] && SH="$ROOTFS/bin/sh"
        log INFO "Trying: musl direct exec $MUSL $SH ..."
        env -i HOME=/root PATH=/sbin:/usr/sbin:/bin:/usr/bin \
            LD_LIBRARY_PATH="$ROOTFS/lib" \
            "$MUSL" "$SH" -c "$CMD" 2>>"$LOG_FILE" && return 0
        log WARN "Musl direct exec failed"
    fi

    # 5. Rootfs busybox chroot (last resort)
    if [ -x "$ROOTFS/bin/busybox" ]; then
        log INFO "Trying: rootfs busybox chroot ..."
        "$ROOTFS/bin/busybox" chroot "$ROOTFS" /bin/sh -c "$CMD" 2>>"$LOG_FILE" && return 0
        log WARN "Rootfs busybox chroot failed"
    fi

    log WARN "All chroot methods exhausted"
    return 1
}

find_dl_tool() {
    DL=""
    if command -v curl >/dev/null 2>&1; then
        DL="env -u LD_PRELOAD curl -L --connect-timeout 15 --max-time 300 -f -o"
    elif command -v wget >/dev/null 2>&1; then
        DL="wget --timeout=300 -O"
    elif [ -f /system/bin/toybox ] && /system/bin/toybox wget --help >/dev/null 2>&1; then
        DL="/system/bin/toybox wget --timeout=300 -O"
    fi
    [ -z "$DL" ] && return 1
    return 0
}

download_alpine() {
    local OUT_TAR="$1"
    # Android su injects LD_PRELOAD=libsigchain.so which breaks curl SSL
    unset LD_PRELOAD 2>/dev/null
    find_dl_tool || die "No download tool (wget/curl)"
    for VER in "3.20.2" "3.20.1" "3.20.0" "3.19.1"; do
        # Multiple mirrors for faster download (ordered by reliability)
        for BASE_URL in \
            "https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/${ALPINE_ARCH}" \
            "https://mirror.init7.net/alpine/v3.20/releases/${ALPINE_ARCH}" \
            "https://uk.alpinelinux.org/alpine/v3.20/releases/${ALPINE_ARCH}" \
            "https://mirror.uepg.br/alpine/v3.20/releases/${ALPINE_ARCH}" \
            "https://alpine.mirror.lstn.net/alpine/v3.20/releases/${ALPINE_ARCH}"; do
            local URL="${BASE_URL}/alpine-minirootfs-${VER}-${ALPINE_ARCH}.tar.gz"
            log INFO "Downloading Alpine ${VER} for ${ARCH_NAME}..."
            rm -f "$OUT_TAR"
            $DL "$OUT_TAR" "$URL" 2>&1
            if [ -s "$OUT_TAR" ]; then
                local FSIZE=$(stat -c%s "$OUT_TAR" 2>/dev/null || echo 0)
                if [ "$FSIZE" -gt 100000 ]; then
                    local HEAD=$(dd if="$OUT_TAR" bs=1 count=2 2>/dev/null | od -A n -t x1 | tr -d ' ')
                    if [ "$HEAD" = "1f8b" ]; then
                        log OK "Alpine ${VER} downloaded (${FSIZE} bytes)"
                        return 0
                    fi
                fi
                log WARN "Invalid download from $(echo $URL | cut -d/ -f3) (${FSIZE} bytes)"
                rm -f "$OUT_TAR"
            else
                log WARN "Download failed from $(echo $URL | cut -d/ -f3), retrying..."
                sleep 2
            fi
        done
        log WARN "All mirrors failed for ${VER}, trying next version..."
    done
    return 1
}

extract_rootfs() {
    local TARBALL="$1"
    local DEST="$2"
    mkdir -p "$DEST"
    local TMPDIR="$ANK_DIR/.extract_tmp"
    rm -rf "$TMPDIR" && mkdir -p "$TMPDIR"
    cd "$TMPDIR" && tar xzf "$TARBALL" 2>>"$LOG_FILE"; local TAR_RC=$?; cd /
    if [ $TAR_RC -ne 0 ]; then
        log WARN "tar extraction failed (rc=$TAR_RC)"
        return 1
    fi
    rm -rf "$DEST"/*; mkdir -p "$DEST"
    # Check if tar extracted with a single top-level directory (nested)
    local ITEMS=$(ls "$TMPDIR" 2>/dev/null)
    local COUNT=$(echo "$ITEMS" | wc -l)
    if [ "$COUNT" -eq 1 ] && [ -d "$TMPDIR/$ITEMS" ]; then
        # Single directory inside - move its CONTENTS, not the directory itself
        for item in "$TMPDIR/$ITEMS"/*; do
            [ -e "$item" ] && mv "$item" "$DEST/"
        done
        for item in "$TMPDIR/$ITEMS"/.*; do
            [ -e "$item" ] && [ "$(basename "$item")" != "." ] && [ "$(basename "$item")" != ".." ] && mv "$item" "$DEST/"
        done
    else
        for item in "$TMPDIR"/*; do
            [ -e "$item" ] && mv "$item" "$DEST/"
        done
    fi
    rm -rf "$TMPDIR"
    [ -f "$DEST/bin/sh" ] || [ -L "$DEST/bin/sh" ] || [ -f "$DEST/bin/busybox" ]
}

# ============================================================
# MAIN
# ============================================================

# Android su injects LD_PRELOAD=libsigchain.so which breaks curl SSL
unset LD_PRELOAD 2>/dev/null

mkdir -p "$ANK_DIR/logs" "$ANK_DIR/cache"
init_log
detect_arch

NETNS=0; PIDNS=0; OVERLAY=0; CHROOT=0; CGROUPS=0
command -v chroot >/dev/null 2>&1 && CHROOT=1
ip netns add _ank_test 2>/dev/null && { ip netns del _ank_test 2>/dev/null; NETNS=1; }
unshare --pid --fork /bin/true 2>/dev/null && PIDNS=1
cat /proc/filesystems 2>/dev/null | grep -q overlay && OVERLAY=1
[ -d /sys/fs/cgroup/ank ] 2>/dev/null || { mkdir -p /sys/fs/cgroup/ank 2>/dev/null && CGROUPS=1; }

if [ "$NETNS" -eq 1 ] && [ "$PIDNS" -eq 1 ] && [ "$CHROOT" -eq 1 ]; then
    MODE="isolated"
elif [ "$PIDNS" -eq 1 ] && [ "$CHROOT" -eq 1 ]; then
    MODE="shared_network"
elif [ "$CHROOT" -eq 1 ]; then
    MODE="shared_host"
else
    MODE="native_host"
fi

ui_print ""
ui_print "  ================================"
ui_print "   ANK - Android Konteiner v${ANK_VERSION}"
ui_print "  ================================"
ui_print ""

# --- STEP 1: Clean ---
log STEP "1/4 > Clean..."
cleanup
log OK "Done"

# Write mode file
mkdir -p "$ANK_DIR"
cat > "$ANK_DIR/mode" << MODEEOF
{"mode":"$MODE","chroot":$CHROOT,"netns":$NETNS,"pidns":$PIDNS,"overlay":$OVERLAY,"cgroups":$CGROUPS}
MODEEOF
log INFO "Mode: $MODE (chroot=$CHROOT netns=$NETNS pidns=$PIDNS overlay=$OVERLAY cgroups=$CGROUPS)"

# --- STEP 2: Get tarball (prebuild or build from scratch) ---
log STEP "2/4 > ANK-Engine..."

TARBALL="$ANK_DIR/cache/ank-prebuild-${ARCH_NAME}.tar.gz"
ALPINE_CACHE="$ANK_DIR/cache/alpine-minirootfs-${ALPINE_ARCH}.tar.gz"

# Try prebuild from ZIP
PREBUILD="$MODPATH/ankfs/ank-prebuild-${ARCH_NAME}.tar.gz"
if [ ! -s "$PREBUILD" ]; then
    log INFO "Extracting ank-prebuild..."
    unzip -o "$ZIPFILE" -d "$MODPATH" >>"$LOG_FILE" 2>&1
    rm -rf "$MODPATH/META-INF"
    PREBUILD="$MODPATH/ankfs/ank-prebuild-${ARCH_NAME}.tar.gz"
fi

if [ -s "$PREBUILD" ]; then
    # PATH A: Prebuild tarball found → use it
    log INFO "Using prebuilt: $(basename "$PREBUILD")"
    cp "$PREBUILD" "$TARBALL"
    log OK "Tarball ready"
else
    # PATH B: No tarball → download Alpine + install packages
    log WARN "ank-prebuild not found, building from scratch..."

    # Download Alpine minirootfs
    if [ ! -s "$ALPINE_CACHE" ]; then
        download_alpine "$ALPINE_CACHE" || die "Alpine download failed"
    fi

    # Build tarball from Alpine
    BUILDROOT="$ANK_DIR/cache/buildroot"
    rm -rf "$BUILDROOT"
    extract_rootfs "$ALPINE_CACHE" "$BUILDROOT" || die "Failed to extract Alpine"

    # Setup DNS + repos
    mkdir -p "$BUILDROOT/etc" "$BUILDROOT/etc/apk" "$BUILDROOT/var/cache/apk"
    echo "nameserver 8.8.8.8" > "$BUILDROOT/etc/resolv.conf"
    echo "nameserver 8.8.4.4" >> "$BUILDROOT/etc/resolv.conf"
    echo "127.0.0.1 localhost" > "$BUILDROOT/etc/hosts"
    echo "https://dl-cdn.alpinelinux.org/alpine/v3.20/main" > "$BUILDROOT/etc/apk/repositories"
    echo "https://dl-cdn.alpinelinux.org/alpine/v3.20/community" >> "$BUILDROOT/etc/apk/repositories"

    # Create /dev nodes in chroot (needed by openssh post-install)
    mkdir -p "$BUILDROOT/dev"
    [ -e "$BUILDROOT/dev/null" ] || mknod "$BUILDROOT/dev/null" c 1 3 2>/dev/null
    [ -e "$BUILDROOT/dev/urandom" ] || mknod "$BUILDROOT/dev/urandom" c 1 9 2>/dev/null
    [ -e "$BUILDROOT/dev/random" ] || mknod "$BUILDROOT/dev/random" c 1 8 2>/dev/null
    [ -e "$BUILDROOT/dev/tty" ] || mknod "$BUILDROOT/dev/tty" c 5 0 2>/dev/null
    [ -e "$BUILDROOT/dev/ptmx" ] || mknod "$BUILDROOT/dev/ptmx" c 5 2 2>/dev/null
    chmod 666 "$BUILDROOT/dev/null" "$BUILDROOT/dev/urandom" "$BUILDROOT/dev/random" "$BUILDROOT/dev/tty" "$BUILDROOT/dev/ptmx" 2>/dev/null
    mount --bind /dev/null "$BUILDROOT/dev/null" 2>/dev/null
    mount --bind /dev/urandom "$BUILDROOT/dev/urandom" 2>/dev/null
    mount --bind /dev/random "$BUILDROOT/dev/random" 2>/dev/null
    mount -t proc proc "$BUILDROOT/proc" 2>/dev/null

    # Inject host busybox into buildroot so chroot has a shell
    local HOST_BB=""
    for b in $(command -v busybox 2>/dev/null) /system/xbin/busybox /system/bin/busybox; do
        [ -x "$b" ] && HOST_BB="$b" && break
    done
    if [ -n "$HOST_BB" ]; then
        mkdir -p "$BUILDROOT/bin"
        cp -f "$HOST_BB" "$BUILDROOT/bin/busybox" 2>/dev/null
        chmod 755 "$BUILDROOT/bin/busybox" 2>/dev/null
        [ -L "$BUILDROOT/bin/sh" ] || ln -sf /bin/busybox "$BUILDROOT/bin/sh" 2>/dev/null
    fi

    # Install ALL packages — universal chroot (tries toybox, busybox, musl)
    log INFO "Installing packages..."
    APK_CMD="export PATH=/sbin:/usr/sbin:/bin:/usr/bin; apk update && apk add --no-cache python3 openssl openssh bash busybox shadow sshpass nginx"
    _chroot_rootfs "$BUILDROOT" "$APK_CMD"
    RET=$?
    umount "$BUILDROOT/proc" 2>/dev/null
    umount "$BUILDROOT/dev/null" 2>/dev/null
    umount "$BUILDROOT/dev/urandom" 2>/dev/null
    umount "$BUILDROOT/dev/random" 2>/dev/null
    [ $RET -ne 0 ] && die "Failed to install packages (all chroot methods failed)"
    log OK "All packages installed"

    # Setup busybox symlinks
    _chroot_rootfs "$BUILDROOT" "/bin/busybox --install -s /bin" 2>/dev/null || true
    [ ! -f "$BUILDROOT/bin/sh" ] && ln -sf /bin/busybox "$BUILDROOT/bin/sh" 2>/dev/null

    # Save as tarball
    rm -f "$TARBALL"
    cd "$BUILDROOT" && tar czf "$TARBALL" * 2>>"$LOG_FILE"; cd /
    RET=$?
    rm -rf "$BUILDROOT"
    [ $RET -ne 0 ] && [ ! -s "$TARBALL" ] && die "Failed to create tarball"
    log OK "Tarball built ($(stat -c%s "$TARBALL" 2>/dev/null || echo 0) bytes)"
fi

# --- STEP 2.5: Build ANKFS (tarball + engine) + ANK-ALPINEBASE (tarball limpo) ---
log STEP "2.5/4 > Building ANKFS + ANK-ALPINEBASE..."

# --- ANKFS = tarball + engine files ---
rm -rf "$ANKFS"
mkdir -p "$ANKFS"
cd "$ANKFS" && tar xzf "$TARBALL" 2>>"$LOG_FILE"; cd /
[ -f "$ANKFS/bin/sh" ] || [ -L "$ANKFS/bin/sh" ] || die "Failed to extract ANKFS from tarball"

# Device nodes for ANKFS
mkdir -p "$ANKFS/dev"
[ -e "$ANKFS/dev/null" ] || mknod "$ANKFS/dev/null" c 1 3 2>/dev/null
[ -e "$ANKFS/dev/urandom" ] || mknod "$ANKFS/dev/urandom" c 1 9 2>/dev/null
[ -e "$ANKFS/dev/random" ] || mknod "$ANKFS/dev/random" c 1 8 2>/dev/null
[ -e "$ANKFS/dev/tty" ] || mknod "$ANKFS/dev/tty" c 5 0 2>/dev/null
[ -e "$ANKFS/dev/ptmx" ] || mknod "$ANKFS/dev/ptmx" c 5 2 2>/dev/null
chmod 666 "$ANKFS/dev/null" "$ANKFS/dev/urandom" "$ANKFS/dev/random" "$ANKFS/dev/tty" "$ANKFS/dev/ptmx" 2>/dev/null

# DNS in ANKFS
mkdir -p "$ANKFS/etc"
echo "nameserver 8.8.8.8" > "$ANKFS/etc/resolv.conf"
echo "nameserver 8.8.4.4" >> "$ANKFS/etc/resolv.conf"
echo "127.0.0.1 localhost" > "$ANKFS/etc/hosts"

# System users in ANKFS
for u in nginx nobody; do
    grep -q "^${u}:" "$ANKFS/etc/passwd" 2>/dev/null || \
        echo "${u}:x:100:65534::/dev/null:/sbin/nologin" >> "$ANKFS/etc/passwd"
done
for g in nginx; do
    grep -q "^${g}:" "$ANKFS/etc/group" 2>/dev/null || \
        echo "${g}:x:100:" >> "$ANKFS/etc/group"
done

log OK "ANKFS built"

# --- ANK-ALPINEBASE = tarball limpo (pra containers) ---
ANKBASE="$ANK_DIR/images/ank-alpinebase-3.20"
log INFO "Building ANK-ALPINEBASE..."
rm -rf "$ANKBASE"
mkdir -p "$ANKBASE"
cd "$ANKBASE" && tar xzf "$TARBALL" 2>>"$LOG_FILE"; cd /
[ -f "$ANKBASE/bin/sh" ] || [ -L "$ANKBASE/bin/sh" ] || die "Failed to extract ANK-ALPINEBASE from tarball"

# Device nodes for ANK-ALPINEBASE
mkdir -p "$ANKBASE/dev"
[ -e "$ANKBASE/dev/null" ] || mknod "$ANKBASE/dev/null" c 1 3 2>/dev/null
[ -e "$ANKBASE/dev/urandom" ] || mknod "$ANKBASE/dev/urandom" c 1 9 2>/dev/null
[ -e "$ANKBASE/dev/random" ] || mknod "$ANKBASE/dev/random" c 1 8 2>/dev/null
[ -e "$ANKBASE/dev/tty" ] || mknod "$ANKBASE/dev/tty" c 5 0 2>/dev/null
[ -e "$ANKBASE/dev/ptmx" ] || mknod "$ANKBASE/dev/ptmx" c 5 2 2>/dev/null
chmod 666 "$ANKBASE/dev/null" "$ANKBASE/dev/urandom" "$ANKBASE/dev/random" "$ANKBASE/dev/tty" "$ANKBASE/dev/ptmx" 2>/dev/null

# DNS + repos for ANK-ALPINEBASE
mkdir -p "$ANKBASE/etc/apk" "$ANKBASE/var/cache/apk"
echo "http://dl-cdn.alpinelinux.org/alpine/v3.20/main" > "$ANKBASE/etc/apk/repositories"
echo "http://dl-cdn.alpinelinux.org/alpine/v3.20/community" >> "$ANKBASE/etc/apk/repositories"
echo "nameserver 8.8.8.8" > "$ANKBASE/etc/resolv.conf"
echo "nameserver 8.8.4.4" >> "$ANKBASE/etc/resolv.conf"
echo "127.0.0.1 localhost" > "$ANKBASE/etc/hosts"

# SSH config for containers
sed -i 's|^root:[^:]*:[^:]*:[^:]*:[^:]*:[^:]*:.*|root:x:0:0:root:/root:/bin/bash|' "$ANKBASE/etc/passwd" 2>/dev/null
mkdir -p "$ANKBASE/etc/ssh" "$ANKBASE/run/sshd"
cat > "$ANKBASE/etc/ssh/sshd_config" << 'SSHEOF'
Port 22
ListenAddress 0.0.0.0
PermitRootLogin yes
PasswordAuthentication yes
ChallengeResponseAuthentication no
X11Forwarding no
AllowTcpForwarding no
PidFile /run/sshd.pid
Subsystem sftp internal-sftp
SSHEOF
# Generate SSH host keys (needs /dev/urandom)
mount -t proc proc "$ANKBASE/proc" 2>/dev/null
_chroot_rootfs "$ANKBASE" "/usr/bin/ssh-keygen -A" 2>/dev/null || true
umount "$ANKBASE/proc" 2>/dev/null
mkdir -p "$ANKBASE/root/.ssh"
chmod 700 "$ANKBASE/root/.ssh"
touch "$ANKBASE/root/.ssh/authorized_keys"
chmod 600 "$ANKBASE/root/.ssh/authorized_keys"

# Security: no server files in container base image
rm -rf "$ANKBASE/opt/ank" 2>/dev/null

log OK "ANK-ALPINEBASE built"

# Remove buildroot cache
rm -rf "$ANK_DIR/cache/buildroot" 2>/dev/null

# ===== HANDSHAKE: export tarball if build_tarball.sh exists =====
EXPORT_SCRIPT="$MODPATH/server/scripts/build_tarball.sh"
[ ! -f "$EXPORT_SCRIPT" ] && EXPORT_SCRIPT="$(dirname "$MODPATH")/server/scripts/build_tarball.sh"
if [ -f "$EXPORT_SCRIPT" ]; then
    log INFO "Exporting prebuilt engine..."
    EXPORT_DIR="/sdcard/Download/ank-exports"
    mkdir -p "$EXPORT_DIR"
    EXPORT_OUT="$EXPORT_DIR/ank-prebuild-${ARCH_NAME}.tar.gz"
    cp "$TARBALL" "$EXPORT_OUT" 2>>"$LOG_FILE"
    if [ -s "$EXPORT_OUT" ]; then
        log OK "Prebuild exported to $EXPORT_OUT"
    else
        log WARN "Export failed (non-critical)"
    fi
else
    log INFO "Export skipped (export script not available)"
    # No export script → remove temp tarball after use
    rm -f "$TARBALL"
fi

# --- Extract ZIP early (STEP 3 needs $SRC) ---
SRC="$MODPATH"
if [ ! -f "$SRC/server/server.py" ]; then
    mkdir -p "$SRC"
    unzip -o "$ZIPFILE" -d "$SRC" >>"$LOG_FILE" 2>&1
    rm -rf "$SRC/META-INF"
fi

# --- STEP 3: ANK Core addons (config only - prebuild already has all packages) ---
log STEP "3/4 > Configuring ANK Core addons..."
# Setup DNS + mount proc (needed for ssh-keygen in chroot)
mkdir -p "$ANKFS/etc/apk" "$ANKFS/var/cache/apk" 2>/dev/null
echo "nameserver 8.8.8.8" > "$ANKFS/etc/resolv.conf" 2>/dev/null
echo "nameserver 8.8.4.4" >> "$ANKFS/etc/resolv.conf" 2>/dev/null
echo "https://dl-cdn.alpinelinux.org/alpine/v3.20/main" > "$ANKFS/etc/apk/repositories" 2>/dev/null
echo "https://dl-cdn.alpinelinux.org/alpine/v3.20/community" >> "$ANKFS/etc/apk/repositories" 2>/dev/null
mount -t proc proc "$ANKFS/proc" 2>/dev/null

# Configure sshd (prebuild already has openssh, bash, shadow installed)
if [ -d "$ANKFS/etc/ssh" ]; then
    sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
    sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
    sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
    sed -i '/^UsePAM/d' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
    [ ! -f "$ANKFS/etc/ssh/ssh_host_rsa_key" ] && \
        _chroot_rootfs "$ANKFS" "/usr/bin/ssh-keygen -A" 2>/dev/null || true
    mkdir -p "$ANKFS/root/.ssh"
    chmod 700 "$ANKFS/root/.ssh"
    touch "$ANKFS/root/.ssh/authorized_keys"
    chmod 600 "$ANKFS/root/.ssh/authorized_keys"
    mkdir -p "$ANKFS/run/sshd"
        # Configure sshd for ANK SSH access (port 2200)
        mkdir -p "$ANKFS/etc/ssh/sshd_config.d"
        cat > "$ANKFS/etc/ssh/ank-sshd.conf" << 'SSHEOF'
Port 2200
ListenAddress 0.0.0.0
PermitRootLogin yes
PasswordAuthentication yes
ChallengeResponseAuthentication no
X11Forwarding no
AllowTcpForwarding no
PidFile /run/ankd/sshd.pid
Subsystem sftp internal-sftp
SSHEOF
        # Merge into main sshd_config
        if [ -f "$ANKFS/etc/ssh/sshd_config" ]; then
            grep -v "^Port \|^ListenAddress \|^PermitRootLogin \|^PasswordAuthentication \|^ChallengeResponse \|^X11Forwarding \|^AllowTcpForwarding \|^PidFile \|^Subsystem sftp" \
                "$ANKFS/etc/ssh/sshd_config" > "$ANKFS/etc/ssh/sshd_config.tmp" 2>/dev/null
            cat "$ANKFS/etc/ssh/ank-sshd.conf" >> "$ANKFS/etc/ssh/sshd_config.tmp"
            mv "$ANKFS/etc/ssh/sshd_config.tmp" "$ANKFS/etc/ssh/sshd_config"
        fi
        mkdir -p "$ANKFS/run/ankd"
        log OK "SSH configured (port 2200)"
    fi
umount "$ANKFS/proc" 2>/dev/null

# Install ANK shell + set root shell
if [ -f "$ANKFS/usr/sbin/sshd" ]; then
    cp "$SRC/server/ank-shell.sh" "$ANKFS/ank-shell.sh" 2>/dev/null
    chmod 755 "$ANKFS/ank-shell.sh" 2>/dev/null
    sed -i '1s|#!/system/bin/sh|#!/bin/sh|' "$ANKFS/ank-shell.sh" 2>/dev/null
    sed -i 's|^root:.*|root:/bin/sh|' "$ANKFS/etc/passwd" 2>/dev/null
    log OK "ANK Shell installed"
fi
log OK "ANK Core addons installed"

# Install ankcoreshell in ankfs
if [ -f "$SRC/server/ankcoreshell.sh" ]; then
    cp "$SRC/server/ankcoreshell.sh" "$ANKFS/ankcoreshell.sh"
    chmod 755 "$ANKFS/ankcoreshell.sh"
    # Set root shell to ankcoreshell
    sed -i 's|^root:[^:]*:[^:]*:[^:]*:[^:]*:[^:]*:.*|root:x:0:0:root:/root:/ankcoreshell.sh|' "$ANKFS/etc/passwd" 2>/dev/null
    log OK "ankcoreshell installed"
fi

# Set root password in ankfs from config.json
ANK_PASS=$(grep -o '"password":"[^"]*"' "$ANK_DIR/config.json" 2>/dev/null | head -1 | cut -d'"' -f4)
[ -z "$ANK_PASS" ] && ANK_PASS="ank123"
if [ -f "$ANKFS/usr/sbin/chpasswd" ] || [ -f "$ANKFS/usr/bin/chpasswd" ]; then
    echo "root:${ANK_PASS}" | _chroot_rootfs "$ANKFS" "cat > /tmp/pw && chpasswd" 2>/dev/null || \
    echo "root:${ANK_PASS}" | _chroot_rootfs "$ANKFS" "/sbin/chpasswd" 2>/dev/null || true
    log OK "root password set in ankfs"
fi

# --- STEP 4: Server + scripts ---
log STEP "4/4 > Server + scripts..."

mkdir -p "$ANKFS/opt/ank/static" "$ANK_DIR/core"
[ -f "$SRC/server/server.py" ] || die "server.py not found"

cp "$SRC/server/server.py" "$ANKFS/opt/ank/server.py"
chmod 755 "$ANKFS/opt/ank/server.py"

# Copy all server modules (stack_manager, node_manager, backup_*, ank_*, etc.)
for f in "$SRC/server/"*.py; do
    [ -f "$f" ] && cp "$f" "$ANKFS/opt/ank/" && chmod 755 "$ANKFS/opt/ank/$(basename "$f")"
done

SC=0
cp -r "$SRC/server/static/"* "$ANKFS/opt/ank/static/" 2>/dev/null
SC=$(find "$ANKFS/opt/ank/static/" -type f 2>/dev/null | wc -l)

SHC=0
for f in "$SRC/scripts/"*.sh; do
    [ -f "$f" ] || continue
    cp "$f" "$ANK_DIR/core/"
    chmod 755 "$ANK_DIR/core/$(basename "$f")"
    SHC=$((SHC+1))
done

mkdir -p "$ANKFS/opt/ank/scripts"
for f in "$SRC/scripts/"*.sh; do [ -f "$f" ] && cp "$f" "$ANKFS/opt/ank/scripts/"; done
mkdir -p "$ANKFS/opt/ank/bin"
mkdir -p "$ANK_DIR/core/ankd"
if [ -d "$SRC/server/ankd" ]; then
    cp -r "$SRC/server/ankd/"* "$ANK_DIR/core/ankd/" 2>/dev/null
    chmod 755 "$ANK_DIR/core/ankd/"*.sh 2>/dev/null
fi
if [ -f "$SRC/server/static/ank-cli.py" ]; then
    cp "$SRC/server/static/ank-cli.py" "$ANKFS/opt/ank/bin/ank"
    cp "$SRC/server/static/ank-cli.py" "$ANKFS/opt/ank/bin/ank-core"
    chmod 755 "$ANKFS/opt/ank/bin/ank" "$ANKFS/opt/ank/bin/ank-core"
fi
if [ -f "$SRC/server/static/ank-profile.sh" ]; then
    cp "$SRC/server/static/ank-profile.sh" "$ANKFS/opt/ank/ank-profile.sh"
    chmod 755 "$ANKFS/opt/ank/ank-profile.sh"
fi
if [ -f "$SRC/scripts/ank-shell.sh" ]; then
    cp "$SRC/scripts/ank-shell.sh" "$ANKFS/ank-shell.sh"
    chmod 755 "$ANKFS/ank-shell.sh"
fi
mkdir -p "$ANK_DIR/core/static"
cp -r "$SRC/server/static/"* "$ANK_DIR/core/static/" 2>/dev/null
mkdir -p "$ANK_DIR/images"
mkdir -p "$ANK_DIR/ank-engine"

[ "$SHC" -eq 0 ] && die "No scripts found"

if [ ! -f "$ANK_DIR/config.json" ]; then
    cat > "$ANK_DIR/config.json" << EOF
{"version":"$ANK_VERSION","panel_port":8001,"username":"admin","password":"admin123","first_boot":true,"autostart_on_boot":true,"host_sh":"/system/bin/sh","network":{"bridge":"ank0","subnet":"10.20.30.0","gateway":"10.20.30.1","nat":true},"resources":{"max_ram_mb":512,"cpu_shares":512}}
EOF
fi

mkdir -p "$ANK_SDCARD"
cat > "$ANK_SDCARD/CREDENCIAIS.txt" << EOF
ANK v$ANK_VERSION
Painel: https://localhost:8001
Usuario: admin
Senha: admin123
EOF

log OK "$SC static, $SHC scripts"

echo "" >> "$LOG_FILE"
echo "=== Complete ===" >> "$LOG_FILE"
log OK "Installation complete!"
cp_log_to_sdcard

ui_print ""
ui_print "  DONE > $ARCH_NAME > $MODE"
ui_print "  Panel: https://localhost:8001"
ui_print "  Login: admin / admin123"
ui_print "  Log: $ANK_DIR/logs/install.log"
ui_print ""
exit 0

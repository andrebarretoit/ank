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
    ui_print "[$level] $*"
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
    local raw=$(uname -m)
    case "$raw" in
        aarch64|arm64) ARCH_NAME="aarch64" ;;
        armv7*|armhf|armv8*) ARCH_NAME="armv7" ;;
        x86_64) ARCH_NAME="x86_64" ;;
        *) ARCH_NAME="$raw" ;;
    esac
}

find_dl_tool() {
    DL=""
    command -v wget >/dev/null 2>&1 && DL="wget -q -O"
    if [ -z "$DL" ]; then
        command -v curl >/dev/null 2>&1 && DL="curl -sL -o"
    fi
    if [ -z "$DL" ]; then
        [ -f /system/bin/toybox ] && /system/bin/toybox wget --help >/dev/null 2>&1 && DL="/system/bin/toybox wget -q -O"
    fi
    [ -z "$DL" ] && return 1
    return 0
}

download_alpine() {
    local OUT_TAR="$1"
    find_dl_tool || die "No download tool (wget/curl)"
    for VER in "3.20.2" "3.20.1" "3.20.0" "3.19.1"; do
        local URL="https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/${ARCH_NAME}/alpine-minirootfs-${VER}-${ARCH_NAME}.tar.gz"
        log INFO "Downloading Alpine ${VER} ${ARCH_NAME}..."
        rm -f "$OUT_TAR"
        $DL "$OUT_TAR" "$URL" 2>>"$LOG_FILE"
        if [ -s "$OUT_TAR" ]; then
            local FSIZE=$(stat -c%s "$OUT_TAR" 2>/dev/null || echo 0)
            if [ "$FSIZE" -gt 100000 ]; then
                local HEAD=$(dd if="$OUT_TAR" bs=1 count=2 2>/dev/null | od -A n -t x1 | tr -d ' ')
                if [ "$HEAD" = "1f8b" ]; then
                    log OK "Alpine ${VER} downloaded (${FSIZE} bytes)"
                    return 0
                fi
            fi
            log WARN "Invalid download for ${VER} (${FSIZE} bytes), trying next..."
            rm -f "$OUT_TAR"
        fi
    done
    return 1
}

extract_rootfs() {
    local TARBALL="$1"
    local DEST="$2"
    mkdir -p "$DEST"
    local TMPDIR="$ANK_DIR/.extract_tmp"
    rm -rf "$TMPDIR" && mkdir -p "$TMPDIR"
    cd "$TMPDIR" && tar xzf "$TARBALL" 2>>"$LOG_FILE"; cd /
    rm -rf "$DEST"/*; mkdir -p "$DEST"
    for item in "$TMPDIR"/*; do
        [ -e "$item" ] && mv "$item" "$DEST/"
    done
    rm -rf "$TMPDIR"
    [ -f "$DEST/bin/sh" ] || [ -L "$DEST/bin/sh" ] || [ -f "$DEST/bin/busybox" ]
}

# ============================================================
# MAIN
# ============================================================

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

# --- STEP 2: Find or build ankcore tarball ---
log STEP "2/4 > Rootfs + Python3..."

# Try to locate tarball: inside ZIP > on sdcard
ANKCORE="$MODPATH/ankcore-${ARCH_NAME}.tar.gz"
if [ ! -s "$ANKCORE" ]; then
    ANKCORE="/sdcard/Download/ankcore-${ARCH_NAME}.tar.gz"
fi
if [ ! -s "$ANKCORE" ]; then
    log INFO "Extracting tarball from ZIP..."
    unzip -o "$ZIPFILE" -d "$MODPATH" >>"$LOG_FILE" 2>&1
    rm -rf "$MODPATH/META-INF"
    ANKCORE="$MODPATH/ankcore-${ARCH_NAME}.tar.gz"
fi
TARBALL_FOUND=0
[ -s "$ANKCORE" ] && TARBALL_FOUND=1

# Shared Alpine tarball cache (used for both ankfs build-from-scratch AND container image)
ALPINE_CACHE="$ANK_DIR/cache/alpine-minirootfs-${ARCH_NAME}.tar.gz"

if [ "$TARBALL_FOUND" -eq 1 ]; then
    # ===== PATH A: Tarball exists -> extract as ankfs =====
    log INFO "ankcore tarball found: $(stat -c%s "$ANKCORE" 2>/dev/null || echo 0) bytes"
    rm -rf "$ANKFS"
    mkdir -p "$ANKFS"
    cd "$ANKFS" && tar xzf "$ANKCORE" 2>>"$LOG_FILE"; cd /
    log OK "ankcore extracted"

    # Ensure container base image exists (download if needed)
    IMG_DIR="$ANK_DIR/images/$BASE_IMAGE"
    if [ ! -e "$IMG_DIR/bin/sh" ] && [ ! -e "$IMG_DIR/bin/busybox" ]; then
        log INFO "Container base image not found, downloading..."
        if [ ! -s "$ALPINE_CACHE" ]; then
            download_alpine "$ALPINE_CACHE" || die "Alpine download failed"
        fi
        extract_rootfs "$ALPINE_CACHE" "$IMG_DIR" || die "Failed to extract container base image"
        # Configure repos + DNS on image
        mkdir -p "$IMG_DIR/etc/apk" "$IMG_DIR/var/cache/apk"
        echo "http://dl-cdn.alpinelinux.org/alpine/v3.20/main" > "$IMG_DIR/etc/apk/repositories"
        echo "http://dl-cdn.alpinelinux.org/alpine/v3.20/community" >> "$IMG_DIR/etc/apk/repositories"
        echo "nameserver 8.8.8.8" > "$IMG_DIR/etc/resolv.conf"
        echo "nameserver 8.8.4.4" >> "$IMG_DIR/etc/resolv.conf"
        echo "127.0.0.1 localhost" > "$IMG_DIR/etc/hosts"
        log OK "Container base image ready"
    fi
else
    # ===== PATH B: No tarball -> build ankfs from scratch + save image =====
    log WARN "ankcore tarball not found, building from scratch..."

    # Download Alpine minirootfs
    if [ ! -s "$ALPINE_CACHE" ]; then
        download_alpine "$ALPINE_CACHE" || die "Alpine download failed"
    fi

    # Build ankfs from Alpine
    BUILDROOT="$ANK_DIR/cache/buildroot"
    rm -rf "$BUILDROOT"
    extract_rootfs "$ALPINE_CACHE" "$BUILDROOT" || die "Failed to extract Alpine for ankfs"

    # Setup DNS + repos
    mkdir -p "$BUILDROOT/etc" "$BUILDROOT/etc/apk" "$BUILDROOT/var/cache/apk"
    echo "nameserver 8.8.8.8" > "$BUILDROOT/etc/resolv.conf"
    echo "nameserver 8.8.4.4" >> "$BUILDROOT/etc/resolv.conf"
    echo "127.0.0.1 localhost" > "$BUILDROOT/etc/hosts"
    echo "https://dl-cdn.alpinelinux.org/alpine/v3.20/main" > "$BUILDROOT/etc/apk/repositories"
    echo "https://dl-cdn.alpinelinux.org/alpine/v3.20/community" >> "$BUILDROOT/etc/apk/repositories"

    # Install python3 + deps in ankfs
    log INFO "Installing python3, openssl, openssh in chroot..."
    mount -t proc proc "$BUILDROOT/proc" 2>/dev/null
    chroot "$BUILDROOT" /bin/sh -c "apk update && apk add --no-cache python3 openssl openssh bash busybox shadow" 2>>"$LOG_FILE"
    RET=$?
    umount "$BUILDROOT/proc" 2>/dev/null
    [ $RET -ne 0 ] && die "Failed to install packages in chroot"

    # Setup busybox symlinks
    if [ -f "$BUILDROOT/bin/busybox" ]; then
        chroot "$BUILDROOT" /bin/busybox --install -s /bin 2>/dev/null
    fi
    [ ! -f "$BUILDROOT/bin/sh" ] && ln -sf /bin/busybox "$BUILDROOT/bin/sh" 2>/dev/null

    # Save as ankfs
    rm -rf "$ANKFS"
    mv "$BUILDROOT" "$ANKFS"
    log OK "ankfs built from scratch"

    # Save clean Alpine as container base image (same download, no packages installed)
    IMG_DIR="$ANK_DIR/images/$BASE_IMAGE"
    extract_rootfs "$ALPINE_CACHE" "$IMG_DIR" || die "Failed to extract container base image"
    mkdir -p "$IMG_DIR/etc/apk" "$IMG_DIR/var/cache/apk"
    echo "http://dl-cdn.alpinelinux.org/alpine/v3.20/main" > "$IMG_DIR/etc/apk/repositories"
    echo "http://dl-cdn.alpinelinux.org/alpine/v3.20/community" >> "$IMG_DIR/etc/apk/repositories"
    echo "nameserver 8.8.8.8" > "$IMG_DIR/etc/resolv.conf"
    echo "nameserver 8.8.4.4" >> "$IMG_DIR/etc/resolv.conf"
    echo "127.0.0.1 localhost" > "$IMG_DIR/etc/hosts"
    log OK "Container base image saved"
fi

# --- STEP 2.5: Build ank-alpinebase (pre-built container base with openssh/bash/busybox) ---
log STEP "2.5/4 > Building ank-alpinebase..."
ANKBASE="$ANK_DIR/images/ank-alpinebase"
if [ ! -d "$ANKBASE/bin" ]; then
    IMG_DIR="$ANK_DIR/images/$BASE_IMAGE"
    if [ -d "$IMG_DIR" ]; then
        cp -a "$IMG_DIR" "$ANKBASE"
        echo "nameserver 8.8.8.8" > "$ANKBASE/etc/resolv.conf"
        echo "nameserver 8.8.4.4" >> "$ANKBASE/etc/resolv.conf"
        echo "127.0.0.1 localhost" > "$ANKBASE/etc/hosts"
        mount -t proc proc "$ANKBASE/proc" 2>/dev/null
        chroot "$ANKBASE" /sbin/apk add --no-cache busybox bash shadow openssh s6 2>>"$LOG_FILE"
        RET=$?
        umount "$ANKBASE/proc" 2>/dev/null
        if [ $RET -eq 0 ]; then
            chroot "$ANKBASE" /bin/busybox --install -s /bin 2>/dev/null
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
            chroot "$ANKBASE" /usr/bin/ssh-keygen -A 2>>"$LOG_FILE" || true
            mkdir -p "$ANKBASE/root/.ssh"
            chmod 700 "$ANKBASE/root/.ssh"
            touch "$ANKBASE/root/.ssh/authorized_keys"
            chmod 600 "$ANKBASE/root/.ssh/authorized_keys"
            mkdir -p "$ANKBASE/etc/s6/services"
            rm -rf "$ANKBASE/opt/ank" 2>/dev/null
            log OK "ank-alpinebase built (openssh, bash, busybox, shadow, s6)"
        else
            log WARN "ank-alpinebase apk install failed, containers will install packages individually"
        fi
    fi
else
    log OK "ank-alpinebase already exists"
fi

# --- Verify python3 in ankfs ---
[ ! -f "$ANKFS/usr/bin/python3" ] && die "python3 not found in ankfs"
log OK "python3 installed"

# System users in ankfs
for u in nginx nobody; do
    grep -q "^${u}:" "$ANKFS/etc/passwd" 2>/dev/null || \
        echo "${u}:x:100:65534::/dev/null:/sbin/nologin" >> "$ANKFS/etc/passwd"
done
for g in nginx; do
    grep -q "^${g}:" "$ANKFS/etc/group" 2>/dev/null || \
        echo "${g}:x:100:" >> "$ANKFS/etc/group"
done
log OK "system users created"

# DNS in ankfs
mkdir -p "$ANKFS/etc"
echo "nameserver 8.8.8.8" > "$ANKFS/etc/resolv.conf"
echo "nameserver 8.8.4.4" >> "$ANKFS/etc/resolv.conf"
echo "127.0.0.1 localhost" > "$ANKFS/etc/hosts"

# --- STEP 3: openssh in ankfs ---
log STEP "3/4 > openssh..."
if [ -f "$ANKFS/usr/bin/apk" ]; then
    chroot "$ANKFS" /usr/bin/apk add --no-cache openssh openssl 2>>"$LOG_FILE" || log WARN "openssh install failed (non-fatal)"
    if [ -d "$ANKFS/etc/ssh" ]; then
        sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        sed -i '/^UsePAM/d' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        [ ! -f "$ANKFS/etc/ssh/ssh_host_rsa_key" ] && \
            chroot "$ANKFS" /usr/bin/ssh-keygen -A 2>>"$LOG_FILE" || true
        mkdir -p "$ANKFS/root/.ssh"
        chmod 700 "$ANKFS/root/.ssh"
        touch "$ANKFS/root/.ssh/authorized_keys"
        chmod 600 "$ANKFS/root/.ssh/authorized_keys"
        mkdir -p "$ANKFS/run/sshd"
        log OK "openssh configured"
    fi
fi

# Copy openssh binaries + libs to container base image
IMG_DIR="$ANK_DIR/images/$BASE_IMAGE"
if [ -f "$ANKFS/usr/sbin/sshd" ] && [ -d "$IMG_DIR" ]; then
    mkdir -p "$IMG_DIR/usr/sbin" "$IMG_DIR/usr/bin" "$IMG_DIR/usr/lib"
    cp "$ANKFS/usr/sbin/sshd" "$IMG_DIR/usr/sbin/sshd" 2>/dev/null
    cp "$ANKFS/usr/bin/ssh" "$IMG_DIR/usr/bin/ssh" 2>/dev/null
    cp "$ANKFS/usr/bin/ssh-keygen" "$IMG_DIR/usr/bin/ssh-keygen" 2>/dev/null
    mkdir -p "$IMG_DIR/etc/ssh"
    [ -d "$ANKFS/etc/ssh" ] && cp "$ANKFS/etc/ssh/"* "$IMG_DIR/etc/ssh/" 2>/dev/null
    mkdir -p "$IMG_DIR/root/.ssh"
    chmod 700 "$IMG_DIR/root/.ssh"
    touch "$IMG_DIR/root/.ssh/authorized_keys"
    chmod 600 "$IMG_DIR/root/.ssh/authorized_keys"
    mkdir -p "$IMG_DIR/run/sshd"
    for lib in "$ANKFS/usr/lib/"libcrypto*.so* "$ANKFS/usr/lib/"libssl*.so* "$ANKFS/lib/"libz*.so* "$ANKFS/lib/"libc*.so* "$ANKFS/lib/"libutil*.so* "$ANKFS/lib/"libpthread*.so*; do
        [ -e "$lib" ] && cp "$lib" "$IMG_DIR/usr/lib/" 2>/dev/null
    done
    log OK "openssh copied to container image"
fi
# Security: ensure no server files in container image
rm -rf "$IMG_DIR/opt/ank" 2>/dev/null
log OK "$BASE_IMAGE image ready"

# --- STEP 4: Server + scripts ---
log STEP "4/4 > Server..."
SRC="$MODPATH"
if [ ! -f "$SRC/server/server.py" ]; then
    mkdir -p "$SRC"
    unzip -o "$ZIPFILE" -d "$SRC" >>"$LOG_FILE" 2>&1
    rm -rf "$SRC/META-INF"
fi

mkdir -p "$ANKFS/opt/ank/static" "$ANK_DIR/core"
[ -f "$SRC/server/server.py" ] || die "server.py not found"

cp "$SRC/server/server.py" "$ANKFS/opt/ank/server.py"
chmod 755 "$ANKFS/opt/ank/server.py"

SC=0
for f in "$SRC/server/static/"*; do [ -f "$f" ] && cp "$f" "$ANKFS/opt/ank/static/" && SC=$((SC+1)); done

SHC=0
for f in "$SRC/scripts/"*.sh; do
    [ -f "$f" ] || continue
    cp "$f" "$ANK_DIR/core/"
    chmod 755 "$ANK_DIR/core/$(basename "$f")"
    SHC=$((SHC+1))
done

mkdir -p "$ANKFS/opt/ank/scripts"
for f in "$SRC/scripts/"*.sh; do [ -f "$f" ] && cp "$f" "$ANKFS/opt/ank/scripts/"; done
mkdir -p "$ANK_DIR/core/static"
for f in "$SRC/server/static/"*; do [ -f "$f" ] && cp "$f" "$ANK_DIR/core/static/"; done
mkdir -p "$ANK_DIR/images"

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
cp_log_to_sdcard

ui_print ""
ui_print "  DONE > $ARCH_NAME > $MODE"
ui_print "  Panel: https://localhost:8001"
ui_print "  Login: admin / admin123"
ui_print "  Log: $ANK_DIR/logs/install.log"
ui_print ""
exit 0

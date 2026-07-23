#!/system/bin/sh
ANK_VERSION="2.0.0"
ANK_DIR="/data/local/ank"
ANKFS="$ANK_DIR/ankfs"
ANK_SDCARD="/sdcard/AndroidKonteiner"
LOG_FILE="$ANK_DIR/logs/install.log"
REPO="http://dl-cdn.alpinelinux.org/alpine/v3.20"

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
    # Kill server
    pkill -f "ld-musl.*python3.*server.py" 2>/dev/null
    # Kill ALL container init processes (they hold mount points)
    for cpid in $(pgrep -f "sh.*_ank_exit" 2>/dev/null); do
        kill -TERM "$cpid" 2>/dev/null
    done
    # Also kill any sshd inside containers
    for cpid in $(pgrep -f "sshd.*PidFile" 2>/dev/null); do
        kill -TERM "$cpid" 2>/dev/null
    done
    sleep 1
    # Force kill anything remaining
    pkill -9 -f "sh.*_ank_exit" 2>/dev/null
    pkill -9 -f "sshd.*PidFile" 2>/dev/null
    # Unmount all container filesystems
    for c in "$ANK_DIR/containers"/*/; do
        [ -d "$c" ] || continue
        umount "$c/merged/proc" 2>/dev/null
        umount "$c/merged/dev/pts" 2>/dev/null
        umount "$c/merged/dev/shm" 2>/dev/null
        umount "$c/merged/dev" 2>/dev/null
        umount "$c/merged/sys" 2>/dev/null
        umount "$c/merged" 2>/dev/null
    done
    umount "$ANKFS/proc" 2>/dev/null
    umount "$ANKFS/dev/pts" 2>/dev/null
    umount "$ANKFS/dev/shm" 2>/dev/null
    umount "$ANKFS/dev" 2>/dev/null
    umount "$ANKFS/sys" 2>/dev/null
    rm -rf "$ANKFS" "$ANK_DIR/containers" "$ANK_DIR/core" "$ANK_DIR/images" "$ANK_DIR/config.json"
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

# ============================================================
# MAIN
# ============================================================

mkdir -p "$ANK_DIR/logs" "$ANK_DIR/cache"
init_log
detect_arch

# Detect mode > tiered by available capabilities
NETNS=0; PIDNS=0; OVERLAY=0; CHROOT=0; CGROUPS=0
command -v chroot >/dev/null 2>&1 && CHROOT=1
ip netns add _ank_test 2>/dev/null && { ip netns del _ank_test 2>/dev/null; NETNS=1; }
unshare --pid --fork /bin/true 2>/dev/null && PIDNS=1
cat /proc/filesystems 2>/dev/null | grep -q overlay && OVERLAY=1
[ -d /sys/fs/cgroup/ank ] 2>/dev/null || { mkdir -p /sys/fs/cgroup/ank 2>/dev/null && CGROUPS=1; }

# Tier selection:
#   isolated      = netns + pidns + chroot + overlay (Tier X)
#   shared_network = pidns + chroot + overlay, no netns (Tier Y)
#   shared_host   = chroot only (Tier Z)
#   native_host   = nothing (Tier W)
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

# Write mode file AFTER cleanup (cleanup no longer deletes it)
mkdir -p "$ANK_DIR"
cat > "$ANK_DIR/mode" << MODEEOF
{"mode":"$MODE","chroot":$CHROOT,"netns":$NETNS,"pidns":$PIDNS,"overlay":$OVERLAY,"cgroups":$CGROUPS}
MODEEOF
log INFO "Mode: $MODE (chroot=$CHROOT netns=$NETNS pidns=$PIDNS overlay=$OVERLAY cgroups=$CGROUPS)"

# --- STEP 2+3: Rootfs + Python3 (pre-built ankcore) ---
log STEP "2/4 > Rootfs + Python3..."

ANKCORE="$MODPATH/ankcore-${ARCH_NAME}.tar.gz"
if [ ! -s "$ANKCORE" ]; then
    ANKCORE="/sdcard/Download/ankcore-${ARCH_NAME}.tar.gz"
fi
if [ ! -s "$ANKCORE" ]; then
    # Extract from ZIP directly
    log INFO "Extracting tarball from ZIP..."
    unzip -o "$ZIPFILE" -d "$MODPATH" >>"$LOG_FILE" 2>&1
    rm -rf "$MODPATH/META-INF"
    ANKCORE="$MODPATH/ankcore-${ARCH_NAME}.tar.gz"
fi

# Build rootfs from scratch if tarball not found
if [ ! -s "$ANKCORE" ]; then
    log WARN "ankcore tarball not found â€” building from scratch..."
    BUILDROOT="$ANK_DIR/cache/buildroot"
    rm -rf "$BUILDROOT"
    mkdir -p "$BUILDROOT" "$ANK_DIR/cache"

    # Determine Alpine arch
    case "$ARCH_NAME" in
        aarch64) ALPINE_ARCH="aarch64" ;;
        armv7) ALPINE_ARCH="armv7" ;;
        x86_64) ALPINE_ARCH="x86_64" ;;
        *) ALPINE_ARCH="$ARCH_NAME" ;;
    esac

    # Find available download tool
    DL=""
    command -v wget >/dev/null 2>&1 && DL="wget -q -O"
    if [ -z "$DL" ]; then
        command -v curl >/dev/null 2>&1 && DL="curl -sL -o"
    fi
    # Android toybox wget (no HTTPS usually, but try)
    if [ -z "$DL" ]; then
        [ -f /system/bin/toybox ] && /system/bin/toybox wget --help >/dev/null 2>&1 && DL="/system/bin/toybox wget -q -O"
    fi
    [ -z "$DL" ] && die "No download tool found (wget/curl). InstallBusybox first."

    # Try multiple Alpine versions
    ALPINE_TAR="$ANK_DIR/cache/alpine-minirootfs.tar.gz"
    OK=0
    for VER in "3.20.2" "3.20.1" "3.20.0" "3.19.1" "3.19.0"; do
        ALPINE_URL="https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/${ALPINE_ARCH}/alpine-minirootfs-${VER}-${ALPINE_ARCH}.tar.gz"
        log INFO "Trying Alpine ${VER} ${ALPINE_ARCH}..."
        rm -f "$ALPINE_TAR"
        $DL "$ALPINE_TAR" "$ALPINE_URL" 2>>"$LOG_FILE"
        # Validate: file must be >100KB and start with valid gzip magic
        if [ -s "$ALPINE_TAR" ]; then
            FSIZE=$(stat -c%s "$ALPINE_TAR" 2>/dev/null || echo 0)
            if [ "$FSIZE" -gt 100000 ]; then
                # Check gzip magic (1f 8b)
                HEAD=$(dd if="$ALPINE_TAR" bs=1 count=2 2>/dev/null | od -A n -t x1 | tr -d ' ')
                if [ "$HEAD" = "1f8b" ]; then
                    log OK "Alpine ${VER} downloaded (${FSIZE} bytes)"
                    OK=1
                    break
                fi
            fi
            log WARN "Invalid download for ${VER} (${FSIZE} bytes), trying next..."
            rm -f "$ALPINE_TAR"
        fi
    done
    [ "$OK" -eq 0 ] && die "Failed to download Alpine minirootfs for ${ALPINE_ARCH}"

    # Extract minirootfs
    rm -rf "$BUILDROOT"
    mkdir -p "$BUILDROOT"
    cd "$BUILDROOT" && tar xzf "$ALPINE_TAR" 2>>"$LOG_FILE"
    if [ $? -ne 0 ] || [ ! -f "$BUILDROOT/bin/sh" ]; then
        cd /
        rm -rf "$BUILDROOT"
        die "Failed to extract Alpine minirootfs (tar error or missing /bin/sh)"
    fi
    cd /
    log OK "Alpine minirootfs extracted"

    # Setup DNS
    mkdir -p "$BUILDROOT/etc"
    echo "nameserver 8.8.8.8" > "$BUILDROOT/etc/resolv.conf"
    echo "nameserver 8.8.4.4" >> "$BUILDROOT/etc/resolv.conf"
    echo "127.0.0.1 localhost" > "$BUILDROOT/etc/hosts"

    # Setup apk repos
    mkdir -p "$BUILDROOT/etc/apk"
    echo "https://dl-cdn.alpinelinux.org/alpine/v3.20/main" > "$BUILDROOT/etc/apk/repositories"
    echo "https://dl-cdn.alpinelinux.org/alpine/v3.20/community" >> "$BUILDROOT/etc/apk/repositories"

    # Install packages inside chroot (mount /proc first for apk)
    log INFO "Installing python3, openssl, openssh in chroot..."
    mount -t proc proc "$BUILDROOT/proc" 2>/dev/null
    chroot "$BUILDROOT" /bin/sh -c "apk update && apk add --no-cache python3 openssl openssh bash busybox" 2>>"$LOG_FILE"
    RET=$?
    umount "$BUILDROOT/proc" 2>/dev/null
    [ $RET -ne 0 ] && die "Failed to install packages in chroot"
    log OK "Packages installed"

    # Setup busybox symlinks
    if [ -f "$BUILDROOT/usr/bin/busybox" ]; then
        for cmd in sh bash ls cat cp rm mkdir mount umount chmod chown sed awk grep find tar gzip ps kill su id; do
            [ ! -f "$BUILDROOT/bin/$cmd" ] && ln -sf /usr/bin/busybox "$BUILDROOT/bin/$cmd" 2>/dev/null
        done
    fi

    # Ensure /bin/sh exists
    [ ! -f "$BUILDROOT/bin/sh" ] && ln -sf /bin/busybox "$BUILDROOT/bin/sh" 2>/dev/null
    [ ! -f "$BUILDROOT/bin/sh" ] && die "/bin/sh not found after chroot setup"

    # Package as ankcore tarball
    log INFO "Packaging ankcore tarball..."
    cd "$BUILDROOT" && tar czf "$ANK_DIR/cache/ankcore-${ARCH_NAME}.tar.gz" . 2>>"$LOG_FILE"; cd /
    ANKCORE="$ANK_DIR/cache/ankcore-${ARCH_NAME}.tar.gz"
    [ ! -s "$ANKCORE" ] && die "Failed to package ankcore tarball"
    log OK "ankcore built from scratch ($(stat -c%s "$ANKCORE" 2>/dev/null || echo 0) bytes)"

    # Use buildroot directly as ankfs (already extracted)
    rm -rf "$ANKFS"
    mv "$BUILDROOT" "$ANKFS"
else
    log INFO "ankcore: $(stat -c%s "$ANKCORE" 2>/dev/null || echo 0) bytes"

    # Extract pre-built rootfs
    rm -rf "$ANKFS"
    mkdir -p "$ANKFS"
    cd "$ANKFS" && tar xzf "$ANKCORE" 2>>"$LOG_FILE"; cd /
    log OK "ankcore extracted"
fi

# Verify python3 exists
[ ! -f "$ANKFS/usr/bin/python3" ] && die "python3 not found in ankcore"
log OK "python3 installed"

# Create common system users needed by services (nginx, sshd, etc.)
for u in nginx nobody; do
    grep -q "^${u}:" "$ANKFS/etc/passwd" 2>/dev/null || \
        echo "${u}:x:100:65534::/dev/null:/sbin/nologin" >> "$ANKFS/etc/passwd"
done
for g in nginx; do
    grep -q "^${g}:" "$ANKFS/etc/group" 2>/dev/null || \
        echo "${g}:x:100:" >> "$ANKFS/etc/group"
done
log OK "system users created"

# Ensure DNS is available for chroot apk operations (BEFORE any chroot)
mkdir -p "$ANKFS/etc"
echo "nameserver 8.8.8.8" > "$ANKFS/etc/resolv.conf"
echo "nameserver 8.8.4.4" >> "$ANKFS/etc/resolv.conf"
echo "127.0.0.1 localhost" > "$ANKFS/etc/hosts"

# Install openssh in rootfs for container SSH access
log STEP "Installing openssh..."
if [ -f "$ANKFS/usr/bin/apk" ]; then
    chroot "$ANKFS" /usr/bin/apk add --no-cache openssh openssl 2>>"$LOG_FILE" || log WARN "openssh/openssl install failed (non-fatal)"
    # Configure sshd
    if [ -d "$ANKFS/etc/ssh" ]; then
        # PermitRootLogin yes, PasswordAuthentication yes
        sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        # Disable password login for ssh key only (we want password)
        sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        # Generate host keys if missing
        [ ! -f "$ANKFS/etc/ssh/ssh_host_rsa_key" ] && \
            chroot "$ANKFS" /usr/bin/ssh-keygen -A 2>>"$LOG_FILE" || true
        # Allow root login via ssh
        echo "PermitRootLogin yes" >> "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        echo "PasswordAuthentication yes" >> "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        echo "UsePAM no" >> "$ANKFS/etc/ssh/sshd_config" 2>/dev/null
        # Ensure sshd can run (create empty authorized_keys for root)
        mkdir -p "$ANKFS/root/.ssh" 2>/dev/null
        chmod 700 "$ANKFS/root/.ssh" 2>/dev/null
        touch "$ANKFS/root/.ssh/authorized_keys" 2>/dev/null
        chmod 600 "$ANKFS/root/.ssh/authorized_keys" 2>/dev/null
        # Create /run/sshd for pid file
        mkdir -p "$ANKFS/run/sshd" 2>/dev/null
        log OK "openssh configured"
    fi
fi

# Copy clean rootfs as container image
log INFO "Copying rootfs as container image..."
mkdir -p "$ANK_DIR/images/alpine-3.20"
cd "$ANKFS" && tar xzf "$ANKCORE" -C "$ANK_DIR/images/alpine-3.20" 2>>"$LOG_FILE"; cd /
# Create system users in container image too
for u in nginx nobody; do
    grep -q "^${u}:" "$ANK_DIR/images/alpine-3.20/etc/passwd" 2>/dev/null || \
        echo "${u}:x:100:65534::/dev/null:/sbin/nologin" >> "$ANK_DIR/images/alpine-3.20/etc/passwd"
done
for g in nginx; do
    grep -q "^${g}:" "$ANK_DIR/images/alpine-3.20/etc/group" 2>/dev/null || \
        echo "${g}:x:100:" >> "$ANK_DIR/images/alpine-3.20/etc/group"
done
# Copy openssh config + host keys to image
if [ -f "$ANKFS/usr/sbin/sshd" ]; then
    cp "$ANKFS/usr/sbin/sshd" "$ANK_DIR/images/alpine-3.20/usr/sbin/sshd" 2>/dev/null
    cp "$ANKFS/usr/bin/ssh" "$ANK_DIR/images/alpine-3.20/usr/bin/ssh" 2>/dev/null
    cp "$ANKFS/usr/bin/ssh-keygen" "$ANK_DIR/images/alpine-3.20/usr/bin/ssh-keygen" 2>/dev/null
    mkdir -p "$ANK_DIR/images/alpine-3.20/etc/ssh" 2>/dev/null
    cp "$ANKFS/etc/ssh/"* "$ANK_DIR/images/alpine-3.20/etc/ssh/" 2>/dev/null
    mkdir -p "$ANK_DIR/images/alpine-3.20/root/.ssh" 2>/dev/null
    chmod 700 "$ANK_DIR/images/alpine-3.20/root/.ssh" 2>/dev/null
    touch "$ANK_DIR/images/alpine-3.20/root/.ssh/authorized_keys" 2>/dev/null
    chmod 600 "$ANK_DIR/images/alpine-3.20/root/.ssh/authorized_keys" 2>/dev/null
    mkdir -p "$ANK_DIR/images/alpine-3.20/run/sshd" 2>/dev/null
    # Copy necessary libs
    for lib in "$ANKFS/usr/lib/"libcrypto*.so* "$ANKFS/usr/lib/"libssl*.so* "$ANKFS/lib/"libz*.so* "$ANKFS/lib/"libc*.so* "$ANKFS/lib/"libutil*.so* "$ANKFS/lib/"libpthread*.so*; do
        [ -e "$lib" ] && cp "$lib" "$ANK_DIR/images/alpine-3.20/usr/lib/" 2>/dev/null
    done
    log OK "openssh copied to image"
fi
log OK "alpine-3.20 image ready"

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

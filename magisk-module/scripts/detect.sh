#!/system/bin/sh
# Ank - Device capability detection
# Usage: detect.sh [check|info|setup]

ANK_DIR="${ANK_DIR:-/data/local/ank}"
ANK_SDCARD="/sdcard/AndroidKonteiner"
MODE_FILE="$ANK_DIR/mode"

check_netns() {
    ip netns add _ank_test 2>/dev/null
    if [ $? -eq 0 ]; then
        ip netns del _ank_test 2>/dev/null
        return 0
    fi
    return 1
}

check_pidns() {
    [ -f /proc/self/ns/pid ] || return 1
    unshare --pid --fork /bin/true 2>/dev/null
    return $?
}

check_overlayfs() {
    cat /proc/filesystems 2>/dev/null | grep -q overlay
    return $?
}

check_cgroups() {
    [ -d /sys/fs/cgroup/ank ] && return 0
    mkdir -p /sys/fs/cgroup/ank/_test 2>/dev/null
    if [ $? -eq 0 ]; then
        rmdir /sys/fs/cgroup/ank/_test 2>/dev/null
        return 0
    fi
    return 1
}

check_chroot() {
    which chroot >/dev/null 2>&1 || return 1
    # Try existing Alpine chroot first
    if [ -d /data/local/chroot-distro/alpine/bin ]; then
        chroot /data/local/chroot-distro/alpine /bin/true 2>/dev/null
        return $?
    fi
    # Try our own ankfs
    if [ -d "$ANK_DIR/ankfs/bin" ]; then
        chroot "$ANK_DIR/ankfs" /bin/true 2>/dev/null
        return $?
    fi
    # Fallback: just check chroot binary exists
    return 0
}

# ============================================================
# Detect all capabilities
# ============================================================
detect_all() {
    NETNS=0; PIDNS=0; OVERLAY=0; CGROUP=0; CHROOT=0

    check_netns    && NETNS=1
    check_pidns    && PIDNS=1
    check_overlayfs && OVERLAY=1
    check_cgroups  && CGROUP=1
    check_chroot   && CHROOT=1

    # Determine mode
    if [ "$NETNS" -eq 1 ] && [ "$PIDNS" -eq 1 ] && [ "$CHROOT" -eq 1 ]; then
        MODE="isolated"
    elif [ "$PIDNS" -eq 1 ] && [ "$CHROOT" -eq 1 ]; then
        MODE="shared_network"
    elif [ "$CHROOT" -eq 1 ]; then
        MODE="shared_host"
    else
        MODE="native_host"
    fi
}

# ============================================================
# Print info
# ============================================================
print_info() {
    detect_all
    echo "=== Ank Device Detection ==="
    echo "Mode:      $MODE"
    echo "Chroot:    $([ $CHROOT -eq 1 ] && echo YES || echo NO)"
    echo "NET_NS:    $([ $NETNS -eq 1 ] && echo YES || echo NO)"
    echo "PID_NS:    $([ $PIDNS -eq 1 ] && echo YES || echo NO)"
    echo "OverlayFS: $([ $OVERLAY -eq 1 ] && echo YES || echo NO)"
    echo "Cgroups:   $([ $CGROUP -eq 1 ] && echo YES || echo NO)"
    echo ""
    case "$MODE" in
        full)  echo "Full mode: all features available" ;;
        compat) echo "Compat mode: chroot + iptables only" ;;
        none)  echo "No supported features found" ;;
    esac
}

# ============================================================
# Save mode to file
# ============================================================
save_mode() {
    detect_all
    mkdir -p "$ANK_DIR"
    cat > "$MODE_FILE" << EOF
{
  "mode": "$MODE",
  "chroot": $CHROOT,
  "netns": $NETNS,
  "pidns": $PIDNS,
  "overlay": $OVERLAY,
  "cgroups": $CGROUP
}
EOF
    echo "$MODE"
}

# ============================================================
# Main
# ============================================================
case "${1:-check}" in
    check) save_mode ;;
    info)  print_info ;;
    setup)
        save_mode
        print_info
        ;;
    *) echo "Usage: $0 {check|info|setup}" ;;
esac

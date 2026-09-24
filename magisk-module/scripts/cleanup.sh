#!/system/bin/sh
# Ank - Cleanup orphaned resources
# Usage: cleanup.sh [container_name]

ANK_DIR="${ANK_DIR:-/data/local/ank}"
ANK_SDCARD="/sdcard/AndroidKonteiner"

# ============================================================
# Cleanup specific container
# ============================================================
cleanup_container() {
    local NAME="$1"
    local NS="netns_${NAME}"
    local VETH="veth_ank_${NAME}"

    echo "Cleaning up: $NAME"

    # Remove netns
    ip netns del "$NS" 2>/dev/null && echo "  Removed netns: $NS"

    # Remove veth
    ip link del "$VETH" 2>/dev/null && echo "  Removed veth: $VETH"

    # Unmount overlayfs
    umount "$ANK_DIR/containers/$NAME/merged" 2>/dev/null && echo "  Unmounted overlayfs"

    # Remove cgroup
    rmdir "/sys/fs/cgroup/ank/$NAME" 2>/dev/null && echo "  Removed cgroup"

    # Remove container directory if empty/invalid
    if [ -d "$ANK_DIR/containers/$NAME" ]; then
        if [ ! -f "$ANK_DIR/containers/$NAME/config.json" ]; then
            rm -rf "$ANK_DIR/containers/$NAME"
            echo "  Removed invalid container directory"
        fi
    fi
}

# ============================================================
# Cleanup all orphans
# ============================================================
cleanup_all() {
    echo "=== Cleaning up orphaned resources ==="

    # Find orphaned netns
    for ns in $(ip netns list 2>/dev/null | cut -d' ' -f1); do
        case "$ns" in
            netns_*)
                local name=${ns#netns_}
                if [ ! -d "$ANK_DIR/containers/$name" ]; then
                    ip netns del "$ns" 2>/dev/null && echo "Removed orphaned netns: $ns"
                fi
                ;;
        esac
    done

    # Find orphaned veths
    for veth in $(ip link show type veth 2>/dev/null | grep -o 'veth_ank_[a-zA-Z0-9_-]*'); do
        local name=${veth#veth_ank_}
        if [ ! -d "$ANK_DIR/containers/$name" ]; then
            ip link del "$veth" 2>/dev/null && echo "Removed orphaned veth: $veth"
        fi
    done

    # Find orphaned cgroups
    if [ -d "/sys/fs/cgroup/ank" ]; then
        for cg in /sys/fs/cgroup/ank/*/; do
            [ -d "$cg" ] || continue
            local name=$(basename "$cg")
            if [ ! -d "$ANK_DIR/containers/$name" ]; then
                rmdir "$cg" 2>/dev/null && echo "Removed orphaned cgroup: $name"
            fi
        done
    fi

    # Find orphaned iptables rules
    iptables -L FORWARD -n 2>/dev/null | grep "10.0.0." | while read line; do
        # This is a simplified check - in production you'd want more robust parsing
        :
    done

    echo "=== Cleanup complete ==="
}

# ============================================================
# Main
# ============================================================
if [ -n "$1" ]; then
    cleanup_container "$1"
else
    cleanup_all
fi

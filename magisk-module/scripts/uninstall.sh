#!/system/bin/sh
# ANK - Android Konteiner
# Complete Uninstall Script
# Removes all containers, images, configs, network rules, and ANK directory

ANK_DIR="/data/local/ank"
ANK_SDCARD="/sdcard/AndroidKonteiner"
IMAGES_DIR="$ANK_DIR/images"
CONTAINERS_DIR="$ANK_DIR/containers"
SCRIPTS_DIR="$ANK_DIR/core"
LOGS_DIR="$ANK_DIR/logs"

echo "========================================="
echo "  ANK - Android Konteiner"
echo "  Complete Uninstaller v0.1"
echo "========================================="
echo ""

# Check root
if [ "$(id -u)" != "0" ]; then
    echo "ERROR: This script must run as root (su)"
    exit 1
fi

echo "[1/7] Stopping ANK server..."
kill $(pgrep -f "ld-musl-armhf") 2>/dev/null
sleep 1
echo "  OK"

echo "[2/7] Stopping all containers..."
if [ -d "$CONTAINERS_DIR" ]; then
    for dir in "$CONTAINERS_DIR"/*/; do
        name=$(basename "$dir")
        config="$dir/config.json"
        if [ -f "$config" ]; then
            pid=$(grep -o '"pid": [^,]*' "$config" | cut -d' ' -f2)
            if [ -n "$pid" ] && [ "$pid" != "null" ]; then
                kill "$pid" 2>/dev/null
                echo "  Stopped container: $name (PID $pid)"
            fi
            # Unmount chroot mounts
            merged="$dir/merged"
            umount "$merged/proc" 2>/dev/null
            umount "$merged/sys" 2>/dev/null
            umount "$merged/dev" 2>/dev/null
            umount "$merged" 2>/dev/null
        fi
    done
else
    echo "  No containers found"
fi
echo "  OK"

echo "[3/7] Removing iptables rules..."
# Remove ANK iptables rules
iptables -t nat -S 2>/dev/null | grep "ank" | sed 's/-A/-D/g' | while read rule; do
    iptables -t nat $rule 2>/dev/null
done
iptables -S 2>/dev/null | grep "ank" | sed 's/-A/-D/g' | while read rule; do
    iptables $rule 2>/dev/null
done
# Remove ank0 bridge
ip link set ank0 down 2>/dev/null
ip link delete ank0 2>/dev/null
# Remove network namespaces
ip netns list 2>/dev/null | grep "netns_" | cut -d' ' -f1 | while read ns; do
    ip netns delete "$ns" 2>/dev/null
done
echo "  OK"

echo "[4/7] Removing cgroups..."
if [ -d "/sys/fs/cgroup/ank" ]; then
    rm -rf "/sys/fs/cgroup/ank"
    echo "  Removed /sys/fs/cgroup/ank"
else
    echo "  No cgroups to remove"
fi
echo "  OK"

echo "[5/7] Removing all containers..."
if [ -d "$CONTAINERS_DIR" ]; then
    rm -rf "$CONTAINERS_DIR"
    echo "  Removed $CONTAINERS_DIR"
else
    echo "  No containers to remove"
fi
echo "  OK"

echo "[6/7] Removing images..."
if [ -d "$IMAGES_DIR" ]; then
    rm -rf "$IMAGES_DIR"
    echo "  Removed $IMAGES_DIR"
else
    echo "  No images to remove"
fi
echo "  OK"

echo "[7/7] Removing ANK directory..."
# Keep logs last, then remove everything
if [ -d "$ANK_DIR" ]; then
    rm -rf "$ANK_DIR"
    echo "  Removed $ANK_DIR"
else
    echo "  No ANK directory found"
fi
echo "  OK"

echo ""
echo "========================================="
echo "  ANK has been completely uninstalled."
echo "  Reboot recommended."
echo "========================================="
echo ""

exit 0

#!/system/bin/sh
# ANK - Android Konteiner
# Complete Uninstall Script
# Removes all containers, images, configs, network rules, Magisk module, and ANK directory

ANK_DIR="/data/local/ank"
ANK_SDCARD="/sdcard/AndroidKonteiner"
IMAGES_DIR="$ANK_DIR/images"
CONTAINERS_DIR="$ANK_DIR/containers"

echo "========================================="
echo "  ANK - Android Konteiner"
echo "  Complete Uninstaller v0.2"
echo "========================================="
echo ""

if [ "$(id -u)" != "0" ]; then
    echo "ERROR: Must run as root (su)"
    exit 1
fi

echo "[1/8] Stopping ANK server..."
pkill -9 -f "ld-musl.*python3.*server.py" 2>/dev/null
pkill -9 -f "ld-musl.*server.py" 2>/dev/null
sleep 1
echo "  OK"

echo "[2/8] Stopping all containers + killing all chroot processes..."
if [ -d "$CONTAINERS_DIR" ]; then
    for dir in "$CONTAINERS_DIR"/*/; do
        name=$(basename "$dir")
        merged="$dir/merged"
        echo "  Cleaning container: $name"

        # Kill ALL processes whose exe/cwd is inside this rootfs
        for pid_dir in /proc/[0-9]*; do
            pid=$(basename "$pid_dir")
            exe=$(readlink "$pid_dir/exe" 2>/dev/null)
            cwd=$(readlink "$pid_dir/cwd" 2>/dev/null)
            case "$exe" in ${merged}/*) kill -9 "$pid" 2>/dev/null ;; esac
            case "$cwd" in ${merged}/*) kill -9 "$pid" 2>/dev/null ;; esac
        done

        # Kill main PID tree
        config="$dir/config.json"
        if [ -f "$config" ]; then
            pid=$(grep -o '"pid": [^,]*' "$config" | cut -d' ' -f2)
            [ -n "$pid" ] && [ "$pid" != "null" ] && kill -9 "$pid" 2>/dev/null
        fi

        # Unmount ALL
        for m in dev/pts dev/shm dev proc sys run tmp; do
            umount "$merged/$m" 2>/dev/null
            umount -l "$merged/$m" 2>/dev/null
        done
        umount "$merged" 2>/dev/null
        umount -l "$merged" 2>/dev/null
    done
else
    echo "  No containers found"
fi

# Kill any remaining stray sshd/nginx
pkill -9 -f "sshd.*PidFile" 2>/dev/null
pkill -9 -f "nginx.*ank" 2>/dev/null
echo "  OK"

echo "[3/8] Removing iptables rules..."
iptables -t nat -S 2>/dev/null | grep -i "ank" | sed 's/-A/-D/g' | while read rule; do
    iptables -t nat $rule 2>/dev/null
done
iptables -S 2>/dev/null | grep -i "ank" | sed 's/-A/-D/g' | while read rule; do
    iptables $rule 2>/dev/null
done
echo "  OK"

echo "[4/8] Removing network interfaces..."
ip link set ank0 down 2>/dev/null
ip link delete ank0 2>/dev/null
# Remove network namespaces
ip netns list 2>/dev/null | grep -i "netns_\|ank" | cut -d' ' -f1 | while read ns; do
    ip netns delete "$ns" 2>/dev/null
done
echo "  OK"

echo "[5/8] Removing cgroups..."
rm -rf "/sys/fs/cgroup/ank" 2>/dev/null
echo "  OK"

echo "[6/8] Removing containers + images..."
rm -rf "$CONTAINERS_DIR" 2>/dev/null
rm -rf "$IMAGES_DIR" 2>/dev/null
echo "  OK"

echo "[7/8] Removing ANK directory + sdcard data..."
rm -rf "$ANK_DIR" 2>/dev/null
rm -rf "$ANK_SDCARD" 2>/dev/null
echo "  OK"

echo "[8/8] Removing Magisk module..."
magisk --remove-module ank 2>/dev/null
echo "  OK"

echo ""
echo "========================================="
echo "  ANK completely uninstalled."
echo "  Reboot recommended."
echo "========================================="
echo ""

exit 0

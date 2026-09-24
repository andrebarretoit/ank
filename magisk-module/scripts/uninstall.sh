#!/system/bin/sh
# ANK - Android Konteiner
# Complete Uninstall Script v3.0
# Handles: chroot (rooted) + PRoot (unrooted) modes
# Unmounts everything, kills all processes, removes ALL ANK data

ANK_DIR="${ANK_DIR:-/data/local/ank}"
ANK_SDCARD="/sdcard/AndroidKonteiner"
CONTAINERS_DIR="$ANK_DIR/containers"

echo "========================================="
echo "  ANK - Android Konteiner"
echo "  Complete Uninstaller v3.0"
echo "========================================="
echo ""

# ── Step 1: Kill server ──────────────────────────────────────────────────────
echo "[1/10] Stopping ANK server..."
pkill -9 -f "ld-musl.*python3.*server.py" 2>/dev/null
pkill -9 -f "python3.*server.py" 2>/dev/null
pkill -9 -f "python3.*ankd" 2>/dev/null
sleep 1
echo "  OK"

# ── Step 2: Stop all containers + kill chroot/PRoot processes ───────────────
echo "[2/10] Stopping all containers..."
if [ -d "$CONTAINERS_DIR" ]; then
    for dir in "$CONTAINERS_DIR"/*/; do
        [ -d "$dir" ] || continue
        name=$(basename "$dir")
        merged="$dir/merged"
        echo "  Cleaning container: $name"

        # Kill ALL processes whose exe/cwd is inside this rootfs
        for pid_dir in /proc/[0-9]*; do
            pid=$(basename "$pid_dir") 2>/dev/null
            [ -z "$pid" ] && continue
            exe=$(readlink "$pid_dir/exe" 2>/dev/null)
            cwd=$(readlink "$pid_dir/cwd" 2>/dev/null)
            case "$exe" in ${merged}/*) kill -9 "$pid" 2>/dev/null ;; esac
            case "$cwd" in ${merged}/*) kill -9 "$pid" 2>/dev/null ;; esac
        done

        # Kill main PID from config
        config="$dir/config.json"
        if [ -f "$config" ]; then
            pid=$(grep -o '"pid": *[^,}]*' "$config" | head -1 | sed 's/"pid": *//')
            [ -n "$pid" ] && [ "$pid" != "null" ] && kill -9 "$pid" 2>/dev/null
        fi

        # Unmount ALL container mounts (order matters: inner first)
        for m in dev/pts dev/shm dev proc sys run tmp root home; do
            umount "$merged/$m" 2>/dev/null
            umount -l "$merged/$m" 2>/dev/null
        done
        umount "$merged" 2>/dev/null
        umount -l "$merged" 2>/dev/null
    done
else
    echo "  No containers found"
fi

# Kill any remaining stray sshd/nginx inside ANK
pkill -9 -f "sshd.*PidFile" 2>/dev/null
pkill -9 -f "nginx.*ank" 2>/dev/null
echo "  OK"

# ── Step 3: Kill PRoot processes (for lite/unrooted mode) ───────────────────
echo "[3/10] Killing PRoot processes..."
pkill -9 -f "proot.*ankfs" 2>/dev/null
pkill -9 -f "proot.*rootfs" 2>/dev/null
# Kill all PRoot fake PID 1 (the init process)
for pid_dir in /proc/[0-9]*; do
    pid=$(basename "$pid_dir") 2>/dev/null
    [ -z "$pid" ] && continue
    exe=$(readlink "$pid_dir/exe" 2>/dev/null)
    case "$exe" in
        *proot*|*/ankfs/*) kill -9 "$pid" 2>/dev/null ;;
    esac
done
sleep 1
echo "  OK"

# ── Step 4: Unmount ANKFS bind mounts (chroot mode) ────────────────────────
echo "[4/10] Unmounting ANKFS bind mounts..."
for sub in dev dev/pts dev/shm proc sys tmp run; do
    mnt="$ANK_DIR/ankfs/$sub"
    umount "$mnt" 2>/dev/null
    umount -l "$mnt" 2>/dev/null
done

# Unmount any overlay mounts that reference ANK
for pid_dir in /proc/[0-9]*; do
    pid=$(basename "$pid_dir") 2>/dev/null
    [ -z "$pid" ] && continue
    mount_info=$(cat "$pid_dir/mountinfo" 2>/dev/null)
    case "$mount_info" in
        */ankfs/*|*/ank/*)
            # Get the mountpoint (6th field)
            echo "$mount_info" | while read _ _ mp _ _ _ _ _ _ _ _; do
                umount "$mp" 2>/dev/null
                umount -l "$mp" 2>/dev/null
            done
            ;;
    esac
done

# Also try to unmount the root itself
umount "$ANK_DIR/ankfs" 2>/dev/null
umount -l "$ANK_DIR/ankfs" 2>/dev/null
echo "  OK"

# ── Step 5: Clean iptables ─────────────────────────────────────────────────
echo "[5/10] Removing iptables rules..."
iptables -t nat -S 2>/dev/null | grep -i "ank" | sed 's/-A/-D/g' | while read rule; do
    iptables -t nat $rule 2>/dev/null
done
iptables -S 2>/dev/null | grep -i "ank" | sed 's/-A/-D/g' | while read rule; do
    iptables $rule 2>/dev/null
done
# Also clean ip6tables
ip6tables -t nat -S 2>/dev/null | grep -i "ank" | sed 's/-A/-D/g' | while read rule; do
    ip6tables -t nat $rule 2>/dev/null
done
ip6tables -S 2>/dev/null | grep -i "ank" | sed 's/-A/-D/g' | while read rule; do
    ip6tables $rule 2>/dev/null
done
echo "  OK"

# ── Step 6: Remove network interfaces + namespaces ──────────────────────────
echo "[6/10] Removing network interfaces..."
ip link set ank0 down 2>/dev/null
ip link delete ank0 2>/dev/null
ip netns list 2>/dev/null | grep -i "netns_\|ank" | cut -d' ' -f1 | while read ns; do
    ip netns delete "$ns" 2>/dev/null
done
echo "  OK"

# ── Step 7: Remove cgroups ──────────────────────────────────────────────────
echo "[7/10] Removing cgroups..."
rm -rf "/sys/fs/cgroup/ank" 2>/dev/null
echo "  OK"

# ── Step 8: Remove proot binary ─────────────────────────────────────────────
echo "[8/10] Removing proot binary..."
rm -f "$ANK_DIR/proot" 2>/dev/null
rm -f "$ANK_DIR/proot-arm" 2>/dev/null
rm -f "$ANK_DIR/proot-arm64" 2>/dev/null
rm -f "$ANK_DIR/proot-x86" 2>/dev/null
rm -f "$ANK_DIR/proot-x86_64" 2>/dev/null
echo "  OK"

# ── Step 9: Remove ALL ANK data ─────────────────────────────────────────────
echo "[9/10] Removing all ANK data..."
rm -rf "$CONTAINERS_DIR" 2>/dev/null
rm -rf "$ANK_DIR/images" 2>/dev/null
rm -rf "$ANK_DIR/ankfs" 2>/dev/null
rm -rf "$ANK_DIR" 2>/dev/null
rm -rf "$ANK_SDCARD" 2>/dev/null
# Also remove Magisk module persistent data (rooted installs only)
if [ -d "/data/adb/modules/ank" ]; then
    rm -rf "/data/adb/modules/ank" 2>/dev/null
fi
echo "  OK"

# ── Step 10: Remove Magisk module ───────────────────────────────────────────
echo "[10/10] Removing Magisk module..."
if command -v magisk >/dev/null 2>&1; then
    magisk --remove-module ank 2>/dev/null
else
    echo "  Magisk not present, skipping"
fi
echo "  OK"

echo ""
echo "========================================="
echo "  ANK completely uninstalled."
echo "  Device will reboot to complete cleanup."
echo "========================================="
echo ""

# Reboot to ensure clean state
reboot

#!/system/bin/sh
# ============================================================
# ANK - Android Konteiner
# post-fs-data.sh - network setup (runs early in boot)
# ============================================================

ANK_DIR="/data/local/ank"
ANK_SDCARD="/sdcard/AndroidKonteiner"
MODE_FILE="$ANK_DIR/mode"

# Only setup if ANK is installed
[ ! -d "$ANK_DIR" ] && exit 0

# Setup bridge (if kernel supports it)
ip link add name ank0 type bridge 2>/dev/null
ip addr add 10.20.30.1/24 dev ank0 2>/dev/null
ip link set dev ank0 up 2>/dev/null

# IP forwarding
echo 1 > /proc/sys/net/ipv4/ip_forward 2>/dev/null

# Detect WAN interface
WAN_IF="wlan0"
for iface in rmnet0 rmnet_data0 ppp0; do
    ip link show "$iface" 2>/dev/null | grep -q "UP" && WAN_IF="$iface" && break
done

# NAT
iptables -t nat -A POSTROUTING -s 10.20.30.0/24 -o "$WAN_IF" -j MASQUERADE 2>/dev/null
iptables -A FORWARD -i ank0 -o "$WAN_IF" -j ACCEPT 2>/dev/null
iptables -A FORWARD -i "$WAN_IF" -o ank0 -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null

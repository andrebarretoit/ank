#!/system/bin/sh
# Ank - Network management (full + compat mode)
# Usage: network.sh <command> <container_name> [args...]

ANK_DIR="/data/local/ank"
ANK_SDCARD="/sdcard/AndroidKonteiner"
CONFIG_FILE="$ANK_DIR/config.json"
BRIDGE="ank0"

# ============================================================
# Read config.json values
# ============================================================
read_config() {
    local key="$1"
    local default="$2"
    if [ -f "$CONFIG_FILE" ]; then
        local val=$(grep -o "\"$key\": *\"[^\"]*\"" "$CONFIG_FILE" 2>/dev/null | head -1 | cut -d'"' -f4)
        [ -n "$val" ] && echo "$val" && return 0
    fi
    echo "$default"
}

get_subnet_base() {
    local subnet=$(read_config "subnet" "10.20.30.0")
    echo "${subnet%.0}"
}

get_gateway() {
    local gw=$(read_config "gateway" "")
    if [ -n "$gw" ]; then
        echo "$gw"
    else
        echo "$(get_subnet_base).1"
    fi
}

get_bridge_ip() {
    echo "$(get_gateway)"
}

# ============================================================
# Get next available IP
# ============================================================
get_next_ip() {
    local base=$(get_subnet_base)
    local used_ips=""
    for config in "$ANK_DIR"/containers/*/config.json; do
        [ -f "$config" ] || continue
        local ip=$(grep -o '"ip_address": *"[^"]*"' "$config" | cut -d'"' -f4)
        [ -n "$ip" ] && used_ips="$used_ips $ip"
    done
    for i in $(seq 2 254); do
        local candidate="${base}.$i"
        echo "$used_ips" | grep -q "$candidate" || { echo "$candidate"; return 0; }
    done
    echo ""
    return 1
}

# ============================================================
# FULL MODE: netns + veth + bridge
# ============================================================

setup_bridge() {
    local gw=$(get_gateway)
    local subnet=$(read_config "subnet" "10.20.30.0")

    if ! ip link show ank0 >/dev/null 2>&1; then
        ip link add name ank0 type bridge
        ip addr add "${gw}/24" dev ank0
        ip link set dev ank0 up
    fi
}

cmd_create() {
    local NAME="$1"
    local IP="$2"
    local NS="netns_${NAME}"
    local VETH_ANK="veth_ank_${NAME}"
    local VETH_CTR="veth_ctr_${NAME}"
    local gw=$(get_gateway)

    setup_bridge

    if [ -z "$IP" ]; then
        IP=$(get_next_ip)
        [ -z "$IP" ] && { echo "ERROR: No available IPs"; exit 1; }
    fi

    ip netns add "$NS" || { echo "ERROR: Failed to create netns"; exit 1; }

    ip link add "$VETH_ANK" type veth peer name "$VETH_CTR" || {
        ip netns del "$NS" 2>/dev/null
        echo "ERROR: Failed to create veth"; exit 1;
    }

    ip link set "$VETH_ANK" master "$BRIDGE" || {
        ip link del "$VETH_ANK" 2>/dev/null
        ip netns del "$NS" 2>/dev/null
        echo "ERROR: Failed to attach to bridge"; exit 1;
    }

    ip link set "$VETH_ANK" up
    ip link set "$VETH_CTR" netns "$NS" || {
        ip link del "$VETH_ANK" 2>/dev/null
        ip netns del "$NS" 2>/dev/null
        echo "ERROR: Failed to move veth"; exit 1;
    }

    ip netns exec "$NS" ip link set dev "$VETH_CTR" name eth0
    ip netns exec "$NS" ip link set eth0 up
    ip netns exec "$NS" ip addr add "${IP}/24" dev eth0
    ip netns exec "$NS" ip route add default via "$gw"
    ip netns exec "$NS" ip link set lo up

    echo "$IP"
}

cmd_destroy() {
    local NAME="$1"
    ip netns del "netns_${NAME}" 2>/dev/null
    ip link del "veth_ank_${NAME}" 2>/dev/null
}

# ============================================================
# COMPAT MODE: no netns, iptables NAT only
# ============================================================

setup_bridge_compat() {
    echo 1 > /proc/sys/net/ipv4/ip_forward 2>/dev/null

    local gw=$(get_gateway)
    local subnet=$(read_config "subnet" "10.20.30.0")
    local nat=$(read_config "nat" "true")

    # Create ank0 interface with gateway IP
    if ! ip link show ank0 >/dev/null 2>&1; then
        ip link add name ank0 type bridge 2>/dev/null || \
        ip link add name ank0 type dummy 2>/dev/null || \
        ip tuntap add mode tap name ank0 2>/dev/null || true
        ip addr add "${gw}/24" dev ank0 2>/dev/null || true
        ip link set dev ank0 up 2>/dev/null || true
    fi

    # Find WAN interface
    local wan=""
    for iface in wlan0 rmnet_data0 ppp0; do
        if ip link show "$iface" 2>/dev/null | grep -q "UP"; then
            wan="$iface"
            break
        fi
    done
    [ -z "$wan" ] && wan="wlan0"

    # Setup NAT if enabled
    if [ "$nat" = "true" ] && [ -n "$wan" ]; then
        # Only add if not already present
        iptables -t nat -C POSTROUTING -s "${subnet}/24" -o "$wan" -j MASQUERADE 2>/dev/null || \
            iptables -t nat -A POSTROUTING -s "${subnet}/24" -o "$wan" -j MASQUERADE 2>/dev/null
        iptables -C FORWARD -i ank0 -o "$wan" -j ACCEPT 2>/dev/null || \
            iptables -A FORWARD -i ank0 -o "$wan" -j ACCEPT 2>/dev/null
        iptables -C FORWARD -i "$wan" -o ank0 -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || \
            iptables -A FORWARD -i "$wan" -o ank0 -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null
    fi
}

cmd_create_compat() {
    local NAME="$1"
    local IP="$2"

    setup_bridge_compat

    if [ -z "$IP" ]; then
        IP=$(get_next_ip)
        [ -z "$IP" ] && { echo "ERROR: No available IPs"; exit 1; }
    fi

    # In compat mode, containers share host network
    # IP is tracked in config for reference/policies
    echo "$IP"
}

cmd_destroy_compat() {
    local NAME="$1"
    local CONFIG="$ANK_DIR/containers/$NAME/config.json"
    if [ -f "$CONFIG" ]; then
        local IP=$(grep -o '"ip_address": *"[^"]*"' "$CONFIG" | cut -d'"' -f4)
        [ -n "$IP" ] && ip addr del "${IP}/24" dev ank0 2>/dev/null
    fi
}

# ============================================================
# Apply iptables policies (FULL MODE)
# ============================================================

cmd_apply_policies() {
    local NAME="$1"
    local CONFIG="$ANK_DIR/containers/$NAME/config.json"
    [ -f "$CONFIG" ] || return 1

    local IP=$(grep -o '"ip_address": *"[^"]*"' "$CONFIG" | cut -d'"' -f4)
    local P2P=$(grep -o '"inter_container_p2p": *[a-z]*' "$CONFIG" | cut -d' ' -f2)
    local HOST=$(grep -o '"allow_host_access": *[a-z]*' "$CONFIG" | cut -d' ' -f2)
    local gw=$(get_gateway)

    P2P=${P2P:-false}
    HOST=${HOST:-false}

    if [ "$P2P" = "false" ]; then
        for other in "$ANK_DIR"/containers/*/config.json; do
            [ -f "$other" ] || continue
            local other_name=$(basename "$(dirname "$other")")
            [ "$other_name" = "$NAME" ] && continue
            local other_ip=$(grep -o '"ip_address": *"[^"]*"' "$other" | cut -d'"' -f4)
            [ -z "$other_ip" ] && continue
            iptables -A FORWARD -s "$IP" -d "$other_ip" -j DROP 2>/dev/null
            iptables -A FORWARD -s "$other_ip" -d "$IP" -j DROP 2>/dev/null
        done
    fi

    if [ "$HOST" = "false" ]; then
        iptables -A INPUT -i "$BRIDGE" -s "$IP" -d "$gw" -j DROP 2>/dev/null
        iptables -A FORWARD -s "$IP" -d "$gw" -j DROP 2>/dev/null
    fi
}

cmd_apply_ports() {
    local NAME="$1"
    local CONFIG="$ANK_DIR/containers/$NAME/config.json"
    [ -f "$CONFIG" ] || return 1

    local IP=$(grep -o '"ip_address": *"[^"]*"' "$CONFIG" | cut -d'"' -f4)
    local ports=$(grep -o '"host_port": *[0-9]*' "$CONFIG" | cut -d' ' -f2)
    local cports=$(grep -o '"container_port": *[0-9]*' "$CONFIG" | cut -d' ' -f2)
    local protos=$(grep -o '"protocol": *"[^"]*"' "$CONFIG" | cut -d'"' -f4)

    # Detect WAN interface
    local wan=""
    for iface in wlan0 rmnet_data0 rmnet0 ppp0 eth0; do
        if ip link show "$iface" 2>/dev/null | grep -q "UP"; then
            wan="$iface"
            break
        fi
    done
    [ -z "$wan" ] && wan="wlan0"

    # Flush old rules for this container IP first
    iptables -t nat -S 2>/dev/null | grep "$IP" | sed 's/-A/-D/g' | while read rule; do
        iptables -t nat $rule 2>/dev/null
    done

    local i=0
    for hp in $ports; do
        i=$((i + 1))
        local cp=$(echo "$cports" | sed -n "${i}p")
        local pr=$(echo "$protos" | sed -n "${i}p")
        pr=${pr:-tcp}
        [ -z "$cp" ] && continue
        # PREROUTING for external access
        iptables -t nat -A PREROUTING -p "$pr" --dport "$hp" \
            -j DNAT --to-destination "${IP}:${cp}" 2>/dev/null
        iptables -A FORWARD -p "$pr" -d "$IP" --dport "$cp" \
            -m state --state NEW,ESTABLISHED,RELATED -j ACCEPT 2>/dev/null
        # OUTPUT for localhost access
        iptables -t nat -A OUTPUT -p "$pr" --dport "$hp" \
            -j DNAT --to-destination "${IP}:${cp}" 2>/dev/null
    done
}

# ============================================================
# Remove port forwarding rules for container
# ============================================================
cmd_remove_ports() {
    local NAME="$1"
    local CONFIG="$ANK_DIR/containers/$NAME/config.json"
    [ -f "$CONFIG" ] || return 1

    local IP=$(grep -o '"ip_address": *"[^"]*"' "$CONFIG" | cut -d'"' -f4)
    [ -z "$IP" ] || [ "$IP" = "none" ] && return 0

    # Remove all iptables rules matching this container IP
    iptables -t nat -S 2>/dev/null | grep "$IP" | sed 's/-A/-D/g' | while read rule; do
        iptables -t nat $rule 2>/dev/null
    done
    iptables -S 2>/dev/null | grep "$IP" | sed 's/-A/-D/g' | while read rule; do
        iptables $rule 2>/dev/null
    done
}

# ============================================================
# COMPAT MODE policies (simplified iptables)
# ============================================================

cmd_apply_policies_compat() {
    local NAME="$1"
    local CONFIG="$ANK_DIR/containers/$NAME/config.json"
    [ -f "$CONFIG" ] || return 1

    local IP=$(grep -o '"ip_address": *"[^"]*"' "$CONFIG" | cut -d'"' -f4)
    local P2P=$(grep -o '"inter_container_p2p": *[a-z]*' "$CONFIG" | cut -d' ' -f2)
    local HOST=$(grep -o '"allow_host_access": *[a-z]*' "$CONFIG" | cut -d' ' -f2)
    local gw=$(get_gateway)

    P2P=${P2P:-false}
    HOST=${HOST:-false}

    # In compat mode we can still apply iptables rules
    # since all containers share the host network stack
    if [ "$P2P" = "false" ]; then
        for other in "$ANK_DIR"/containers/*/config.json; do
            [ -f "$other" ] || continue
            local other_name=$(basename "$(dirname "$other")")
            [ "$other_name" = "$NAME" ] && continue
            local other_ip=$(grep -o '"ip_address": *"[^"]*"' "$other" | cut -d'"' -f4)
            [ -z "$other_ip" ] && continue
            iptables -A FORWARD -s "$IP" -d "$other_ip" -j DROP 2>/dev/null
            iptables -A FORWARD -s "$other_ip" -d "$IP" -j DROP 2>/dev/null
        done
    fi
}

cmd_apply_ports_compat() {
    local NAME="$1"
    local CONFIG="$ANK_DIR/containers/$NAME/config.json"
    [ -f "$CONFIG" ] || return 1

    local ports=$(grep -o '"host_port": *[0-9]*' "$CONFIG" | cut -d' ' -f2)
    local cports=$(grep -o '"container_port": *[0-9]*' "$CONFIG" | cut -d' ' -f2)
    local protos=$(grep -o '"protocol": *"[^"]*"' "$CONFIG" | cut -d'"' -f4)

    # In compat mode, containers share host network
    # Just do port remapping via REDIRECT + OUTPUT for localhost
    local i=0
    for hp in $ports; do
        i=$((i + 1))
        local cp=$(echo "$cports" | sed -n "${i}p")
        local pr=$(echo "$protos" | sed -n "${i}p")
        pr=${pr:-tcp}
        [ -z "$cp" ] || [ "$hp" = "$cp" ] && continue
        iptables -t nat -A OUTPUT -p "$pr" --dport "$hp" \
            -j REDIRECT --to-port "$cp" 2>/dev/null
        iptables -t nat -A PREROUTING -p "$pr" --dport "$hp" \
            -j REDIRECT --to-port "$cp" 2>/dev/null
    done
}

# ============================================================
# Cleanup
# ============================================================

cmd_cleanup() {
    for ns in $(ip netns list 2>/dev/null | cut -d' ' -f1); do
        case "$ns" in
            netns_*)
                local name=${ns#netns_}
                [ ! -d "$ANK_DIR/containers/$name" ] && ip netns del "$ns" 2>/dev/null
                ;;
        esac
    done
    for veth in $(ip link show type veth 2>/dev/null | grep -o 'veth_ank_[a-zA-Z0-9_-]*'); do
        local name=${veth#veth_ank_}
        [ ! -d "$ANK_DIR/containers/$name" ] && ip link del "$veth" 2>/dev/null
    done
}

# ============================================================
# Get network info (for API)
# ============================================================

cmd_info() {
    local gw=$(get_gateway)
    local subnet=$(read_config "subnet" "10.20.30.0")
    local nat=$(read_config "nat" "true")
    local wan=""

    for iface in wlan0 rmnet_data0 ppp0; do
        if ip link show "$iface" 2>/dev/null | grep -q "UP"; then
            wan="$iface"
            break
        fi
    done

    local ip_forward="0"
    [ -f /proc/sys/net/ipv4/ip_forward ] && ip_forward=$(cat /proc/sys/net/ipv4/ip_forward)

    echo "{\"bridge\":\"$BRIDGE\",\"gateway\":\"$gw\",\"subnet\":\"$subnet/24\",\"nat_enabled\":$nat,\"wan_interface\":\"$wan\",\"ip_forward\":$ip_forward}"
}

# ============================================================
# Main
# ============================================================
CMD="$1"
NAME="$2"

case "$CMD" in
    create)              cmd_create "$NAME" "$3" ;;
    create_compat)       cmd_create_compat "$NAME" "$3" ;;
    apply_policies)      cmd_apply_policies "$NAME" ;;
    apply_policies_compat) cmd_apply_policies_compat "$NAME" ;;
    apply_ports)         cmd_apply_ports "$NAME" ;;
    apply_ports_compat)  cmd_apply_ports_compat "$NAME" ;;
    remove_ports)        cmd_remove_ports "$NAME" ;;
    destroy)             cmd_destroy "$NAME" ;;
    destroy_compat)      cmd_destroy_compat "$NAME" ;;
    cleanup)             cmd_cleanup ;;
    setup_bridge)        setup_bridge ;;
    setup_bridge_compat) setup_bridge_compat ;;
    info)                cmd_info ;;
    *)
        echo "Usage: $0 {create|create_compat|apply_policies|apply_ports|remove_ports|destroy|cleanup|info} <name>"
        exit 1
        ;;
esac

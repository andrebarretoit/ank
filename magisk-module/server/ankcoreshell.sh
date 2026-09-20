#!/bin/sh
# ============================================================
# ANK Core Shell
# Login shell for SSH connections to ANK host
# Drops user into the ANK interactive shell
# ============================================================

ANK_DIR="/data/local/ank"
CONFIG="$ANK_DIR/config.json"
SCRIPTS_DIR="$ANK_DIR/core"

# Non-interactive SSH: pass command to /bin/sh
if [ "$#" -gt 0 ]; then
    exec /bin/sh "$@"
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
NC='\033[0m'

clear 2>/dev/null

# Dynamic MOTD
_cpu() {
    read _ u1 n1 s1 _ < /proc/stat
    sleep 1
    read _ u2 n2 s2 _ < /proc/stat
    total=$(( (u2+n2+s2) - (u1+n1+s1) ))
    idle=$(( u2 - u1 ))
    [ "$total" -gt 0 ] && echo $(( (total - idle) * 100 / total )) || echo 0
}
_mem() {
    local t=$(awk '/^MemTotal/{print $2}' /proc/meminfo)
    local a=$(awk '/^MemAvailable/{print $2}' /proc/meminfo)
    [ -n "$t" ] && [ "$t" -gt 0 ] 2>/dev/null && echo $(( (t - a) * 100 / t )) || echo 0
}
_up() {
    awk '{d=int($1/86400);h=int(($1%86400)/3600);m=int(($1%3600)/60);printf "%dd %dh %dm",d,h,m}' /proc/uptime
}

echo ""
echo -e "${CYAN}          /$$$$$$  /$$   /$$ /$$   /$$${NC}"
echo -e "${CYAN}         /$$__  $$| $$$ | $$| $$  /$$/${NC}"
echo -e "${CYAN}        | $$  \ $$| $$$$| $$| $$ /$$/${NC}"
echo -e "${CYAN}        | $$$$$$$$| $$ $$ $$| $$$$$/${NC}"
echo -e "${CYAN}        | $$__  $$| $$  $$$$| $$  $${NC}"
echo -e "${CYAN}        | $$  | $$| $$\  $$$| $$\  $${NC}"
echo -e "${CYAN}        | $$  | $$| $$ \  $$| $$ \  $${NC}"
echo -e "${CYAN}        |__/  |__/|__/  \__/|__/  \__/${NC}"
echo ""
echo -e "       Android Konteiner | ANK CLI"
printf "       CPU: %s%%  MEM: %s%%  UPTIME: %s\n" "$(_cpu)" "$(_mem)" "$(_up)"

# Show container summary
if [ -d "$ANK_DIR/containers" ]; then
    RUNNING=0
    TOTAL=0
    for d in "$ANK_DIR/containers"/*/; do
        [ -d "$d" ] || continue
        TOTAL=$((TOTAL + 1))
        CFG="$d/config.json"
        if [ -f "$CFG" ]; then
            STATUS=$(grep -o '"status":"[^"]*"' "$CFG" 2>/dev/null | cut -d'"' -f4)
            [ "$STATUS" = "running" ] && RUNNING=$((RUNNING + 1))
        fi
    done
    echo -e "  ${GREEN}$RUNNING${NC} running / $TOTAL total containers"
fi

# Show device info
IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}')
[ -z "$IP" ] && IP=$(ifconfig wlan0 2>/dev/null | grep 'inet addr' | awk '{print $2}' | cut -d: -f2)
echo -e "  IP: ${BLUE}${IP:-unknown}${NC}"
echo ""

# Drop into ank shell
export PATH="/opt/ank/bin:$PATH"
if [ -f "$SCRIPTS_DIR/ank-shell.sh" ]; then
    exec /bin/sh "$SCRIPTS_DIR/ank-shell.sh"
elif [ -f "/opt/ank/bin/ank" ]; then
    exec /opt/ank/bin/ank
elif [ -f "/bin/ank" ]; then
    exec /bin/ank
else
    echo -e "${YELLOW}  ANK shell not found. Dropping to system shell.${NC}"
    echo ""
    exec /bin/sh
fi

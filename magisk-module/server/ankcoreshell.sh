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

# Dynamic MOTD (no colors, no IP)
_cpu() {
    read _ u1 n1 s1 _ < /proc/stat
    sleep 1
    read _ u2 n2 s2 _ < /proc/stat
    total=$(( (u2+n2+s2) - (u1+n1+s1) ))
    idle=$(( u2 - u1 ))
    [ "$total" -gt 0 ] && echo $(( (total - idle) * 100 / total )) || echo 0
}
_mem() {
    t=$(awk '/^MemTotal/{print $2}' /proc/meminfo)
    a=$(awk '/^MemAvailable/{print $2}' /proc/meminfo)
    [ -n "$t" ] && [ "$t" -gt 0 ] 2>/dev/null && echo $(( (t - a) * 100 / t )) || echo 0
}
_up() {
    awk '{d=int($1/86400);h=int(($1%86400)/3600);m=int(($1%3600)/60);printf "%dd %dh %dm",d,h,m}' /proc/uptime
}

echo ""
echo '          /$$$$$$  /$$   /$$ /$$   /$$'
echo '         /$$__  $$| $$$ | $$| $$  /$$/'
echo '        | $$  \ $$| $$$$| $$| $$ /$$/'
echo '        | $$$$$$$$| $$ $$ $$| $$$$$/'
echo '        | $$__  $$| $$  $$$$| $$  $$'
echo '        | $$  | $$| $$\  $$$| $$\  $$'
echo '        | $$  | $$| $$ \  $$| $$ \  $$'
echo '        |__/  |__/|__/  \__/|__/  \__/'
echo ""
echo "       Android Konteiner | ANK CLI"
printf "       CPU: %s%%  MEM: %s%%  UPTIME: %s\n" "$(_cpu)" "$(_mem)" "$(_up)"
echo ""

# Drop into ank shell
if [ -f "/ank-shell.sh" ]; then
    exec /bin/sh "/ank-shell.sh"
elif [ -f "$SCRIPTS_DIR/ank-shell.sh" ]; then
    exec /bin/sh "$SCRIPTS_DIR/ank-shell.sh"
else
    exec /bin/sh
fi

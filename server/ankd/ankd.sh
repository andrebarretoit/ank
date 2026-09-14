#!/bin/sh
# ============================================================
# ANKD - Android Konteiner Daemon
# Service manager for ANK containers
# ============================================================
# Usage:
#   ankd.sh daemon          Start as daemon (reads .ankdd, manages services)
#   ankd.sh install         Install ankd into container rootfs
#   ankd.sh <command>       CLI mode (ankctl proxy)
#
# Commands (CLI mode):
#   status                  Show all services
#   start <service>         Start a service
#   stop <service>          Stop a service
#   restart <service>       Restart a service
#   add-service             Interactive service creation
#   rm-service <name>       Remove a service
#   daemon-reload           Reload configuration
#   tail <service>          Follow service logs (Ctrl+C to stop)
#   help                    Show help
# ============================================================

# ============================================================
# PATHS
# ============================================================
ANKD_DIR="/usr/ankd"
ANKD_CORE="$ANKD_DIR/core"
ANKD_SERVICES="/etc/ankd/services.d"
ANKD_GENERATED="/etc/ankd/services"
ANKD_RUN="/var/run/ankd"
ANKD_LOG="/var/log/ankd"
# PID/PGID registry. Deliberately under /etc (real rootfs, not tmpfs) so the
# HOST can read these files directly from containers/<name>/merged/etc/ankd/pids
# without bind mounts, /proc scanning, or ps/tag matching. One file per
# service UUID, containing a single integer that is simultaneously the
# service's PID, PGID and SID (see _ankd_spawn_service below).
ANKD_PIDS="/etc/ankd/pids"

# ============================================================
# INIT DIRECTORIES
# ============================================================
_ankd_init_dirs() {
    mkdir -p "$ANKD_SERVICES" 2>/dev/null
    mkdir -p "$ANKD_GENERATED" 2>/dev/null
    mkdir -p "$ANKD_RUN" 2>/dev/null
    mkdir -p "$ANKD_LOG" 2>/dev/null
    mkdir -p "$ANKD_PIDS" 2>/dev/null
}

# ============================================================
# PGID FILE HELPERS
# ============================================================
# Path of the pgid file for a given service uuid
_ankd_pgid_file() {
    echo "$ANKD_PIDS/$1.pgid"
}

# Record a service's pgid (called right after backgrounding it)
_ankd_write_pgid() {
    local uuid="$1"
    local pgid="$2"
    echo "$pgid" > "$(_ankd_pgid_file "$uuid")" 2>/dev/null
}

# Read a service's pgid, empty if none recorded
_ankd_read_pgid() {
    cat "$(_ankd_pgid_file "$1")" 2>/dev/null
}

# ============================================================
# UUID GENERATION (6 hex chars)
# ============================================================
_ankd_uuid() {
    # Generate 6-char hex UUID using /dev/urandom
    if [ -r "/dev/urandom" ]; then
        cat /dev/urandom 2>/dev/null | head -c 3 | od -An -tx1 | tr -d ' \n' | head -c 6
    else
        # Fallback: use timestamp + random
        local ts=$(date +%s 2>/dev/null || echo "0")
        local rnd=$RANDOM 2>/dev/null || echo "$$"
        printf "%06x" $(( (ts + rnd) % 16777216 ))
    fi
}

# ============================================================
# LOGGING
# ============================================================
_ankd_log() {
    local level="$1"
    local msg="$2"
    local ts=$(date "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "0000-00-00 00:00:00")
    echo "[$ts] [$level] $msg" >> "$ANKD_LOG/ankd.log" 2>/dev/null
}

_ankd_service_log() {
    local service="$1"
    local msg="$2"
    local ts=$(date "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "0000-00-00 00:00:00")
    echo "[$ts] [$service] $msg" >> "$ANKD_LOG/${service}.log" 2>/dev/null
}

# Boot message: writes to stdout (captured as container log) AND internal log
_ankd_boot() {
    local level="$1"
    local msg="$2"
    local ts=$(date "+%H:%M:%S" 2>/dev/null || echo "??:??:??")
    echo "[boot] $ts $msg"
    _ankd_log "$level" "$msg"
}

# Check if a service is alive, given its UUID.
# Because every service is spawned via _ankd_spawn_service (setsid, no fork),
# its PID == PGID == SID for its whole life, including across sshd's
# re-exec (execve keeps the PID) and across nginx forking workers (fork
# keeps the same PGID for the children, so the master's PID alone is what
# we need to watch). One syscall, zero /proc reads, zero races from
# scanning a changing process list.
_ankd_is_alive() {
    local uuid="$1"
    local pgid=$(_ankd_read_pgid "$uuid")
    [ -z "$pgid" ] && return 1
    kill -0 "$pgid" 2>/dev/null
}

_ankd_boot_ok() {
    local service="$1"
    local pid="$2"
    local ts=$(date "+%H:%M:%S" 2>/dev/null || echo "??:??:??")
    echo "[boot] $ts  OK  $service (PID: $pid)"
    _ankd_service_log "$service" "Started (PID: $pid)"
}

_ankd_boot_fail() {
    local service="$1"
    local reason="$2"
    local ts=$(date "+%H:%M:%S" 2>/dev/null || echo "??:??:??")
    echo "[boot] $ts FAIL $service: $reason"
    _ankd_log "ERROR" "$service failed: $reason"
}

_ankd_sleep() {
    sleep "$1" 2>/dev/null || busybox sleep "$1" 2>/dev/null || {
        local i=0
        while [ "$i" -lt "$1" ]; do i=$((i + 1)); done
    }
}

# ============================================================
# PARSE .ANK FILE
# ============================================================
_ankd_parse_ank() {
    local file="$1"
    if [ ! -f "$file" ]; then
        return 1
    fi
    # Read key=value pairs, strip comments, trim whitespace
    while IFS= read -r line; do
        # Skip comments and empty lines
        case "$line" in
            \#*|"") continue ;;
        esac
        # Extract key=value
        local key=$(echo "$line" | cut -d'=' -f1 | tr -d ' ')
        local val=$(echo "$line" | cut -d'=' -f2- | sed 's/^ *//;s/ *$//')
        # Remove surrounding quotes if present
        val=$(echo "$val" | sed 's/^"//;s/"$//' | sed "s/^'//;s/'$//")
        case "$key" in
            NAME)           ANK_NAME="$val" ;;
            CMD)            ANK_CMD="$val" ;;
            DIR)            ANK_DIR_C="$val" ;;
            PID_FILE)       ANK_PID_FILE="$val" ;;
            STOP_SIGNAL)    ANK_STOP_SIGNAL="$val" ;;
            HEALTH_CHECK)   ANK_HEALTH_CHECK="$val" ;;
            RESTART_POLICY) ANK_RESTART_POLICY="$val" ;;
            RESTART_DELAY)  ANK_RESTART_DELAY="$val" ;;
            TYPE)           ANK_TYPE="$val" ;;
            DEPENDS)        ANK_DEPENDS="$val" ;;
            LOG_FILE)       ANK_LOG_FILE="$val" ;;
            PORT)           ANK_PORT="$val" ;;
        esac
    done < "$file"
}

# Reset .ankdd variables
_ankd_reset_vars() {
    ANK_NAME=""
    ANK_CMD=""
    ANK_DIR_C=""
    ANK_PID_FILE=""
    ANK_STOP_SIGNAL="TERM"
    ANK_HEALTH_CHECK=""
    ANK_RESTART_POLICY="always"
    ANK_RESTART_DELAY="3"
    ANK_TYPE="daemon"
    ANK_DEPENDS=""
    ANK_LOG_FILE=""
    ANK_PORT=""
}

# ============================================================
# GENERATE SERVICE SCRIPT
# ============================================================
_ankd_generate_service() {
    local uuid="$1"
    local name="$2"
    local script_path="$ANKD_GENERATED/${uuid}-${name}.sh"

    cat > "$script_path" << SCRIPT_EOF
#!/bin/sh
# Auto-generated by ankd - DO NOT EDIT
# UUID: $uuid
# Service: $name

UUID="$uuid"
SERVICE="$name"
CMD="$ANK_CMD"
DIR="$ANK_DIR_C"
PID_FILE="$ANK_PID_FILE"
STOP_SIGNAL="$ANK_STOP_SIGNAL"
LOG_FILE="$ANKD_LOG/${name}.log"

# ============================================================
# NORMAL START (daemon mode)
# ============================================================

# Change to working directory
cd "\$DIR" 2>/dev/null || cd /

# Ensure PATH is set
export PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin

# Redirect stdout/stderr to log file
exec >> "\$LOG_FILE" 2>&1

# Log start
ts=\$(date "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "0000-00-00 00:00:00")
echo "[\$ts] [\$SERVICE] Started (PID: \$\$)"

# This process (\$\$) is NOT a process-group leader (it was backgrounded by
# ankd without job control), so "setsid" below succeeds WITHOUT forking: it
# just calls setsid(2) on this same PID and then execve()s straight into
# CMD. No new PID is created, so the PID ankd already captured stays valid
# forever, and it is now also this service's PGID and SID.
#
# argv[0] is left completely untouched (unlike the old "exec -a TAG"
# approach), so sshd's own re-exec (which requires argv[0] to be an
# absolute path) works normally.
exec setsid \$CMD
SCRIPT_EOF

    chmod +x "$script_path" 2>/dev/null
    echo "$script_path"
}

# ============================================================
# SPAWN + REGISTER a generated service script
# Backgrounds the script and immediately records its pid (== pgid == sid)
# in the pgid registry. Echoes the pid to the caller.
# ============================================================
_ankd_spawn_service() {
    local uuid="$1"
    local script="$2"
    local svc_log="$3"

    chmod +x "$script" 2>/dev/null
    /bin/sh "$script" > "$svc_log" 2>&1 &
    local pid=$!
    _ankd_write_pgid "$uuid" "$pid"
    echo "$pid"
}

# ============================================================
# GENERATE ANKCTL CLI
# ============================================================
_ankd_generate_ankctl() {
    local ankctl_path="/bin/ankctl"

    cat > "$ankctl_path" << 'ANKCTL_EOF'
#!/bin/sh
# ============================================================
# ANKCTL - Android Konteiner Control
# CLI for managing container services
# ============================================================

ANKD_DIR="/usr/ankd"
ANKD_SERVICES="/etc/ankd/services.d"
ANKD_GENERATED="/etc/ankd/services"
ANKD_RUN="/var/run/ankd"
ANKD_LOG="/var/log/ankd"
ANKD_PIDS="/etc/ankd/pids"
mkdir -p "$ANKD_PIDS" 2>/dev/null

# A service's pid file under $ANKD_PIDS holds a single integer that is
# simultaneously its PID, PGID and SID (see the generated service scripts,
# which start CMD via "setsid"). This lets us check liveness with one
# kill -0 and kill the whole tree with one "kill -- -PGID", with no ps
# text-matching and no /proc scanning.
_pgid_file() { echo "$ANKD_PIDS/$1.pgid"; }
_pgid_read() { cat "$(_pgid_file "$1")" 2>/dev/null; }
_pgid_alive() {
    local pgid=$(_pgid_read "$1")
    [ -z "$pgid" ] && return 1
    kill -0 "$pgid" 2>/dev/null
}

# Colors (if terminal supports them)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ============================================================
# STATUS
# ============================================================
cmd_status() {
    printf "${BLUE}%-8s %-16s %-8s %-10s %-10s %s${NC}\n" \
        "UUID" "SERVICE" "PID" "PROCESSES" "STATUS" "UPTIME"
    echo "─────────────────────────────────────────────────────────────────────"
    for svc_file in "$ANKD_SERVICES"/*.ankd; do
        [ -f "$svc_file" ] || continue
        
        local name=$(basename "$svc_file" .ankd | sed 's/^[0-9]*-//')
        local uuid=""
        local pid=""
        local status="stopped"
        local procs="0"
        local uptime="-"
        
        # Find UUID for this service
        for gen in "$ANKD_GENERATED"/*-${name}.sh; do
            [ -f "$gen" ] || continue
            uuid=$(basename "$gen" | cut -d'-' -f1)
            break
        done
        
        if [ -n "$uuid" ]; then
            pid=$(_pgid_read "$uuid")
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                status="running"
                # Process count for this group (master + forked workers/children)
                procs=$(ps -o pid= -g "$pid" 2>/dev/null | wc -l)
                [ "$procs" -eq 0 ] 2>/dev/null && procs=1
                # Get uptime from pid
                local start_time=$(ps -o lstart= -p "$pid" 2>/dev/null)
                if [ -n "$start_time" ]; then
                    uptime="$start_time"
                fi
            else
                status="dead"
                rm -f "$(_pgid_file "$uuid")" 2>/dev/null
            fi
        fi
        
        # Status color
        local status_display="$status"
        case "$status" in
            running) status_display="${GREEN}$status${NC}" ;;
            stopped) status_display="${YELLOW}$status${NC}" ;;
            dead)    status_display="${RED}$status${NC}" ;;
        esac
        
        printf "%-8s %-16s %-8s %-10s " "$uuid" "$name" "$pid" "$procs"
        printf "$status_display"
        printf "        %s\n" "$uptime"
    done
}

# ============================================================
# START SERVICE
# ============================================================
cmd_start() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: ankctl start <service>"
        return 1
    fi
    
    # Find .ankd file
    local ank_file=""
    for f in "$ANKD_SERVICES"/*-${name}.ankd "$ANKD_SERVICES"/*.ankd; do
        [ -f "$f" ] || continue
        local fname=$(basename "$f" .ankd | sed 's/^[0-9]*-//')
        if [ "$fname" = "$name" ]; then
            ank_file="$f"
            break
        fi
    done
    
    if [ -z "$ank_file" ]; then
        echo "Service not found: $name"
        return 1
    fi
    
    # Check if already running
    for gen in "$ANKD_GENERATED"/*-${name}.sh; do
        [ -f "$gen" ] || continue
        local uuid=$(basename "$gen" | cut -d'-' -f1)
        if _pgid_alive "$uuid"; then
            echo "Service $name is already running (PID: $(_pgid_read "$uuid"))"
            return 0
        fi
    done
    
    # Generate and start
    local uuid=$(cat /dev/urandom 2>/dev/null | head -c 3 | od -An -tx1 | tr -d ' \n' | head -c 6)
    [ -z "$uuid" ] && uuid=$(printf "%06x" $((RANDOM % 16777216)))
    
    # Parse .ankd file
    local cmd="" dir="" pid_file="" stop_signal="TERM"
    while IFS= read -r line; do
        case "$line" in \#*|"") continue ;; esac
        local key=$(echo "$line" | cut -d'=' -f1 | tr -d ' ')
        local val=$(echo "$line" | cut -d'=' -f2- | sed 's/^ *//;s/ *$//')
        val=$(echo "$val" | sed 's/^"//;s/"$//' | sed "s/^'//;s/'$//")
        case "$key" in
            CMD) cmd="$val" ;;
            DIR) dir="$val" ;;
            PID_FILE) pid_file="$val" ;;
            STOP_SIGNAL) stop_signal="$val" ;;
        esac
    done < "$ank_file"
    
    [ -z "$cmd" ] && echo "Invalid .ankd file: no CMD defined" && return 1
    [ -z "$dir" ] && dir="/"
    [ -z "$pid_file" ] && pid_file="/run/${uuid}.pid"
    
    # Generate service script
    local script="$ANKD_GENERATED/${uuid}-${name}.sh"
    cat > "$script" << SCRIPT_EOF
#!/bin/sh
UUID="$uuid"
SERVICE="$name"
CMD="$cmd"
DIR="$dir"
PID_FILE="$pid_file"
STOP_SIGNAL="$stop_signal"
LOG_FILE="$ANKD_LOG/${name}.log"
ANKD_DIR="$ANKD_DIR"

cd "\$DIR" 2>/dev/null || cd /
export PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin
exec >> "\$LOG_FILE" 2>&1
ts=\$(date "+%Y-%m-%d %H:%M:%S" 2>/dev/null)
echo "[\$ts] [\$SERVICE] Started (PID: \$\$)"
# Not a process-group leader here, so setsid succeeds without forking:
# PID stays the same and becomes this service's PGID/SID too. argv[0] is
# left untouched so sshd's re-exec (needs an absolute path) still works.
exec setsid \$CMD
SCRIPT_EOF
    chmod +x "$script"
    
    # Start in background, record pid==pgid==sid immediately
    local svc_log="$ANKD_LOG/${name}.log"
    /bin/sh "$script" > "$svc_log" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$(_pgid_file "$uuid")" 2>/dev/null
    
    echo "Started $name (UUID: $uuid, PID: $new_pid)"
}

# ============================================================
# STOP SERVICE
# ============================================================
cmd_stop() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: ankctl stop <service>"
        return 1
    fi
    
    local found=0
    for gen in "$ANKD_GENERATED"/*-${name}.sh; do
        [ -f "$gen" ] || continue
        local uuid=$(basename "$gen" | cut -d'-' -f1)
        local pid=$(_pgid_read "$uuid")

        if [ -n "$pid" ]; then
            # Negative PID = kill the whole process group in one syscall:
            # master + every forked child (e.g. nginx workers) that hasn't
            # detached into its own session. No ps/pgrep needed.
            kill -9 -- "-$pid" 2>/dev/null
            kill -9 "$pid" 2>/dev/null
            rm -f "$(_pgid_file "$uuid")" 2>/dev/null
            echo "Stopped $name (UUID: $uuid)"
            found=1
        fi
    done
    
    [ $found -eq 0 ] && echo "Service not running: $name"
}

# ============================================================
# RESTART SERVICE
# ============================================================
cmd_restart() {
    local name="$1"
    cmd_stop "$name"
    _ankd_sleep 1
    cmd_start "$name"
}

# ============================================================
# ADD SERVICE (interactive)
# ============================================================
cmd_add_service() {
    echo "Add new service"
    echo "───────────────"
    
    printf "Service name: "
    read -r svc_name
    [ -z "$svc_name" ] && echo "Cancelled." && return 1
    
    # Validate name (no spaces, alphanumeric + hyphens)
    case "$svc_name" in
        *[^a-zA-Z0-9-]*) echo "Invalid name (use only letters, numbers, hyphens)." && return 1 ;;
    esac
    
    printf "Command: "
    read -r svc_cmd
    [ -z "$svc_cmd" ] && echo "Cancelled." && return 1
    
    printf "Working directory [/]: "
    read -r svc_dir
    [ -z "$svc_dir" ] && svc_dir="/"
    
    printf "Restart policy (always/on-failure/no) [always]: "
    read -r svc_restart
    [ -z "$svc_restart" ] && svc_restart="always"
    
    printf "Stop signal (TERM/HUP/INT) [TERM]: "
    read -r svc_signal
    [ -z "$svc_signal" ] && svc_signal="TERM"
    
    # Determine order number
    local order="50"
    local existing=$(ls "$ANKD_SERVICES"/*.ankd 2>/dev/null | wc -l)
    if [ "$existing" -eq 0 ]; then
        order="02"
    fi
    
    # Create .ankd file
    local ank_file="$ANKD_SERVICES/${order}-${svc_name}.ankd"
    cat > "$ank_file" << ANK_EOF
NAME=$svc_name
CMD=$svc_cmd
DIR=$svc_dir
PID_FILE=/run/${svc_name}.pid
STOP_SIGNAL=$svc_signal
RESTART_POLICY=$svc_restart
RESTART_DELAY=3
ANK_EOF
    
    # Generate script immediately so user can start without daemon-reload
    local new_uuid=$(_ankd_uuid)
    _ankd_generate_service "$new_uuid" "$svc_name" > /dev/null 2>&1

    echo ""
    echo "Created $ank_file"
    echo "Run 'ankctl start $svc_name' to start."
}

# ============================================================
# REMOVE SERVICE
# ============================================================
cmd_rm_service() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: ankctl rm-service <service>"
        return 1
    fi
    
    # Stop if running
    cmd_stop "$name" 2>/dev/null
    
    # Remove .ankd file
    for f in "$ANKD_SERVICES"/*-${name}.ankd "$ANKD_SERVICES"/*.ankd; do
        [ -f "$f" ] || continue
        local fname=$(basename "$f" .ankd | sed 's/^[0-9]*-//')
        if [ "$fname" = "$name" ]; then
            rm -f "$f"
            echo "Removed $f"
        fi
    done
    
    # Remove generated script
    rm -f "$ANKD_GENERATED"/*-${name}.sh 2>/dev/null
    
    echo "Service $name removed."
}

# ============================================================
# DAEMON RELOAD
# ============================================================
cmd_daemon_reload() {
    echo "Reloading ankd configuration..."
    
    # Regenerate scripts for all .ankd files
    local count=0
    for svc_file in "$ANKD_SERVICES"/*.ankd; do
        [ -f "$svc_file" ] || continue
        local name=$(basename "$svc_file" .ankd | sed 's/^[0-9]*-//')
        
        # Check if script already exists
        local exists=0
        for gen in "$ANKD_GENERATED"/*-${name}.sh; do
            [ -f "$gen" ] && exists=1 && break
        done
        
        if [ $exists -eq 0 ]; then
            local uuid=$(_ankd_uuid)
            _ankd_reset_vars
            _ankd_parse_ank "$svc_file"
            [ -n "$ANK_CMD" ] && _ankd_generate_service "$uuid" "$name" > /dev/null 2>&1
            count=$((count + 1))
        fi
    done
    
    echo "Reloaded. $count new service(s) configured."
    
    # Smart detection: check for cron
    if [ -x "/usr/sbin/crond" ] || [ -x "/usr/bin/crond" ]; then
        local has_cron=0
        for f in "$ANKD_SERVICES"/*cron*.ankd; do
            [ -f "$f" ] && has_cron=1 && break
        done
        if [ $has_cron -eq 0 ]; then
            echo ""
            printf "  [suggestion] crond detected but not configured.\n"
            printf "              Add to startup? [y/N] "
            read -r answer
            case "$answer" in
                y|Y)
                    cat > "$ANKD_SERVICES/50-cron.ankd" << 'CRON_EOF'
NAME=cron
CMD=/usr/sbin/crond -f -l 8
DIR=/
PID_FILE=/run/cron.pid
STOP_SIGNAL=TERM
RESTART_POLICY=always
RESTART_DELAY=3
CRON_EOF
                    echo "  Created 50-cron.ankd"
                    ;;
            esac
        fi
    fi
}

# ============================================================
# TAIL SERVICE LOGS
# ============================================================
cmd_tail() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: ankctl tail <service>"
        return 1
    fi
    
    local log_file="$ANKD_LOG/${name}.log"
    if [ ! -f "$log_file" ]; then
        echo "No logs for service: $name"
        return 1
    fi
    
    echo "Following $name logs (Ctrl+C to stop):"
    echo "────────────────────────────────────────"
    tail -f "$log_file" 2>/dev/null
    echo ""
    echo "Stopped following $name."
}

# ============================================================
# HELP
# ============================================================
cmd_help() {
    echo "ankctl - Android Konteiner Control"
    echo "═══════════════════════════════════"
    echo ""
    echo "Usage: ankctl <command> [args]"
    echo ""
    echo "Commands:"
    echo "  status              Show all services with status"
    echo "  start <service>     Start a service"
    echo "  stop <service>      Stop a service"
    echo "  restart <service>   Restart a service"
    echo "  add-service         Create new service (interactive)"
    echo "  rm-service <name>   Remove a service"
    echo "  daemon-reload       Reload configuration"
    echo "  tail <service>      Follow service logs (Ctrl+C to stop)"
    echo "  help                Show this help"
    echo ""
    echo "Service Definition Files:"
    echo "  /etc/ankd/services.d/*.ankd"
    echo ""
    echo "Examples:"
    echo "  ankctl status"
    echo "  ankctl stop nginx"
    echo "  ankctl tail sshd"
    echo "  ankctl add-service"
}

# ============================================================
# MAIN
# ============================================================
case "$1" in
    status)     cmd_status ;;
    start)      cmd_start "$2" ;;
    stop)       cmd_stop "$2" ;;
    restart)    cmd_restart "$2" ;;
    add-service) cmd_add_service ;;
    rm-service) cmd_rm_service "$2" ;;
    daemon-reload) cmd_daemon_reload ;;
    tail)       cmd_tail "$2" ;;
    help|--help|-h) cmd_help ;;
    *)
        echo "ankctl: unknown command '$1'"
        echo "Try 'ankctl help' for usage."
        exit 1
        ;;
esac

exit 0
ANKCTL_EOF

    chmod +x "$ankctl_path" 2>/dev/null
}

# ============================================================
# DAEMON MODE
# ============================================================
_ankd_daemon() {
    _ankd_init_dirs

    echo ""
    echo "  ANK Container Boot v2.0.0"
    echo "  ========================"
    _ankd_boot "INFO" "ankd starting..."

    # Mount filesystems
    _ankd_boot "INFO" "Mounting filesystems..."
    mkdir -p /dev/pts /dev/shm /run 2>/dev/null
    mount -t proc proc /proc 2>/dev/null
    mount -t sysfs sysfs /sys 2>/dev/null
    mount -t devpts devpts /dev/pts 2>/dev/null || true
    _ankd_boot "INFO" "Filesystems mounted"

    # Set hostname
    hostname "${ANKD_CONTAINER:-ank}" 2>/dev/null
    _ankd_boot "INFO" "Hostname: $(hostname 2>/dev/null)"

    # Generate ankctl if not exists
    if [ ! -x "/bin/ankctl" ]; then
        _ankd_generate_ankctl
        _ankd_boot "INFO" "Generated /bin/ankctl"
    fi

    # Count services
    local svc_count=0
    for svc_file in "$ANKD_SERVICES"/*.ankd; do
        [ -f "$svc_file" ] && svc_count=$((svc_count + 1))
    done
    _ankd_boot "INFO" "Found $svc_count service(s) in $ANKD_SERVICES"

    # Start services
    for svc_file in "$ANKD_SERVICES"/*.ankd; do
        [ -f "$svc_file" ] || continue

        local name=$(basename "$svc_file" .ankd | sed 's/^[0-9]*-//')
        _ankd_reset_vars
        _ankd_parse_ank "$svc_file"

        if [ -z "$ANK_CMD" ]; then
            _ankd_boot_fail "$name" "no CMD defined"
            continue
        fi

        _ankd_boot "INFO" "Starting $name..."

        # Check if .sh already exists for this service (reuse UUID)
        local uuid=""
        local script=""
        for existing in "$ANKD_GENERATED"/*-${name}.sh; do
            [ -f "$existing" ] || continue
            uuid=$(basename "$existing" | sed "s/-${name}.sh$//")
            script="$existing"
            break
        done

        # Only generate new if doesn't exist
        if [ -z "$script" ]; then
            uuid=$(_ankd_uuid)
            script=$(_ankd_generate_service "$uuid" "$name")
        fi

        # Start service (setsid-based: pid == pgid == sid, recorded in $ANKD_PIDS)
        local svc_log="$ANKD_LOG/${name}.log"
        local pid=$(_ankd_spawn_service "$uuid" "$script" "$svc_log")

        # Brief wait to catch immediate crashes
        _ankd_sleep 2
        # Check via the recorded pgid - single kill -0, no /proc scanning
        if _ankd_is_alive "$uuid"; then
            _ankd_boot_ok "$name" "$pid"
        else
            # Show last lines of service log on crash
            local svc_log="$ANKD_LOG/${name}.log"
            local err_output=""
            if [ -f "$svc_log" ]; then
                err_output=$(tail -3 "$svc_log" 2>/dev/null)
            fi
            if [ -n "$err_output" ]; then
                _ankd_boot_fail "$name" "crashed immediately"
                echo "$err_output" | while IFS= read -r line; do
                    # Hide internal ANK paths
                    line=$(echo "$line" | sed \
                        -e 's|/usr/ankd/core/ankd\.sh|ankd|g' \
                        -e 's|/usr/ankd/[^ ]*|ankd|g' \
                        -e 's|/data/local/ank/core/[^ ]*|ank|g' \
                        -e 's|/etc/ankd/[^ ]*|ankd|g' \
                        -e 's|/var/log/ankd/[^ ]*|ankd|g' \
                        -e 's|/var/run/ankd/[^ ]*|ankd|g')
                    echo "    > $line"
                done
            else
                _ankd_boot_fail "$name" "crashed immediately (no output)"
            fi
            rm -f "$ANKD_RUN/${uuid}.pid" "$(_ankd_pgid_file "$uuid")" 2>/dev/null
        fi
    done

    echo ""
    echo "  Container ready."
    echo "  ========================"

    # Show service ports
    local _svc_ports=""
    for svc_file in "$ANKD_SERVICES"/*.ankd; do
        [ -f "$svc_file" ] || continue
        local _p=$(grep "^PORT=" "$svc_file" 2>/dev/null | cut -d= -f2)
        [ -z "$_p" ] && continue
        local _n=$(basename "$svc_file" .ankd | sed 's/^[0-9]*-//')
        [ "$_n" = "sshd" ] && continue
        _svc_ports="${_svc_ports:+$_svc_ports, }${_n}=${_p}"
    done
    [ -n "$_svc_ports" ] && _ankd_boot "INFO" "Service port(s): $_svc_ports"

    _ankd_boot "INFO" "ankd running. Waiting for services..."
    
    # Wait for all children — check services by tag
    # Track restart counts per service to prevent infinite restart loops
    local _restart_counts=""
    while true; do
        # Check for shutdown signal
        if [ -f "$ANKD_RUN/.shutdown" ]; then
            echo "Shutdown signal received, exiting ankd"
            break
        fi

        # Check each service via its recorded pgid (kill -0, no ps/proc scanning)
        for svc_file in "$ANKD_SERVICES"/*.ankd; do
            [ -f "$svc_file" ] || continue
            local svc_name=$(basename "$svc_file" .ankd | sed 's/^[0-9]*-//')
            local svc_uuid=""
            for gen in "$ANKD_GENERATED"/*-${svc_name}.sh; do
                [ -f "$gen" ] || continue
                svc_uuid=$(basename "$gen" | cut -d'-' -f1)
                break
            done
            [ -z "$svc_uuid" ] && continue

            if ! _ankd_is_alive "$svc_uuid"; then
                # Get current restart count
                local rcount=0
                local new_counts=""
                for entry in $_restart_counts; do
                    local ename=$(echo "$entry" | cut -d: -f1)
                    local ecount=$(echo "$entry" | cut -d: -f2)
                    if [ "$ename" = "$svc_name" ]; then
                        rcount=$ecount
                    else
                        new_counts="$new_counts $ename:$ecount"
                    fi
                done
                rcount=$((rcount + 1))
                new_counts=$(echo "$new_counts" | sed 's/^ *//')
                _restart_counts="$new_counts $svc_name:$rcount"

                # Check restart policy and max restarts
                local policy=$(grep "^RESTART_POLICY=" "$svc_file" | cut -d'=' -f2)
                local delay=$(grep "^RESTART_DELAY=" "$svc_file" | cut -d'=' -f2)
                [ -z "$policy" ] && policy="always"
                [ -z "$delay" ] && delay="3"

                if [ "$rcount" -gt 10 ]; then
                    _ankd_boot "INFO" "Service $svc_name restarted $rcount times, giving up"
                elif [ "$policy" = "always" ] || [ "$policy" = "on-failure" ]; then
                    _ankd_boot "INFO" "Restarting $svc_name in ${delay}s (policy: $policy, attempt $rcount)"
                    _ankd_sleep "$delay"

                    local existing_sh="$ANKD_GENERATED/${svc_uuid}-${svc_name}.sh"
                    if [ -f "$existing_sh" ]; then
                        local svc_log="$ANKD_LOG/${svc_name}.log"
                        local new_pid=$(_ankd_spawn_service "$svc_uuid" "$existing_sh" "$svc_log")
                        _ankd_boot_ok "$svc_name" "$new_pid"
                    else
                        _ankd_boot_fail "$svc_name" ".sh not found"
                    fi
                else
                    _ankd_boot "INFO" "Service $svc_name died (policy: $policy, not restarting)"
                fi
            else
                # Service is alive — reset restart count
                local new_counts=""
                for entry in $_restart_counts; do
                    local ename=$(echo "$entry" | cut -d: -f1)
                    local ecount=$(echo "$entry" | cut -d: -f2)
                    if [ "$ename" != "$svc_name" ]; then
                        new_counts="$new_counts $ename:$ecount"
                    fi
                done
                _restart_counts=$(echo "$new_counts" | sed 's/^ *//')
            fi
        done
        _ankd_sleep 3
    done
}

# ============================================================
# INSTALL MODE
# ============================================================
_ankd_install() {
    local rootfs="$1"
    if [ -z "$rootfs" ]; then
        echo "Usage: ankd.sh install <rootfs>"
        return 1
    fi
    
    echo "Installing ankd into $rootfs..."
    
    # Create directories
    mkdir -p "$rootfs/usr/ankd/core" 2>/dev/null
    mkdir -p "$rootfs/usr/ankd/services.d" 2>/dev/null
    mkdir -p "$rootfs/usr/ankd/services" 2>/dev/null
    mkdir -p "$rootfs/etc/ankd/services.d" 2>/dev/null
    mkdir -p "$rootfs/etc/ankd/services" 2>/dev/null
    mkdir -p "$rootfs/var/run/ankd" 2>/dev/null
    mkdir -p "$rootfs/var/log/ankd" 2>/dev/null
    
    # Copy ankd.sh
    cp "$0" "$rootfs/usr/ankd/core/ankd.sh" 2>/dev/null
    chmod +x "$rootfs/usr/ankd/core/ankd.sh" 2>/dev/null
    
    # Generate ankdctl
    _ankd_generate_ankctl > "$rootfs/bin/ankctl" 2>/dev/null
    chmod +x "$rootfs/bin/ankctl" 2>/dev/null
    
    echo "ankd installed successfully."
    echo ""
    echo "Directory structure:"
    echo "  /usr/ankd/core/ankd.sh     # Core daemon"
    echo "  /etc/ankd/services.d/      # Service definitions (.ankd)"
    echo "  /etc/ankd/services/        # Generated scripts"
    echo "  /var/run/ankd/             # PID files"
    echo "  /var/log/ankd/             # Logs"
    echo "  /bin/ankctl                # CLI tool"
}

# ============================================================
# MAIN
# ============================================================
case "$1" in
    daemon)
        _ankd_daemon
        ;;
    install)
        _ankd_install "$2"
        ;;
    *)
        # CLI mode - proxy to ankdctl
        exec /bin/ankctl "$@"
        ;;
esac

exit 0

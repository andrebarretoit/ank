#!/bin/sh
# ============================================================
# ANKD - Android Konteiner Daemon
# Service manager for ANK containers
# ============================================================
# Usage:
#   ankd.sh daemon          Start as daemon (reads .ankd, manages services)
#   ankd.sh install         Install ankd into container rootfs
#   ankd.sh <command>       CLI mode (ankctl proxy)
#
# Signal mode (used by the host panel via `container.sh exec`):
#   ankd.sh ankd.servicestop <name>    Stop ONLY the named service (writes a
#                                      stop-flag the daemon respects, kills
#                                      just that service's process group)
#   ankd.sh ankd.servicestart <name>   Start ONLY the named service
#   ankd.sh ankd.servicerestart <name> Restart ONLY the named service
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
# Manual-stop flags: one file per service NAME. While the flag exists the
# daemon never (re)starts that service — this is how ankd.servicestop wins
# against RESTART_POLICY=always. Cleared by ankd.servicestart.
ANKD_STOPPED="/etc/ankd/stopped"
# Control request queue: the host-side signal mode (chroot-exec'd by
# server.py via container.sh exec) drops stop-<name>/start-<name> files
# here; the daemon (inside the container's PID namespace) processes and
# removes them. This is the only reliable channel into PID-namespaced
# containers, where a host-side chroot exec cannot see service pids.
ANKD_CTL="/etc/ankd/ctl"

# ============================================================
# INIT DIRECTORIES
# ============================================================
_ankd_init_dirs() {
    mkdir -p "$ANKD_SERVICES" 2>/dev/null
    mkdir -p "$ANKD_GENERATED" 2>/dev/null
    mkdir -p "$ANKD_RUN" 2>/dev/null
    mkdir -p "$ANKD_LOG" 2>/dev/null
    mkdir -p "$ANKD_PIDS" 2>/dev/null
    mkdir -p "$ANKD_STOPPED" 2>/dev/null
    mkdir -p "$ANKD_CTL" 2>/dev/null
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
# SIGNAL MODE (host-initiated single-service control)
# Invoked by server.py via: container.sh exec <name> \
#     "/usr/ankd/core/ankd.sh ankd.servicestop <service>"
# These stop/start/restart ONLY the named service. The ankd daemon,
# the container init and every other service are never touched.
# ============================================================

_ankd_validate_name() {
    case "$1" in
        ""|*[!A-Za-z0-9._-]*) return 1 ;;
    esac
    return 0
}

# Resolve the .ankd definition for a service name. Files are named
# 'NN-<name>.ankd' (numeric order prefix, e.g. 01-sshd.ankd) or
# '<name>.ankd'; the prefix is stripped and the NAME= field is also
# accepted. Echoes the file path, nothing if not found.
_ankd_find_ank_file() {
    local name="$1" f base stripped name_val
    for f in "$ANKD_SERVICES"/*.ankd; do
        [ -f "$f" ] || continue
        base=$(basename "$f" .ankd)
        stripped=$(echo "$base" | sed 's/^[0-9][0-9]*-//')
        [ "$stripped" = "$name" ] && { echo "$f"; return 0; }
        name_val=$(grep '^NAME=' "$f" 2>/dev/null | head -1 | cut -d= -f2-)
        [ "$name_val" = "$name" ] && { echo "$f"; return 0; }
    done
    return 1
}

# Generate /usr/ankd/core/ankd-svckill.sh — the validated single-service
# stopper (see the script's own header for what it does and refuses).
_ankd_generate_svckill() {
    local core_dir="${1:-$ANKD_CORE}"
    mkdir -p "$core_dir" 2>/dev/null
    cat > "$core_dir/ankd-svckill.sh" << 'SVKILL_EOF'
#!/bin/sh
# ============================================================
# ankd-svckill.sh - stop exactly ONE ankd service
# Generated by /usr/ankd/core/ankd.sh - DO NOT EDIT
# Usage: ankd-svckill.sh <stop|kill> <service-name>
#
# Invoked by 'ankd.sh ankd.servicestop <name>' (chroot-exec'd by the
# host) and by the ankd daemon's ctl handler. Resolves the service's
# .ankd definition (numeric order prefix stripped), reads PID_FILE and
# STOP_SIGNAL from it, finds the service's pgid from the
# /etc/ankd/pids/<uuid>.pgid registry (PID_FILE as fallback) and
# signals the WHOLE process group (kill -- -PGID) so the master and all
# forked children die, escalating to SIGKILL after a short wait.
#
# It REFUSES (exit 0 + deferral note, the ankd daemon finishes the job
# from inside the PID namespace) to signal anything it cannot prove
# belongs to the named service: PID 1, itself, its own process group,
# or a process whose /proc/<pid>/root or argv[0] doesn't match. The
# old stop path had no such checks and killed whatever integer sat in
# the pgid registry - including recycled pids and namespaced pids,
# which nuked the container's init group.
# ============================================================

SVC_NAME="$2"
ANKD_SERVICES="/etc/ankd/services.d"
ANKD_GENERATED="/etc/ankd/services"
ANKD_PIDS="/etc/ankd/pids"
ANKD_STOPPED="/etc/ankd/stopped"
ANKD_LOG="/var/log/ankd"

_sv_log() {
    printf '[%s] [svckill] %s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo '?')" \
        "$*" >> "$ANKD_LOG/ankd.log" 2>/dev/null
}

_sv_out() {
    echo "$*"
    _sv_log "$*"
}

_sv_fail() {
    echo "ERROR: $*"
    _sv_log "$*"
    exit 1
}

[ -z "$SVC_NAME" ] && _sv_fail "usage: ankd-svckill.sh <stop|kill> <service>"

case "$SVC_NAME" in
    *[!A-Za-z0-9._-]*) _sv_fail "invalid service name '$SVC_NAME'" ;;
esac

mkdir -p "$ANKD_PIDS" "$ANKD_STOPPED" 2>/dev/null

# 1. Resolve the .ankd definition: strip the numeric order prefix
#    (01-sshd.ankd -> sshd) and also accept the NAME= field.
SVC_ANK=""
for _f in "$ANKD_SERVICES"/*.ankd; do
    [ -f "$_f" ] || continue
    _base=$(basename "$_f" .ankd)
    _stripped=$(echo "$_base" | sed 's/^[0-9][0-9]*-//')
    if [ "$_stripped" = "$SVC_NAME" ] || [ "$_base" = "$SVC_NAME" ]; then
        SVC_ANK="$_f"
        break
    fi
    _nval=$(grep '^NAME=' "$_f" 2>/dev/null | head -1 | cut -d= -f2-)
    if [ "$_nval" = "$SVC_NAME" ]; then
        SVC_ANK="$_f"
        break
    fi
done
[ -z "$SVC_ANK" ] && _sv_fail "service '$SVC_NAME' not found in $ANKD_SERVICES"

# 2. PID_FILE / STOP_SIGNAL / CMD from the .ankd file
SVC_PID_FILE=""
SVC_SIGNAL="TERM"
SVC_ARGV0=""
while IFS= read -r _line; do
    case "$_line" in
        \#*|"") continue ;;
    esac
    _key=$(echo "$_line" | cut -d= -f1 | tr -d ' ')
    _val=$(echo "$_line" | cut -d= -f2- | sed 's/^ *//;s/ *$//')
    case "$_key" in
        PID_FILE)    SVC_PID_FILE="$_val" ;;
        STOP_SIGNAL) SVC_SIGNAL="$_val" ;;
        CMD)         SVC_ARGV0=${_val%% *} ;;
    esac
done < "$SVC_ANK"

# the signal is used as a kill(1) argument: names/numbers only
case "$SVC_SIGNAL" in
    *[!A-Za-z0-9]*) SVC_SIGNAL="TERM" ;;
esac

# 3. Mark the service manually-stopped BEFORE killing anything, so the
#    daemon's restart loop (RESTART_POLICY=always) can't resurrect it
#    mid-stop. Cleared only by ankd.servicestart / 'ankctl start'.
: > "$ANKD_STOPPED/$SVC_NAME" 2>/dev/null

# 4. Find a live pgid: uuid registry first, PID_FILE as fallback.
SVC_UUID=""
SVC_PGID=""
for _gen in "$ANKD_GENERATED"/*-"${SVC_NAME}.sh"; do
    [ -f "$_gen" ] || continue
    _u=$(basename "$_gen" | sed "s/-${SVC_NAME}\.sh\$//")
    _p=$(cat "$ANKD_PIDS/${_u}.pgid" 2>/dev/null)
    case "$_p" in
        ''|*[!0-9]*) continue ;;
    esac
    if kill -0 "$_p" 2>/dev/null; then
        SVC_UUID="$_u"
        SVC_PGID="$_p"
        break
    fi
done
if [ -z "$SVC_PGID" ] && [ -n "$SVC_PID_FILE" ]; then
    _p=$(cat "$SVC_PID_FILE" 2>/dev/null)
    case "$_p" in
        ''|*[!0-9]*) _p="" ;;
    esac
    if [ -n "$_p" ] && kill -0 "$_p" 2>/dev/null; then
        SVC_PGID="$_p"
    fi
fi

# Not running: drop stale registry entries for dead instances and exit.
if [ -z "$SVC_PGID" ]; then
    for _gen in "$ANKD_GENERATED"/*-"${SVC_NAME}.sh"; do
        [ -f "$_gen" ] || continue
        _u=$(basename "$_gen" | sed "s/-${SVC_NAME}\.sh\$//")
        _p=$(cat "$ANKD_PIDS/${_u}.pgid" 2>/dev/null)
        case "$_p" in
            ''|*[!0-9]*) continue ;;
        esac
        kill -0 "$_p" 2>/dev/null || rm -f "$ANKD_PIDS/${_u}.pgid" 2>/dev/null
    done
    _sv_out "Service '$SVC_NAME' is not running (marked stopped)"
    exit 0
fi

# 5. SAFETY VALIDATION - never signal the container init, the ankd
#    daemon, or a process that doesn't belong to this service.
[ "$SVC_PGID" = "1" ] && _sv_fail "refusing to signal PID 1 (container init)"
[ "$SVC_PGID" = "$$" ] && _sv_fail "refusing to signal myself"
_stat=$(cat /proc/self/stat 2>/dev/null)
if [ -n "$_stat" ]; then
    _rest=${_stat##*\)}
    _own_pgid=$(echo "$_rest" | awk '{print $3}')
    if [ -n "$_own_pgid" ] && [ "$SVC_PGID" = "$_own_pgid" ]; then
        _sv_fail "refusing to signal own process group (ankd daemon)"
    fi
fi

# /proc is required for the ownership checks - mount it (exec context)
# if it isn't visible from here.
[ -e /proc/self ] || mount -t proc proc /proc 2>/dev/null
if [ ! -e "/proc/$SVC_PGID" ]; then
    _sv_out "pgid $SVC_PGID of '$SVC_NAME' not visible here - deferring stop to the ankd daemon"
    exit 0
fi
if [ -r "/proc/$SVC_PGID/root" ]; then
    _tgt_root=$(readlink "/proc/$SVC_PGID/root" 2>/dev/null)
    _my_root=$(readlink /proc/self/root 2>/dev/null)
    if [ -n "$_tgt_root" ] && [ -n "$_my_root" ] && [ "$_tgt_root" != "$_my_root" ]; then
        _sv_out "pgid $SVC_PGID (root=$_tgt_root) is outside this rootfs - deferring stop of '$SVC_NAME' to the ankd daemon"
        exit 0
    fi
fi
if [ -n "$SVC_ARGV0" ] && [ -r "/proc/$SVC_PGID/cmdline" ]; then
    _got0=$(tr '\000' '\n' < "/proc/$SVC_PGID/cmdline" 2>/dev/null | head -1)
    if [ -n "$_got0" ] && [ "$_got0" != "$SVC_ARGV0" ] \
        && [ "${_got0##*/}" != "${SVC_ARGV0##*/}" ]; then
        _sv_out "pgid $SVC_PGID (argv0=$_got0) does not look like '$SVC_NAME' - deferring stop to the ankd daemon"
        exit 0
    fi
fi

# 6. Signal the whole process group: master + every forked child.
_sv_out "Stopping '$SVC_NAME' (pgid $SVC_PGID, signal $SVC_SIGNAL)"
kill -"$SVC_SIGNAL" -- "-$SVC_PGID" 2>/dev/null
kill -"$SVC_SIGNAL" -"$SVC_PGID" 2>/dev/null
kill -s "$SVC_SIGNAL" -- "-$SVC_PGID" 2>/dev/null
kill -"$SVC_SIGNAL" "$SVC_PGID" 2>/dev/null

# 7. Short wait, then escalate to SIGKILL.
_i=0
while [ "$_i" -lt 10 ] && kill -0 "$SVC_PGID" 2>/dev/null; do
    sleep 0.5 2>/dev/null || sleep 1
    _i=$((_i + 1))
done
if kill -0 "$SVC_PGID" 2>/dev/null; then
    _sv_out "Escalating '$SVC_NAME' to SIGKILL (pgid $SVC_PGID)"
    kill -KILL -- "-$SVC_PGID" 2>/dev/null
    kill -KILL -"$SVC_PGID" 2>/dev/null
    kill -KILL "$SVC_PGID" 2>/dev/null
    _i=0
    while [ "$_i" -lt 5 ] && kill -0 "$SVC_PGID" 2>/dev/null; do
        sleep 0.5 2>/dev/null || sleep 1
        _i=$((_i + 1))
    done
fi

# 8. Remove the stale .pgid registry file.
[ -n "$SVC_UUID" ] && rm -f "$ANKD_PIDS/$SVC_UUID.pgid" 2>/dev/null

if kill -0 "$SVC_PGID" 2>/dev/null; then
    _sv_fail "service '$SVC_NAME' (pgid $SVC_PGID) survived SIGKILL"
fi
_sv_out "Service '$SVC_NAME' stopped"
exit 0
SVKILL_EOF

    chmod +x "$core_dir/ankd-svckill.sh" 2>/dev/null
}

# ------------------------------------------------------------
# Signal-mode entry points
# ------------------------------------------------------------

_ankd_signal_stop() {
    local name="$1"
    _ankd_init_dirs
    if ! _ankd_validate_name "$name"; then
        echo "ERROR: invalid service name '$name'" >&2
        exit 1
    fi
    if [ -z "$(_ankd_find_ank_file "$name")" ]; then
        echo "ERROR: service '$name' not found in $ANKD_SERVICES" >&2
        exit 1
    fi
    # Manual-stop flag first: closes the restart race before any kill,
    # and keeps the service down until ankd.servicestart clears it.
    : > "$ANKD_STOPPED/$name" 2>/dev/null
    # Queue the same request for the daemon: it lives inside the
    # container's PID namespace, so it can always reach processes a
    # chroot-exec'd script cannot see (isolated/shared_network modes).
    : > "$ANKD_CTL/stop-$name" 2>/dev/null
    # Direct attempt (instant in shared_host mode). svckill validates
    # the recorded pgid and defers to the daemon when it can't prove
    # the target belongs to this service.
    _ankd_generate_svckill
    sh "$ANKD_CORE/ankd-svckill.sh" stop "$name"
}

_ankd_signal_start() {
    local name="$1"
    _ankd_init_dirs
    if ! _ankd_validate_name "$name"; then
        echo "ERROR: invalid service name '$name'" >&2
        exit 1
    fi
    if [ -z "$(_ankd_find_ank_file "$name")" ]; then
        echo "ERROR: service '$name' not found in $ANKD_SERVICES" >&2
        exit 1
    fi
    # Clear the manual-stop flag so the daemon may run this service.
    rm -f "$ANKD_STOPPED/$name" 2>/dev/null
    # The daemon does the spawn: only it is guaranteed to be inside the
    # container's PID namespace, so the service lands in the right
    # namespace with its pgid recorded for later stops.
    : > "$ANKD_CTL/start-$name" 2>/dev/null
    echo "Service '$name' start requested (ankd will start it shortly)"
}

_ankd_signal_restart() {
    local name="$1"
    _ankd_signal_stop "$name" || {
        echo "ERROR: restart of '$name' aborted at stop stage" >&2
        exit 1
    }
    _ankd_signal_start "$name"
}

# ------------------------------------------------------------
# Daemon-side ctl handlers (run INSIDE the container's PID namespace,
# reached via the $ANKD_CTL queue written by the signal mode above)
# ------------------------------------------------------------

# Stop one service from inside the container. svckill is the canonical
# implementation; for a service whose .ankd definition was already
# deleted (service delete) we kill straight from the pgid registry and
# clean up its generated scripts too.
_ankd_daemon_stop_service() {
    local name="$1" gen u p i ank_file
    mkdir -p "$ANKD_STOPPED" "$ANKD_PIDS" 2>/dev/null
    : > "$ANKD_STOPPED/$name" 2>/dev/null
    ank_file=$(_ankd_find_ank_file "$name")
    if [ -n "$ank_file" ]; then
        sh "$ANKD_CORE/ankd-svckill.sh" stop "$name"
        return
    fi
    for gen in "$ANKD_GENERATED"/*-"${name}.sh"; do
        [ -f "$gen" ] || continue
        u=$(basename "$gen" | sed "s/-${name}\.sh\$//")
        p=$(_ankd_read_pgid "$u")
        [ -z "$p" ] && continue
        [ "$p" = "1" ] && continue
        [ "$p" = "$$" ] && continue
        kill -TERM -- "-$p" 2>/dev/null
        kill -TERM -"$p" 2>/dev/null
        kill -s TERM -- "-$p" 2>/dev/null
        kill -TERM "$p" 2>/dev/null
        i=0
        while [ "$i" -lt 6 ] && kill -0 "$p" 2>/dev/null; do
            sleep 0.5 2>/dev/null || sleep 1
            i=$((i + 1))
        done
        kill -0 "$p" 2>/dev/null && {
            kill -KILL -- "-$p" 2>/dev/null
            kill -KILL -"$p" 2>/dev/null
            kill -KILL "$p" 2>/dev/null
        }
        rm -f "$(_ankd_pgid_file "$u")" 2>/dev/null
    done
    rm -f "$ANKD_GENERATED"/*-"${name}.sh" 2>/dev/null
    rm -f "$ANKD_STOPPED/$name" 2>/dev/null
}

# Start one service from inside the container (mirrors the daemon's
# boot path: reuse the existing uuid/generated script when present).
_ankd_daemon_start_service() {
    local name="$1" ank_file uuid script gen pid svc_log
    mkdir -p "$ANKD_STOPPED" 2>/dev/null
    rm -f "$ANKD_STOPPED/$name" 2>/dev/null
    ank_file=$(_ankd_find_ank_file "$name")
    if [ -z "$ank_file" ]; then
        _ankd_log "ERROR" "ctl start: service '$name' not found"
        return 1
    fi
    _ankd_reset_vars
    _ankd_parse_ank "$ank_file"
    if [ -z "$ANK_CMD" ]; then
        _ankd_log "ERROR" "ctl start: '$name' has no CMD"
        return 1
    fi
    uuid=""
    script=""
    for gen in "$ANKD_GENERATED"/*-"${name}.sh"; do
        [ -f "$gen" ] || continue
        uuid=$(basename "$gen" | sed "s/-${name}\.sh\$//")
        script="$gen"
        break
    done
    if [ -z "$script" ]; then
        uuid=$(_ankd_uuid)
        script=$(_ankd_generate_service "$uuid" "$name")
    fi
    if _ankd_is_alive "$uuid"; then
        _ankd_log "INFO" "ctl start: '$name' already running"
        return 0
    fi
    svc_log="$ANKD_LOG/${name}.log"
    pid=$(_ankd_spawn_service "$uuid" "$script" "$svc_log")
    _ankd_sleep 2
    if _ankd_is_alive "$uuid"; then
        _ankd_boot_ok "$name" "$pid"
        return 0
    fi
    _ankd_boot_fail "$name" "ctl start: crashed immediately"
    rm -f "$(_ankd_pgid_file "$uuid")" 2>/dev/null
    return 1
}

# ============================================================
# GENERATE HALT/REBOOT SHIMS
# ============================================================
_ankd_generate_haltshims() {
    local tmp="/run/ankd/.shim"
    local d n
    mkdir -p /run/ankd 2>/dev/null

    cat > "$tmp.halt" << 'HALT_EOF'
#!/bin/sh
# ANK: stop THIS container only (host runs its Stop flow) — never the device.
mkdir -p /run/ankd/requests 2>/dev/null
echo "halt" > /run/ankd/requests/host-action 2>/dev/null
touch /run/ankd/.shutdown 2>/dev/null
echo "Shutdown requested: the host will stop this container."
exit 0
HALT_EOF

    cat > "$tmp.reboot" << 'REBOOT_EOF'
#!/bin/sh
# ANK: restart THIS container only (host runs its Restart flow) — never the device.
mkdir -p /run/ankd/requests 2>/dev/null
echo "reboot" > /run/ankd/requests/host-action 2>/dev/null
touch /run/ankd/.shutdown 2>/dev/null
echo "Restart requested: the host will restart this container."
exit 0
REBOOT_EOF

    cat > "$tmp.shutdown" << 'SHUT_EOF'
#!/bin/sh
# ANK: shutdown for THIS container only — never the device.
_reboot=0
for _a in "$@"; do
    case "$_a" in
        -r|--reboot|-r*) _reboot=1 ;;
    esac
done
mkdir -p /run/ankd/requests 2>/dev/null
if [ "$_reboot" -eq 1 ]; then
    echo "reboot" > /run/ankd/requests/host-action 2>/dev/null
    echo "Restart requested: the host will restart this container."
else
    echo "halt" > /run/ankd/requests/host-action 2>/dev/null
    echo "Shutdown requested: the host will stop this container."
fi
touch /run/ankd/.shutdown 2>/dev/null
exit 0
SHUT_EOF

    chmod 755 "$tmp.halt" "$tmp.reboot" "$tmp.shutdown" 2>/dev/null
    # rm BEFORE cp: these paths are usually busybox symlinks, and cp
    # would otherwise follow the link and overwrite the busybox binary.
    for d in /sbin /usr/sbin /usr/local/sbin /usr/bin /bin; do
        mkdir -p "$d" 2>/dev/null
        for n in halt poweroff reboot shutdown; do
            rm -f "$d/$n" 2>/dev/null
        done
        cp "$tmp.halt" "$d/halt" 2>/dev/null
        cp "$tmp.halt" "$d/poweroff" 2>/dev/null
        cp "$tmp.reboot" "$d/reboot" 2>/dev/null
        cp "$tmp.shutdown" "$d/shutdown" 2>/dev/null
    done
    rm -f "$tmp.halt" "$tmp.reboot" "$tmp.shutdown" 2>/dev/null
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
ANKD_STOPPED="/etc/ankd/stopped"
mkdir -p "$ANKD_PIDS" "$ANKD_STOPPED" 2>/dev/null

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
    
    # Clear the manual-stop flag so the daemon may run this service
    mkdir -p "$ANKD_STOPPED" 2>/dev/null
    rm -f "$ANKD_STOPPED/$name" 2>/dev/null
    
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
    
    # Mark manually-stopped so the daemon's restart loop doesn't
    # resurrect the service (RESTART_POLICY=always) behind our back
    mkdir -p "$ANKD_STOPPED" 2>/dev/null
    : > "$ANKD_STOPPED/$name" 2>/dev/null
    
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
    
    # Remove any manual-stop flag
    rm -f "$ANKD_STOPPED/$name" 2>/dev/null
    
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
    "")
        cmd_status
        ;;
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
# CONTAINER IDENTITY
# Every container shares ONE kernel hostname on this device (no UTS
# namespace), so a container's real name cannot live in the kernel.
# ankd owns it and writes it to files at boot:
#   /etc/hostname                source of truth
#   /etc/profile.d/ank-prompt.sh login prompt shows this container's name
#   /bin/hostname                reports /etc/hostname, not the kernel
# ============================================================
_ankd_setup_identity() {
    local name="$1"
    [ -z "$name" ] && name="ank"

    { printf '%s\n' "$name" > /etc/hostname; } 2>/dev/null
    _ankd_generate_prompt "$name"
    _ankd_generate_hostname
}

_ankd_generate_prompt() {
    local name="$1"
    { mkdir -p /etc/profile.d
      printf '%s\n' \
        '# ANK container identity - written by ankd at boot.' \
        "export ANKD_CONTAINER=$name" \
        'if [ -n "${BASH_VERSION:-}" ] && [ -n "${PS1:-}" ] && [ -n "${ANKD_CONTAINER:-}" ]; then' \
        '    PS1="${PS1//\\h/$ANKD_CONTAINER}"' \
        'fi' > /etc/profile.d/ank-prompt.sh
      chmod 644 /etc/profile.d/ank-prompt.sh 2>/dev/null
    } 2>/dev/null
}

_ankd_generate_hostname() {
    # Write the new binary first: if this fails, the existing hostname
    # command must stay untouched.
    local tmp="/bin/.hostname.ank-new"
    { /bin/cat > "$tmp" << 'ANKHN_EOF'
#!/bin/sh
# ANK-HOSTNAME-WRAPPER
# The kernel hostname is shared by every container on this device, so this
# container reports /etc/hostname instead.
if [ "$#" -eq 0 ]; then
    if [ -r /etc/hostname ]; then
        _ank_h=""
        IFS= read -r _ank_h < /etc/hostname 2>/dev/null || true
        printf '%s\n' "$_ank_h"
        exit 0
    fi
elif [ -r /etc/hostname ]; then
    case "$1" in
        -*) ;;
        *) { printf '%s\n' "$1" > /etc/hostname; } 2>/dev/null ;;
    esac
fi
if [ -x /bin/hostname.real ]; then
    exec /bin/hostname.real "$@"
fi
if [ -x /bin/busybox ]; then
    exec /bin/busybox hostname "$@"
fi
exit 1
ANKHN_EOF
      chmod 755 "$tmp" 2>/dev/null
    } 2>/dev/null

    [ -f "$tmp" ] || return 0

    # Never overwrite a hostname binary twice: keep the real one aside.
    if [ -f /bin/hostname ] && ! grep -q 'ANK-HOSTNAME-WRAPPER' /bin/hostname 2>/dev/null; then
        if [ -L /bin/hostname ]; then
            rm -f /bin/hostname
        else
            mv /bin/hostname /bin/hostname.real 2>/dev/null || rm -f /bin/hostname
        fi
    fi

    mv -f "$tmp" /bin/hostname 2>/dev/null || rm -f "$tmp"
}

# ============================================================
# ANKD TCP HEALTH LISTENER
# Responds to TCP connections on $ANKD_PORT with "ANKD_OK\n<status>\n"
# The host probes this port to determine if the container is truly alive.
# ============================================================
_ankd_health_listener() {
    local port="$1"
    [ -z "$port" ] && return 1

    # Try busybox nc first, thenncat, then shell-based fallback
    local cname="${ANKD_CONTAINER:-ank}"
    if command -v nc >/dev/null 2>&1; then
        # busybox nc: listen mode, exec per connection
        while true; do
            echo -e "ANKD_OK\n${cname}\nrunning" | nc -l -p "$port" -w 1 2>/dev/null
        done &
    elif command -v ncat >/dev/null 2>&1; then
        while true; do
            echo -e "ANKD_OK\n${cname}\nrunning" | ncat -l "$port" -w 1 2>/dev/null
        done &
    else
        # Pure shell fallback: use /dev/tcp or busybox
        while true; do
            # Create a minimal TCP responder using a file-based approach
            local tmp=$(mktemp /tmp/ankd_hc_XXXXXX 2>/dev/null)
            # Use busybox httpd style or simple echo
            _ankd_sleep 1
        done &
    fi
    echo $!
}

# ============================================================
# DAEMON MODE
# ============================================================
_ankd_daemon() {
    _ankd_init_dirs

    echo ""
    echo "  ANK Booting ${ANKD_CONTAINER:-ank}"
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
    _ankd_setup_identity "${ANKD_CONTAINER:-ank}"
    hostname "${ANKD_CONTAINER:-ank}" 2>/dev/null
    _ankd_boot "INFO" "Hostname: $(hostname 2>/dev/null)"

    # (Re)generate ankctl on every boot: version-synced like svckill,
    # executable, and heals containers still carrying the old
    # exec-proxy ankctl (proxy + CLI-mode exec = infinite loop)
    _ankd_generate_ankctl 2>/dev/null
    _ankd_boot "INFO" "ankctl regenerated"

    # Regenerate the service-stop helper so it always matches this
    # ankd version, and purge ctl requests from a previous run.
    mkdir -p "$ANKD_STOPPED" "$ANKD_CTL" 2>/dev/null
    rm -f "$ANKD_CTL"/* 2>/dev/null
    # Never boot with a leftover shutdown signal from a previous stop
    rm -f "$ANKD_RUN/.shutdown" 2>/dev/null
    _ankd_generate_svckill 2>/dev/null
    _ankd_generate_haltshims 2>/dev/null

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

        # Manually-stopped services stay stopped across container restarts
        if [ -f "$ANKD_STOPPED/$name" ]; then
            _ankd_boot "INFO" "Skipping $name (manually stopped)"
            continue
        fi
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

    _ankd_boot "INFO" "SSH running at port $ANKD_SSHD_PORT"

    # Start health check TCP listener on ankd port
    if [ -n "$ANKD_PORT" ]; then
        _ankd_health_listener "$ANKD_PORT"
    fi

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
    local _given_up=""
    while true; do
        # Check for shutdown signal
        if [ -f "$ANKD_RUN/.shutdown" ]; then
            echo "Shutdown signal received, exiting ankd"
            break
        fi

        # ------------------------------------------------------------
        # Service control requests from the host signal mode
        # ('ankd.sh ankd.servicestop/start <name>' writes these files
        # via chroot exec). Handled here because the daemon is the only
        # process guaranteed to be inside the container's PID
        # namespace. stop-* first so a restart's stop+start pair
        # executes in order.
        # ------------------------------------------------------------
        for ctl_file in "$ANKD_CTL"/stop-*; do
            [ -f "$ctl_file" ] || continue
            local ctl_name=$(basename "$ctl_file" | sed 's/^stop-//')
            _ankd_boot "INFO" "ctl: stopping $ctl_name"
            _ankd_daemon_stop_service "$ctl_name"
            rm -f "$ctl_file" 2>/dev/null
        done
        for ctl_file in "$ANKD_CTL"/start-*; do
            [ -f "$ctl_file" ] || continue
            local ctl_name=$(basename "$ctl_file" | sed 's/^start-//')
            _ankd_boot "INFO" "ctl: starting $ctl_name"
            _ankd_daemon_start_service "$ctl_name"
            rm -f "$ctl_file" 2>/dev/null
        done

        # Check each service via its recorded pgid (kill -0, no ps/proc scanning)
        for svc_file in "$ANKD_SERVICES"/*.ankd; do
            [ -f "$svc_file" ] || continue
            local svc_name=$(basename "$svc_file" .ankd | sed 's/^[0-9]*-//')

            # Manually-stopped (ankd.servicestop / ankctl stop): never
            # resurrect, never count as a failure.
            [ -f "$ANKD_STOPPED/$svc_name" ] && continue

            # Shutdown requested: stop watching/resurrecting services now
            [ -f "$ANKD_RUN/.shutdown" ] && break

            # Skip services that already gave up
            local _already_gave_up=0
            for gu in $_given_up; do
                [ "$gu" = "$svc_name" ] && _already_gave_up=1 && break
            done
            [ "$_already_gave_up" -eq 1 ] && continue

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

                if [ "$rcount" -gt 3 ]; then
                    _ankd_boot "FAIL" "$svc_name: service failed after 3 attempts, giving up"
                    _given_up="$_given_up $svc_name"
                elif [ "$policy" = "always" ] || [ "$policy" = "on-failure" ]; then
                    _ankd_boot "INFO" "Restarting $svc_name in ${delay}s (policy: $policy, attempt $rcount)"
                    _ankd_sleep "$delay"
                    # Shutdown requested while waiting: do not respawn
                    [ -f "$ANKD_RUN/.shutdown" ] && break

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

        # Write health status for host-side detection
        if [ -n "$ANK_HEALTH_FILE" ]; then
            if [ -n "$_given_up" ]; then
                echo "DOWN" > "$ANK_HEALTH_FILE" 2>/dev/null
            else
                echo "UP" > "$ANK_HEALTH_FILE" 2>/dev/null
            fi
        fi

        _ankd_sleep 3
    done

    # Clean up health file on shutdown
    [ -n "$ANK_HEALTH_FILE" ] && rm -f "$ANK_HEALTH_FILE" 2>/dev/null
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
    
    # Generate the service-stop helper alongside it
    _ankd_generate_svckill "$rootfs/usr/ankd/core" 2>/dev/null
    
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
    ankd.servicestop)
        _ankd_signal_stop "$2"
        ;;
    ankd.servicestart)
        _ankd_signal_start "$2"
        ;;
    ankd.servicerestart)
        _ankd_signal_restart "$2"
        ;;
    *)
        # CLI mode - proxy to ankctl. Always regenerate first: an old
        # exec-proxy ankctl plus this exec would ping-pong forever.
        _ankd_generate_ankctl 2>/dev/null
        if [ -x "/bin/ankctl" ]; then
            exec /bin/ankctl "$@"
        else
            echo "ankd: /bin/ankctl not found. Run 'ankd.sh install <rootfs>' first." >&2
            exit 1
        fi
        ;;
esac

# Propagate the last command's status: the signal modes' rc (e.g.
# svckill refusing an unsafe target) must reach the caller — a blind
# 'exit 0' here used to mask every failure.
exit $?

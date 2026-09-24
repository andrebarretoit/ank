#!/system/bin/sh
# Ank - Cgroup resource management
# Usage: resources.sh <command> <container_name> [value]

ANK_DIR="${ANK_DIR:-/data/local/ank}"
ANK_SDCARD="/sdcard/AndroidKonteiner"
CGROUP_BASE="/sys/fs/cgroup/ank"

# ============================================================
# Setup cgroup for container
# ============================================================
cmd_setup() {
    local NAME="$1"
    local MEMORY_LIMIT="$2"
    local CPU_PERCENT="$3"
    local CGROUP="$CGROUP_BASE/$NAME"

    mkdir -p "$CGROUP" 2>/dev/null || {
        echo "WARN: Failed to create cgroup (cgroups may not be available) - continuing without resource limits"
        return 0
    }

    # Memory limit (default 256M)
    MEMORY_LIMIT=${MEMORY_LIMIT:-268435456}  # 256 * 1024 * 1024
    if [ -f "$CGROUP/memory.max" ]; then
        echo "$MEMORY_LIMIT" > "$CGROUP/memory.max" 2>/dev/null
    elif [ -f "$CGROUP/memory.limit_in_bytes" ]; then
        echo "$MEMORY_LIMIT" > "$CGROUP/memory.limit_in_bytes" 2>/dev/null
    fi

    # CPU limit (default 50%)
    CPU_PERCENT=${CPU_PERCENT:-50}
    local CPU_QUOTA=$((CPU_PERCENT * 1000))
    if [ -f "$CGROUP/cpu.max" ]; then
        echo "$CPU_QUOTA 100000" > "$CGROUP/cpu.max" 2>/dev/null
    elif [ -f "$CGROUP/cpu.cfs_quota_us" ]; then
        echo "$CPU_QUOTA" > "$CGROUP/cpu.cfs_quota_us" 2>/dev/null
        echo "100000" > "$CGROUP/cpu.cfs_period_us" 2>/dev/null
    fi

    # PIDs limit (default 128)
    if [ -f "$CGROUP/pids.max" ]; then
        echo "128" > "$CGROUP/pids.max" 2>/dev/null
    fi

    echo "Cgroup configured for $NAME (mem: ${MEMORY_LIMIT}B, cpu: ${CPU_PERCENT}%)"
    return 0
}

# ============================================================
# Add process to cgroup
# ============================================================
cmd_attach() {
    local NAME="$1"
    local PID="$2"
    local CGROUP="$CGROUP_BASE/$NAME"

    if [ ! -d "$CGROUP" ]; then
        echo "ERROR: Cgroup for '$NAME' not found"
        return 1
    fi

    echo "$PID" > "$CGROUP/cgroup.procs" 2>/dev/null || {
        # Try legacy cgroup
        echo "$PID" > "$CGROUP/tasks" 2>/dev/null
    }

    return 0
}

# ============================================================
# Get container stats
# ============================================================
cmd_stats() {
    local NAME="$1"
    local CGROUP="$CGROUP_BASE/$NAME"

    if [ ! -d "$CGROUP" ]; then
        echo '{"error": "cgroup not found"}'
        return 1
    fi

    local memory_current="-"
    local memory_limit="-"
    local cpu_usage="-"
    local pids_current="-"

    # Memory usage
    if [ -f "$CGROUP/memory.current" ]; then
        memory_current=$(cat "$CGROUP/memory.current" 2>/dev/null)
    elif [ -f "$CGROUP/memory.usage_in_bytes" ]; then
        memory_current=$(cat "$CGROUP/memory.usage_in_bytes" 2>/dev/null)
    fi

    # Memory limit
    if [ -f "$CGROUP/memory.max" ]; then
        memory_limit=$(cat "$CGROUP/memory.max" 2>/dev/null)
    elif [ -f "$CGROUP/memory.limit_in_bytes" ]; then
        memory_limit=$(cat "$CGROUP/memory.limit_in_bytes" 2>/dev/null)
    fi

    # CPU usage
    if [ -f "$CGROUP/cpu.stat" ]; then
        cpu_usage=$(cat "$CGROUP/cpu.stat" 2>/dev/null | head -1 | cut -d' ' -f2)
    fi

    # PIDs
    if [ -f "$CGROUP/pids.current" ]; then
        pids_current=$(cat "$CGROUP/pids.current" 2>/dev/null)
    fi

    cat << STATSEOF
{
  "memory_bytes": ${memory_current:-0},
  "memory_limit": ${memory_limit:-0},
  "cpu_usage": ${cpu_usage:-0},
  "pids": ${pids_current:-0}
}
STATSEOF
}

# ============================================================
# Update limits
# ============================================================
cmd_set() {
    local NAME="$1"
    local KEY="$2"
    local VALUE="$3"
    local CGROUP="$CGROUP_BASE/$NAME"

    if [ ! -d "$CGROUP" ]; then
        echo "ERROR: Cgroup for '$NAME' not found"
        return 1
    fi

    case "$KEY" in
        memory)
            if [ -f "$CGROUP/memory.max" ]; then
                echo "$VALUE" > "$CGROUP/memory.max"
            elif [ -f "$CGROUP/memory.limit_in_bytes" ]; then
                echo "$VALUE" > "$CGROUP/memory.limit_in_bytes"
            fi
            ;;
        cpu)
            local CPU_QUOTA=$((VALUE * 1000))
            if [ -f "$CGROUP/cpu.max" ]; then
                echo "$CPU_QUOTA 100000" > "$CGROUP/cpu.max"
            elif [ -f "$CGROUP/cpu.cfs_quota_us" ]; then
                echo "$CPU_QUOTA" > "$CGROUP/cpu.cfs_quota_us"
            fi
            ;;
        pids)
            if [ -f "$CGROUP/pids.max" ]; then
                echo "$VALUE" > "$CGROUP/pids.max"
            fi
            ;;
        *)
            echo "ERROR: Unknown key '$KEY'"
            return 1
            ;;
    esac

    return 0
}

# ============================================================
# Remove cgroup
# ============================================================
cmd_destroy() {
    local NAME="$1"
    local CGROUP="$CGROUP_BASE/$NAME"

    if [ ! -d "$CGROUP" ]; then
        return 0
    fi

    # Kill all processes in cgroup
    if [ -f "$CGROUP/cgroup.procs" ]; then
        for pid in $(cat "$CGROUP/cgroup.procs" 2>/dev/null); do
            kill -9 "$pid" 2>/dev/null
        done
    fi

    rmdir "$CGROUP" 2>/dev/null
    return 0
}

# ============================================================
# Main
# ============================================================
CMD="$1"
NAME="$2"

case "$CMD" in
    setup)   cmd_setup "$NAME" "$3" "$4" ;;
    attach)  cmd_attach "$NAME" "$3" ;;
    stats)   cmd_stats "$NAME" ;;
    set)     cmd_set "$NAME" "$3" "$4" ;;
    destroy) cmd_destroy "$NAME" ;;
    *)
        echo "Usage: $0 {setup|attach|stats|set|destroy} <name> [args]"
        exit 1
        ;;
esac

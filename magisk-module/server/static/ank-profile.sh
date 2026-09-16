#!/system/bin/sh
# ============================================================
# ANK Shell - Custom interactive shell for ANK management
# Runs on Android host (outside chroot)
# Usage: /data/local/ank/ankfs/ank-shell.sh
# ============================================================

ANK_DIR="/data/local/ank"
ANK_ENGINE="$ANK_DIR/ank-engine"
CONTAINERS_DIR="$ANK_DIR/containers"
IMAGES_DIR="$ANK_DIR/images"
STACKS_DIR="$ANK_DIR/stacks"
BACKUPS_DIR="$ANK_DIR/backups"
NODES_DIR="$ANK_DIR/nodes"
SCRIPTS_DIR="$ANK_DIR/core"
LOGS_DIR="$ANK_DIR/logs"
CONFIG_FILE="$ANK_DIR/config.json"
ENGINE_DIR="$ANK_DIR/ank-engine"
ANK_TMP="$ANK_DIR/tmp"
HISTORY_FILE="$ANK_DIR/.ank_history"
HISTORY_MAX=500

# Server port
ANK_PORT=8001
if [ -f "$LOGS_DIR/port.conf" ]; then
    ANK_PORT=$(cat "$LOGS_DIR/port.conf" 2>/dev/null)
fi

# Create tmp dir
mkdir -p "$ANK_TMP" 2>/dev/null

# ============================================================
# HELPER: Get config value (simple grep+cut)
# ============================================================
_json_val() {
    local file="$1" key="$2"
    grep -o "\"$key\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$file" 2>/dev/null | head -1 | sed "s/.*\"$key\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/"
}

_json_num() {
    local file="$1" key="$2"
    grep -o "\"$key\"[[:space:]]*:[[:space:]]*[0-9]*" "$file" 2>/dev/null | head -1 | grep -o '[0-9]*$'
}

_json_bool() {
    local file="$1" key="$2"
    grep -o "\"$key\"[[:space:]]*:[[:space:]]*[a-z]*" "$file" 2>/dev/null | head -1 | grep -o '[a-z]*$'
}

# ============================================================
# HELPER: API GET via curl
# ============================================================
_ank_login() {
    local user=$(_json_val "$CONFIG_FILE" "username")
    local pass=$(_json_val "$CONFIG_FILE" "password")
    [ -z "$user" ] && user="ank"
    [ -z "$pass" ] && pass="ank123"
    local resp=$(curl -s -X POST -H "Content-Type: application/json" \
        -d "{\"username\":\"$user\",\"password\":\"$pass\"}" \
        "http://127.0.0.1:${ANK_PORT:-8001}/api/auth/login" 2>/dev/null)
    ANK_TOKEN=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null)
    [ -n "$ANK_TOKEN" ] && return 0 || return 1
}

_ensure_token() {
    [ -n "$ANK_TOKEN" ] && return 0
    _ank_login 2>/dev/null
}

ANK_TOKEN=""
_ank_login 2>/dev/null

_api_get() {
    local path="$1"
    _ensure_token
    if [ -n "$ANK_TOKEN" ]; then
        curl -s -H "Authorization: Bearer $ANK_TOKEN" "http://127.0.0.1:${ANK_PORT:-8001}${path}" 2>/dev/null
    else
        curl -s "http://127.0.0.1:${ANK_PORT:-8001}${path}" 2>/dev/null
    fi
}

_api_post() {
    local path="$1" data="$2"
    _ensure_token
    if [ -n "$ANK_TOKEN" ]; then
        curl -s -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $ANK_TOKEN" -d "$data" "http://127.0.0.1:${ANK_PORT:-8001}${path}" 2>/dev/null
    else
        curl -s -X POST -H "Content-Type: application/json" -d "$data" "http://127.0.0.1:${ANK_PORT:-8001}${path}" 2>/dev/null
    fi
}

_api_delete() {
    local path="$1"
    _ensure_token
    if [ -n "$ANK_TOKEN" ]; then
        curl -s -X DELETE -H "Authorization: Bearer $ANK_TOKEN" "http://127.0.0.1:${ANK_PORT:-8001}${path}" 2>/dev/null
    else
        curl -s -X DELETE "http://127.0.0.1:${ANK_PORT:-8001}${path}" 2>/dev/null
    fi
}

# ============================================================
# HELPER: Find which node a container lives on
# Returns: "local" or node_id
# ============================================================
_find_container_node() {
    local name="$1"
    local json=$(_api_get "/api/containers/all")
    [ -z "$json" ] && echo "local" && return
    echo "$json" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for c in data:
        if c.get('name') == '$name':
            print(c.get('node', 'local'))
            sys.exit(0)
    print('local')
except: print('local')
" 2>/dev/null
}

# ============================================================
# HELPER: Resolve container node_id to alias
# ============================================================
_node_alias() {
    local node_id="$1"
    [ "$node_id" = "local" ] && echo "local" && return
    local fp="$NODES_DIR/${node_id}.json"
    if [ -f "$fp" ]; then
        _json_val "$fp" "alias"
    else
        echo "$node_id"
    fi
}

# ============================================================
# HELPER: History (index-based)
# ============================================================
HIST_FILE="$ANK_DIR/.ank_history"
HIST_MAX=500
HIST_IDX=0

_history_load() {
    : > /dev/null
}

_history_count() {
    if [ -f "$HIST_FILE" ]; then
        wc -l < "$HIST_FILE" 2>/dev/null | tr -d ' '
    else
        echo 0
    fi
}

_history_get() {
    local idx="$1"
    local total=$(_history_count)
    if [ "$idx" -ge 1 ] && [ "$idx" -le "$total" ]; then
        sed -n "${idx}p" "$HIST_FILE" 2>/dev/null
    fi
}

_history_save() {
    local cmd="$1"
    [ -z "$cmd" ] && return
    local last=$(tail -1 "$HIST_FILE" 2>/dev/null)
    [ "$cmd" = "$last" ] && return
    echo "$cmd" >> "$HIST_FILE"
    local count=$(_history_count)
    if [ "$count" -gt "$HIST_MAX" ]; then
        local tmp="$ANK_TMP/history_trim.tmp"
        tail -n "$HISTORY_MAX" "$HIST_FILE" > "$tmp" 2>/dev/null
        mv "$tmp" "$HIST_FILE" 2>/dev/null
    fi
    HIST_IDX=$(_history_count)
}

_history_show() {
    if [ ! -f "$HIST_FILE" ]; then
        echo "No history."
        return
    fi
    local num=0
    while IFS= read -r line; do
        num=$((num + 1))
        printf "%4d  %s\n" "$num" "$line"
    done < "$HIST_FILE"
}

# ============================================================
# HELPER: Tab completion
# ============================================================
_cmds="ank ank-core exit help history"
_ank_subcmds="ps start stop restart rm logs exec inspect images list-images templates deploy pull build npad ls copy ren erase stack backup node ping traceroute nslookup ip ifconfig route netstat ss --version help history --man exit"
_ank_stack_subcmds="ls inspect create scale rm"
_ank_backup_subcmds="ls inspect run rm"
_ank_node_subcmds="ls inspect add rm"
_ank_core_subcmds="status restart info network clean logs help --man"

_complete_input() {
    local input="$1"
    local parts=""
    local last=""
    local completions=""

    parts=$(echo "$input" | sed 's/  */ /g' | sed 's/^ //;s/ $//')
    last=$(echo "$parts" | awk '{print $NF}')
    local nwords=$(echo "$parts" | wc -w | tr -d ' ')

    if [ "$nwords" -le 1 ] 2>/dev/null; then
        completions=$(echo "$_cmds" | tr ' ' '\n' | grep "^${last}" | tr '\n' ' ')
    elif [ "$nwords" -eq 2 ] 2>/dev/null; then
        local first=$(echo "$parts" | awk '{print $1}')
        case "$first" in
            ank)
                completions=$(echo "$_ank_subcmds" | tr ' ' '\n' | grep "^${last}" | tr '\n' ' ')
                ;;
            ank-core)
                completions=$(echo "$_ank_core_subcmds" | tr ' ' '\n' | grep "^${last}" | tr '\n' ' ')
                ;;
        esac
    elif [ "$nwords" -eq 3 ] 2>/dev/null; then
        local first=$(echo "$parts" | awk '{print $1}')
        local second=$(echo "$parts" | awk '{print $2}')
        case "$first" in
            ank)
                case "$second" in
                    stack)
                        completions=$(echo "$_ank_stack_subcmds" | tr ' ' '\n' | grep "^${last}" | tr '\n' ' ')
                        ;;
                    backup)
                        completions=$(echo "$_ank_backup_subcmds" | tr ' ' '\n' | grep "^${last}" | tr '\n' ' ')
                        ;;
                    node)
                        completions=$(echo "$_ank_node_subcmds" | tr ' ' '\n' | grep "^${last}" | tr '\n' ' ')
                        ;;
                    deploy)
                        completions=$(echo "alpine python nginx apache php node" | tr ' ' '\n' | grep "^${last}" | tr '\n' ' ')
                        ;;
                esac
                ;;
        esac
    fi

    if [ -n "$completions" ]; then
        local count=$(echo "$completions" | wc -w | tr -d ' ')
        if [ "$count" -eq 1 ]; then
            local prefix=$(echo "$parts" | sed "s/${last}$//")
            echo "${prefix}${completions}"
        else
            printf "\r\n%s\r\n(root@ank-shell) ~ [/ank-engine] > %s" "$completions" "$parts"
        fi
    fi
}

# ============================================================
# HELPER: Read line with arrow keys + tab
# ============================================================
_read_line() {
    local result=""
    local saved_term=""
    local raw_ok=0

    if command -v stty >/dev/null 2>&1; then
        saved_term=$(stty -g 2>/dev/null)
        stty -echo -icanon min 1 time 0 2>/dev/null && raw_ok=1
    fi

    printf "(root@ank-shell) ~ [/ank-engine] > " >&2

    if [ "$raw_ok" -eq 1 ]; then
        while true; do
            local c=""
            c=$(dd bs=1 count=1 2>/dev/null)

            if [ -z "$c" ]; then
                # raw mode broken or stdin EOF — restore and fall back
                stty "$saved_term" 2>/dev/null
                printf "(root@ank-shell) ~ [/ank-engine] > " >&2
                read -r result 2>/dev/null
                echo "$result"
                return
            fi

            case "$c" in
                $'\n')
                    printf "\n" >&2
                    break
                    ;;
                $'\033')
                    local seq1=""
                    local seq2=""
                    seq1=$(dd bs=1 count=1 2>/dev/null)
                    if [ "$seq1" = "[" ]; then
                        seq2=$(dd bs=1 count=1 2>/dev/null)
                        case "$seq2" in
                            A)
                                local total=$(_history_count)
                                if [ "$total" -gt 0 ] 2>/dev/null; then
                                    if [ "$HIST_IDX" -lt "$total" ] 2>/dev/null; then
                                        HIST_IDX=$((HIST_IDX + 1))
                                    fi
                                    result=$(_history_get "$HIST_IDX")
                                    printf "\033[2K\r(root@ank-shell) ~ [/ank-engine] > %s" "$result" >&2
                                fi
                                ;;
                            B)
                                if [ "$HIST_IDX" -gt 0 ] 2>/dev/null; then
                                    HIST_IDX=$((HIST_IDX - 1))
                                    if [ "$HIST_IDX" -eq 0 ]; then
                                        result=""
                                        printf "\033[2K\r(root@ank-shell) ~ [/ank-engine] > " >&2
                                    else
                                        result=$(_history_get "$HIST_IDX")
                                        printf "\033[2K\r(root@ank-shell) ~ [/ank-engine] > %s" "$result" >&2
                                    fi
                                fi
                                ;;
                            C)
                                result="${result}$(dd bs=1 count=1 2>/dev/null)"
                                printf "%s" "$(dd bs=1 count=1 2>/dev/null)" >&2
                                ;;
                            D)
                                local len=${#result}
                                if [ "$len" -gt 0 ] 2>/dev/null; then
                                    result=$(echo "$result" | cut -c1-$((len-1)))
                                    printf "\b" >&2
                                fi
                                ;;
                        esac
                    elif [ "$seq1" = "O" ]; then
                        local seq2=""
                        seq2=$(dd bs=1 count=1 2>/dev/null)
                    fi
                    ;;
                $'\t')
                    local completed=""
                    completed=$(_complete_input "$result")
                    if [ -n "$completed" ]; then
                        result="$completed"
                        printf "\033[2K\r(root@ank-shell) ~ [/ank-engine] > %s" "$result" >&2
                    fi
                    ;;
                $'\177')
                    local len=${#result}
                    if [ "$len" -gt 0 ] 2>/dev/null; then
                        result=$(echo "$result" | cut -c1-$((len-1)))
                        printf "\b \b" >&2
                    fi
                    ;;
                $'\004')
                    if [ -z "$result" ]; then
                        printf "\n" >&2
                        result="exit"
                        break
                    fi
                    ;;
                $'\003')
                    printf "\n" >&2
                    result=""
                    break
                    ;;
                *)
                    result="${result}${c}"
                    printf "%s" "$c" >&2
                    ;;
            esac
        done

        if command -v stty >/dev/null 2>&1 && [ -n "$saved_term" ]; then
            stty "$saved_term" 2>/dev/null
        fi
    else
        read -r result 2>/dev/null
    fi

    echo "$result"
}

# ============================================================
# HELPER: List containers
# ============================================================
_list_containers() {
    for dir in "$CONTAINERS_DIR"/*/; do
        [ -f "$dir/config.json" ] || continue
        echo "$dir/config.json"
    done
}

# ============================================================
# HELPER: Print formatted table
# ============================================================
_print_row() {
    printf "%-20s %-12s %-16s %-15s %s\n" "$1" "$2" "$3" "$4" "$5"
}

# ============================================================
# ANK: help
# ============================================================
ank_help() {
    cat << 'EOF'
ANK - Android Konteiner CLI (Full Cluster Support)

Container commands:
  ank ps                      List all containers (local + remote)
  ank start <name>            Start a container (auto-detects node)
  ank stop <name>             Stop a container (auto-detects node)
  ank restart <name>          Restart a container (auto-detects node)
  ank rm <name>               Delete a container (auto-detects node)
  ank logs <name>             Show container logs (local + remote)
  ank exec <name> <cmd>       Execute command in container
  ank inspect <name>          Show container details (local + remote)

Image commands:
  ank images                  List images (all nodes)
  ank templates               List deploy templates
  ank deploy <tpl> <name>     Create container from template
  ank pull [version]          Download Alpine base rootfs
  ank build -i <file>         Build image from .ankfile

File commands:
  ank npad <file>             Edit .ankfile (vi-like)
  ank ls                      List files
  ank copy <src> <dst>        Copy file
  ank ren <old> <new>         Rename file
  ank erase <file>            Delete file

Stack commands:
  ank stack ls                List stacks
  ank stack inspect <name>    Show stack details
  ank stack create <n> [t]    Create stack
  ank stack scale <n> <c>     Scale stack
  ank stack rm <name>         Delete stack

Backup commands:
  ank backup ls               List backup routines
  ank backup inspect <id>     Show routine details
  ank backup run <id>         Execute backup
  ank backup rm <id>          Delete routine

Node commands:
  ank node ls                 List connected nodes (with status)
  ank node inspect <id>       Show node details + live stats
  ank node add                Pair a new remote node
  ank node rm <id>            Remove a paired node

Diagnostics:
  ank ping <host> [count]     Ping a host
  ank traceroute <host>       Trace route to host
  ank nslookup <host>         DNS lookup
  ank ip                      Show IP addresses
  ank ifconfig                Show network interfaces
  ank route                   Show routing table
  ank netstat                 Show network connections
  ank ss                      Show socket stats

System:
  ank help                    Show this help
  ank --version               Show version
  ank history                 Show command history
  ank !{NUM}                  Re-execute from history
  ank --man <cmd>             Detailed help for a command
  ank exit                    Exit ANK shell

ANK-Core commands:
  ank-core status             Cluster status (all nodes)
  ank-core restart            Restart ANK server
  ank-core info               Device info + cluster overview
  ank-core network            Show network config
  ank-core clean              Cleanup orphaned resources
  ank-core logs               Show server logs
  ank-core --man <cmd>        Detailed help
EOF
}

# ============================================================
# ANK: exit
# ============================================================
ank_exit() {
    exit 0
}

# ============================================================
# ANK: history
# ============================================================
ank_history() {
    _history_show
}

# ============================================================
# ANK: ps
# ============================================================
ank_ps() {
    _print_row "NAME" "STATUS" "IP" "IMAGE" "PID"
    printf "%s\n" "----------------------------------------------------------------------"
    local found=0
    if command -v curl >/dev/null 2>&1; then
        local json=$(_api_get "/api/containers/all")
        if [ -n "$json" ] && [ "$json" != "null" ]; then
            local i=0
            while true; do
                local name=$(echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$i]['name'] if $i<len(d) else '');" 2>/dev/null)
                [ -z "$name" ] && break
                local status=$(echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$i].get('status',''))" 2>/dev/null)
                local ip=$(echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$i].get('ip_address','N/A'))" 2>/dev/null)
                local image=$(echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$i].get('template_name') or d[$i].get('image',''))" 2>/dev/null)
                local pid=$(echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); p=d[$i].get('pid'); print(p if p else '-')" 2>/dev/null)
                local node=$(echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); n=d[$i].get('node','local'); print('local' if n=='local' else d[$i].get('node_alias',n[:8]))" 2>/dev/null)
                [ -z "$ip" ] && ip="N/A"
                [ -z "$pid" ] && pid="-"
                if [ "$node" != "local" ] && [ -n "$node" ]; then
                    _print_row "$name" "$status" "$ip" "$image" "$pid" "[$node]"
                else
                    _print_row "$name" "$status" "$ip" "$image" "$pid"
                fi
                found=1
                i=$((i + 1))
            done
        fi
    fi
    if [ "$found" -eq 0 ]; then
        for cfg in $(_list_containers); do
            local name=$(_json_val "$cfg" "name")
            local status=$(_json_val "$cfg" "status")
            local ip=$(_json_val "$cfg" "ip_address")
            local image=$(_json_val "$cfg" "image")
            local pid=$(_json_num "$cfg" "pid")
            [ -z "$ip" ] && ip="N/A"
            [ -z "$pid" ] && pid="-"
            _print_row "$name" "$status" "$ip" "$image" "$pid"
            found=1
        done
    fi
    [ "$found" -eq 0 ] && echo "No containers found."
}

# ============================================================
# ANK: start
# ============================================================
ank_start() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: ank start <name>"
        return 1
    fi
    local node=$(_find_container_node "$name")
    if [ "$node" != "local" ]; then
        echo "Starting '$name' on node $(_node_alias "$node")..."
        _api_post "/api/nodes/${node}/containers/${name}/start" "{}"
        echo "Start command sent"
    else
        sh "$SCRIPTS_DIR/container.sh" start "$name" 2>&1 | tail -20
    fi
}

# ============================================================
# ANK: stop
# ============================================================
ank_stop() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: ank stop <name>"
        return 1
    fi
    local node=$(_find_container_node "$name")
    if [ "$node" != "local" ]; then
        echo "Stopping '$name' on node $(_node_alias "$node")..."
        _api_post "/api/nodes/${node}/containers/${name}/stop" "{}"
        echo "Stop command sent"
    else
        sh "$SCRIPTS_DIR/container.sh" stop "$name" 2>&1 | tail -5
    fi
}

# ============================================================
# ANK: restart
# ============================================================
ank_restart() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: ank restart <name>"
        return 1
    fi
    local node=$(_find_container_node "$name")
    if [ "$node" != "local" ]; then
        echo "Restarting '$name' on node $(_node_alias "$node")..."
        local resp=$(_api_post "/api/nodes/${node}/containers/${name}/restart" "{}")
        if echo "$resp" | grep -q "Unauthorized"; then
            echo "ERROR: Unauthorized — token invalid, retrying login..."
            ANK_TOKEN=""
            _ank_login 2>/dev/null
            resp=$(_api_post "/api/nodes/${node}/containers/${name}/restart" "{}")
        fi
        if echo "$resp" | grep -qi "error"; then
            echo "ERROR: $resp"
        else
            echo "Restart command sent"
        fi
    else
        sh "$SCRIPTS_DIR/container.sh" stop "$name" >/dev/null 2>&1
        sleep 1
        sh "$SCRIPTS_DIR/container.sh" start "$name" 2>&1 | tail -5
    fi
}

# ============================================================
# ANK: rm
# ============================================================
ank_rm() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: ank rm <name>"
        return 1
    fi
    local node=$(_find_container_node "$name")
    if [ "$node" != "local" ]; then
        echo "Deleting '$name' on node $(_node_alias "$node")..."
        _api_delete "/api/nodes/${node}/containers/${name}"
        echo "Delete command sent"
    else
        sh "$SCRIPTS_DIR/container.sh" delete "$name" 2>&1 | tail -5
    fi
}

# ============================================================
# ANK: logs
# ============================================================
ank_logs() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: ank logs <name>"
        return 1
    fi
    local node=$(_find_container_node "$name")
    if [ "$node" != "local" ]; then
        local json=$(_api_get "/api/nodes/${node}/containers/${name}/logs")
        if [ -n "$json" ]; then
            echo "$json" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    logs = d.get('logs', [])
    if isinstance(logs, list):
        for l in logs: print(l)
    else:
        print(logs)
except: pass
" 2>/dev/null
        else
            echo "No logs for '$name' on remote node"
        fi
    else
        local logpath="$LOGS_DIR/${name}.log"
        if [ -f "$logpath" ]; then
            tail -50 "$logpath"
        else
            echo "No logs for '$name'"
        fi
    fi
}

# ============================================================
# ANK: exec
# ============================================================
ank_exec() {
    local name="$1"
    shift
    local cmd="$*"
    if [ -z "$name" ] || [ -z "$cmd" ]; then
        echo "Usage: ank exec <name> <command>"
        return 1
    fi
    local node=$(_find_container_node "$name")
    if [ "$node" != "local" ]; then
        local json=$(_api_post "/api/nodes/${node}/containers/${name}/exec" "{\"command\":\"$cmd\"}")
        if [ -n "$json" ]; then
            echo "$json" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('stdout', ''))
    if d.get('stderr'): print(d['stderr'], file=sys.stderr)
except: pass
" 2>/dev/null
        else
            echo "Exec failed on remote node"
        fi
    else
        local config="$CONTAINERS_DIR/$name/config.json"
        if [ ! -f "$config" ]; then
            echo "Container '$name' not found"
            return 1
        fi
        local status=$(_json_val "$config" "status")
        if [ "$status" != "running" ]; then
            echo "Container '$name' not running"
            return 1
        fi
        local merged="$CONTAINERS_DIR/$name/merged"
        chroot "$merged" /bin/sh -c "export PATH=/bin:/sbin:/usr/bin:/usr/sbin; hostname $name 2>/dev/null; $cmd"
    fi
}

# ============================================================
# ANK: inspect
# ============================================================
ank_inspect() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: ank inspect <name>"
        return 1
    fi
    local node=$(_find_container_node "$name")
    if [ "$node" != "local" ]; then
        local json=$(_api_get "/api/nodes/${node}/containers/${name}")
        if [ -n "$json" ] && [ "$json" != "{}" ]; then
            echo "$json" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'Name:       {d.get(\"name\", \"-\")}')
    print(f'Status:     {d.get(\"status\", \"-\")}')
    print(f'Node:       {_node_alias(\"$node\")}')
    print(f'Image:      {d.get(\"template_name\") or d.get(\"image\", \"-\")}')
    print(f'Mode:       {d.get(\"mode\", \"-\")}')
    print(f'IP:         {d.get(\"ip_address\", \"N/A\")}')
    print(f'PID:        {d.get(\"pid\") or \"N/A\"}')
    r = d.get('resources', {})
    print(f'Memory:     {r.get(\"memory_limit\", \"N/A\")}')
    print(f'CPU:        {r.get(\"cpu_limit_percent\", \"N/A\")}%')
    print(f'Created:    {d.get(\"created_at\", \"?\")}')
except Exception as e: print(f'Error: {e}')
" 2>/dev/null
        else
            echo "Container '$name' not found on remote node"
        fi
    else
        local config="$CONTAINERS_DIR/$name/config.json"
        if [ ! -f "$config" ]; then
            echo "Container '$name' not found"
            return 1
        fi
        local cname=$(_json_val "$config" "name")
        local status=$(_json_val "$config" "status")
        local image=$(_json_val "$config" "image")
        local mode=$(_json_val "$config" "mode")
        local ip=$(_json_val "$config" "ip_address")
        local pid=$(_json_num "$config" "pid")
        local tpl=$(_json_val "$config" "template_name")
        local autostart=$(_json_bool "$config" "autostart")
        local mem=$(_json_val "$config" "memory_limit")
        local cpu=$(_json_num "$config" "cpu_limit_percent")
        local created=$(_json_val "$config" "created_at")
        [ -z "$ip" ] && ip="N/A"
        [ -z "$pid" ] && pid="N/A"
        [ -z "$tpl" ] && tpl="none"
        [ -z "$mem" ] && mem="N/A"
        [ -z "$cpu" ] && cpu="N/A"
        [ -z "$created" ] && created="?"
        printf "Name:       %s\n" "$cname"
        printf "Status:     %s\n" "$status"
        printf "Image:      %s\n" "$image"
        printf "Mode:       %s\n" "$mode"
        printf "IP:         %s\n" "$ip"
        printf "PID:        %s\n" "$pid"
        printf "Template:   %s\n" "$tpl"
        printf "Autostart:  %s\n" "$autostart"
        printf "Memory:     %s\n" "$mem"
        printf "CPU:        %s%%\n" "$cpu"
        printf "Created:    %s\n" "$created"
    fi
}

# ============================================================
# ANK: images / list-images
# ============================================================
ank_images() {
    local json=$(_api_get "/api/images/all")
    if [ -n "$json" ] && [ "$json" != "[]" ] && [ "$json" != "null" ]; then
        printf "%-25s %-12s %s\n" "NAME" "SIZE" "NODE"
        printf "%s\n" "--------------------------------------------------------------"
        echo "$json" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for img in data:
        name = img.get('name', img.get('id', '?'))
        size = img.get('size', 0)
        size_str = f'{size/(1024*1024):.1f} MB' if size and size > 0 else '-'
        node = img.get('node', 'local')
        node_str = 'local' if node == 'local' else img.get('node_alias', node[:8])
        print(f'{name:25s} {size_str:12s} {node_str}')
except: pass
" 2>/dev/null
    else
        echo "No images found."
    fi
}

# ============================================================
# ANK: templates
# ============================================================
ank_templates() {
    printf "%-12s %-20s %s\n" "ID" "NAME" "STATUS"
    printf "%s\n" "---------------------------------------------------"
    local alpine_ready="need base"
    [ -d "$IMAGES_DIR/ank-alpinebase-3.20" ] && [ -e "$IMAGES_DIR/ank-alpinebase-3.20/bin/sh" ] && alpine_ready="ready"
    printf "%-12s %-20s %s\n" "alpine" "Alpine 3.20" "$alpine_ready"
    local tpl_status="need base"
    [ -d "$IMAGES_DIR/alpine-3.20" ] && tpl_status="ready"
    printf "%-12s %-20s %s\n" "python" "Python 3.12" "$tpl_status"
    printf "%-12s %-20s %s\n" "nginx" "Nginx Static" "$tpl_status"
    printf "%-12s %-20s %s\n" "apache" "Apache Static" "$tpl_status"
    printf "%-12s %-20s %s\n" "php" "PHP 8.2" "$tpl_status"
    printf "%-12s %-20s %s\n" "node" "Node.js 20" "$tpl_status"
}

# ============================================================
# ANK: deploy
# ============================================================
ank_deploy() {
    local template="$1"
    local name="$2"
    if [ -z "$template" ] || [ -z "$name" ]; then
        echo "Usage: ank deploy <template> <name>"
        echo "Templates: alpine, python, nginx, apache, php, node"
        return 1
    fi
    local image=""
    local pkgs=""
    local port=""
    case "$template" in
        alpine)  image="ank-alpinebase-3.20" ;;
        python)  image="python-3.20"; pkgs="python3 py3-pip"; port=5000 ;;
        nginx)   image="nginx-3.20"; pkgs="nginx curl"; port=8080 ;;
        apache)  image="apache-3.20"; pkgs="apache2 curl"; port=9090 ;;
        php)     image="php-3.20"; pkgs="php82 php82-mbstring php82-json php82-cgi"; port=8000 ;;
        node)    image="node-3.20"; pkgs="nodejs npm"; port=3000 ;;
        *)
            echo "Unknown template: $template"
            echo "Templates: alpine, python, nginx, apache, php, node"
            return 1
            ;;
    esac
    echo "Deploying '$name' from template '$template'..."
    local DEFAULT_PASS=$(_json_val "$CONFIG_FILE" "default_container_password")
    [ -z "$DEFAULT_PASS" ] && DEFAULT_PASS="ank123"
    sh "$SCRIPTS_DIR/container.sh" create "$name" "$image" "$DEFAULT_PASS" "" "$pkgs"
}

# ============================================================
# ANK: pull
# ============================================================
ank_pull() {
    local version="${1:-3.20}"
    echo "Pulling base image alpine-$version..."
    sh "$SCRIPTS_DIR/download-rootfs.sh" "$version"
}

# ============================================================
# ANK: build (build image from .ankfile)
# ============================================================
ank_build() {
    local flag="$1"
    local ankfile="$2"
    if [ "$flag" != "-i" ] || [ -z "$ankfile" ]; then
        echo "Usage: ank build -i <file.ankfile>"
        return 1
    fi
    case "$ankfile" in */*) echo "Error: no paths allowed, use filename only"; return 1 ;; esac

    local filepath="$ENGINE_DIR/$ankfile"
    if [ ! -f "$filepath" ]; then
        echo "Ankfile not found: $ankfile"
        return 1
    fi

    if ! echo "$ankfile" | grep -q '\.ankfile$'; then
        echo "Error: file must have .ankfile extension"
        return 1
    fi

    echo "Validating $ankfile..."
    if ! _validate_ankfile "$filepath"; then
        return 1
    fi

    local base_image=""
    local run_cmds=""
    local cmd=""
    local expose=""
    local workdir=""
    local volume=""
    local passwd=""

    while IFS= read -r line; do
        case "$line" in
            ""|"#"*|[:space:]*) continue ;;
        esac
        local directive=$(echo "$line" | awk '{print $1}')
        local value=$(echo "$line" | cut -d' ' -f2-)
        case "$directive" in
            FROM)    base_image="$value" ;;
            RUN)     run_cmds="${run_cmds}${value}" ;;
            CMD)     cmd="$value" ;;
            EXPOSE)  expose="$value" ;;
            WORKDIR) workdir="$value" ;;
            VOLUME)  volume="$value" ;;
            PASSWD)  passwd="$value" ;;
        esac
    done < "$filepath"

    local image_name=$(echo "$ankfile" | sed 's/\.ankfile$//')
    local image_dir="$IMAGES_DIR/$image_name"

    if [ -d "$image_dir" ]; then
        echo "Image '$image_name' already exists. Remove it first."
        return 1
    fi

    local base_dir="$IMAGES_DIR/$base_image"
    if [ ! -d "$base_dir" ]; then
        echo "Base image '$base_image' not found. Run: ank pull"
        return 1
    fi

    echo "Building image '$image_name' from '$base_image'..."
    cp -a "$base_dir" "$image_dir" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to copy base image"
        return 1
    fi

    mkdir -p "$image_dir/etc" 2>/dev/null
    echo "nameserver 8.8.8.8" > "$image_dir/etc/resolv.conf" 2>/dev/null
    echo "nameserver 8.8.4.4" >> "$image_dir/etc/resolv.conf" 2>/dev/null
    echo "127.0.0.1 localhost" > "$image_dir/etc/hosts" 2>/dev/null

    mkdir -p "$image_dir/dev/pts" 2>/dev/null
    umount "$image_dir/dev" 2>/dev/null
    mount -t tmpfs -o size=16m tmpfs "$image_dir/dev" 2>/dev/null
    [ -e "$image_dir/dev/null" ] || mknod "$image_dir/dev/null" c 1 3 2>/dev/null
    chmod 666 "$image_dir/dev/null" 2>/dev/null
    [ -e "$image_dir/dev/urandom" ] || mknod "$image_dir/dev/urandom" c 1 9 2>/dev/null
    chmod 666 "$image_dir/dev/urandom" 2>/dev/null
    mount -t proc proc "$image_dir/proc" 2>/dev/null

    if [ -n "$run_cmds" ]; then
        echo "Running build commands..."
        echo "$run_cmds" | chroot "$image_dir" /bin/sh 2>&1
        local rc=$?
        if [ $rc -ne 0 ]; then
            echo "WARN: Some commands returned errors (exit $rc)"
        fi
    fi

    if [ -n "$passwd" ]; then
        echo "root:$passwd" | chroot "$image_dir" /usr/sbin/chpasswd 2>/dev/null
    fi

    if [ -n "$workdir" ]; then
        mkdir -p "$image_dir$workdir" 2>/dev/null
    fi

    umount "$image_dir/proc" 2>/dev/null
    umount "$image_dir/dev" 2>/dev/null

    local meta="$image_dir/.ank_meta"
    echo "FROM=$base_image" > "$meta"
    [ -n "$cmd" ] && echo "CMD=$cmd" >> "$meta"
    [ -n "$expose" ] && echo "EXPOSE=$expose" >> "$meta"
    [ -n "$workdir" ] && echo "WORKDIR=$workdir" >> "$meta"
    [ -n "$volume" ] && echo "VOLUME=$volume" >> "$meta"
    echo "BUILT=$(date +%Y-%m-%dT%H:%M:%S)" >> "$meta"
    echo "ANKFILE=$ankfile" >> "$meta"

    echo "Image '$image_name' built successfully!"
    echo "  Base:  $base_image"
    [ -n "$cmd" ] && echo "  CMD:   $cmd"
    [ -n "$expose" ] && echo "  Port:  $expose"
    [ -n "$workdir" ] && echo "  Dir:   $workdir"
    [ -n "$volume" ] && echo "  Vol:   $volume"
}

# ============================================================
# ANK: stack ls
# ============================================================
ank_stack_ls() {
    if [ ! -d "$STACKS_DIR" ]; then
        echo "No stacks found."
        return
    fi
    printf "%-20s %-12s %-8s %-8s %s\n" "NAME" "STATUS" "MIN" "MAX" "PORT"
    printf "%s\n" "--------------------------------------------------------------------"
    local found=0
    for dir in "$STACKS_DIR"/*/; do
        [ -f "$dir/config.json" ] || continue
        local cfg="$dir/config.json"
        local name=$(_json_val "$cfg" "name")
        local status=$(_json_val "$cfg" "status")
        local min=$(_json_num "$cfg" "min")
        local max=$(_json_num "$cfg" "max")
        local port=$(_json_num "$cfg" "port")
        _print_row "$name" "$status" "$min" "$max" "$port"
        found=1
    done
    [ "$found" -eq 0 ] && echo "No stacks found."
}

# ============================================================
# ANK: stack inspect
# ============================================================
ank_stack_inspect() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: ank stack inspect <name>"
        return 1
    fi
    local cfg="$STACKS_DIR/$name/config.json"
    if [ ! -f "$cfg" ]; then
        echo "Stack '$name' not found"
        return 1
    fi
    cat "$cfg"
}

# ============================================================
# ANK: stack create
# ============================================================
ank_stack_create() {
    local name="$1"
    local template="${2:-nginx}"
    local count="${3:-1}"
    if [ -z "$name" ]; then
        echo "Usage: ank stack create <name> [template] [count]"
        return 1
    fi
    local stack_dir="$STACKS_DIR/$name"
    if [ -d "$stack_dir" ]; then
        echo "Stack '$name' already exists"
        return 1
    fi
    mkdir -p "$stack_dir/data"
    local port=$(sh "$SCRIPTS_DIR/container.sh" create "__probe__" 2>/dev/null; echo "")
    # Find a free port (simple approach)
    port=30000
    while [ -f "$STACKS_DIR/*/config.json" ] && grep -q "\"port\": $port" "$STACKS_DIR"/*/config.json 2>/dev/null; do
        port=$((port + 1))
    done

    # Create containers
    local containers=""
    local i=1
    while [ "$i" -le "$count" ]; do
        local cname="stack-${name}-${i}"
        echo "Creating container '$cname'..."
        sh "$SCRIPTS_DIR/container.sh" create "$cname" "" "" "" ""
        if [ $? -eq 0 ]; then
            if [ -z "$containers" ]; then
                containers="\"$cname\""
            else
                containers="$containers, \"$cname\""
            fi
        fi
        i=$((i + 1))
    done

    # Write stack config
    cat > "$stack_dir/config.json" << EOF
{
  "name": "$name",
  "template": "$template",
  "port": $port,
  "min": $count,
  "max": $count,
  "trigger": "requests",
  "threshold_up": 100,
  "threshold_down": 20,
  "scale_up_after": 30,
  "scale_down_after": 120,
  "load_balance": "least_conn",
  "containers": [$containers],
  "status": "active",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%Y-%m-%dT%H:%M:%SZ)",
  "metrics": {"requests_total": 0, "last_scale_event": 0}
}
EOF
    echo "Stack '$name' created (template=$template, port=$port)"
}

# ============================================================
# ANK: stack scale
# ============================================================
ank_stack_scale() {
    local name="$1"
    local count="$2"
    if [ -z "$name" ] || [ -z "$count" ]; then
        echo "Usage: ank stack scale <name> <count>"
        return 1
    fi
    local cfg="$STACKS_DIR/$name/config.json"
    if [ ! -f "$cfg" ]; then
        echo "Stack '$name' not found"
        return 1
    fi
    local current=0
    for dir in "$CONTAINERS_DIR"/stack-${name}-*/; do
        [ -d "$dir" ] && current=$((current + 1))
    done

    if [ "$count" -gt "$current" ]; then
        local i=$((current + 1))
        while [ "$i" -le "$count" ]; do
            local cname="stack-${name}-${i}"
            echo "Creating container '$cname'..."
            sh "$SCRIPTS_DIR/container.sh" create "$cname" "" "" "" ""
            i=$((i + 1))
        done
    elif [ "$count" -lt "$current" ]; then
        local i=$((current))
        while [ "$i" -gt "$count" ]; do
            local cname="stack-${name}-${i}"
            echo "Removing container '$cname'..."
            sh "$SCRIPTS_DIR/container.sh" stop "$cname" 2>/dev/null
            sh "$SCRIPTS_DIR/container.sh" delete "$cname" 2>/dev/null
            i=$((i - 1))
        done
    fi

    # Update config
    sed -i "s/\"min\": [0-9]*/\"min\": $count/" "$cfg" 2>/dev/null
    sed -i "s/\"max\": [0-9]*/\"max\": $count/" "$cfg" 2>/dev/null
    echo "Stack '$name' scaled to $count"
}

# ============================================================
# ANK: stack rm
# ============================================================
ank_stack_rm() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: ank stack rm <name>"
        return 1
    fi
    local cfg="$STACKS_DIR/$name/config.json"
    if [ ! -f "$cfg" ]; then
        echo "Stack '$name' not found"
        return 1
    fi
    echo "Deleting stack '$name'..."
    # Stop and delete all containers
    for dir in "$CONTAINERS_DIR"/stack-${name}-*/; do
        [ -d "$dir" ] || continue
        local cname=$(basename "$dir")
        echo "  Removing container '$cname'..."
        sh "$SCRIPTS_DIR/container.sh" stop "$cname" 2>/dev/null
        sh "$SCRIPTS_DIR/container.sh" delete "$cname" 2>/dev/null
    done
    rm -rf "$STACKS_DIR/$name"
    echo "Stack '$name' deleted"
}

# ============================================================
# ANK: backup ls
# ============================================================
ank_backup_ls() {
    local routines_dir="$BACKUPS_DIR/routines"
    if [ ! -d "$routines_dir" ]; then
        echo "No backup routines found."
        return
    fi
    printf "%-30s %-12s %-10s %s\n" "ID" "TYPE" "ENABLED" "SOURCE"
    printf "%s\n" "--------------------------------------------------------------------"
    local found=0
    for fp in "$routines_dir"/*.json; do
        [ -f "$fp" ] || continue
        local id=$(_json_val "$fp" "id")
        local type=$(_json_val "$fp" "type")
        local enabled=$(_json_bool "$fp" "enabled")
        local source=$(_json_val "$fp" "source")
        [ -z "$type" ] && type="full"
        [ -z "$enabled" ] && enabled="true"
        [ -z "$source" ] && source="?"
        printf "%-30s %-12s %-10s %s\n" "$id" "$type" "$enabled" "$source"
        found=1
    done
    [ "$found" -eq 0 ] && echo "No backup routines found."
}

# ============================================================
# ANK: backup inspect
# ============================================================
ank_backup_inspect() {
    local id="$1"
    if [ -z "$id" ]; then
        echo "Usage: ank backup inspect <id>"
        return 1
    fi
    local fp="$BACKUPS_DIR/routines/${id}.json"
    if [ ! -f "$fp" ]; then
        echo "Routine '$id' not found"
        return 1
    fi
    cat "$fp"
}

# ============================================================
# ANK: backup run (uses server API - no shell script available)
# ============================================================
ank_backup_run() {
    local id="$1"
    if [ -z "$id" ]; then
        echo "Usage: ank backup run <id>"
        return 1
    fi
    local fp="$BACKUPS_DIR/routines/${id}.json"
    if [ ! -f "$fp" ]; then
        echo "Routine '$id' not found"
        return 1
    fi
    echo "Executing backup '$id'..."
    # Use server API for backup execution (no shell script equivalent)
    if command -v curl >/dev/null 2>&1; then
        curl -s -X POST "http://127.0.0.1:$ANK_PORT/api/backups/$id/execute"
    else
        echo "Note: Backup execution requires the ANK server to be running."
        echo "Start the server first, then try again."
        return 1
    fi
}

# ============================================================
# ANK: backup rm
# ============================================================
ank_backup_rm() {
    local id="$1"
    if [ -z "$id" ]; then
        echo "Usage: ank backup rm <id>"
        return 1
    fi
    local fp="$BACKUPS_DIR/routines/${id}.json"
    if [ ! -f "$fp" ]; then
        echo "Routine '$id' not found"
        return 1
    fi
    rm -f "$fp"
    echo "Routine '$id' deleted"
}

# ============================================================
# ANK: node ls
# ============================================================
ank_node_ls() {
    local json=$(_api_get "/api/nodes")
    if [ -n "$json" ]; then
        printf "%-15s %-16s %-8s %-10s %-10s %s\n" "ALIAS" "IP" "PORT" "STATUS" "CPU" "RAM"
        printf "%s\n" "--------------------------------------------------------------------------"
        echo "$json" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    nodes = d.get('nodes', d) if isinstance(d, dict) else d
    if not nodes: print('No nodes found.')
    for n in nodes:
        alias = n.get('alias') or n.get('ip', '?')
        ip = n.get('ip', '?')
        port = n.get('port', 8001)
        status = n.get('status', '?')
        cpu = f\"{n.get('cpu_percent', 0):.0f}%\" if status == 'online' else '-'
        ram = f\"{n.get('mem_used_gb',0):.1f}/{n.get('mem_total_gb',0):.1f}GB\" if status == 'online' else '-'
        print(f'{alias:15s} {ip:16s} {port:<8d} {status:10s} {cpu:10s} {ram}')
except: print('No nodes found.')
" 2>/dev/null
    else
        echo "No nodes found."
    fi
}

# ============================================================
# ANK: node inspect
# ============================================================
ank_node_inspect() {
    local id="$1"
    if [ -z "$id" ]; then
        echo "Usage: ank node inspect <id>"
        return 1
    fi
    local fp="$NODES_DIR/${id}.json"
    if [ ! -f "$fp" ]; then
        echo "Node '$id' not found"
        return 1
    fi
    local alias=$(_json_val "$fp" "alias")
    local ip=$(_json_val "$fp" "ip")
    local port=$(_json_num "$fp" "port")
    local status=$(_json_val "$fp" "status")
    local node_id=$(_json_val "$fp" "id")
    echo "Node: ${alias:-$ip}"
    echo "ID:   $node_id"
    echo "IP:   $ip"
    echo "Port: ${port:-8001}"
    echo "Status: ${status:-?}"
    echo ""
    if [ "$status" = "online" ]; then
        echo "Fetching live status..."
        local info=$(_api_get "/api/nodes/${node_id}/status")
        if [ -n "$info" ]; then
            echo "$info" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    cpu = d.get('cpu_usage', '-')
    disk = d.get('disk', {})
    uptime = d.get('uptime', 0)
    running = d.get('containers_running', 0)
    total = d.get('containers_total', 0)
    print(f'CPU:      {cpu}%')
    print(f'Disk:     {disk.get(\"used\",\"?\")} / {disk.get(\"total\",\"?\")} GB')
    print(f'Uptime:   {uptime}s')
    print(f'Containers: {running} running / {total - running} stopped')
except: pass
" 2>/dev/null
        fi
    fi
}

# ============================================================
# ANK: node add (uses server API - needs HTTP auth)
# ============================================================
ank_node_add() {
    echo "Add remote ANK node"
    printf "Panel IP: "
    read -r node_ip
    printf "Panel Port [8001]: "
    read -r node_port
    node_port="${node_port:-8001}"
    printf "Username: "
    read -r node_user
    printf "Password: "
    read -r node_pass
    printf "Alias (optional): "
    read -r node_alias

    if [ -z "$node_ip" ] || [ -z "$node_user" ] || [ -z "$node_pass" ]; then
        echo "IP, username and password are required"
        return 1
    fi

    echo "Connecting to node at $node_ip:$node_port..."
    if command -v curl >/dev/null 2>&1; then
        curl -s -X POST "http://127.0.0.1:$ANK_PORT/api/nodes" \
            -H "Content-Type: application/json" \
            -d "{\"ip\":\"$node_ip\",\"port\":$node_port,\"user\":\"$node_user\",\"password\":\"$node_pass\",\"alias\":\"$node_alias\"}"
    else
        echo "Note: Adding nodes requires the ANK server to be running."
        echo "Start the server first, then try again."
        return 1
    fi
}

# ============================================================
# ANK: node rm
# ============================================================
ank_node_rm() {
    local id="$1"
    if [ -z "$id" ]; then
        echo "Usage: ank node rm <id>"
        return 1
    fi
    local fp="$NODES_DIR/${id}.json"
    if [ ! -f "$fp" ]; then
        echo "Node '$id' not found"
        return 1
    fi
    rm -f "$fp"
    echo "Node '$id' removed"
}

# ============================================================
# ANK: diagnostic commands (host-level)
# ============================================================
ank_ping() {
    if [ -z "$1" ]; then
        echo "Usage: ank ping <host> [count]"
        return 1
    fi
    local host="$1"
    local count="${2:-4}"
    ping -c "$count" "$host" 2>&1
}

ank_traceroute() {
    if [ -z "$1" ]; then
        echo "Usage: ank traceroute <host>"
        return 1
    fi
    traceroute "$1" 2>&1 || echo "traceroute not available on this device"
}

ank_nslookup() {
    if [ -z "$1" ]; then
        echo "Usage: ank nslookup <host>"
        return 1
    fi
    nslookup "$1" 2>&1 || echo "nslookup not available on this device"
}

ank_ip() {
    ip "$@" 2>&1
}

ank_ifconfig() {
    ifconfig "$@" 2>&1 || echo "ifconfig not available on this device"
}

ank_route() {
    route "$@" 2>&1 || ip route "$@" 2>&1
}

ank_netstat() {
    netstat "$@" 2>&1 || echo "netstat not available on this device"
}

ank_ss() {
    ss "$@" 2>&1 || echo "ss not available on this device"
}

# ============================================================
# ANK: ls (list files in ank-engine)
# ============================================================
ank_ls() {
    local dir="$ENGINE_DIR"
    if [ ! -d "$dir" ]; then
        echo "  (empty)"
        return 0
    fi
    local count=0
    for f in "$dir"/*; do
        [ -e "$f" ] || continue
        local name=$(basename "$f")
        if [ -d "$f" ]; then
            printf "  \033[1;34m%s/\033[0m\n" "$name"
        elif [ -x "$f" ]; then
            printf "  \033[1;32m%s\033[0m\n" "$name"
        else
            printf "  %s\n" "$name"
        fi
        count=$((count + 1))
    done
    [ "$count" -eq 0 ] && echo "  (empty)"
}

# ============================================================
# ANK: copy (copy file)
# ============================================================
ank_copy() {
    local src="$1"
    local dst="$2"
    if [ -z "$src" ] || [ -z "$dst" ]; then
        echo "Usage: ank copy <source> <destination>"
        return 1
    fi
    case "$src" in */*) echo "Error: no paths allowed, use filename only"; return 1 ;; esac
    case "$dst" in */*) echo "Error: no paths allowed, use filename only"; return 1 ;; esac
    local srcpath="$ENGINE_DIR/$src"
    local dstpath="$ENGINE_DIR/$dst"
    if [ ! -e "$srcpath" ]; then
        echo "File not found: $src"
        return 1
    fi
    if [ -e "$dstpath" ]; then
        echo "Destination already exists: $dst"
        return 1
    fi
    cp "$srcpath" "$dstpath"
    echo "Copied '$src' -> '$dst'"
}

# ============================================================
# ANK: ren (rename file)
# ============================================================
ank_ren() {
    local old="$1"
    local new="$2"
    if [ -z "$old" ] || [ -z "$new" ]; then
        echo "Usage: ank ren <old_name> <new_name>"
        return 1
    fi
    case "$old" in */*) echo "Error: no paths allowed, use filename only"; return 1 ;; esac
    case "$new" in */*) echo "Error: no paths allowed, use filename only"; return 1 ;; esac
    local oldpath="$ENGINE_DIR/$old"
    local newpath="$ENGINE_DIR/$new"
    if [ ! -e "$oldpath" ]; then
        echo "File not found: $old"
        return 1
    fi
    if [ -e "$newpath" ]; then
        echo "Destination already exists: $new"
        return 1
    fi
    mv "$oldpath" "$newpath"
    echo "Renamed '$old' -> '$new'"
}

# ============================================================
# ANK: erase (delete file)
# ============================================================
ank_erase() {
    local file="$1"
    if [ -z "$file" ]; then
        echo "Usage: ank erase <filename>"
        return 1
    fi
    case "$file" in */*) echo "Error: no paths allowed, use filename only"; return 1 ;; esac
    local filepath="$ENGINE_DIR/$file"
    if [ ! -e "$filepath" ]; then
        echo "File not found: $file"
        return 1
    fi
    rm -f "$filepath"
    echo "Deleted '$file'"
}

# ============================================================
# ANK: npad (vi-like text editor)
# ============================================================
ank_npad() {
    local file="$1"
    if [ -z "$file" ]; then
        echo "Usage: ank npad <filename>"
        return 1
    fi
    case "$file" in */*) echo "Error: no paths allowed, use filename only"; return 1 ;; esac

    local filepath="$ENGINE_DIR/$file"
    local tmpfile="$ANK_TMP/ank_npad_$$.tmp"
    local undofile="$ANK_TMP/ank_npad_$$.undo"
    rm -f "$tmpfile" "$undofile" 2>/dev/null

    # Load file into buffer
    if [ -f "$filepath" ]; then
        cp "$filepath" "$tmpfile"
    else
        : > "$tmpfile"
    fi

    # Buffer in memory (array via newlines)
    local buf=""
    local cursor=1
    local mode="cmd"
    local modified=0
    local msg=""

    # Load buffer
    if [ -s "$tmpfile" ]; then
        buf=$(cat "$tmpfile")
    fi

    _buf_line_count() {
        if [ -z "$buf" ]; then
            echo 0
        else
            echo "$buf" | wc -l | tr -d ' '
        fi
    }

    _buf_get() {
        local n="$1"
        echo "$buf" | sed -n "${n}p"
    }

    _buf_set() {
        local n="$1"
        local line="$2"
        local newbuf=""
        local i=1
        local total=$(_buf_line_count)
        while [ "$i" -le "$total" ]; do
            if [ "$i" -eq "$n" ]; then
                newbuf="$newbuf$line
"
            else
                newbuf="$newbuf$(_buf_get $i)
"
            fi
            i=$((i + 1))
        done
        # If appending past end
        if [ "$n" -gt "$total" ]; then
            newbuf="$buf$line
"
        fi
        buf="$newbuf"
        modified=1
    }

    _buf_insert() {
        local n="$1"
        local line="$2"
        local newbuf=""
        local i=1
        local total=$(_buf_line_count)
        while [ "$i" -le "$total" ]; do
            if [ "$i" -eq "$n" ]; then
                newbuf="$newbuf$line
"
            fi
            newbuf="$newbuf$(_buf_get $i)
"
            i=$((i + 1))
        done
        # Handle inserting at end
        if [ "$n" -gt "$total" ]; then
            newbuf="$buf$line
"
        fi
        buf="$newbuf"
        modified=1
    }

    _buf_delete() {
        local n="$1"
        local newbuf=""
        local i=1
        local total=$(_buf_line_count)
        while [ "$i" -le "$total" ]; do
            if [ "$i" -ne "$n" ]; then
                newbuf="$newbuf$(_buf_get $i)
"
            fi
            i=$((i + 1))
        done
        buf="$newbuf"
        modified=1
    }

    _buf_save_undo() {
        echo "$buf" > "$undofile"
    }

    _buf_undo() {
        if [ -f "$undofile" ]; then
            buf=$(cat "$undofile")
            rm -f "$undofile"
            modified=1
            msg="Undo"
        else
            msg="Already at oldest change"
        fi
    }

    _buf_display() {
        local total=$(_buf_line_count)
        local start=1
        local end=$total
        if [ "$end" -gt 50 ]; then
            end=50
        fi
        local i=$start
        while [ "$i" -le "$end" ]; do
            local line=$(_buf_get $i)
            if [ "$i" -eq "$cursor" ]; then
                printf "%3d> %s\n" "$i" "$line"
            else
                printf "%3d  %s\n" "$i" "$line"
            fi
            i=$((i + 1))
        done
        if [ "$total" -gt 50 ]; then
            echo "... ($total lines total)"
        fi
        if [ "$total" -eq 0 ]; then
            echo "  (empty buffer)"
        fi
    }

    _buf_write() {
        echo "$buf" > "$tmpfile"
        echo "$buf" > "$filepath"
        modified=0
        msg="\"$file\" ${total}L written"
    }

    # Main loop
    while true; do
        clear 2>/dev/null || printf '\033[2J\033[H'
        printf "=== ank npad: %s [%s] ===\n" "$file" "$mode"
        _buf_display
        echo ""
        if [ -n "$msg" ]; then
            printf "%s\n" "$msg"
            msg=""
        fi
        if [ "$mode" = "cmd" ]; then
            printf ":"
        else
            printf "[INSERT] "
        fi
        read -r input

        if [ "$mode" = "cmd" ]; then
            case "$input" in
                # Save/Quit
                wq|:wq)
                    _buf_save_undo
                    _buf_write
                    rm -f "$tmpfile" "$undofile" 2>/dev/null
                    return 0
                    ;;
                q|:q|:q!)
                    if [ "$modified" -eq 1 ]; then
                        msg="No write since last change (add ! to override)"
                    else
                        rm -f "$tmpfile" "$undofile" 2>/dev/null
                        return 0
                    fi
                    ;;
                q!)
                    rm -f "$tmpfile" "$undofile" 2>/dev/null
                    return 0
                    ;;
                w|:w)
                    _buf_save_undo
                    _buf_write
                    ;;
                # Navigation
                gg)
                    cursor=1
                    ;;
                G)
                    local total=$(_buf_line_count)
                    if [ "$total" -gt 0 ]; then
                        cursor=$total
                    fi
                    ;;
                j)
                    local total=$(_buf_line_count)
                    if [ "$cursor" -lt "$total" ]; then
                        cursor=$((cursor + 1))
                    fi
                    ;;
                k)
                    if [ "$cursor" -gt 1 ]; then
                        cursor=$((cursor - 1))
                    fi
                    ;;
                [0-9]*)
                    local total=$(_buf_line_count)
                    local num=$(echo "$input" | grep -o '^[0-9]*')
                    if [ "$num" -gt 0 ] && [ "$num" -le "$total" ]; then
                        cursor=$num
                    fi
                    ;;
                # Edit commands
                dd)
                    _buf_save_undo
                    local total=$(_buf_line_count)
                    if [ "$total" -gt 0 ]; then
                        _buf_delete "$cursor"
                        local newtotal=$(_buf_line_count)
                        if [ "$cursor" -gt "$newtotal" ] && [ "$newtotal" -gt 0 ]; then
                            cursor=$newtotal
                        fi
                        if [ "$newtotal" -eq 0 ]; then
                            cursor=1
                        fi
                        msg="1 line deleted"
                    fi
                    ;;
                yy)
                    local total=$(_buf_line_count)
                    if [ "$total" -gt 0 ]; then
                        _yank_line=$(_buf_get "$cursor")
                        msg="1 line yanked"
                    fi
                    ;;
                p)
                    if [ -n "$_yank_line" ]; then
                        _buf_save_undo
                        _buf_insert "$cursor" "$_yank_line"
                        cursor=$((cursor + 1))
                        msg="1 line put"
                    fi
                    ;;
                x)
                    _buf_save_undo
                    local total=$(_buf_line_count)
                    if [ "$total" -gt 0 ]; then
                        local line=$(_buf_get "$cursor")
                        local len=${#line}
                        if [ "$len" -gt 0 ]; then
                            local newline=$(echo "$line" | cut -c1-$((len-1)))
                            local newbuf=""
                            local i=1
                            while [ "$i" -le "$total" ]; do
                                if [ "$i" -eq "$cursor" ]; then
                                    newbuf="$newbuf$newline
"
                                else
                                    newbuf="$newbuf$(_buf_get $i)
"
                                fi
                                i=$((i + 1))
                            done
                            buf="$newbuf"
                            modified=1
                            msg="1 character deleted"
                        fi
                    fi
                    ;;
                u)
                    _buf_undo
                    ;;
                i)
                    mode="insert"
                    ;;
                o)
                    _buf_save_undo
                    local total=$(_buf_line_count)
                    _buf_insert "$((cursor + 1))" ""
                    cursor=$((cursor + 1))
                    mode="insert"
                    ;;
                O)
                    _buf_save_undo
                    _buf_insert "$cursor" ""
                    mode="insert"
                    ;;
                a)
                    mode="insert"
                    ;;
                # Visual
                [vV])
                    msg="Visual mode not yet implemented"
                    ;;
                # Search
                /)
                    msg="Search not yet implemented"
                    ;;
                ?)
                    msg="Search not yet implemented"
                    ;;
                n)
                    msg="Search not yet implemented"
                    ;;
                # Misc
                '')
                    ;;
                *)
                    msg="Unknown command: $input"
                    ;;
            esac
        elif [ "$mode" = "insert" ]; then
            case "$input" in
                "")
                    # Empty line = newline
                    _buf_save_undo
                    local total=$(_buf_line_count)
                    _buf_insert "$((cursor + 1))" ""
                    cursor=$((cursor + 1))
                    ;;
                *)
                    _buf_save_undo
                    local total=$(_buf_line_count)
                    _buf_insert "$((cursor + 1))" "$input"
                    cursor=$((cursor + 1))
                    ;;
            esac
            # Check for ESC (exit insert mode)
            # In shell, ESC is hard to detect. Use Ctrl+C or a special key.
            # For now, we'll use a special pattern.
            case "$input" in
                *$'\033'*)
                    mode="cmd"
                    msg=""
                    ;;
            esac
        fi
    done
}

# ============================================================
# VALIDATE ANKFILE SYNTAX
# ============================================================
_validate_ankfile() {
    local file="$1"
    local line_num=0
    local errors=""

    while IFS= read -r line; do
        line_num=$((line_num + 1))
        case "$line" in
            ""|"#"*|[:space:]*) continue ;;
        esac

        local directive=$(echo "$line" | awk '{print $1}' 2>/dev/null || echo "$line" | cut -d' ' -f1)
        local value=$(echo "$line" | cut -d' ' -f2-)

        case "$directive" in
            FROM)
                if [ -z "$value" ]; then
                    errors="${errors}  Line $line_num: FROM requires an image name\n"
                fi
                ;;
            RUN)
                if [ -z "$value" ]; then
                    errors="${errors}  Line $line_num: RUN requires a command\n"
                fi
                ;;
            CMD)
                if [ -z "$value" ]; then
                    errors="${errors}  Line $line_num: CMD requires a command\n"
                fi
                ;;
            EXPOSE)
                case "$value" in
                    ''|*[!0-9]*)
                        errors="${errors}  Line $line_num: EXPOSE requires a valid port number (got: '$value')\n"
                        ;;
                    *)
                        if [ "$value" -lt 1 ] || [ "$value" -gt 65535 ]; then
                            errors="${errors}  Line $line_num: EXPOSE port must be 1-65535\n"
                        fi
                        ;;
                esac
                ;;
            WORKDIR)
                if [ -z "$value" ]; then
                    errors="${errors}  Line $line_num: WORKDIR requires a path\n"
                fi
                ;;
            VOLUME)
                if [ -z "$value" ]; then
                    errors="${errors}  Line $line_num: VOLUME requires a path\n"
                fi
                ;;
            PASSWD)
                if [ -z "$value" ]; then
                    errors="${errors}  Line $line_num: PASSWD requires a password\n"
                fi
                ;;
            *)
                errors="${errors}  Line $line_num: Unknown directive '$directive'\n"
                ;;
        esac
    done < "$file"

    if [ -n "$errors" ]; then
        echo "Ankfile validation errors:"
        printf "$errors"
        return 1
    fi

    echo "Ankfile syntax OK"
    return 0
}

# ============================================================
# ANK-CORE: status
# ============================================================
ank_core_status() {
    local json=$(_api_get "/api/system/dashboard")
    if [ -n "$json" ]; then
        echo "$json" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    local = d.get('local', {})
    cluster = d.get('cluster')
    nodes = d.get('nodes', [])
    ver = d.get('version', '?')

    print(f'ANK Engine v{ver}')
    print(f'')
    print(f'--- Local ---')
    print(f'Containers: {local.get(\"containers_running\",0)} running / {local.get(\"containers_stopped\",0)} stopped')
    print(f'CPU:        {local.get(\"cpu_cores\",0)} cores @ {local.get(\"cpu_percent\",0)}%')
    print(f'Stacks:     {local.get(\"stacks\",0)}')

    if cluster:
        print(f'')
        print(f'--- Cluster ---')
        print(f'Nodes:      {len(nodes)} total')
        print(f'Containers: {cluster.get(\"containers_running\",0)} running / {cluster.get(\"containers_total\",0) - cluster.get(\"containers_running\",0)} stopped ({cluster.get(\"containers_total\",0)} total)')
        print(f'CPU:        {cluster.get(\"cpu_cores\",0)} cores @ {cluster.get(\"cpu_percent\",0)}% avg')
        print(f'RAM:        {cluster.get(\"ram_used_gb\",0):.1f} / {cluster.get(\"ram_total_gb\",0):.1f} GB ({cluster.get(\"ram_percent\",0):.0f}% avg)')
        print(f'Disk:       {cluster.get(\"disk_used_gb\",0):.1f} / {cluster.get(\"disk_total_gb\",0):.1f} GB ({cluster.get(\"disk_percent\",0):.0f}% avg)')
    else:
        print(f'')
        print(f'Cluster:    not configured (single node)')
except: print('Error reading dashboard')
" 2>/dev/null
    else
        echo "ANK server not responding"
    fi
}

# ============================================================
# ANK-CORE: restart
# ============================================================
ank_core_restart() {
    echo "Restarting ANK server..."
    # Kill existing server
    kill $(cat "$LOGS_DIR/server.pid" 2>/dev/null) 2>/dev/null
    pkill -f "ld-musl.*python3.*server.py" 2>/dev/null
    sleep 1
    # Restart
    sh "$ANK_DIR/ankfs/opt/ank/start-server.sh" >/dev/null 2>&1 &
    echo "Server restarted"
}

# ============================================================
# ANK-CORE: info
# ============================================================
ank_core_info() {
    local os="$(getprop ro.build.version.release 2>/dev/null || echo "unknown")"
    local arch=$(uname -m 2>/dev/null || echo "unknown")
    local device=$(getprop ro.product.model 2>/dev/null || echo "unknown")
    local kernel=$(uname -r 2>/dev/null || echo "unknown")

    local cpu_model="unknown"
    if [ -f "/proc/cpuinfo" ]; then
        cpu_model=$(grep -m1 "Hardware" /proc/cpuinfo 2>/dev/null | cut -d: -f2 | sed 's/^ *//')
        [ -z "$cpu_model" ] && cpu_model=$(grep -m1 "model name" /proc/cpuinfo 2>/dev/null | cut -d: -f2 | sed 's/^ *//')
        [ -z "$cpu_model" ] && cpu_model=$(grep -m1 "Processor" /proc/cpuinfo 2>/dev/null | cut -d: -f2 | sed 's/^ *//')
    fi
    local cores=$(nproc 2>/dev/null || grep -c "^processor" /proc/cpuinfo 2>/dev/null || echo "?")

    local ram_total=0
    local ram_used=0
    if [ -f "/proc/meminfo" ]; then
        ram_total=$(grep "MemTotal:" /proc/meminfo 2>/dev/null | cut -d: -f2 | tr -cd '0-9')
        local ram_avail=$(grep "MemAvailable:" /proc/meminfo 2>/dev/null | cut -d: -f2 | tr -cd '0-9')
        if [ -n "$ram_avail" ]; then
            ram_used=$(( (ram_total - ram_avail) / 1024 ))
        else
            local ram_free=$(grep "MemFree:" /proc/meminfo 2>/dev/null | cut -d: -f2 | tr -cd '0-9')
            local ram_buf=$(grep "Buffers:" /proc/meminfo 2>/dev/null | cut -d: -f2 | tr -cd '0-9')
            local ram_cached=$(grep "Cached:" /proc/meminfo 2>/dev/null | cut -d: -f2 | tr -cd '0-9')
            ram_used=$(( (ram_total - ram_free - ram_buf - ram_cached) / 1024 ))
        fi
        ram_total=$((ram_total / 1024))
    fi
    local ram_pct=0
    [ "$ram_total" -gt 0 ] 2>/dev/null && ram_pct=$((ram_used * 100 / ram_total))

    local storage="unknown"
    local storage_line=$(df -h /data 2>/dev/null | tail -1)
    if [ -n "$storage_line" ]; then
        local s_used=$(echo "$storage_line" | tr -s ' ' | cut -d' ' -f3)
        local s_total=$(echo "$storage_line" | tr -s ' ' | cut -d' ' -f2)
        local s_pct=$(echo "$storage_line" | tr -s ' ' | cut -d' ' -f5)
        storage="$s_used / $s_total ($s_pct)"
    fi

    local uptime_str="unknown"
    if [ -f "/proc/uptime" ]; then
        local up_sec=$(cut -d. -f1 /proc/uptime 2>/dev/null)
        local up_days=$((up_sec / 86400))
        local up_hours=$(( (up_sec % 86400) / 3600 ))
        local up_mins=$(( (up_sec % 3600) / 60 ))
        uptime_str="${up_days}d ${up_hours}h ${up_mins}m"
    fi

    local running=0
    local total=0
    if [ -d "$CONTAINERS_DIR" ]; then
        total=$(ls -d "$CONTAINERS_DIR"/*/ 2>/dev/null | wc -l)
        for d in "$CONTAINERS_DIR"/*/; do
            [ -f "$d/config.json" ] || continue
            local st=$(grep -o '"status": *"[^"]*"' "$d/config.json" 2>/dev/null | cut -d'"' -f4)
            [ "$st" = "running" ] && running=$((running + 1))
        done
    fi

    local images=0
    [ -d "$IMAGES_DIR" ] && images=$(ls "$IMAGES_DIR"/*.tar.gz 2>/dev/null | wc -l)

    local mode=$(_json_val "$CONFIG_FILE" "mode")
    [ -z "$mode" ] && mode="isolated"

    local load="unknown"
    if [ -f "/proc/loadavg" ]; then
        load=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)
    fi

    echo ""
    echo " ──────────────────────────────────────────────"
    printf "  %-12s %s (%s)\n" "OS" "$os" "$arch"
    printf "  %-12s %s\n" "Device" "$device"
    printf "  %-12s %s\n" "Kernel" "$kernel"
    printf "  %-12s %s (%s cores)\n" "CPU" "$cpu_model" "$cores"
    printf "  %-12s %sM / %sM (%s%%)\n" "RAM" "$ram_used" "$ram_total" "$ram_pct"
    printf "  %-12s %s\n" "Storage" "$storage"
    printf "  %-12s %s\n" "Uptime" "$uptime_str"
    printf "  %-12s %s\n" "Load" "$load"
    echo ""
    printf "  %-12s %s / %s running\n" "Containers" "$running" "$total"
    printf "  %-12s %s available\n" "Images" "$images"
    printf "  %-12s %s\n" "Mode" "$mode"
    echo " ──────────────────────────────────────────────"

    local dash=$(_api_get "/api/system/dashboard")
    if [ -n "$dash" ]; then
        echo "$dash" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    nodes = d.get('nodes', [])
    if nodes:
        print(f'')
        print(f' ── Cluster ({len(nodes)} nodes) ───────────────')
        for n in nodes:
            status_icon = '+' if n.get('status') == 'online' else '-'
            alias = n.get('alias') or n.get('ip', '?')
            cpu = f\"{n.get('cpu_percent',0):.0f}%\" if n.get('status') == 'online' else '-'
            ram = f\"{n.get('mem_used_gb',0):.1f}/{n.get('mem_total_gb',0):.1f}GB\" if n.get('status') == 'online' else '-'
            cont = f\"{n.get('containers_running',0)}/{n.get('containers',0)}\" if n.get('status') == 'online' else '-'
            print(f'  [{status_icon}] {alias:15s} CPU:{cpu:5s} RAM:{ram:12s} Containers:{cont}')
        print(f' ──────────────────────────────────────────────')
except: pass
" 2>/dev/null
    fi
}

# ============================================================
# ANK-CORE: network
# ============================================================
ank_core_network() {
    local bridge=$(_json_val "$CONFIG_FILE" "bridge")
    local subnet=$(_json_val "$CONFIG_FILE" "subnet")
    local gateway=$(_json_val "$CONFIG_FILE" "gateway")
    local nat=$(_json_bool "$CONFIG_FILE" "nat")
    [ -z "$bridge" ] && bridge="ank0"
    [ -z "$subnet" ] && subnet="10.20.30.0"
    [ -z "$gateway" ] && gateway="10.20.30.1"
    [ -z "$nat" ] && nat="true"
    printf "Bridge:     %s\n" "$bridge"
    printf "Subnet:     %s/24\n" "$subnet"
    printf "Gateway:    %s\n" "$gateway"
    printf "NAT:        %s\n" "$nat"
}

# ============================================================
# ANK-CORE: clean
# ============================================================
ank_core_clean() {
    sh "$SCRIPTS_DIR/cleanup.sh"
}

# ============================================================
# ANK-CORE: logs
# ============================================================
ank_core_logs() {
    local logfile="$LOGS_DIR/server.log"
    if [ -f "$logfile" ]; then
        tail -30 "$logfile"
    else
        echo "No server logs"
    fi
}

# ============================================================
# MAN PAGES - ANK
# ============================================================
ank_man() {
    local cmd="$1"
    case "$cmd" in
        ps)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - LIST CONTAINERS (ps)"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank ps - List all containers across all nodes."
            echo ""
            echo "SYNOPSIS"
            echo "    ank ps"
            echo ""
            echo "DESCRIPTION"
            echo "    Displays a table of ALL containers from the local device AND"
            echo "    all connected remote nodes. Remote containers are tagged"
            echo "    with [node_alias] in the last column."
            echo ""
            echo "FIELDS"
            echo "    NAME       Container name (unique identifier)"
            echo "    STATUS     running | stopped | building | error"
            echo "    IP         Container IP on the ank0 bridge"
            echo "    IMAGE      Base image used (e.g. alpine-3.20, nginx-3.20)"
            echo "    PID        Main process ID (- if not running)"
            echo "    NODE       [alias] for remote containers, blank for local"
            echo ""
            echo "EXAMPLES"
            echo "    ank ps"
            echo "    NAME        STATUS      IP              IMAGE        PID    NODE"
            echo "    my-site     running     10.20.30.3      nginx-3.20   1234"
            echo "    dev-server  stopped     10.20.30.4      python-3.20  -"
            echo "    api         running     10.171.0.205    alpine-3.20  5678   [ank-app02]"
            echo ""
            echo "TIPS"
            echo "    - Use 'ank start <name>' to start a stopped container"
            echo "    - Use 'ank logs <name>' to view container logs"
            echo "    - Use 'ank inspect <name>' for detailed info"
            echo "    - Remote containers are managed automatically via the API"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        start)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - START CONTAINER"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank start - Start a stopped container (local or remote)."
            echo ""
            echo "SYNOPSIS"
            echo "    ank start <name>"
            echo ""
            echo "DESCRIPTION"
            echo "    Starts a previously created or stopped container. The"
            echo "    container's filesystem is mounted, network is configured,"
            echo "    and services (sshd, nginx, etc.) are launched."
            echo ""
            echo "    On start, ANK will:"
            echo "    1. Mount the overlay filesystem (merged dir)"
            echo "    2. Configure network (bridge, iptables, DNS)"
            echo "    3. Set root password from config.json"
            echo "    4. Start sshd on the configured port"
            echo "    5. Mark container as 'running' in config"
            echo ""
            echo "OPTIONS"
            echo "    <name>     Name of the container (from 'ank ps')"
            echo ""
            echo "EXAMPLES"
            echo "    ank start my-site"
            echo "    ank start dev-server"
            echo "    # Start multiple containers:"
            echo "    ank start web && ank start api && ank start db"
            echo ""
            echo "EXIT STATUS"
            echo "    0    Container started successfully"
            echo "    1    Container not found or already running"
            echo ""
            echo "SEE ALSO"
            echo "    ank stop, ank restart, ank ps"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        stop)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - STOP CONTAINER"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank stop - Stop a running container (local or remote)."
            echo ""
            echo "SYNOPSIS"
            echo "    ank stop <name>"
            echo ""
            echo "DESCRIPTION"
            echo "    Gracefully stops a running container. All processes inside"
            echo "    the container are terminated, SSH connections are closed,"
            echo "    and network rules are removed."
            echo ""
            echo "    On stop, ANK will:"
            echo "    1. Kill the container's main process tree (recursive)"
            echo "    2. Kill all sshd processes on the container's port"
            echo "    3. Remove iptables rules and network namespace"
            echo "    4. Unmount overlay filesystems"
            echo "    5. Mark container as 'stopped' in config"
            echo ""
            echo "OPTIONS"
            echo "    <name>     Name of the container"
            echo ""
            echo "EXAMPLES"
            echo "    ank stop my-site"
            echo "    # Stop all running containers:"
            echo "    for c in $(ank ps | awk '/running/{print $1}'); do ank stop $c; done"
            echo ""
            echo "EXIT STATUS"
            echo "    0    Container stopped successfully"
            echo "    1    Container not found or not running"
            echo ""
            echo "SEE ALSO"
            echo "    ank start, ank restart, ank rm"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        restart)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - RESTART CONTAINER"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank restart - Restart a container (local or remote, stop + start)."
            echo ""
            echo "SYNOPSIS"
            echo "    ank restart <name>"
            echo ""
            echo "DESCRIPTION"
            echo "    Convenience command that performs 'ank stop' followed by"
            echo "    'ank start' on the specified container. Useful when you"
            echo "    need to reload configuration or apply changes."
            echo ""
            echo "OPTIONS"
            echo "    <name>     Name of the container"
            echo ""
            echo "EXAMPLES"
            echo "    ank restart my-site"
            echo "    # After editing nginx config inside the container:"
            echo "    ank exec my-site nginx -s reload"
            echo ""
            echo "SEE ALSO"
            echo "    ank start, ank stop"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        rm)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - DELETE CONTAINER"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank rm - Delete a container and all its data (local or remote)."
            echo ""
            echo "SYNOPSIS"
            echo "    ank rm <name>"
            echo ""
            echo "DESCRIPTION"
            echo "    Permanently removes a container. If the container is"
            echo "    running, it is stopped first. All data in the container"
            echo "    (filesystem, config, logs) is deleted."
            echo ""
            echo "    WARNING: This action is irreversible!"
            echo ""
            echo "OPTIONS"
            echo "    <name>     Name of the container"
            echo ""
            echo "EXAMPLES"
            echo "    ank rm my-site"
            echo ""
            echo "    # Force delete (skip confirmation):"
            echo "    ank rm -f my-site"
            echo ""
            echo "EXIT STATUS"
            echo "    0    Container deleted successfully"
            echo "    1    Container not found"
            echo ""
            echo "SEE ALSO"
            echo "    ank stop, ank ps"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        logs)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - VIEW CONTAINER LOGS"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank logs - Display the last lines of container logs (local or remote)."
            echo ""
            echo "SYNOPSIS"
            echo "    ank logs <name>"
            echo ""
            echo "DESCRIPTION"
            echo "    Shows the last 50 lines from the container's log file."
            echo "    Logs include boot messages, service starts, and any"
            echo "    output from processes inside the container."
            echo ""
            echo "OPTIONS"
            echo "    <name>     Name of the container"
            echo ""
            echo "EXAMPLES"
            echo "    ank logs my-site"
            echo "    ank logs my-site | tail -20"
            echo ""
            echo "TIPS"
            echo "    - Use 'ank exec <name> <cmd>' to run commands interactively"
            echo "    - Logs are stored in /ank-engine/logs/<name>.log"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        exec)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - EXECUTE COMMAND IN CONTAINER"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank exec - Execute a command inside a running container."
            echo ""
            echo "SYNOPSIS"
            echo "    ank exec <name> <command> [args...]"
            echo ""
            echo "DESCRIPTION"
            echo "    Runs the specified command inside the container's"
            echo "    filesystem using chroot. The command runs as root."
            echo "    Output is displayed directly in the shell."
            echo ""
            echo "OPTIONS"
            echo "    <name>      Name of the container"
            echo "    <command>   Command to execute"
            echo "    [args...]   Optional arguments for the command"
            echo ""
            echo "EXAMPLES"
            echo "    ank exec my-site ls /var/www/html"
            echo "    ank exec my-site cat /etc/nginx/nginx.conf"
            echo "    ank exec my-site sh -c 'echo hello > /tmp/test'"
            echo "    ank exec my-site apk update"
            echo "    ank exec my-site ps aux"
            echo ""
            echo "TIPS"
            echo "    - Use 'ank ssh <name>' for an interactive shell"
            echo "    - Use quotes around complex commands: ank exec <name> 'cmd arg'"
            echo ""
            echo "SEE ALSO"
            echo "    ank ssh, ank start"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        inspect)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - INSPECT CONTAINER"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    inspect - Show detailed information about a container (local or remote)."
            echo ""
            echo "SYNOPSIS"
            echo "    ank inspect <name>"
            echo ""
            echo "DESCRIPTION"
            echo "    Displays comprehensive details including:"
            echo "    - Name, status, image, PID"
            echo "    - IP address and SSH port"
            echo "    - Creation date and last start time"
            echo "    - Resource limits (RAM, CPU)"
            echo "    - Network configuration"
            echo "    - Root password hint"
            echo ""
            echo "OPTIONS"
            echo "    <name>     Name of the container"
            echo ""
            echo "EXAMPLES"
            echo "    ank inspect my-site"
            echo ""
            echo "SEE ALSO"
            echo "    ank ps"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        images|list-images)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - LIST IMAGES"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank images - List all available container images across all nodes."
            echo ""
            echo "SYNOPSIS"
            echo "    ank images"
            echo ""
            echo "DESCRIPTION"
            echo "    Shows all container images available on this device."
            echo "    Images are the base filesystems used to create containers."
            echo "    Each image shows its name, size, and creation date."
            echo ""
            echo "EXAMPLES"
            echo "    ank images"
            echo "    NAME                SIZE       DATE"
            echo "    alpine-3.20         128 MB     2025-01-15"
            echo "    nginx-3.20          156 MB     2025-01-15"
            echo ""
            echo "SEE ALSO"
            echo "    ank pull, ank deploy"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        templates)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - LIST TEMPLATES"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank templates - List available deploy templates."
            echo ""
            echo "SYNOPSIS"
            echo "    ank templates"
            echo ""
            echo "DESCRIPTION"
            echo "    Shows all pre-configured deployment templates. Templates"
            echo "    are ready-to-use container configurations with specific"
            echo "    software pre-installed."
            echo ""
            echo "AVAILABLE TEMPLATES"
            echo "    alpine    Base Alpine 3.20 (minimal, ~128 MB)"
            echo "    python    Python 3.12 with pip"
            echo "    nginx     Nginx web server on port 8080"
            echo "    apache    Apache web server on port 9090"
            echo "    php       PHP 8.2 with CGI"
            echo "    node      Node.js 20 with npm"
            echo ""
            echo "EXAMPLES"
            echo "    ank templates"
            echo "    # Deploy a template:"
            echo "    ank deploy nginx my-site"
            echo ""
            echo "SEE ALSO"
            echo "    ank deploy, ank images"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        deploy)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - DEPLOY CONTAINER FROM TEMPLATE"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank deploy - Create and configure a container from a template."
            echo ""
            echo "SYNOPSIS"
            echo "    ank deploy <template> <name>"
            echo ""
            echo "DESCRIPTION"
            echo "    Deploys a new container based on a pre-configured template."
            echo "    The template determines the base image and packages installed."
            echo "    A new image is built automatically if it doesn't exist yet."
            echo ""
            echo "    The container is created with the default root password"
            echo "    configured in Settings (default: ank123)."
            echo ""
            echo "OPTIONS"
            echo "    <template>  Template ID (see 'ank templates' for list)"
            echo "    <name>      Name for the new container (must be unique)"
            echo ""
            echo "TEMPLATES"
            echo "    alpine    Base Alpine Linux (no extra packages)"
            echo "    python    Python 3.12 + pip"
            echo "    nginx     Nginx + curl (port 8080)"
            echo "    apache    Apache2 + curl (port 9090)"
            echo "    php       PHP 8.2 + mbstring + json + cgi"
            echo "    node      Node.js 20 + npm (port 3000)"
            echo ""
            echo "EXAMPLES"
            echo "    ank deploy nginx my-site"
            echo "    ank deploy python ml-server"
            echo "    ank deploy node api-backend"
            echo ""
            echo "    After deployment:"
            echo "    ank ps                           # Check status"
            echo "    ank ssh my-site                  # Connect via SSH"
            echo "    curl http://10.20.30.x:8080     # Test web server"
            echo ""
            echo "EXIT STATUS"
            echo "    0    Container deployed successfully"
            echo "    1    Invalid template or deployment failed"
            echo ""
            echo "SEE ALSO"
            echo "    ank templates, ank images, ank pull"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        pull)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - DOWNLOAD BASE IMAGE"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank pull - Download the base Alpine image."
            echo ""
            echo "SYNOPSIS"
            echo "    ank pull [version]"
            echo ""
            echo "DESCRIPTION"
            echo "    Downloads the Alpine Linux rootfs tarball for the specified"
            echo "    version. This is required before creating containers with"
            echo "    that version. Default version is 3.20."
            echo ""
            echo "OPTIONS"
            echo "    [version]  Alpine version (default: 3.20)"
            echo ""
            echo "EXAMPLES"
            echo "    ank pull          # Download Alpine 3.20"
            echo "    ank pull 3.19     # Download Alpine 3.19"
            echo ""
            echo "SEE ALSO"
            echo "    ank images, ank deploy"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        stack)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - MANAGE CONTAINER STACKS"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank stack - Manage container stacks with load balancing."
            echo ""
            echo "SYNOPSIS"
            echo "    ank stack <subcommand> [args...]"
            echo ""
            echo "DESCRIPTION"
            echo "    Stacks allow you to run multiple instances of the same"
            echo "    container template with automatic load balancing via nginx."
            echo "    Useful for scaling services across multiple replicas."
            echo ""
            echo "SUBCOMMANDS"
            echo "    ank stack ls                  List all stacks"
            echo "    ank stack create <name> [template] [count]"
            echo "                                 Create a new stack"
            echo "    ank stack scale <name> <count>"
            echo "                                 Scale stack to N replicas"
            echo "    ank stack rm <name>           Delete a stack"
            echo "    ank stack inspect <name>      Show stack details"
            echo ""
            echo "OPTIONS"
            echo "    <name>      Stack name (unique identifier)"
            echo "    <template>  Template to use (default: alpine)"
            echo "    <count>     Number of replicas (default: 2)"
            echo ""
            echo "EXAMPLES"
            echo "    ank stack create web-frontend nginx 3"
            echo "    ank stack ls"
            echo "    ank stack scale web-frontend 5"
            echo "    ank stack inspect web-frontend"
            echo "    ank stack rm web-frontend"
            echo ""
            echo "SEE ALSO"
            echo "    ank deploy, ank templates"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        backup)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - MANAGE BACKUPS"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank backup - Manage container backup routines."
            echo ""
            echo "SYNOPSIS"
            echo "    ank backup <subcommand> [args...]"
            echo ""
            echo "DESCRIPTION"
            echo "    Create and manage automated backups for your containers."
            echo "    Backups save container state and can be restored later."
            echo ""
            echo "SUBCOMMANDS"
            echo "    ank backup ls                 List all backup routines"
            echo "    ank backup inspect <id>       Show routine details"
            echo "    ank backup run <id>           Execute backup now"
            echo "    ank backup rm <id>            Delete backup routine"
            echo ""
            echo "EXAMPLES"
            echo "    ank backup ls"
            echo "    ank backup run 1"
            echo ""
            echo "SEE ALSO"
            echo "    ank ps"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        node)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - MANAGE REMOTE NODES"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank node - Manage remote ANK instances."
            echo ""
            echo "SYNOPSIS"
            echo "    ank node <subcommand> [args...]"
            echo ""
            echo "DESCRIPTION"
            echo "    Manage paired ANK nodes on other devices. This allows"
            echo "    you to control multiple ANK instances from one panel."
            echo ""
            echo "SUBCOMMANDS"
            echo "    ank node ls                   List all paired nodes"
            echo "    ank node inspect <id>         Show node details"
            echo "    ank node add                  Add remote node (interactive)"
            echo "    ank node rm <id>              Remove a node"
            echo ""
            echo "EXAMPLES"
            echo "    ank node ls"
            echo "    ank node add"
            echo "    ank node rm node-001"
            echo ""
            echo "SEE ALSO"
            echo "    ank ps"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        npad)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - TEXT EDITOR (npad)"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank npad - Vi-like text editor for .ankfile files."
            echo ""
            echo "SYNOPSIS"
            echo "    ank npad <filename>"
            echo ""
            echo "DESCRIPTION"
            echo "    A lightweight vi-like editor for creating and editing"
            echo "    .ankfile files. Files are saved in /ank-engine/."
            echo "    .ankfile files are validated on save for syntax errors."
            echo ""
            echo "COMMAND MODE (default)"
            echo "    :w              Save file"
            echo "    :wq             Save and quit"
            echo "    :q              Quit (without saving)"
            echo "    :q!             Quit without saving (discard changes)"
            echo "    gg              Go to first line"
            echo "    G               Go to last line"
            echo "    j               Move down one line"
            echo "    k               Move up one line"
            echo "    dd              Delete current line"
            echo "    yy              Yank (copy) current line"
            echo "    p               Paste yanked line"
            echo "    x               Delete character under cursor"
            echo "    u               Undo last change"
            echo "    i               Enter insert mode"
            echo "    o               Insert new line below"
            echo "    O               Insert new line above"
            echo ""
            echo "INSERT MODE"
            echo "    Type text normally (each line is a new line)"
            echo "    Press Ctrl+C to return to command mode"
            echo ""
            echo "ANKFILE SYNTAX"
            echo "    FROM <image>           Base image"
            echo "    PASSWD <password>      Set root password"
            echo "    RUN <command>          Execute command"
            echo "    EXPOSE <port>          Expose port"
            echo "    COPY <src> <dst>       Copy file"
            echo "    CMD <command>          Default command on start"
            echo ""
            echo "EXAMPLES"
            echo "    ank npad my-app.ankfile"
            echo "    # Then type your Dockerfile-like instructions"
            echo ""
            echo "SEE ALSO"
            echo "    ank build"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        ssh)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - SSH INTO CONTAINER"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank ssh - Open an SSH session to a container."
            echo ""
            echo "SYNOPSIS"
            echo "    ank ssh <name>"
            echo ""
            echo "DESCRIPTION"
            echo "    Connects to a running container via SSH. You will be"
            echo "    logged in as root. The password is the one set during"
            echo "    container creation (default: ank123)."
            echo ""
            echo "OPTIONS"
            echo "    <name>     Name of the container"
            echo ""
            echo "EXAMPLES"
            echo "    ank ssh my-site"
            echo "    # Enter password (default: ank123)"
            echo ""
            echo "TIPS"
            echo "    - Use 'ank exec <name> <cmd>' for single commands"
            echo "    - The SSH port is shown in 'ank inspect <name>'"
            echo ""
            echo "SEE ALSO"
            echo "    ank exec, ank inspect"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        build)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - BUILD IMAGE FROM ANKFILE"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank build - Build an image from an .ankfile."
            echo ""
            echo "SYNOPSIS"
            echo "    ank build <ankfile>"
            echo ""
            echo "DESCRIPTION"
            echo "    Builds a container image from an .ankfile (similar to"
            echo "    Dockerfile). The image can then be used to create"
            echo "    containers."
            echo ""
            echo "OPTIONS"
            echo "    <ankfile>   Path to the .ankfile"
            echo ""
            echo "EXAMPLES"
            echo "    ank build my-app.ankfile"
            echo ""
            echo "SEE ALSO"
            echo "    ank npad, ank images"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        ls)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - LIST FILES"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank ls - List files in the working directory."
            echo ""
            echo "SYNOPSIS"
            echo "    ank ls [path]"
            echo ""
            echo "DESCRIPTION"
            echo "    Lists files and directories. Default path is"
            echo "    /ank-engine/ (the working directory)."
            echo ""
            echo "OPTIONS"
            echo "    [path]     Directory to list (default: /ank-engine/)"
            echo ""
            echo "EXAMPLES"
            echo "    ank ls"
            echo "    ank ls /tmp"
            echo ""
            echo "SEE ALSO"
            echo "    ank copy, ank ren, ank erase"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        copy|ren|erase)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - FILE OPERATIONS"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank copy - Copy files"
            echo "    ank ren  - Rename/move files"
            echo "    ank erase - Delete files"
            echo ""
            echo "SYNOPSIS"
            echo "    ank copy <source> <destination>"
            echo "    ank ren <old_name> <new_name>"
            echo "    ank erase <file>"
            echo ""
            echo "DESCRIPTION"
            echo "    File operations within /ank-engine/."
            echo ""
            echo "EXAMPLES"
            echo "    ank copy myfile.txt backup.txt"
            echo "    ank ren old.txt new.txt"
            echo "    ank erase tempfile.txt"
            echo ""
            echo "SEE ALSO"
            echo "    ank ls, ank npad"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        ip|ifconfig|route|netstat|ss|ping|traceroute|nslookup)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - NETWORK DIAGNOSTIC TOOLS"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    Network diagnostic commands."
            echo ""
            echo "SYNOPSIS"
            echo "    ank ip [args]          Show IP addresses"
            echo "    ank ifconfig [args]    Show network interfaces"
            echo "    ank route [args]       Show routing table"
            echo "    ank netstat [args]     Show network statistics"
            echo "    ank ss [args]          Show socket statistics"
            echo "    ank ping <host>        Ping a host"
            echo "    ank traceroute <host>  Trace route to host"
            echo "    ank nslookup <host>    DNS lookup"
            echo ""
            echo "DESCRIPTION"
            echo "    These are wrappers around standard network tools."
            echo "    Use them for diagnosing container networking issues."
            echo ""
            echo "EXAMPLES"
            echo "    ank ip addr"
            echo "    ank ss -tlnp          # List listening ports"
            echo "    ank ping 8.8.8.8"
            echo "    ank nslookup google.com"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        history)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - COMMAND HISTORY"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank history - Show command history."
            echo ""
            echo "SYNOPSIS"
            echo "    ank history"
            echo ""
            echo "DESCRIPTION"
            echo "    Displays all previously executed commands with indices."
            echo "    Re-execute a command with !<number>."
            echo ""
            echo "EXAMPLES"
            echo "    ank history"
            echo "    # Re-execute command 5:"
            echo "    !5"
            echo ""
            echo "SEE ALSO"
            echo "    ank help"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        help|--help|-h)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - HELP"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank help - Show available commands."
            echo ""
            echo "SYNOPSIS"
            echo "    ank help"
            echo ""
            echo "DESCRIPTION"
            echo "    Lists all available commands with brief descriptions."
            echo "    Use 'ank --man <command>' for detailed documentation."
            echo ""
            echo "AVAILABLE COMMANDS"
            echo "    ps                  List all containers"
            echo "    start <name>        Start a container"
            echo "    stop <name>         Stop a container"
            echo "    restart <name>      Restart a container"
            echo "    rm <name>           Delete a container"
            echo "    logs <name>         View container logs"
            echo "    exec <name> <cmd>   Execute command in container"
            echo "    ssh <name>          SSH into a container"
            echo "    inspect <name>      Show container details"
            echo "    images              List available images"
            echo "    templates           List deploy templates"
            echo "    deploy <tpl> <name> Deploy container from template"
            echo "    pull [version]      Download base Alpine image"
            echo "    build <ankfile>     Build image from .ankfile"
            echo "    stack <sub>         Manage container stacks"
            echo "    backup <sub>        Manage backup routines"
            echo "    node <sub>          Manage remote ANK nodes"
            echo "    npad <file>         Text editor"
            echo "    ls [path]           List files"
            echo "    copy <src> <dst>    Copy files"
            echo "    ren <old> <new>     Rename files"
            echo "    erase <file>        Delete files"
            echo "    history             Command history"
            echo "    ip/ifconfig/route   Network tools"
            echo "    exit                Exit ANK shell"
            echo ""
            echo "DETAILED HELP"
            echo "    Use 'ank --man <command>' for full documentation."
            echo ""
            echo "EXAMPLES"
            echo "    ank --man deploy    # Full manual for deploy"
            echo "    ank --man ssh       # Full manual for SSH"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        --version|-v)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK - VERSION"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank --version - Show ANK version and system info."
            echo ""
            echo "SYNOPSIS"
            echo "    ank --version"
            echo ""
            echo "DESCRIPTION"
            echo "    Displays the ANK engine version, container statistics,"
            echo "    running mode, and server port."
            echo ""
            echo "EXAMPLES"
            echo "    ank --version"
            echo "    ANK Engine v2.0.0"
            echo "    Containers: 3 running, 1 stopped, 4 total"
            echo "    Mode:       compat"
            echo "    Port:       8001"
            echo ""
            echo "SEE ALSO"
            echo "    ank-core info"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        *)
            echo "No man page for '$cmd'."
            echo "Type 'ank help' for available commands."
            echo "Type 'ank --man <command>' for detailed documentation."
            ;;
    esac
}

# ============================================================
# MAN PAGES - ANK-CORE
# ============================================================
ank_core_man() {
    local cmd="$1"
    case "$cmd" in
        status)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK-CORE - SHOW SYSTEM STATUS"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank-core status - Display ANK engine status and statistics."
            echo ""
            echo "SYNOPSIS"
            echo "    ank-core status"
            echo ""
            echo "DESCRIPTION"
            echo "    Shows a comprehensive overview of the ANK engine including:"
            echo "    - Engine version"
            echo "    - Container counts (running / stopped / total)"
            echo "    - Operating mode (compat or isolated)"
            echo "    - Server port"
            echo ""
            echo "OUTPUT"
            echo "    ANK Engine v2.0.0"
            echo "    Containers: 3 running, 1 stopped, 4 total"
            echo "    Mode:       compat"
            echo "    Port:       8001"
            echo ""
            echo "MODES"
            echo "    compat      Traditional mode (full compatibility)"
            echo "    isolated    Enhanced isolation (uses PID namespaces)"
            echo ""
            echo "EXAMPLES"
            echo "    ank-core status"
            echo ""
            echo "SEE ALSO"
            echo "    ank-core info, ank ps"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        restart)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK-CORE - RESTART SERVER"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank-core restart - Restart the ANK server process."
            echo ""
            echo "SYNOPSIS"
            echo "    ank-core restart"
            echo ""
            echo "DESCRIPTION"
            echo "    Stops the ANK server and starts it again. Running containers"
            echo "    remain alive (they are not stopped)."
            echo ""
            echo "    Use this command when:"
            echo "    - You changed server configuration"
            echo "    - The web panel is not responding"
            echo "    - After installing/updating the ANK module"
            echo ""
            echo "    The restart process:"
            echo "    1. Kills the existing server process"
            echo "    2. Waits for cleanup"
            echo "    3. Starts a fresh server instance"
            echo ""
            echo "EXAMPLES"
            echo "    ank-core restart"
            echo ""
            echo "WARNING"
            echo "    Running containers stay alive but the web panel will be"
            echo "    briefly unavailable during restart."
            echo ""
            echo "SEE ALSO"
            echo "    ank-core status, ank-core logs"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        info)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK-CORE - DEVICE INFORMATION"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank-core info - Show detailed device information."
            echo ""
            echo "SYNOPSIS"
            echo "    ank-core info"
            echo ""
            echo "DESCRIPTION"
            echo "    Displays comprehensive system information about the host"
            echo "    device. This includes:"
            echo ""
            echo "    DEVICE INFO"
            echo "    - OS version (Android version)"
            echo "    - Device model"
            echo "    - Kernel version"
            echo "    - CPU model and core count"
            echo "    - RAM usage (used / total / percentage)"
            echo "    - Storage usage on /data partition"
            echo "    - System uptime"
            echo "    - CPU load average"
            echo ""
            echo "    ANK INFO"
            echo "    - Container count (running / total)"
            echo "    - Available images"
            echo "    - Operating mode"
            echo ""
            echo "OUTPUT"
            echo "    ──────────────────────────────────────────────"
            echo "      OS           14 (arm64)"
            echo "      Device       SM-G991B"
            echo "      Kernel       5.10.101-android13-..."
            echo "      CPU          Qualcomm Snapdragon 888 (8 cores)"
            echo "      RAM          1240M / 7800M (16%)"
            echo "      Storage      32G / 128G (25%)"
            echo "      Uptime       3d 12h 45m"
            echo "      Load         0.52 0.48 0.45"
            echo ""
            echo "      Containers   3 / 4 running"
            echo "      Images       5 available"
            echo "      Mode         compat"
            echo "    ──────────────────────────────────────────────"
            echo ""
            echo "EXAMPLES"
            echo "    ank-core info"
            echo ""
            echo "SEE ALSO"
            echo "    ank-core status, ank-core network"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        network)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK-CORE - NETWORK CONFIGURATION"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank-core network - Show ANK network configuration."
            echo ""
            echo "SYNOPSIS"
            echo "    ank-core network"
            echo ""
            echo "DESCRIPTION"
            echo "    Displays the virtual network configuration used by containers."
            echo "    ANK creates an isolated bridge network for containers."
            echo ""
            echo "FIELDS"
            echo "    Bridge     Virtual bridge interface (default: ank0)"
            echo "    Subnet     Container subnet (default: 10.20.30.0/24)"
            echo "    Gateway    Gateway IP for containers (default: 10.20.30.1)"
            echo "    NAT        Network address translation (true/false)"
            echo ""
            echo "OUTPUT"
            echo "    Bridge:     ank0"
            echo "    Subnet:     10.20.30.0/24"
            echo "    Gateway:    10.20.30.1"
            echo "    NAT:        true"
            echo ""
            echo "NETWORK ARCHITECTURE"
            echo "    Containers get IPs in the 10.20.30.x range."
            echo "    The bridge (ank0) connects containers to the host."
            echo "    NAT allows containers to access the internet."
            echo "    Port mapping (npad) enables host access to containers."
            echo ""
            echo "EXAMPLES"
            echo "    ank-core network"
            echo ""
            echo "SEE ALSO"
            echo "    ank-core info, ank-core clean"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        clean)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK-CORE - CLEANUP RESOURCES"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank-core clean - Clean up orphaned resources."
            echo ""
            echo "SYNOPSIS"
            echo "    ank-core clean"
            echo ""
            echo "DESCRIPTION"
            echo "    Removes orphaned resources left behind after crashes or"
            echo "    improper shutdowns. This includes:"
            echo "    - Orphaned network namespaces"
            echo "    - Leftover veth interfaces"
            echo "    - Unused cgroup hierarchies"
            echo "    - Stale PID files"
            echo "    - Temporary files"
            echo ""
            echo "    Safe to run at any time. Only removes resources not"
            echo "    currently in use by running containers."
            echo ""
            echo "WHEN TO USE"
            echo "    - After a device crash or forced restart"
            echo "    - If containers show unexpected network errors"
            echo "    - If disk usage seems higher than expected"
            echo "    - As periodic maintenance"
            echo ""
            echo "EXAMPLES"
            echo "    ank-core clean"
            echo ""
            echo "SEE ALSO"
            echo "    ank-core network, ank-core status"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        logs)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK-CORE - SERVER LOGS"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank-core logs - Show ANK server logs."
            echo ""
            echo "SYNOPSIS"
            echo "    ank-core logs"
            echo ""
            echo "DESCRIPTION"
            echo "    Displays the last 30 lines of the ANK server log file."
            echo "    The log contains startup messages, API requests, errors,"
            echo "    and other server events."
            echo ""
            echo "LOG LOCATION"
            echo "    /data/ank/logs/server.log"
            echo ""
            echo "TIPS"
            echo "    - Use 'ank-core logs' to check for startup errors"
            echo "    - Look for 'ERROR' or 'WARN' messages"
            echo "    - Logs rotate automatically (oldest entries removed)"
            echo ""
            echo "EXAMPLES"
            echo "    ank-core logs"
            echo "    ank-core logs | grep ERROR"
            echo ""
            echo "SEE ALSO"
            echo "    ank logs <container>, ank-core status"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        shell)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK-CORE - HOST SHELL"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank-core shell - Open a full host shell."
            echo ""
            echo "SYNOPSIS"
            echo "    ank-core shell"
            echo ""
            echo "DESCRIPTION"
            echo "    Opens an interactive shell with root access to the Android"
            echo "    host. Commands run directly on the host system."
            echo ""
            echo "WARNING"
            echo "    This gives you ROOT access to the device."
            echo "    Be very careful with what commands you run."
            echo "    Mistakes can brick your device."
            echo ""
            echo "USE CASES"
            echo "    - Debugging ANK internals"
            echo "    - Inspecting host network configuration"
            echo "    - Checking system-level processes"
            echo "    - Manual cleanup of stuck resources"
            echo ""
            echo "EXAMPLES"
            echo "    ank-core shell"
            echo "    # You are now in a root shell on the host"
            echo "    ls /data/ank/"
            echo "    ps aux | grep ank"
            echo ""
            echo "SEE ALSO"
            echo "    ank-core logs, ank-core clean"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        help|--help|-h)
            echo "═══════════════════════════════════════════════════════════════"
            echo "  ANK-CORE - HELP"
            echo "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "NAME"
            echo "    ank-core help - Show available admin commands."
            echo ""
            echo "SYNOPSIS"
            echo "    ank-core --help"
            echo ""
            echo "DESCRIPTION"
            echo "    Lists all available ank-core commands with brief"
            echo "    descriptions. Use 'ank-core --man <command>' for"
            echo "    detailed documentation."
            echo ""
            echo "AVAILABLE COMMANDS"
            echo "    ank-core status            Show system status"
            echo "    ank-core restart           Restart ANK server"
            echo "    ank-core info              Show device info"
            echo "    ank-core network           Show network config"
            echo "    ank-core clean             Cleanup orphaned resources"
            echo "    ank-core logs              Show server logs"
            echo "    ank-core shell             Full host shell access"
            echo "    ank-core --help            Show this help"
            echo "    ank-core --man <command>   Detailed manual"
            echo ""
            echo "DETAILED HELP"
            echo "    Use 'ank-core --man <command>' for full documentation."
            echo ""
            echo "EXAMPLES"
            echo "    ank-core --man status     # Full manual for status"
            echo "    ank-core --man info       # Full manual for info"
            echo "═══════════════════════════════════════════════════════════════"
            ;;
        *)
            echo "No man page for '$cmd'."
            echo "Type 'ank-core --help' for available commands."
            echo "Type 'ank-core --man <command>' for detailed documentation."
            ;;
    esac
}

# ============================================================
# MAIN LOOP
# ============================================================
cd "$ENGINE_DIR" 2>/dev/null || mkdir -p "$ENGINE_DIR" && cd "$ENGINE_DIR"
mkdir -p "$ANK_TMP" 2>/dev/null
_history_load

while true; do
    printf "(root@ank-shell) ~ [/ank-engine] > " >&2
    read -r input 2>/dev/null

    # Skip empty input
    [ -z "$input" ] && continue

    # Save to history
    _history_save "$input"

    # Handle !{NUM} - re-execute history command
    case "$input" in
        \!*)
            local hist_num="${input#!}"
            if [ "$hist_num" -ge 1 ] 2>/dev/null; then
                local hist_cmd=$(_history_get "$hist_num")
                if [ -n "$hist_cmd" ]; then
                    echo "  $hist_cmd" >&2
                    input="$hist_cmd"
                else
                    echo "  !${hist_num}: event not found" >&2
                    continue
                fi
            else
                echo "  !${hist_num}: event not found" >&2
                continue
            fi
            ;;
    esac

    # Parse first word
    cmd1=$(echo "$input" | cut -d' ' -f1)
    rest=$(echo "$input" | cut -d' ' -f2-)

    case "$cmd1" in
        exit)
            break
            ;;
        ank)
            subcmd=$(echo "$rest" | cut -d' ' -f1)
            args=$(echo "$rest" | cut -d' ' -f2-)

            case "$subcmd" in
                help|-h|--help)
                    ank_help
                    ;;
                --version|-v)
                    ank_core_info
                    ;;
                history)
                    ank_history
                    ;;
                --man)
                    local_cmd=$(echo "$args" | cut -d' ' -f1)
                    ank_man "$local_cmd"
                    ;;
                ps)
                    ank_ps
                    ;;
                start)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    ank_start "$arg1"
                    ;;
                stop)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    ank_stop "$arg1"
                    ;;
                restart)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    ank_restart "$arg1"
                    ;;
                rm)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    ank_rm "$arg1"
                    ;;
                logs)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    ank_logs "$arg1"
                    ;;
                exec)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    arg2=$(echo "$args" | cut -d' ' -f2-)
                    ank_exec "$arg1" $arg2
                    ;;
                inspect)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    ank_inspect "$arg1"
                    ;;
                images|list-images)
                    ank_images
                    ;;
                templates)
                    ank_templates
                    ;;
                deploy)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    arg2=$(echo "$args" | cut -d' ' -f2)
                    ank_deploy "$arg1" "$arg2"
                    ;;
                pull)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    ank_pull "$arg1"
                    ;;
                build)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    arg2=$(echo "$args" | cut -d' ' -f2)
                    ank_build "$arg1" "$arg2"
                    ;;
                npad)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    ank_npad "$arg1"
                    ;;
                ls)
                    ank_ls
                    ;;
                copy)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    arg2=$(echo "$args" | cut -d' ' -f2)
                    ank_copy "$arg1" "$arg2"
                    ;;
                ren)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    arg2=$(echo "$args" | cut -d' ' -f2)
                    ank_ren "$arg1" "$arg2"
                    ;;
                erase)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    ank_erase "$arg1"
                    ;;
                stack)
                    stack_subcmd=$(echo "$args" | cut -d' ' -f1)
                    stack_args=$(echo "$args" | cut -d' ' -f2-)
                    case "$stack_subcmd" in
                        ls|list)
                            ank_stack_ls
                            ;;
                        inspect)
                            arg1=$(echo "$stack_args" | cut -d' ' -f1)
                            ank_stack_inspect "$arg1"
                            ;;
                        create)
                            arg1=$(echo "$stack_args" | cut -d' ' -f1)
                            arg2=$(echo "$stack_args" | cut -d' ' -f2)
                            arg3=$(echo "$stack_args" | cut -d' ' -f3)
                            ank_stack_create "$arg1" "$arg2" "$arg3"
                            ;;
                        scale)
                            arg1=$(echo "$stack_args" | cut -d' ' -f1)
                            arg2=$(echo "$stack_args" | cut -d' ' -f2)
                            ank_stack_scale "$arg1" "$arg2"
                            ;;
                        rm|delete)
                            arg1=$(echo "$stack_args" | cut -d' ' -f1)
                            ank_stack_rm "$arg1"
                            ;;
                        *)
                            echo "Usage: ank stack {ls|inspect|create|scale|rm}"
                            ;;
                    esac
                    ;;
                backup)
                    backup_subcmd=$(echo "$args" | cut -d' ' -f1)
                    backup_args=$(echo "$args" | cut -d' ' -f2-)
                    case "$backup_subcmd" in
                        ls|list)
                            ank_backup_ls
                            ;;
                        inspect)
                            arg1=$(echo "$backup_args" | cut -d' ' -f1)
                            ank_backup_inspect "$arg1"
                            ;;
                        run|execute)
                            arg1=$(echo "$backup_args" | cut -d' ' -f1)
                            ank_backup_run "$arg1"
                            ;;
                        rm|delete)
                            arg1=$(echo "$backup_args" | cut -d' ' -f1)
                            ank_backup_rm "$arg1"
                            ;;
                        *)
                            echo "Usage: ank backup {ls|inspect|run|rm}"
                            ;;
                    esac
                    ;;
                node)
                    node_subcmd=$(echo "$args" | cut -d' ' -f1)
                    node_args=$(echo "$args" | cut -d' ' -f2-)
                    case "$node_subcmd" in
                        ls|list)
                            ank_node_ls
                            ;;
                        inspect)
                            arg1=$(echo "$node_args" | cut -d' ' -f1)
                            ank_node_inspect "$arg1"
                            ;;
                        add)
                            ank_node_add
                            ;;
                        rm|delete)
                            arg1=$(echo "$node_args" | cut -d' ' -f1)
                            ank_node_rm "$arg1"
                            ;;
                        *)
                            echo "Usage: ank node {ls|inspect|add|rm}"
                            ;;
                    esac
                    ;;
                ping)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    arg2=$(echo "$args" | cut -d' ' -f2)
                    ank_ping "$arg1" "$arg2"
                    ;;
                traceroute)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    ank_traceroute "$arg1"
                    ;;
                nslookup)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    ank_nslookup "$arg1"
                    ;;
                ip)
                    ank_ip $args
                    ;;
                ifconfig)
                    ank_ifconfig $args
                    ;;
                route)
                    ank_route $args
                    ;;
                netstat)
                    ank_netstat $args
                    ;;
                ss)
                    ank_ss $args
                    ;;
                *)
                    echo "Unknown ank command: $subcmd"
                    echo "Type 'ank help' for available commands."
                    ;;
            esac
            ;;
        ank-core)
            subcmd=$(echo "$rest" | cut -d' ' -f1)
            args=$(echo "$rest" | cut -d' ' -f2-)

            case "$subcmd" in
                help|-h|--help)
                    echo "ANK-Core - Android Konteiner System Management"
                    echo ""
                    echo "Usage: ank-core <command>"
                    echo ""
                    echo "Commands:"
                    echo "  status       Show system status"
                    echo "  restart      Restart ANK server"
                    echo "  info         Show device info"
                    echo "  network      Show network config"
                    echo "  clean        Cleanup orphaned resources"
                    echo "  logs         Show server logs"
                    echo "  shell        Open host shell"
                    echo "  --man <cmd>  Show detailed help"
                    ;;
                --man)
                    local_cmd=$(echo "$args" | cut -d' ' -f1)
                    ank_core_man "$local_cmd"
                    ;;
                status)
                    ank_core_status
                    ;;
                restart)
                    ank_core_restart
                    ;;
                info)
                    ank_core_info
                    ;;
                network)
                    ank_core_network
                    ;;
                clean)
                    ank_core_clean
                    ;;
                logs)
                    ank_core_logs
                    ;;
                *)
                    echo "Unknown ank-core command: $subcmd"
                    echo "Type 'ank-core --help' for available commands."
                    ;;
            esac
            ;;
        *)
            echo "Unknown command: $cmd1"
            echo "Type 'ank help' for available commands."
            ;;
    esac
done

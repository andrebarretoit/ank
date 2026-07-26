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

# Server port
ANK_PORT=8001
if [ -f "$LOGS_DIR/port.conf" ]; then
    ANK_PORT=$(cat "$LOGS_DIR/port.conf" 2>/dev/null)
fi

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
ANK - Android Konteiner CLI

Container commands:
  ank ps                    List all containers
  ank start <name>          Start a container
  ank stop <name>           Stop a container
  ank restart <name>        Restart a container
  ank rm <name>             Delete a container
  ank logs <name>           View container logs
  ank exec <name> <cmd>     Execute command in container
  ank inspect <name>        Show container details

Image commands:
  ank images                List available images
  ank list-images           List available images (alias)
  ank templates             List deploy templates
  ank deploy <tpl> <name>   Deploy a template
  ank pull <version>        Download base image

Stack commands:
  ank stack ls              List all stacks
  ank stack inspect <name>  Show stack details
  ank stack create <name> [tpl] [count]  Create a stack
  ank stack scale <name> <count>         Scale stack
  ank stack rm <name>       Delete a stack

Backup commands:
  ank backup ls             List backup routines
  ank backup inspect <id>   Show routine details
  ank backup run <id>       Execute backup
  ank backup rm <id>        Delete backup routine

Node commands:
  ank node ls               List remote nodes
  ank node inspect <id>     Show node details
  ank node add              Add remote node (interactive)
  ank node rm <id>          Remove a node

Editor:
  ank npad <file>           Open text editor (for Ankfiles)

System:
  ank help                  Show this help
  ank --man <cmd>           Show detailed help for a command
  ank exit                  Exit ANK shell

ANK-Core commands:
  ank-core status           Show system status
  ank-core restart          Restart ANK server
  ank-core info             Show device info
  ank-core network          Show network config
  ank-core clean            Cleanup orphaned resources
  ank-core logs             Show server logs
  ank-core shell            Open host shell
  ank-core --man <cmd>      Show detailed help
EOF
}

# ============================================================
# ANK: exit
# ============================================================
ank_exit() {
    exit 0
}

# ============================================================
# ANK: ps
# ============================================================
ank_ps() {
    _print_row "NAME" "STATUS" "IP" "IMAGE" "PID"
    printf "%s\n" "----------------------------------------------------------------------"
    local found=0
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
    sh "$SCRIPTS_DIR/container.sh" start "$name"
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
    sh "$SCRIPTS_DIR/container.sh" stop "$name"
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
    sh "$SCRIPTS_DIR/container.sh" stop "$name" 2>/dev/null
    sleep 1
    sh "$SCRIPTS_DIR/container.sh" start "$name"
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
    sh "$SCRIPTS_DIR/container.sh" delete "$name"
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
    local logpath="$LOGS_DIR/${name}.log"
    if [ -f "$logpath" ]; then
        tail -50 "$logpath"
    else
        echo "No logs for '$name'"
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
    local config="$CONTAINERS_DIR/$name/config.json"
    if [ ! -f "$config" ]; then
        echo "Container '$name' not found"
        return 1
    fi
    local name=$(_json_val "$config" "name")
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
    printf "Name:       %s\n" "$name"
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
}

# ============================================================
# ANK: images / list-images
# ============================================================
ank_images() {
    if [ ! -d "$IMAGES_DIR" ]; then
        echo "No images found."
        return
    fi
    local found=0
    for img in $(ls "$IMAGES_DIR" 2>/dev/null); do
        [ -d "$IMAGES_DIR/$img" ] || continue
        local base="$IMAGES_DIR/$img"
        local has_sh="no"
        [ -e "$base/bin/sh" ] && has_sh="yes"
        printf "%-25s bin/sh: %s\n" "$img" "$has_sh"
        found=1
    done
    [ "$found" -eq 0 ] && echo "No images found."
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
    sh "$SCRIPTS_DIR/container.sh" create "$name" "$image" "" "" "$pkgs"
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
    if [ ! -d "$NODES_DIR" ]; then
        echo "No nodes found."
        return
    fi
    printf "%-15s %-20s %-16s %-10s %s\n" "ID" "ALIAS" "IP" "PORT" "STATUS"
    printf "%s\n" "--------------------------------------------------------------------"
    local found=0
    for fp in "$NODES_DIR"/*.json; do
        [ -f "$fp" ] || continue
        local id=$(_json_val "$fp" "id")
        local alias=$(_json_val "$fp" "alias")
        local ip=$(_json_val "$fp" "ip")
        local port=$(_json_num "$fp" "port")
        local status=$(_json_val "$fp" "status")
        [ -z "$alias" ] && alias="$ip"
        [ -z "$port" ] && port="8001"
        [ -z "$status" ] && status="?"
        printf "%-15s %-20s %-16s %-10s %s\n" "$id" "$alias" "$ip" "$port" "$status"
        found=1
    done
    [ "$found" -eq 0 ] && echo "No nodes found."
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
    cat "$fp"
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
# ANK: npad (text editor with Ankfile validation)
# ============================================================
ank_npad() {
    local file="$1"
    if [ -z "$file" ]; then
        echo "Usage: ank npad <filename>"
        return 1
    fi

    local filepath="$ENGINE_DIR/$file"
    local tmpfile="/tmp/ank_npad_$$.tmp"

    # Copy existing content
    if [ -f "$filepath" ]; then
        cp "$filepath" "$tmpfile"
    else
        : > "$tmpfile"
    fi

    while true; do
        echo "=== ank npad: $file ==="
        if [ -s "$tmpfile" ]; then
            local linenum=0
            while IFS= read -r line; do
                linenum=$((linenum + 1))
                printf "%3d | %s\n" "$linenum" "$line"
            done < "$tmpfile"
        else
            echo "  (empty file)"
        fi
        echo ""
        echo "[a]dd  [d]elete  [e]dit  [s]ave  [q]uit  [:w]rite  [:q]uit"
        printf "> "
        read -r cmd

        case "$cmd" in
            a|add)
                printf "Enter content (or empty to cancel): "
                read -r line
                if [ -n "$line" ]; then
                    echo "$line" >> "$tmpfile"
                fi
                ;;
            d|delete)
                printf "Line number: "
                read -r linenum
                if [ -n "$linenum" ]; then
                    sed -i "${linenum}d" "$tmpfile" 2>/dev/null
                fi
                ;;
            e|edit)
                printf "Line number: "
                read -r linenum
                if [ -n "$linenum" ]; then
                    printf "New content: "
                    read -r line
                    sed -i "${linenum}s/.*/$line/" "$tmpfile" 2>/dev/null
                fi
                ;;
            s|save|:w)
                if _validate_ankfile "$tmpfile"; then
                    cp "$tmpfile" "$filepath"
                    echo "Saved: $filepath"
                fi
                ;;
            q|quit|:q|exit)
                rm -f "$tmpfile"
                return 0
                ;;
            :wq)
                if _validate_ankfile "$tmpfile"; then
                    cp "$tmpfile" "$filepath"
                    echo "Saved: $filepath"
                    rm -f "$tmpfile"
                    return 0
                fi
                ;;
            *)
                echo "Unknown command: $cmd"
                ;;
        esac
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
    local total=0 running=0 stopped=0
    for cfg in $(_list_containers); do
        total=$((total + 1))
        local status=$(_json_val "$cfg" "status")
        if [ "$status" = "running" ]; then
            running=$((running + 1))
        else
            stopped=$((stopped + 1))
        fi
    done

    local version=$(_json_val "$CONFIG_FILE" "version")
    local mode="compat"
    [ -f "$ANK_DIR/mode" ] && mode=$(cat "$ANK_DIR/mode" 2>/dev/null || echo "compat")

    printf "ANK Engine v%s\n" "$version"
    printf "Containers: %s running, %s stopped, %s total\n" "$running" "$stopped" "$total"
    printf "Mode:       %s\n" "$mode"
    printf "Port:       %s\n" "$ANK_PORT"
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
    local device=$(getprop ro.product.model 2>/dev/null || echo "unknown")
    local kernel=$(uname -r 2>/dev/null || echo "unknown")
    local mem_total=0
    if [ -f "/proc/meminfo" ]; then
        mem_total=$(grep "MemTotal:" /proc/meminfo 2>/dev/null | awk '{print $2}' 2>/dev/null || grep "MemTotal:" /proc/meminfo 2>/dev/null | cut -d' ' -f2)
    fi
    printf "Device:     %s\n" "$device"
    printf "Kernel:     %s\n" "$kernel"
    printf "Memory:     %s MB\n" "$((mem_total / 1024))"
    printf "Root:       %s\n" "$ANK_DIR"
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
# ANK-CORE: shell
# ============================================================
ank_core_shell() {
    echo "You are already in the host shell."
    echo "Use 'exit' to leave the ANK shell."
}

# ============================================================
# MAN PAGES - ANK
# ============================================================
ank_man() {
    local cmd="$1"
    case "$cmd" in
        ps)
            echo "ank ps"
            echo ""
            echo "List all containers with their status, IP, image, and PID."
            echo ""
            echo "Usage: ank ps"
            echo ""
            echo "Example:"
            echo "  ank ps"
            echo "  NAME                 STATUS       IP               IMAGE"
            echo "  my-site              running      10.20.30.3       alpine-3.20"
            ;;
        start)
            echo "ank start <name>"
            echo ""
            echo "Start a stopped container."
            echo ""
            echo "Usage: ank start <name>"
            echo ""
            echo "Example:"
            echo "  ank start my-site"
            ;;
        stop)
            echo "ank stop <name>"
            echo ""
            echo "Stop a running container."
            echo ""
            echo "Usage: ank stop <name>"
            ;;
        restart)
            echo "ank restart <name>"
            echo ""
            echo "Restart a container (stop + start)."
            echo ""
            echo "Usage: ank restart <name>"
            ;;
        rm)
            echo "ank rm <name>"
            echo ""
            echo "Delete a container and its data permanently."
            echo ""
            echo "Usage: ank rm <name>"
            ;;
        logs)
            echo "ank logs <name>"
            echo ""
            echo "View the last 50 lines of container logs."
            echo ""
            echo "Usage: ank logs <name>"
            ;;
        exec)
            echo "ank exec <name> <command>"
            echo ""
            echo "Execute a command inside a running container."
            echo ""
            echo "Usage: ank exec <name> <command>"
            echo ""
            echo "Example:"
            echo "  ank exec my-site ls /var/www/html"
            ;;
        inspect)
            echo "ank inspect <name>"
            echo ""
            echo "Show detailed information about a container."
            echo ""
            echo "Usage: ank inspect <name>"
            ;;
        images|list-images)
            echo "ank images"
            echo ""
            echo "List all available container images."
            echo ""
            echo "Usage: ank images"
            ;;
        templates)
            echo "ank templates"
            echo ""
            echo "List all deploy templates with their status."
            echo ""
            echo "Usage: ank templates"
            ;;
        deploy)
            echo "ank deploy <template> <name>"
            echo ""
            echo "Deploy a container from a template."
            echo ""
            echo "Usage: ank deploy <template> <name>"
            echo ""
            echo "Templates: alpine, python, nginx, apache, php, node"
            echo ""
            echo "Example:"
            echo "  ank deploy nginx my-site"
            ;;
        pull)
            echo "ank pull <version>"
            echo ""
            echo "Download the base Alpine image for the specified version."
            echo ""
            echo "Usage: ank pull [version]"
            echo "  Default version: 3.20"
            ;;
        stack)
            echo "ank stack <subcommand>"
            echo ""
            echo "Manage container stacks with load balancing."
            echo ""
            echo "Subcommands:"
            echo "  ank stack ls              List all stacks"
            echo "  ank stack inspect <name>  Show stack details"
            echo "  ank stack create <name> [template] [count]"
            echo "  ank stack scale <name> <count>"
            echo "  ank stack rm <name>"
            ;;
        backup)
            echo "ank backup <subcommand>"
            echo ""
            echo "Manage backup routines."
            echo ""
            echo "Subcommands:"
            echo "  ank backup ls             List backup routines"
            echo "  ank backup inspect <id>   Show routine details"
            echo "  ank backup run <id>       Execute backup"
            echo "  ank backup rm <id>        Delete backup routine"
            ;;
        node)
            echo "ank node <subcommand>"
            echo ""
            echo "Manage remote ANK nodes."
            echo ""
            echo "Subcommands:"
            echo "  ank node ls               List remote nodes"
            echo "  ank node inspect <id>     Show node details"
            echo "  ank node add              Add remote node (interactive)"
            echo "  ank node rm <id>          Remove a node"
            ;;
        npad)
            echo "ank npad <filename>"
            echo ""
            echo "Open a simple text editor for creating/editing Ankfiles."
            echo "Files are saved in /ank-engine/ directory."
            echo "Ankfile syntax is validated before saving."
            echo ""
            echo "Editor commands:"
            echo "  a - Add a line"
            echo "  d - Delete a line"
            echo "  e - Edit a line"
            echo "  s - Save file (validates syntax)"
            echo "  q - Quit without saving"
            echo "  :w - Save file"
            echo "  :q - Quit"
            echo "  :wq - Save and quit"
            echo ""
            echo "Ankfile directives:"
            echo "  FROM <image>      Base image (alpine-3.20, etc.)"
            echo "  RUN <command>     Run command during build"
            echo "  CMD <command>     Default command to run"
            echo "  EXPOSE <port>     Expose a port"
            echo "  WORKDIR <path>    Set working directory"
            echo "  VOLUME <path>     Mount a volume"
            echo "  PASSWD <pass>     Set root password"
            echo "  # comment         Comment line"
            ;;
        *)
            echo "No man page for '$cmd'."
            echo "Type 'ank help' for available commands."
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
            echo "ank-core status"
            echo ""
            echo "Show ANK engine status including container count."
            echo ""
            echo "Usage: ank-core status"
            ;;
        restart)
            echo "ank-core restart"
            echo ""
            echo "Restart the ANK server process."
            echo ""
            echo "Usage: ank-core restart"
            ;;
        info)
            echo "ank-core info"
            echo ""
            echo "Show device information (model, kernel, memory)."
            echo ""
            echo "Usage: ank-core info"
            ;;
        network)
            echo "ank-core network"
            echo ""
            echo "Show network configuration."
            echo ""
            echo "Usage: ank-core network"
            ;;
        clean)
            echo "ank-core clean"
            echo ""
            echo "Cleanup orphaned resources (network namespaces, veths, cgroups)."
            echo ""
            echo "Usage: ank-core clean"
            ;;
        logs)
            echo "ank-core logs"
            echo ""
            echo "Show the last 30 lines of server logs."
            echo ""
            echo "Usage: ank-core logs"
            ;;
        shell)
            echo "ank-core shell"
            echo ""
            echo "You are already in the host shell."
            echo ""
            echo "Usage: ank-core shell"
            ;;
        *)
            echo "No man page for '$cmd'."
            echo "Type 'ank-core --help' for available commands."
            ;;
    esac
}

# ============================================================
# MAIN LOOP
# ============================================================
cd "$ENGINE_DIR" 2>/dev/null || mkdir -p "$ENGINE_DIR" && cd "$ENGINE_DIR"

while true; do
    printf "(root@ank-shell) ~ [/ank-engine] > "
    read -r input

    # Skip empty input
    [ -z "$input" ] && continue

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
                npad)
                    arg1=$(echo "$args" | cut -d' ' -f1)
                    ank_npad "$arg1"
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
                shell)
                    ank_core_shell
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

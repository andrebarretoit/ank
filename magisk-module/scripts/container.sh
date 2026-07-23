#!/system/bin/sh
# Ank - Container lifecycle (full + compat mode)
# Usage: container.sh <command> <container_name> [args...]

ANK_DIR="/data/local/ank"
ANK_SDCARD="/sdcard/AndroidKonteiner"
IMAGES_DIR="$ANK_DIR/images"
CONTAINERS_DIR="$ANK_DIR/containers"
SCRIPTS_DIR="$ANK_DIR/core"
MODE_FILE="$ANK_DIR/mode"

get_mode() {
    if [ -f "$MODE_FILE" ]; then
        local m=$(grep -o '"mode":[[:space:]]*"[^"]*"' "$MODE_FILE" 2>/dev/null | head -1 | sed 's/.*"mode"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
        [ -n "$m" ] && echo "$m" && return 0
    fi
    sh "$SCRIPTS_DIR/detect.sh" check 2>/dev/null
}

# ============================================================
# Lazy build ank-alpinebase if missing (streams output to stdout)
# ============================================================
_ensure_ankbase() {
    local ANKBASE="$IMAGES_DIR/ank-alpinebase"
    local ALPINE="$IMAGES_DIR/alpine-3.20"

    # Already exists? Check for /bin/sh or /bin/busybox
    if [ -e "$ANKBASE/bin/sh" ] || [ -L "$ANKBASE/bin/sh" ] || [ -e "$ANKBASE/bin/busybox" ]; then
        return 0
    fi

    echo "ank-alpinebase not found, building..."

    # Need alpine-3.20 as source
    if [ ! -e "$ALPINE/bin/sh" ] && [ ! -L "$ALPINE/bin/sh" ] && [ ! -e "$ALPINE/bin/busybox" ]; then
        echo "alpine-3.20 not found, downloading..."
        sh "$SCRIPTS_DIR/download-rootfs.sh" 3.20
        if [ ! -e "$ALPINE/bin/sh" ] && [ ! -L "$ALPINE/bin/sh" ]; then
            echo "ERROR: Failed to download Alpine base image"
            return 1
        fi
    fi

    echo "Creating ank-alpinebase from alpine-3.20..."
    cp -a "$ALPINE" "$ANKBASE" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to copy alpine-3.20"
        return 1
    fi

    # Setup DNS
    echo "nameserver 8.8.8.8" > "$ANKBASE/etc/resolv.conf" 2>/dev/null
    echo "nameserver 8.8.4.4" >> "$ANKBASE/etc/resolv.conf" 2>/dev/null
    echo "127.0.0.1 localhost" > "$ANKBASE/etc/hosts" 2>/dev/null

    # Ensure /dev exists for apk
    mkdir -p "$ANKBASE/dev" 2>/dev/null
    [ -e "$ANKBASE/dev/null" ] || mknod "$ANKBASE/dev/null" c 1 3 2>/dev/null
    [ -e "$ANKBASE/dev/urandom" ] || mknod "$ANKBASE/dev/urandom" c 1 9 2>/dev/null

    # Install packages (stream output)
    echo "Installing openssh, bash, busybox, shadow, supervisor..."
    mount -t proc proc "$ANKBASE/proc" 2>/dev/null
    chroot "$ANKBASE" /sbin/apk add --no-cache busybox bash shadow openssh supervisor 2>&1
    local RC=$?
    umount "$ANKBASE/proc" 2>/dev/null

    if [ $RC -ne 0 ]; then
        echo "ERROR: apk install failed (rc=$RC)"
        echo "Cleaning up failed ank-alpinebase..."
        rm -rf "$ANKBASE"
        return 1
    fi

    # Setup busybox symlinks
    chroot "$ANKBASE" /bin/busybox --install -s /bin 2>/dev/null

    # Set root shell to bash
    sed -i 's|^root:[^:]*:[^:]*:[^:]*:[^:]*:[^:]*:.*|root:x:0:0:root:/root:/bin/bash|' "$ANKBASE/etc/passwd" 2>/dev/null

    # Configure sshd
    mkdir -p "$ANKBASE/etc/ssh" "$ANKBASE/run/sshd" 2>/dev/null
    cat > "$ANKBASE/etc/ssh/sshd_config" << 'SSHEOF'
Port 22
ListenAddress 0.0.0.0
PermitRootLogin yes
PasswordAuthentication yes
ChallengeResponseAuthentication no
X11Forwarding no
AllowTcpForwarding no
PidFile /run/sshd.pid
Subsystem sftp internal-sftp
SSHEOF

    # Generate SSH host keys
    chroot "$ANKBASE" /usr/bin/ssh-keygen -A 2>/dev/null || true

    # SSH dir
    mkdir -p "$ANKBASE/root/.ssh" 2>/dev/null
    chmod 700 "$ANKBASE/root/.ssh" 2>/dev/null
    touch "$ANKBASE/root/.ssh/authorized_keys" 2>/dev/null
    chmod 600 "$ANKBASE/root/.ssh/authorized_keys" 2>/dev/null

    # Create default supervisord.conf
    mkdir -p "$ANKBASE/etc/supervisor/conf.d"
    cat > "$ANKBASE/etc/supervisord.conf" << 'SUPEREOF'
[unix_http_server]
file=/run/supervisor.sock

[supervisord]
logfile=/var/log/supervisord.log
logfile_maxbytes=1MB
logfile_backups=2
nodaemon=false
loglevel=info
pidfile=/run/supervisord.pid

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix:///run/supervisor.sock
SUPEREOF

    # Remove server files if any
    rm -rf "$ANKBASE/opt/ank" 2>/dev/null

    # Verify
    if [ -e "$ANKBASE/usr/sbin/sshd" ] && [ -e "$ANKBASE/bin/bash" ]; then
        echo "ank-alpinebase built successfully (openssh, bash, busybox, shadow, supervisor)"
        return 0
    else
        echo "ERROR: ank-alpinebase build incomplete"
        rm -rf "$ANKBASE"
        return 1
    fi
}

# Setup default content + service marker for template images
_setup_template_service() {
    local DIR="$1"
    local IMAGE="$2"
    mkdir -p "$DIR/etc/ank" 2>/dev/null
    case "$IMAGE" in
        nginx*)
            mkdir -p "$DIR/var/www/html" 2>/dev/null
            cat > "$DIR/var/www/html/index.html" << 'NGINXHTML'
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ANK - Nginx</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui;background:#0f172a;color:#e2e8f0}
.card{background:#1e293b;border-radius:16px;padding:48px;max-width:480px;width:90%;text-align:center;
box-shadow:0 25px 50px rgba(0,0,0,.4)}
h1{font-size:48px;background:linear-gradient(135deg,#009639,#22c55e);
-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:0 0 8px}
p{color:#94a3b8;margin:0 0 16px}.badge{display:inline-block;background:rgba(34,197,94,.15);
color:#22c55e;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}</style></head>
<body><div class="card"><h1>NGINX</h1><p>ANK Container - Ready to deploy</p>
<div class="badge">Running</div></div></body></html>
NGINXHTML
            echo "nginx" > "$DIR/etc/ank/service"
            ;;
        apache*)
            mkdir -p "$DIR/var/www/localhost/htdocs" 2>/dev/null
            cat > "$DIR/var/www/localhost/htdocs/index.html" << 'APACHEHTML'
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ANK - Apache</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui;background:#0f172a;color:#e2e8f0}
.card{background:#1e293b;border-radius:16px;padding:48px;max-width:480px;width:90%;text-align:center;
box-shadow:0 25px 50px rgba(0,0,0,.4)}
h1{font-size:48px;background:linear-gradient(135deg,#d22128,#f87171);
-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:0 0 8px}
p{color:#94a3b8;margin:0 0 16px}.badge{display:inline-block;background:rgba(34,197,94,.15);
color:#22c55e;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}</style></head>
<body><div class="card"><h1>APACHE</h1><p>ANK Container - Ready to deploy</p>
<div class="badge">Running</div></div></body></html>
APACHEHTML
            echo "apache" > "$DIR/etc/ank/service"
            ;;
        php*)
            mkdir -p "$DIR/var/www/php" 2>/dev/null
            cat > "$DIR/var/www/php/index.php" << 'PHPPHP'
<?php
echo "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>
<meta name='viewport' content='width=device-width, initial-scale=1.0'>
<title>ANK - PHP</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui;background:#0f172a;color:#e2e8f0}
.card{background:#1e293b;border-radius:16px;padding:48px;max-width:480px;width:90%;text-align:center;
box-shadow:0 25px 50px rgba(0,0,0,.4)}
h1{font-size:48px;background:linear-gradient(135deg,#777BB4,#a78bfa);
-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:0 0 8px}
p{color:#94a3b8;margin:0 0 16px}.badge{display:inline-block;background:rgba(34,197,94,.15);
color:#22c55e;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}</style></head>
<body><div class='card'><h1>PHP " . phpversion() . "</h1><p>ANK Container - Ready to deploy</p>
<div class='badge'>Running</div></div></body></html>";
?>
PHPPHP
            echo "php" > "$DIR/etc/ank/service"
            ;;
        node*)
            mkdir -p "$DIR/var/www/app" 2>/dev/null
            cat > "$DIR/var/www/app/server.js" << 'NODEJS'
const http = require('http');
const fs = require('fs');
const path = require('path');
const PORT = 3000;
const STATIC = '/var/www/app';
const MIME = {'.html':'text/html','.css':'text/css','.js':'application/javascript','.json':'application/json','.png':'image/png','.jpg':'image/jpeg','.svg':'image/svg+xml'};
const INDEX_HTML = `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ANK - Node.js</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui;background:#0f172a;color:#e2e8f0}
.card{background:#1e293b;border-radius:16px;padding:48px;max-width:480px;width:90%;text-align:center;
box-shadow:0 25px 50px rgba(0,0,0,.4)}
h1{font-size:48px;background:linear-gradient(135deg,#339933,#22c55e);
-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:0 0 8px}
p{color:#94a3b8;margin:0 0 16px}.badge{display:inline-block;background:rgba(34,197,94,.15);
color:#22c55e;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}</style></head>
<body><div class="card"><h1>Node.js ${process.version}</h1><p>ANK Container - Ready to deploy</p>
<div class="badge">Running</div></div></body></html>`;
http.createServer((req, res) => {
  let fp = path.join(STATIC, req.url === '/' ? 'index.html' : req.url);
  if (fs.existsSync(fp) && fs.statSync(fp).isFile()) {
    const ext = path.extname(fp);
    res.writeHead(200, {'Content-Type': MIME[ext]||'application/octet-stream'});
    fs.createReadStream(fp).pipe(res);
  } else { res.writeHead(200, {'Content-Type':'text/html'}); res.end(INDEX_HTML); }
}).listen(PORT, '0.0.0.0', () => console.log(`Node.js serving on :${PORT}`));
NODEJS
            echo "node" > "$DIR/etc/ank/service"
            ;;
        python*)
            mkdir -p "$DIR/var/www/app" 2>/dev/null
            cat > "$DIR/var/www/app/server.py" << 'PYTHPY'
import http.server, os, sys
PORT = 5000
INDEX = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ANK - Python</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui;background:#0f172a;color:#e2e8f0}
.card{background:#1e293b;border-radius:16px;padding:48px;max-width:480px;width:90%;text-align:center;
box-shadow:0 25px 50px rgba(0,0,0,.4)}
h1{font-size:48px;background:linear-gradient(135deg,#3776AB,#ffd43b);
-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:0 0 8px}
p{color:#94a3b8;margin:0 0 16px}.badge{display:inline-block;background:rgba(34,197,94,.15);
color:#22c55e;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}</style></head>
<body><div class="card"><h1>Python """ + sys.version.split()[0] + """</h1><p>ANK Container - Ready to deploy</p>
<div class="badge">Running</div></div></body></html>"""
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        fp = os.path.join("/var/www/app", self.path.lstrip("/"))
        if self.path == "/" or not os.path.isfile(fp):
            self.send_response(200); self.send_header("Content-Type","text/html"); self.end_headers()
            self.wfile.write(INDEX.encode())
        else:
            self.send_response(200)
            ext = os.path.splitext(fp)[1]
            ct = {".html":"text/html",".css":"text/css",".js":"application/javascript",".json":"application/json"}.get(ext,"application/octet-stream")
            self.send_header("Content-Type",ct); self.end_headers()
            self.wfile.write(open(fp,"rb").read())
    def log_message(self,*a): pass
http.server.HTTPServer(("0.0.0.0",PORT),H).serve_forever()
PYTHPY
            echo "python" > "$DIR/etc/ank/service"
            ;;
    esac
}

# ============================================================
# Create container
# Usage: container.sh create <name> <image> <root_password> <ssh_port> [packages]
# ============================================================
cmd_create() {
    local NAME="$1"
    local IMAGE="${2:-ank-alpinebase}"
    local ROOT_PASS="${3:-}"
    local SSH_PORT="${4:-}"
    local PKGS="${5:-}"
    local CONTAINER_DIR="$CONTAINERS_DIR/$NAME"
    local MODE=$(get_mode)

    # FROM alias: alpine-3.20 -> ank-alpinebase (clean alpine has no openssh)
    [ "$IMAGE" = "alpine-3.20" ] && IMAGE="ank-alpinebase"

    # Lazy build ank-alpinebase if missing
    if [ "$IMAGE" = "ank-alpinebase" ]; then
        _ensure_ankbase
        if [ $? -ne 0 ]; then
            echo "ERROR: Failed to build ank-alpinebase"
            exit 1
        fi
    fi

    if [ -d "$CONTAINER_DIR/merged" ] && [ -f "$CONTAINER_DIR/config.json" ]; then
        # Only fail if already fully created (has merged/ dir)
        # If only config.json exists (status=building), allow retry
        local EXISTING_STATUS=$(grep -o '"status": *"[^"]*"' "$CONTAINER_DIR/config.json" 2>/dev/null | head -1 | cut -d'"' -f4)
        if [ "$EXISTING_STATUS" != "building" ] && [ "$EXISTING_STATUS" != "failed" ]; then
            echo "ERROR: Container '$NAME' already exists"
            exit 1
        fi
        echo "Retrying creation of '$NAME'..."
        rm -rf "$CONTAINER_DIR"
    fi

    local BASE_DIR="$IMAGES_DIR/$IMAGE"

    # If image doesn't exist but has packages, build it from ank-alpinebase
    if [ ! -d "$BASE_DIR" ] && [ -n "$PKGS" ]; then
        local ANKBASE="$IMAGES_DIR/ank-alpinebase"
        if [ -d "$ANKBASE" ]; then
            echo "Building image '$IMAGE' from ank-alpinebase (packages: $PKGS)..."
            cp -a "$ANKBASE" "$BASE_DIR" 2>/dev/null
            if [ $? -eq 0 ]; then
                mkdir -p "$BASE_DIR/etc" 2>/dev/null
                echo "nameserver 8.8.8.8" > "$BASE_DIR/etc/resolv.conf" 2>/dev/null
                echo "nameserver 8.8.4.4" >> "$BASE_DIR/etc/resolv.conf" 2>/dev/null
                echo "127.0.0.1 localhost" > "$BASE_DIR/etc/hosts" 2>/dev/null
                chroot "$BASE_DIR" /sbin/apk add --no-cache $PKGS 2>/dev/null
                if [ $? -eq 0 ]; then
                    echo "Image '$IMAGE' built successfully"
                    # Setup default content + service marker for template
                    _setup_template_service "$BASE_DIR" "$IMAGE"
                else
                    echo "WARN: Some packages may have failed for '$IMAGE'"
                fi
                else
                    echo "WARN: Failed to build image '$IMAGE', using ank-alpinebase"
                    BASE_DIR="$ANKBASE"
            fi
        fi
    fi

    if [ ! -d "$BASE_DIR" ]; then
        echo "ERROR: Image '$IMAGE' not found."
        exit 1
    fi

    # Validate root password
    if [ -z "$ROOT_PASS" ]; then
        echo "ERROR: root password required"
        exit 1
    fi

    # Validate SSH port
    if [ -z "$SSH_PORT" ]; then
        echo "ERROR: SSH port required"
        exit 1
    fi

    # Check if port is already in use by another container
    for cfg in "$CONTAINERS_DIR"/*/config.json; do
        [ -f "$cfg" ] || continue
        local existing_port=$(grep -o '"ssh_port":[^,]*' "$cfg" 2>/dev/null | cut -d: -f2 | tr -d ' ')
        if [ "$existing_port" = "$SSH_PORT" ]; then
            echo "ERROR: Port $SSH_PORT already used by another container"
            exit 1
        fi
    done

    echo "Creating container: $NAME (mode: $MODE, port: $SSH_PORT)"

    mkdir -p "$CONTAINER_DIR"/{upper,work,merged}

    # Filesystem
    if [ "$MODE" = "lite" ]; then
        mkdir -p "$CONTAINER_DIR/merged"
        for item in "$BASE_DIR"/*; do
            [ -e "$item" ] || continue
            local basename=$(basename "$item")
            [ -e "$CONTAINER_DIR/merged/$basename" ] || ln -s "$item" "$CONTAINER_DIR/merged/$basename" 2>/dev/null
        done
    elif [ "$MODE" = "isolated" ] || [ "$MODE" = "shared_network" ]; then
        mount -t overlay overlay \
            -o lowerdir="$BASE_DIR",upperdir="$CONTAINER_DIR/upper",workdir="$CONTAINER_DIR/work" \
            "$CONTAINER_DIR/merged" 2>/dev/null
        if [ $? -ne 0 ]; then
            echo "WARN: overlayfs failed, falling back to bind mount"
            mount --bind "$BASE_DIR" "$CONTAINER_DIR/merged"
        fi
    else
        cp -a "$BASE_DIR"/. "$CONTAINER_DIR/merged/" 2>/dev/null
        if [ $? -ne 0 ]; then
            echo "WARN: copy failed, falling back to bind mount"
            mount --bind "$BASE_DIR" "$CONTAINER_DIR/merged"
        fi
    fi

    # Networking
    local IP=""
    local NET_RC=0
    if [ "$MODE" = "isolated" ]; then
        IP=$(sh "$SCRIPTS_DIR/network.sh" create "$NAME") || NET_RC=$?
    elif [ "$MODE" = "lite" ]; then
        IP=$(ip -4 -o addr show wlan0 2>/dev/null | cut -d' ' -f7 | cut -d/ -f1)
        [ -z "$IP" ] && IP="127.0.0.1"
    else
        IP=$(sh "$SCRIPTS_DIR/network.sh" create_compat "$NAME") || NET_RC=$?
    fi

    if [ "$NET_RC" -ne 0 ] || [ -z "$IP" ]; then
        echo "WARN: Network setup failed (mode=$MODE), creating container without network"
        IP="none"
    fi

    # Setup cgroups
    sh "$SCRIPTS_DIR/resources.sh" setup "$NAME" 268435456 50 2>/dev/null

    # Setup rootfs (ank-alpinebase already has openssh/bash/busybox/shadow)
    local ROOTFS="$CONTAINER_DIR/merged"
    echo "Setting up container: $NAME..."
    # Ensure DNS works inside chroot
    mkdir -p "$ROOTFS/etc" 2>/dev/null
    echo "nameserver 8.8.8.8" > "$ROOTFS/etc/resolv.conf" 2>/dev/null
    echo "nameserver 8.8.4.4" >> "$ROOTFS/etc/resolv.conf" 2>/dev/null
    # Ensure /dev/null exists
    mkdir -p "$ROOTFS/dev" 2>/dev/null
    [ -e "$ROOTFS/dev/null" ] || mknod "$ROOTFS/dev/null" c 1 3 2>/dev/null
    [ -e "$ROOTFS/dev/urandom" ] || mknod "$ROOTFS/dev/urandom" c 1 9 2>/dev/null
    # Set root password via shadow file directly
    if [ -n "$ROOT_PASS" ]; then
        local ENC_PASS=""
        ENC_PASS=$(chroot "$ROOTFS" /usr/bin/openssl passwd -1 "$ROOT_PASS" 2>/dev/null)
        if [ -z "$ENC_PASS" ]; then
            for op in "$ROOTFS/usr/bin/openssl" "$ROOTFS/usr/sbin/openssl"; do
                [ -f "$op" ] && ENC_PASS=$(LD_LIBRARY_PATH="$ROOTFS/usr/lib:$ROOTFS/lib" "$op" passwd -1 "$ROOT_PASS" 2>/dev/null) && break
            done
        fi
        if [ -n "$ENC_PASS" ] && [ -f "$ROOTFS/etc/shadow" ]; then
            sed -i "s|^root:[^:]*:|root:${ENC_PASS}:|" "$ROOTFS/etc/shadow" 2>/dev/null
            echo "Password set via shadow"
        elif [ -f "$ROOTFS/usr/bin/chpasswd" ]; then
            echo "root:$ROOT_PASS" | chroot "$ROOTFS" /usr/bin/chpasswd 2>/dev/null
            echo "Password set via chpasswd"
        fi
    fi
    echo "Container ready: $NAME"

    # Create config with SSH info
    cat > "$CONTAINER_DIR/config.json" << CFGEOF
{
  "name": "$NAME",
  "status": "stopped",
  "image": "$IMAGE",
  "mode": "$MODE",
  "autostart": false,
  "ip_address": "$IP",
  "ssh_port": $SSH_PORT,
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "pid": null,
  "policies": {
    "inter_container_p2p": false,
    "allow_host_access": false,
    "allow_internet": true
  },
  "resources": {
    "memory_limit": "256M",
    "cpu_limit_percent": 50
  },
  "port_mappings": []
}
CFGEOF

    # Apply network policies
    if [ "$MODE" = "isolated" ]; then
        sh "$SCRIPTS_DIR/network.sh" apply_policies "$NAME"
        sh "$SCRIPTS_DIR/network.sh" apply_ports "$NAME"
    else
        sh "$SCRIPTS_DIR/network.sh" apply_policies_compat "$NAME"
        sh "$SCRIPTS_DIR/network.sh" apply_ports_compat "$NAME"
    fi

    echo "Container '$NAME' created (IP: $IP, SSH port: $SSH_PORT, mode: $MODE)"
    return 0
}

# ============================================================
# Setup iptables port forwarding for SSH
# ============================================================
setup_ssh_forward() {
    local CONTAINER_IP="$1"
    local HOST_PORT="$2"
    if [ "$CONTAINER_IP" = "none" ] || [ -z "$CONTAINER_IP" ]; then
        return 1
    fi
    # Remove existing rule if any
    iptables -t nat -D PREROUTING -p tcp --dport "$HOST_PORT" -j DNAT --to-destination "${CONTAINER_IP}:22" 2>/dev/null
    iptables -D FORWARD -p tcp -d "$CONTAINER_IP" --dport 22 -j ACCEPT 2>/dev/null
    # Add new rules
    iptables -t nat -A PREROUTING -p tcp --dport "$HOST_PORT" -j DNAT --to-destination "${CONTAINER_IP}:22" 2>/dev/null
    iptables -A FORWARD -p tcp -d "$CONTAINER_IP" --dport 22 -j ACCEPT 2>/dev/null
    echo "SSH forward: host:$HOST_PORT -> $CONTAINER_IP:22"
    return 0
}

remove_ssh_forward() {
    local CONTAINER_IP="$1"
    local HOST_PORT="$2"
    iptables -t nat -D PREROUTING -p tcp --dport "$HOST_PORT" -j DNAT --to-destination "${CONTAINER_IP}:22" 2>/dev/null
    iptables -D FORWARD -p tcp -d "$CONTAINER_IP" --dport 22 -j ACCEPT 2>/dev/null
}

# ============================================================
# Start container
# ============================================================
cmd_start() {
    local NAME="$1"
    local CONTAINER_DIR="$CONTAINERS_DIR/$NAME"
    local CONFIG="$CONTAINER_DIR/config.json"
    local MODE=$(get_mode)

    if [ ! -d "$CONTAINER_DIR" ]; then
        echo "ERROR: Container '$NAME' not found"
        exit 1
    fi

    local STATUS=$(grep -o '"status": *"[^"]*"' "$CONFIG" | cut -d'"' -f4)
    local PID=$(grep -o '"pid": [^,]*' "$CONFIG" | cut -d' ' -f2)

    if [ "$STATUS" = "running" ] && [ -n "$PID" ] && [ "$PID" != "null" ]; then
        if kill -0 "$PID" 2>/dev/null; then
            echo "Container '$NAME' is already running (PID: $PID)"
            return 0
        fi
        echo "WARN: Container '$NAME' had stale running status (PID $PID dead), restarting..."
        sed -i "s/\"status\": \"[^\"]*\"/\"status\": \"stopped\"/" "$CONFIG"
        sed -i "s/\"pid\": [^,]*/\"pid\": null/" "$CONFIG"
    fi

    local ROOTFS="$CONTAINER_DIR/merged"

    if [ ! -d "$ROOTFS/bin" ]; then
        echo "ERROR: Rootfs not found at $ROOTFS"
        exit 1
    fi

    local SSH_PORT=$(grep -o '"ssh_port":[^,]*' "$CONFIG" | cut -d: -f2 | tr -d ' ')
    local IP=$(grep -o '"ip_address":[^,]*' "$CONFIG" | cut -d'"' -f4)

    echo "Starting container: $NAME (mode: $MODE, port: $SSH_PORT)"

    # Find shell
    local SHELL=""
    for sh in /bin/sh /bin/ash /usr/bin/sh; do
        [ -e "$ROOTFS$sh" ] || [ -L "$ROOTFS$sh" ] && { SHELL="$sh"; break; }
    done
    [ -z "$SHELL" ] && SHELL="/bin/sh"
    echo "  Shell: $SHELL"

    # Fallback: if isolated mode but netns missing, degrade
    if [ "$MODE" = "isolated" ]; then
        local NS="netns_${NAME}"
        if ! ip netns list 2>/dev/null | grep -q "$NS"; then
            echo "WARN: netns '$NS' not found, falling back to shared_network"
            MODE="shared_network"
        fi
    fi

    if [ "$MODE" = "shared_network" ]; then
        if ! unshare --pid --fork /bin/true 2>/dev/null; then
            echo "WARN: pidns not functional, falling back to shared_host"
            MODE="shared_host"
        fi
    fi

    # Set root password before starting sshd
    local ROOT_PASS=$(grep -o '"root_password":"[^"]*"' "$CONFIG" 2>/dev/null | cut -d'"' -f4)
    if [ -n "$ROOT_PASS" ]; then
        echo "  Setting root password..."
        [ -e "$ROOTFS/dev/null" ] || mknod "$ROOTFS/dev/null" c 1 3 2>/dev/null
        [ -e "$ROOTFS/dev/urandom" ] || mknod "$ROOTFS/dev/urandom" c 1 9 2>/dev/null
        # Set password via shadow directly (most reliable)
        local ENC_PASS=""
        ENC_PASS=$(chroot "$ROOTFS" /usr/bin/openssl passwd -1 "$ROOT_PASS" 2>/dev/null)
        if [ -z "$ENC_PASS" ]; then
            for op in "$ROOTFS/usr/bin/openssl" "$ROOTFS/usr/sbin/openssl"; do
                [ -f "$op" ] && ENC_PASS=$(LD_LIBRARY_PATH="$ROOTFS/usr/lib:$ROOTFS/lib" "$op" passwd -1 "$ROOT_PASS" 2>/dev/null) && break
            done
        fi
        if [ -n "$ENC_PASS" ] && [ -f "$ROOTFS/etc/shadow" ]; then
            sed -i "s|^root:[^:]*:|root:${ENC_PASS}:|" "$ROOTFS/etc/shadow" 2>/dev/null
            echo "  Password set via shadow"
        elif [ -f "$ROOTFS/usr/bin/chpasswd" ]; then
            echo "root:$ROOT_PASS" | chroot "$ROOTFS" /usr/bin/chpasswd 2>/dev/null
            echo "  Password set via chpasswd"
        else
            echo "  WARN: Could not set password (no shadow or chpasswd)"
        fi
    fi

    # Init script: setup dev, start sshd as PID 1
    # In shared_host/isolated modes, sshd listens on SSH_PORT directly (no DNAT needed)
    local SSHD_PORT=22
    if [ "$MODE" = "shared_host" ] || [ "$MODE" = "isolated" ] || [ "$MODE" = "shared_network" ]; then
        if [ -n "$SSH_PORT" ] && [ "$SSH_PORT" != "null" ]; then
            SSHD_PORT="$SSH_PORT"
        fi
    fi

    CONTAINER_INIT='
        export PATH=/bin:/sbin:/usr/bin:/usr/sbin
        trap "" HUP PIPE
        _ank_exit=0
        trap "_ank_exit=1" TERM INT
        echo "[init] Mounting filesystems..."
        mkdir -p /dev/pts /dev/shm /run/sshd 2>/dev/null
        mount -t proc proc /proc 2>/dev/null
        mount -t sysfs sysfs /sys 2>/dev/null
        mount -t devtmpfs devtmpfs /dev 2>/dev/null || true
        for node in "null:1:3" "zero:1:5" "random:1:8" "urandom:1:9" "tty:5:0" "ptmx:5:2" "console:5:1"; do
            n=$(echo "$node" | cut -d: -f1)
            t=$(echo "$node" | cut -d: -f2)
            m=$(echo "$node" | cut -d: -f3)
            [ -e "/dev/$n" ] || mknod "/dev/$n" c "$t" "$m" 2>/dev/null
            chmod 666 "/dev/$n" 2>/dev/null
        done
        mount -t devpts devpts /dev/pts 2>/dev/null || true
        echo "[init] Filesystems mounted"
        hostname CONTAINER_NAME_PLACEHOLDER 2>/dev/null
        cd /root 2>/dev/null || cd /
        echo "[init] Starting sshd on port CONTAINER_SSHD_PORT..."
        if [ -x /usr/sbin/sshd ]; then
            ssh-keygen -A 2>/dev/null
            /usr/sbin/sshd -D -p CONTAINER_SSHD_PORT -o PasswordAuthentication=yes -o PermitRootLogin=yes -o PidFile=/run/sshd.pid -e 2>/dev/null &
            _sshd_pid=$!
            echo "[init] sshd started (PID: $_sshd_pid)"
        else
            echo "[init] WARN: sshd not found"
        fi
        if [ -x /usr/bin/supervisord ]; then
            echo "[init] Starting supervisor..."
            /usr/bin/supervisord -c /etc/supervisord.conf 2>/dev/null &
            _super_pid=$!
            echo "[init] supervisor started (PID: $_super_pid)"
        fi
        if [ -f /etc/ank/service ]; then
            _svc=$(cat /etc/ank/service 2>/dev/null)
            echo "[init] Starting service: $_svc"
            case "$_svc" in
                nginx)  mkdir -p /run/nginx 2>/dev/null; nginx 2>/dev/null & ;;
                apache) httpd -D FOREGROUND 2>/dev/null & ;;
                php)    php -S 0.0.0.0:8080 -t /var/www/php 2>/dev/null & ;;
                node)   cd /var/www/app 2>/dev/null; node server.js 2>/dev/null & ;;
                python) cd /var/www/app 2>/dev/null; python3 server.py 2>/dev/null & ;;
                *)      echo "[init] Unknown service: $_svc" ;;
            esac
        fi
        echo "[init] Container ready"
        while [ "$_ank_exit" = "0" ]; do
            if [ -n "$_sshd_pid" ] && ! kill -0 "$_sshd_pid" 2>/dev/null; then
                echo "[init] sshd died, exiting..."
                break
            fi
            if [ -n "$_super_pid" ] && ! kill -0 "$_super_pid" 2>/dev/null; then
                echo "[init] supervisord died, restarting..."
                /usr/bin/supervisord -c /etc/supervisord.conf 2>/dev/null &
                _super_pid=$!
            fi
            /bin/busybox sleep 5 2>/dev/null || /bin/sleep 5 2>/dev/null || true
        done
    '

    CONTAINER_INIT=$(echo "$CONTAINER_INIT" | sed "s/CONTAINER_NAME_PLACEHOLDER/$NAME/g")
    CONTAINER_INIT=$(echo "$CONTAINER_INIT" | sed "s/CONTAINER_SSHD_PORT/$SSHD_PORT/g")

    if [ "$MODE" = "isolated" ]; then
        nohup ip netns exec "$NS" unshare --fork --pid \
            --mount-proc="$ROOTFS/proc" \
            chroot "$ROOTFS" "$SHELL" -c "$CONTAINER_INIT" </dev/null >/dev/null 2>&1 &
    elif [ "$MODE" = "shared_network" ]; then
        nohup unshare --fork --pid \
            --mount-proc="$ROOTFS/proc" \
            chroot "$ROOTFS" "$SHELL" -c "$CONTAINER_INIT" </dev/null >/dev/null 2>&1 &
    elif [ "$MODE" = "lite" ]; then
        local PROOT_BIN="$ANK_DIR/proot"
        if [ ! -e "$PROOT_BIN" ]; then
            echo "ERROR: PRoot binary not found at $PROOT_BIN"
            exit 1
        fi
        LD_LIBRARY_PATH="$ROOTFS/lib:$ROOTFS/usr/lib" \
        nohup "$PROOT_BIN" -0 -r "$ROOTFS" \
            "$SHELL" -c "$CONTAINER_INIT" </dev/null >/dev/null 2>&1 &
    else
        nohup chroot "$ROOTFS" "$SHELL" -c "$CONTAINER_INIT" </dev/null >"$ANK_DIR/logs/${NAME}.log" 2>&1 &
    fi

    local PID=$!

    sleep 2
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "ERROR: Container process died immediately after start"
        [ -f "$ANK_DIR/logs/${NAME}.log" ] && tail -5 "$ANK_DIR/logs/${NAME}.log" 2>/dev/null
        sed -i "s/\"status\": \"[^\"]*\"/\"status\": \"stopped\"/" "$CONFIG"
        sed -i "s/\"pid\": [^,]*/\"pid\": null/" "$CONFIG"
        exit 1
    fi

    # Move to cgroup
    local CGROUP="/sys/fs/cgroup/ank/$NAME"
    if [ -d "$CGROUP" ]; then
        echo "$PID" > "$CGROUP/cgroup.procs" 2>/dev/null
    fi

    # Setup SSH port forwarding (only for modes with network namespace)
    if [ -n "$SSH_PORT" ] && [ "$SSH_PORT" != "null" ] && [ "$IP" != "none" ] && [ -n "$IP" ]; then
        if [ "$MODE" = "isolated" ]; then
            setup_ssh_forward "$IP" "$SSH_PORT"
        fi
        # In shared_host/shared_network/lite modes, sshd listens directly on SSH_PORT
    fi

    # Setup service port forwarding (nginx/apache=8080, node=3000, python=5000)
    local SVC_PORT=""
    local IMAGE=$(grep -o '"image":"[^"]*"' "$CONFIG" | cut -d'"' -f4)
    case "$IMAGE" in
        nginx*|apache*|php*) SVC_PORT="8080" ;;
        node*) SVC_PORT="3000" ;;
        python*) SVC_PORT="5000" ;;
    esac
    if [ -n "$SVC_PORT" ] && [ "$IP" != "none" ] && [ -n "$IP" ]; then
        if [ "$MODE" = "isolated" ]; then
            iptables -t nat -D PREROUTING -p tcp --dport "$SVC_PORT" -j DNAT --to-destination "${IP}:${SVC_PORT}" 2>/dev/null
            iptables -D FORWARD -p tcp -d "$IP" --dport "$SVC_PORT" -j ACCEPT 2>/dev/null
            iptables -t nat -A PREROUTING -p tcp --dport "$SVC_PORT" -j DNAT --to-destination "${IP}:${SVC_PORT}" 2>/dev/null
            iptables -A FORWARD -p tcp -d "$IP" --dport "$SVC_PORT" -j ACCEPT 2>/dev/null
            echo "Service forward: host:$SVC_PORT -> $IP:$SVC_PORT"
        fi
    fi

    # Update config
    sed -i "s/\"status\": \"[^\"]*\"/\"status\": \"running\"/" "$CONFIG"
    sed -i "s/\"pid\": [^,]*/\"pid\": $PID/" "$CONFIG"

    echo "Container '$NAME' started (PID: $PID, SSH: $SSH_PORT)"
    return 0
}

# ============================================================
# Stop container
# ============================================================
cmd_stop() {
    local NAME="$1"
    local CONTAINER_DIR="$CONTAINERS_DIR/$NAME"
    local CONFIG="$CONTAINER_DIR/config.json"

    if [ ! -d "$CONTAINER_DIR" ]; then
        echo "ERROR: Container '$NAME' not found"
        exit 1
    fi

    local STATUS=$(grep -o '"status": *"[^"]*"' "$CONFIG" | cut -d'"' -f4)
    if [ "$STATUS" != "running" ]; then
        echo "Container '$NAME' is not running"
        return 0
    fi

    local PID=$(grep -o '"pid": [^,]*' "$CONFIG" | cut -d' ' -f2)
    local SSH_PORT=$(grep -o '"ssh_port":[^,]*' "$CONFIG" | cut -d: -f2 | tr -d ' ')
    local IP=$(grep -o '"ip_address":[^,]*' "$CONFIG" | cut -d'"' -f4)
    local ROOTFS="$CONTAINER_DIR/merged"

    echo "Stopping container: $NAME"

    # === Phase 1: Kill ALL processes running inside this chroot ===
    echo "  Scanning for processes..."
    # Find PIDs by checking /proc/*/root symlink target
    local CHROOT_PIDS=""
    for pid_dir in /proc/[0-9]*; do
        local pid=$(basename "$pid_dir")
        local root_link=$(readlink "$pid_dir/root" 2>/dev/null)
        if [ "$root_link" = "$ROOTFS" ] || [ "$root_link" = "/" ]; then
            # Check if process's cwd or exe is inside our rootfs
            local exe=$(readlink "$pid_dir/exe" 2>/dev/null)
            local cwd=$(readlink "$pid_dir/cwd" 2>/dev/null)
            case "$exe" in
                ${ROOTFS}/*) CHROOT_PIDS="$CHROOT_PIDS $pid" ;;
            esac
            case "$cwd" in
                ${ROOTFS}/*) CHROOT_PIDS="$CHROOT_PIDS $pid" ;;
            esac
        fi
    done

    # Also find via cmdline (sshd, nginx, node, python, etc.)
    for pid_dir in /proc/[0-9]*; do
        local pid=$(basename "$pid_dir")
        local cmdline=$(cat "$pid_dir/cmdline" 2>/dev/null | tr '\0' ' ')
        case "$cmdline" in
            *${ROOTFS}*|*"sshd -D"*|*"sshd -e"*) CHROOT_PIDS="$CHROOT_PIDS $pid" ;;
        esac
    done

    # Kill the main PID tree first
    if [ -n "$PID" ] && [ "$PID" != "null" ]; then
        echo "  Stopping main process (PID: $PID)..."
        kill -TERM "$PID" 2>/dev/null
        # Also kill all children recursively
        for child in $(ps -o pid= --ppid "$PID" 2>/dev/null); do
            kill -TERM "$child" 2>/dev/null
        done
    fi

    sleep 1

    # Force kill everything found inside the chroot
    local KILL_COUNT=0
    for cpid in $CHROOT_PIDS; do
        kill -9 "$cpid" 2>/dev/null && KILL_COUNT=$((KILL_COUNT+1))
    done
    [ $KILL_COUNT -gt 0 ] && echo "  Killed $KILL_COUNT stray processes"

    # Kill by name patterns (catch stragglers)
    pkill -9 -f "sshd.*PidFile.*${NAME}" 2>/dev/null
    pkill -9 -f "sshd.*-p.*${SSH_PORT}" 2>/dev/null

    # Final check - kill any remaining in cgroup
    if [ -d "/sys/fs/cgroup/ank/$NAME" ]; then
        while read -r cpid; do
            kill -9 "$cpid" 2>/dev/null
        done < "/sys/fs/cgroup/ank/$NAME/cgroup.procs" 2>/dev/null
    fi
    echo "  All processes stopped"

    # === Phase 2: Unmount ALL chroot mounts ===
    if [ "$MODE" != "lite" ]; then
        echo "  Unmounting filesystems..."
        # Unmount in reverse order of what init script mounts
        umount "$ROOTFS/dev/pts" 2>/dev/null
        umount "$ROOTFS/dev/shm" 2>/dev/null
        umount "$ROOTFS/dev" 2>/dev/null
        umount "$ROOTFS/proc" 2>/dev/null
        umount "$ROOTFS/sys" 2>/dev/null
        # Lazy unmount if still busy
        umount -l "$ROOTFS/dev/pts" 2>/dev/null
        umount -l "$ROOTFS/dev" 2>/dev/null
        umount -l "$ROOTFS/proc" 2>/dev/null
        umount -l "$ROOTFS/sys" 2>/dev/null
        echo "  Filesystems unmounted"
    fi

    # === Phase 3: Remove port forwarding ===
    if [ -n "$SSH_PORT" ] && [ "$SSH_PORT" != "null" ] && [ "$IP" != "none" ] && [ -n "$IP" ]; then
        local MODE=$(get_mode)
        if [ "$MODE" = "isolated" ]; then
            remove_ssh_forward "$IP" "$SSH_PORT"
        fi
    fi

    # Remove service port forwarding
    local IMAGE=$(grep -o '"image":"[^"]*"' "$CONFIG" | cut -d'"' -f4)
    local SVC_PORT=""
    case "$IMAGE" in
        nginx*|apache*|php*) SVC_PORT="8080" ;;
        node*) SVC_PORT="3000" ;;
        python*) SVC_PORT="5000" ;;
    esac
    if [ -n "$SVC_PORT" ] && [ "$IP" != "none" ] && [ -n "$IP" ]; then
        local MODE=$(get_mode)
        if [ "$MODE" = "isolated" ]; then
            iptables -t nat -D PREROUTING -p tcp --dport "$SVC_PORT" -j DNAT --to-destination "${IP}:${SVC_PORT}" 2>/dev/null
            iptables -D FORWARD -p tcp -d "$IP" --dport "$SVC_PORT" -j ACCEPT 2>/dev/null
        fi
    fi

    sed -i "s/\"status\": \"[^\"]*\"/\"status\": \"stopped\"/" "$CONFIG"
    sed -i "s/\"pid\": [^,]*/\"pid\": null/" "$CONFIG"

    echo "Container '$NAME' stopped"
    return 0
}

# ============================================================
# Delete container
# ============================================================
cmd_delete() {
    local NAME="$1"
    local CONTAINER_DIR="$CONTAINERS_DIR/$NAME"

    if [ ! -d "$CONTAINER_DIR" ]; then
        echo "ERROR: Container '$NAME' not found"
        exit 1
    fi

    local CONFIG="$CONTAINER_DIR/config.json"
    local STATUS=""
    if [ -f "$CONFIG" ]; then
        STATUS=$(grep -o '"status": *"[^"]*"' "$CONFIG" | cut -d'"' -f4)
    fi

    if [ "$STATUS" = "running" ] || [ "$STATUS" = "starting" ]; then
        echo "ERROR: Container '$NAME' is $STATUS. Stop it first."
        exit 1
    fi

    echo "Deleting container: $NAME"

    # Kill ANY stray processes (should be stopped, but just in case)
    local ROOTFS="$CONTAINER_DIR/merged"
    for pid_dir in /proc/[0-9]*; do
        local pid=$(basename "$pid_dir")
        local exe=$(readlink "$pid_dir/exe" 2>/dev/null)
        local cwd=$(readlink "$pid_dir/cwd" 2>/dev/null)
        case "$exe" in ${ROOTFS}/*) kill -9 "$pid" 2>/dev/null ;; esac
        case "$cwd" in ${ROOTFS}/*) kill -9 "$pid" 2>/dev/null ;; esac
    done
    local SSH_PORT=$(grep -o '"ssh_port":[^,]*' "$CONFIG" 2>/dev/null | cut -d: -f2 | tr -d ' ')
    [ -n "$SSH_PORT" ] && pkill -9 -f "sshd.*-p.*${SSH_PORT}" 2>/dev/null

    # Unmount everything
    umount "$ROOTFS/dev/pts" 2>/dev/null
    umount "$ROOTFS/dev/shm" 2>/dev/null
    umount "$ROOTFS/dev" 2>/dev/null
    umount "$ROOTFS/proc" 2>/dev/null
    umount "$ROOTFS/sys" 2>/dev/null
    umount "$ROOTFS/run" 2>/dev/null
    umount "$ROOTFS/tmp" 2>/dev/null
    umount -l "$ROOTFS/dev/pts" 2>/dev/null
    umount -l "$ROOTFS/dev" 2>/dev/null
    umount -l "$ROOTFS/proc" 2>/dev/null
    umount -l "$ROOTFS/sys" 2>/dev/null
    umount "$CONTAINER_DIR/merged" 2>/dev/null
    umount -l "$CONTAINER_DIR/merged" 2>/dev/null

    # Clean iptables
    local IP=$(grep -o '"ip_address":[^,]*' "$CONFIG" 2>/dev/null | cut -d'"' -f4)
    if [ -n "$SSH_PORT" ] && [ "$SSH_PORT" != "null" ] && [ -n "$IP" ] && [ "$IP" != "none" ]; then
        local MODE=$(get_mode)
        if [ "$MODE" = "isolated" ]; then
            remove_ssh_forward "$IP" "$SSH_PORT" 2>/dev/null
        fi
        iptables -t nat -D PREROUTING -p tcp --dport "$SSH_PORT" -j REDIRECT --to-port 22 2>/dev/null
        iptables -t nat -D PREROUTING -p tcp --dport "$SSH_PORT" -j DNAT --to-destination "${IP}:22" 2>/dev/null
        iptables -D FORWARD -p tcp -d "$IP" --dport 22 -j ACCEPT 2>/dev/null
    fi

    local IMAGE=$(grep -o '"image":"[^"]*"' "$CONFIG" 2>/dev/null | cut -d'"' -f4)
    local SVC_PORT=""
    case "$IMAGE" in
        nginx*|apache*|php*) SVC_PORT="8080" ;;
        node*) SVC_PORT="3000" ;;
        python*) SVC_PORT="5000" ;;
    esac
    if [ -n "$SVC_PORT" ] && [ -n "$IP" ] && [ "$IP" != "none" ]; then
        local MODE=$(get_mode)
        if [ "$MODE" = "isolated" ]; then
            iptables -t nat -D PREROUTING -p tcp --dport "$SVC_PORT" -j DNAT --to-destination "${IP}:${SVC_PORT}" 2>/dev/null
            iptables -D FORWARD -p tcp -d "$IP" --dport "$SVC_PORT" -j ACCEPT 2>/dev/null
        fi
    fi

    # Destroy network
    local MODE=$(get_mode)
    if [ "$MODE" = "isolated" ]; then
        sh "$SCRIPTS_DIR/network.sh" destroy "$NAME" 2>/dev/null
    else
        sh "$SCRIPTS_DIR/network.sh" destroy_compat "$NAME" 2>/dev/null
    fi

    # Remove cgroup
    rmdir "/sys/fs/cgroup/ank/$NAME" 2>/dev/null

    # Delete everything
    rm -rf "$CONTAINER_DIR"

    echo "Container '$NAME' deleted"
    return 0
}

# ============================================================
# List containers
# ============================================================
cmd_list() {
    local output="["
    local first=true

    for config in "$CONTAINERS_DIR"/*/config.json; do
        [ -f "$config" ] || continue
        [ "$first" = true ] && first=false || output="$output,"
        output="$output$(cat "$config")"
    done

    output="$output]"
    echo "$output"
}

# ============================================================
# Inspect container
# ============================================================
cmd_inspect() {
    local NAME="$1"
    local CONFIG="$CONTAINERS_DIR/$NAME/config.json"
    [ -f "$CONFIG" ] && cat "$CONFIG" || echo "ERROR: Container '$NAME' not found"
}

# ============================================================
# Main
# ============================================================
CMD="$1"
NAME="$2"

case "$CMD" in
    create)  cmd_create "$NAME" "$3" "$4" "$5" "$6" ;;
    start)   cmd_start "$NAME" ;;
    stop)    cmd_stop "$NAME" ;;
    delete)  cmd_delete "$NAME" ;;
    list)    cmd_list ;;
    inspect) cmd_inspect "$NAME" ;;
    *)
        echo "Usage: $0 {create|start|stop|delete|list|inspect} <name> [image] [password] [ssh_port]"
        exit 1
        ;;
esac

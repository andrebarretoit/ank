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
# Lazy build ank-alpinebase-{version} if missing (streams output to stdout)
# ============================================================
_ensure_ankbase() {
    local VERSION="${1:-3.20}"
    local ANKBASE="$IMAGES_DIR/ank-alpinebase-${VERSION}"
    local ALPINE="$IMAGES_DIR/alpine-${VERSION}"

    # Already exists? Check for /bin/sh or /bin/busybox
    if [ -e "$ANKBASE/bin/sh" ] || [ -L "$ANKBASE/bin/sh" ] || [ -e "$ANKBASE/bin/busybox" ]; then
        return 0
    fi

    # Fallback: migrate old unversioned name
    local OLD_BASE="$IMAGES_DIR/ank-alpinebase"
    if [ -e "$OLD_BASE/bin/sh" ] || [ -L "$OLD_BASE/bin/sh" ] || [ -e "$OLD_BASE/bin/busybox" ]; then
        if [ "$OLD_BASE" != "$ANKBASE" ]; then
            echo "Migrating ank-alpinebase -> ank-alpinebase-${VERSION}..."
            mv "$OLD_BASE" "$ANKBASE" 2>/dev/null || cp -a "$OLD_BASE" "$ANKBASE" 2>/dev/null
            if [ -e "$ANKBASE/bin/sh" ] || [ -L "$ANKBASE/bin/sh" ]; then
                return 0
            fi
        fi
    fi

    echo "ank-alpinebase-${VERSION} not found, building..."

    # Need alpine as source
    if [ ! -e "$ALPINE/bin/sh" ] && [ ! -L "$ALPINE/bin/sh" ] && [ ! -e "$ALPINE/bin/busybox" ]; then
        echo "alpine-${VERSION} not found, downloading..."
        sh "$SCRIPTS_DIR/download-rootfs.sh" "$VERSION"
        if [ ! -e "$ALPINE/bin/sh" ] && [ ! -L "$ALPINE/bin/sh" ]; then
            echo "ERROR: Failed to download Alpine base image"
            return 1
        fi
    fi

    echo "Creating ank-alpinebase-${VERSION} from alpine-${VERSION}..."
    cp -a "$ALPINE" "$ANKBASE" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to copy alpine-3.20"
        return 1
    fi

    # Setup DNS
    echo "nameserver 8.8.8.8" > "$ANKBASE/etc/resolv.conf" 2>/dev/null
    echo "nameserver 8.8.4.4" >> "$ANKBASE/etc/resolv.conf" 2>/dev/null
    echo "127.0.0.1 localhost" > "$ANKBASE/etc/hosts" 2>/dev/null

    # Ensure /dev exists for apk (kernel 3.10 + nodev workaround)
    mkdir -p "$ANKBASE/dev/pts" "$ANKBASE/dev/shm" 2>/dev/null
    umount "$ANKBASE/dev" 2>/dev/null
    mount -t tmpfs -o size=16m tmpfs "$ANKBASE/dev" 2>/dev/null
    [ -e "$ANKBASE/dev/null" ] || mknod "$ANKBASE/dev/null" c 1 3 2>/dev/null; chmod 666 "$ANKBASE/dev/null" 2>/dev/null
    [ -e "$ANKBASE/dev/urandom" ] || mknod "$ANKBASE/dev/urandom" c 1 9 2>/dev/null; chmod 666 "$ANKBASE/dev/urandom" 2>/dev/null

    # Install packages (stream output)
    echo "Installing openssh, bash, busybox, shadow, openssl, s6..."
    mount -t proc proc "$ANKBASE/proc" 2>/dev/null
    chroot "$ANKBASE" /sbin/apk add --no-cache busybox bash shadow openssh openssl s6 2>&1
    local RC=$?
    umount "$ANKBASE/proc" 2>/dev/null

    if [ $RC -ne 0 ]; then
        echo "ERROR: apk install failed (rc=$RC)"
        echo "Cleaning up failed ank-alpinebase-${VERSION}..."
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

    # Create s6 service directory structure
    mkdir -p "$ANKBASE/etc/s6-overlay/s6-rc.d"
    mkdir -p "$ANKBASE/etc/s6-overlay/scripts"

    # Create default empty services dir
    mkdir -p "$ANKBASE/etc/s6/services"

    # Remove server files if any
    rm -rf "$ANKBASE/opt/ank" 2>/dev/null

    # Verify
    if [ -e "$ANKBASE/usr/sbin/sshd" ] && [ -e "$ANKBASE/bin/bash" ]; then
        echo "ank-alpinebase-${VERSION} built successfully (openssh, bash, busybox, shadow, s6)"
        return 0
    else
        echo "ERROR: ank-alpinebase-${VERSION} build incomplete"
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
# ============================================================
# Install ankd service manager into container rootfs
# ============================================================
_install_ankd() {
    local ROOTFS="$1"
    local NAME="$2"
    local IMAGE="$3"
    local SSH_PORT="$4"
    local TEMPLATE_ID="${5:-}"

    echo "  Installing ankd service manager..."

    # Create directory structure
    mkdir -p "$ROOTFS/usr/ankd/core" 2>/dev/null
    mkdir -p "$ROOTFS/usr/ankd/services.d" 2>/dev/null
    mkdir -p "$ROOTFS/usr/ankd/services" 2>/dev/null
    mkdir -p "$ROOTFS/etc/ankd/services.d" 2>/dev/null
    mkdir -p "$ROOTFS/etc/ankd/services" 2>/dev/null
    mkdir -p "$ROOTFS/var/run/ankd" 2>/dev/null
    mkdir -p "$ROOTFS/var/log/ankd" 2>/dev/null

    # Copy ankd.sh from host
    local ANKD_SRC="$SCRIPTS_DIR/server/ankd/ankd.sh"
    if [ ! -f "$ANKD_SRC" ]; then
        ANKD_SRC="$SCRIPTS_DIR/ankd/ankd.sh"
    fi
    if [ -f "$ANKD_SRC" ]; then
        cp "$ANKD_SRC" "$ROOTFS/usr/ankd/core/ankd.sh" 2>/dev/null
        chmod +x "$ROOTFS/usr/ankd/core/ankd.sh" 2>/dev/null
    else
        echo "  WARN: ankd.sh not found at $ANKD_SRC"
        return 1
    fi

    # Generate ankdctl CLI
    cat > "$ROOTFS/bin/ankctl" << 'ANKCTL_EOF'
#!/bin/sh
#ankctl - Android Konteiner Control
exec /usr/ankd/core/ankd.sh "$@"
ANKCTL_EOF
    chmod +x "$ROOTFS/bin/ankctl" 2>/dev/null

    # Generate default .ankd files based on image type
    _generate_default_ank_files "$ROOTFS" "${TEMPLATE_ID:-$IMAGE}" "$SSH_PORT"

    echo "  ankd installed successfully"
}

# ============================================================
# Generate default .ankd files for templates
# ============================================================
_generate_default_ank_files() {
    local ROOTFS="$1"
    local IMAGE="$2"
    local SSH_PORT="$3"

    # Always create sshd service (first service, order 01)
    cat > "$ROOTFS/etc/ankd/services.d/01-sshd.ankd" <<SSHD_EOF
NAME=sshd
CMD=/usr/sbin/sshd -D -p $SSH_PORT -o PasswordAuthentication=yes -o PermitRootLogin=yes -e
DIR=/
PID_FILE=/run/sshd.pid
STOP_SIGNAL=TERM
RESTART_POLICY=always
RESTART_DELAY=3
SSHD_EOF

    # Create service-specific .ankd file based on image
    local SVC_NAME=""
    local SVC_CMD=""
    local SVC_DIR="/var/www/html"
    local SVC_PORT=""

    case "$IMAGE" in
        nginx*)
            SVC_NAME="nginx"
            SVC_CMD="nginx -g 'daemon off;'"
            SVC_DIR="/var/www/html"
            SVC_PORT="80"
            # Inject daemon off into nginx.conf (avoids quoting issues with -g flag)
            if [ -f "$ROOTFS/etc/nginx/nginx.conf" ]; then
                grep -q "^daemon off" "$ROOTFS/etc/nginx/nginx.conf" 2>/dev/null || \
                    sed -i '1i daemon off;' "$ROOTFS/etc/nginx/nginx.conf" 2>/dev/null
            fi
            ;;
        apache*)
            SVC_NAME="apache"
            SVC_CMD="httpd -f -p 80 -h /var/www/localhost/htdocs"
            SVC_DIR="/var/www/localhost/htdocs"
            SVC_PORT="80"
            ;;
        php*)
            SVC_NAME="php"
            SVC_CMD="php -S 0.0.0.0:80 -t /var/www/php"
            SVC_DIR="/var/www/php"
            SVC_PORT="80"
            ;;
        node*)
            SVC_NAME="node"
            SVC_CMD="node server.js"
            SVC_DIR="/var/www/app"
            SVC_PORT="3000"
            ;;
        python*)
            SVC_NAME="python"
            SVC_CMD="python3 server.py"
            SVC_DIR="/var/www/app"
            SVC_PORT="5000"
            ;;
    esac

    if [ -n "$SVC_NAME" ]; then
        cat > "$ROOTFS/etc/ankd/services.d/02-${SVC_NAME}.ankd" <<SVC_EOF
NAME=$SVC_NAME
CMD=$SVC_CMD
DIR=$SVC_DIR
PID_FILE=/run/${SVC_NAME}.pid
STOP_SIGNAL=TERM
RESTART_POLICY=always
RESTART_DELAY=3
SVC_EOF
        echo "  Generated .ankd files: sshd + $SVC_NAME"
    else
        echo "  Generated .ankd files: sshd only"
    fi
}

# ============================================================
# Container create
# ============================================================
cmd_create() {
    local NAME="$1"
    local IMAGE="${2:-ank-alpinebase-3.20}"
    local ROOT_PASS="${3:-}"
    local SSH_PORT="${4:-}"
    local PKGS="${5:-}"
    local TEMPLATE_ID="${6:-}"
    local CONTAINER_DIR="$CONTAINERS_DIR/$NAME"
    local MODE=$(get_mode)

    # FROM alias: alpine-X.XX -> ank-alpinebase-X.XX (clean alpine has no openssh)
    case "$IMAGE" in
        alpine-*)
            local _ver="${IMAGE#alpine-}"
            IMAGE="ank-alpinebase-${_ver}"
            ;;
    esac

    # Lazy build ank-alpinebase-{version} if missing
    case "$IMAGE" in
        ank-alpinebase-*)
            local _ver="${IMAGE#ank-alpinebase-}"
            _ensure_ankbase "$_ver"
            if [ $? -ne 0 ]; then
                echo "ERROR: Failed to build $IMAGE"
                exit 1
            fi
            ;;
    esac

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

    # If image doesn't exist but has packages, build it from its ank-alpinebase
    if [ ! -d "$BASE_DIR" ] && [ -n "$PKGS" ]; then
        local ANKBASE="$IMAGES_DIR/ank-alpinebase-3.20"
        if [ -d "$ANKBASE" ]; then
            echo "Building image '$IMAGE' from ank-alpinebase (packages: $PKGS)..."
            cp -a "$ANKBASE" "$BASE_DIR" 2>/dev/null
            if [ $? -eq 0 ]; then
                mkdir -p "$BASE_DIR/etc" 2>/dev/null
                echo "nameserver 8.8.8.8" > "$BASE_DIR/etc/resolv.conf" 2>/dev/null
                echo "nameserver 8.8.4.4" >> "$BASE_DIR/etc/resolv.conf" 2>/dev/null
                echo "127.0.0.1 localhost" > "$BASE_DIR/etc/hosts" 2>/dev/null
                # Mount tmpfs on /dev for chroot (kernel 3.10 + nodev workaround)
                mkdir -p "$BASE_DIR/dev/pts" 2>/dev/null
                umount "$BASE_DIR/dev" 2>/dev/null
                mount -t tmpfs -o size=16m tmpfs "$BASE_DIR/dev" 2>/dev/null
                [ -e "$BASE_DIR/dev/null" ] || mknod "$BASE_DIR/dev/null" c 1 3 2>/dev/null
                chmod 666 "$BASE_DIR/dev/null" 2>/dev/null
                [ -e "$BASE_DIR/dev/urandom" ] || mknod "$BASE_DIR/dev/urandom" c 1 9 2>/dev/null
                chmod 666 "$BASE_DIR/dev/urandom" 2>/dev/null
                mount -t proc proc "$BASE_DIR/proc" 2>/dev/null
                chroot "$BASE_DIR" /sbin/apk add --no-cache $PKGS 2>/dev/null
                local apk_rc=$?
                umount "$BASE_DIR/proc" 2>/dev/null
                umount "$BASE_DIR/dev" 2>/dev/null
                if [ $apk_rc -eq 0 ]; then
                    echo "Image '$IMAGE' built successfully"
                    # Setup default content + service marker for template
                    _setup_template_service "$BASE_DIR" "$IMAGE"
                else
                    echo "WARN: Some packages may have failed for '$IMAGE'"
                fi
            else
                echo "WARN: Failed to copy ank-alpinebase for '$IMAGE', using base"
                BASE_DIR="$ANKBASE"
            fi
        else
            echo "WARN: ank-alpinebase not found, cannot build '$IMAGE'"
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

    # Port allocation - find first free port
    local ORIG_PORT="$SSH_PORT"
    while true; do
        local PORT_IN_USE=0
        for cfg in "$CONTAINERS_DIR"/*/config.json; do
            [ -f "$cfg" ] || continue
            local existing_port=$(grep -o '"ssh_port":[^,]*' "$cfg" 2>/dev/null | cut -d: -f2 | tr -d ' ')
            if [ "$existing_port" = "$SSH_PORT" ]; then
                PORT_IN_USE=1
                break
            fi
        done
        [ "$PORT_IN_USE" -eq 0 ] && break
        SSH_PORT=$((SSH_PORT + 1))
        [ "$SSH_PORT" -gt 65000 ] && SSH_PORT="$ORIG_PORT" && break
    done
    if [ "$SSH_PORT" != "$ORIG_PORT" ]; then
        echo "WARN: Port $ORIG_PORT in use, using $SSH_PORT instead"
    fi

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

    # Setup rootfs (ank-alpinebase-3.20 already has openssh/bash/busybox/shadow)
    local ROOTFS="$CONTAINER_DIR/merged"
    echo "Setting up container: $NAME..."
    # Ensure DNS works inside chroot
    mkdir -p "$ROOTFS/etc" 2>/dev/null
    echo "nameserver 8.8.8.8" > "$ROOTFS/etc/resolv.conf" 2>/dev/null
    echo "nameserver 8.8.4.4" >> "$ROOTFS/etc/resolv.conf" 2>/dev/null
    # Ensure /dev/null exists (on tmpfs for nodev workaround)
    mkdir -p "$ROOTFS/dev/pts" "$ROOTFS/dev/shm" 2>/dev/null
    umount "$ROOTFS/dev" 2>/dev/null
    mount -t tmpfs -o size=16m tmpfs "$ROOTFS/dev" 2>/dev/null
    for node_info in "null:1:3" "zero:1:5" "random:1:8" "urandom:1:9" "tty:5:0" "ptmx:5:2" "console:5:1"; do
        local _n=$(echo "$node_info" | cut -d: -f1)
        local _t=$(echo "$node_info" | cut -d: -f2)
        local _m=$(echo "$node_info" | cut -d: -f3)
        [ -e "$ROOTFS/dev/$_n" ] || mknod "$ROOTFS/dev/$_n" c "$_t" "$_m" 2>/dev/null
        chmod 666 "$ROOTFS/dev/$_n" 2>/dev/null
    done

    # Install ankd service manager
    _install_ankd "$ROOTFS" "$NAME" "$IMAGE" "$SSH_PORT" "$TEMPLATE_ID"
    # Set root password — use host openssl via musl linker (no chroot needed)
    if [ -n "$ROOT_PASS" ]; then
        local ENC_PASS=""
        local MUSL=$(find "$ANK_DIR/ankfs/lib" -name "ld-musl-*.so*" 2>/dev/null | head -1)
        local HOST_SSL=""
        for op in "$ANK_DIR/ankfs/usr/bin/openssl" "$ANK_DIR/ankfs/usr/sbin/openssl"; do
            [ -f "$op" ] && HOST_SSL="$op" && break
        done
        if [ -n "$HOST_SSL" ] && [ -n "$MUSL" ]; then
            ENC_PASS=$(LD_LIBRARY_PATH="$ANK_DIR/ankfs/usr/lib:$ANK_DIR/ankfs/lib" "$MUSL" "$HOST_SSL" passwd -1 "$ROOT_PASS" 2>/dev/null)
        fi
        if [ -n "$ENC_PASS" ] && [ -f "$ROOTFS/etc/shadow" ]; then
            sed -i "s|^root:[^:]*:|root:${ENC_PASS}:|" "$ROOTFS/etc/shadow" 2>/dev/null
            echo "Password set via shadow"
        else
            echo "WARN: Could not set password (openssl hash failed)"
        fi
    fi
    echo "Container ready: $NAME"

    # Create config with SSH info
    local INSTANCE_UUID=$(cat /dev/urandom 2>/dev/null | head -c 3 | od -An -tx1 | tr -d ' \n' | head -c 6)
    [ -z "$INSTANCE_UUID" ] && INSTANCE_UUID=$(printf "%06x" $((RANDOM % 16777216)))
    cat > "$CONTAINER_DIR/config.json" << CFGEOF
{
  "name": "$NAME",
  "instance_uuid": "$INSTANCE_UUID",
  "status": "building",
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
    local IMAGE=$(grep -o '"image":[^,]*' "$CONFIG" 2>/dev/null | cut -d'"' -f4)
    local TEMPLATE_ID=$(grep -o '"template_id":[^,]*' "$CONFIG" 2>/dev/null | cut -d'"' -f4)

    echo "Starting container: $NAME (mode: $MODE, port: $SSH_PORT)"

    # Ensure nginx runs in foreground (daemon off) — inject at start time
    # for both new and existing containers
    case "${TEMPLATE_ID:-$IMAGE}" in
        nginx*)
            if [ -f "$ROOTFS/etc/nginx/nginx.conf" ]; then
                grep -q "^daemon off" "$ROOTFS/etc/nginx/nginx.conf" 2>/dev/null || \
                    sed -i '1i daemon off;' "$ROOTFS/etc/nginx/nginx.conf" 2>/dev/null
            fi
            ;;
    esac

    # Ensure .ankd service files exist (regenerate for containers created with older code)
    if [ -d "$ROOTFS/etc/ankd/services.d" ]; then
        local ANKD_COUNT=$(ls "$ROOTFS/etc/ankd/services.d/"*.ankd 2>/dev/null | wc -l)
        if [ "$ANKD_COUNT" -eq 0 ]; then
            echo "  Regenerating .ankd service files..."
            _generate_default_ank_files "$ROOTFS" "${TEMPLATE_ID:-$IMAGE}" "$SSH_PORT"
        fi
    fi

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

    # Mount tmpfs on /dev before any mknod (kernel 3.10 + nodev workaround)
    mkdir -p "$ROOTFS/dev/pts" "$ROOTFS/dev/shm" "$ROOTFS/run/sshd" 2>/dev/null
    umount "$ROOTFS/dev" 2>/dev/null
    mount -t tmpfs -o size=16m tmpfs "$ROOTFS/dev" 2>/dev/null
    for node_info in "null:1:3" "zero:1:5" "random:1:8" "urandom:1:9" "tty:5:0" "ptmx:5:2" "console:5:1"; do
        local _n=$(echo "$node_info" | cut -d: -f1)
        local _t=$(echo "$node_info" | cut -d: -f2)
        local _m=$(echo "$node_info" | cut -d: -f3)
        mknod "$ROOTFS/dev/$_n" c "$_t" "$_m" 2>/dev/null
        chmod 666 "$ROOTFS/dev/$_n" 2>/dev/null
    done
    mount -t devpts devpts "$ROOTFS/dev/pts" 2>/dev/null
    mount -t tmpfs -o size=16m tmpfs "$ROOTFS/dev/shm" 2>/dev/null

    # Set root password before starting sshd
    local ROOT_PASS=$(tr -d ' ' < "$CONFIG" 2>/dev/null | grep -o '"root_password":"[^"]*"' | cut -d'"' -f4)
    if [ -n "$ROOT_PASS" ]; then
        echo "  Setting root password..."
        # Generate hash using host openssl via musl linker (no chroot needed)
        local ENC_PASS=""
        local MUSL=$(find "$ANK_DIR/ankfs/lib" -name "ld-musl-*.so*" 2>/dev/null | head -1)
        local HOST_SSL=""
        for op in "$ANK_DIR/ankfs/usr/bin/openssl" "$ANK_DIR/ankfs/usr/sbin/openssl"; do
            [ -f "$op" ] && HOST_SSL="$op" && break
        done
        if [ -n "$HOST_SSL" ] && [ -n "$MUSL" ]; then
            ENC_PASS=$(LD_LIBRARY_PATH="$ANK_DIR/ankfs/usr/lib:$ANK_DIR/ankfs/lib" "$MUSL" "$HOST_SSL" passwd -1 "$ROOT_PASS" 2>/dev/null)
        fi
        if [ -n "$ENC_PASS" ] && [ -f "$ROOTFS/etc/shadow" ]; then
            sed -i "s|^root:[^:]*:|root:${ENC_PASS}:|" "$ROOTFS/etc/shadow" 2>/dev/null
            echo "  Password set via shadow (openssl hash)"
        elif [ -f "$ROOTFS/etc/shadow" ]; then
            # Fallback: use busybox openssl inside container
            mount -t proc proc "$ROOTFS/proc" 2>/dev/null
            ENC_PASS=$(chroot "$ROOTFS" /usr/bin/openssl passwd -1 "$ROOT_PASS" 2>/dev/null)
            if [ -n "$ENC_PASS" ]; then
                sed -i "s|^root:[^:]*:|root:${ENC_PASS}:|" "$ROOTFS/etc/shadow" 2>/dev/null
                echo "  Password set via shadow (chroot openssl)"
            fi
            umount "$ROOTFS/proc" 2>/dev/null
        fi
        # Final fallback: try chpasswd (check both /usr/bin and /usr/sbin)
        if ! grep -q 'root:\$' "$ROOTFS/etc/shadow" 2>/dev/null; then
            mount -t proc proc "$ROOTFS/proc" 2>/dev/null
            local CP=""
            for cp in "$ROOTFS/usr/sbin/chpasswd" "$ROOTFS/usr/bin/chpasswd"; do
                [ -f "$cp" ] && CP="$cp" && break
            done
            if [ -n "$CP" ]; then
                echo "root:$ROOT_PASS" | chroot "$ROOTFS" "$CP" 2>/dev/null
                echo "  Password set via chpasswd"
            else
                echo "  ERROR: Could not set password (no chpasswd found)"
            fi
            umount "$ROOTFS/proc" 2>/dev/null
        fi
    fi

    # Init script: start sshd as PID 1
    # In shared_host/isolated modes, sshd listens on SSH_PORT directly (no DNAT needed)
    local SSHD_PORT=22
    if [ "$MODE" = "shared_host" ] || [ "$MODE" = "isolated" ] || [ "$MODE" = "shared_network" ]; then
        if [ -n "$SSH_PORT" ] && [ "$SSH_PORT" != "null" ]; then
            SSHD_PORT="$SSH_PORT"
        fi
    fi

    # Cleanup stale PID files and temp files from previous run
    rm -f "$ROOTFS/run/nginx.pid" "$ROOTFS/run/nginx.lock" 2>/dev/null
    rm -f "$ROOTFS/run/sshd.pid" "$ROOTFS/run/sshd.pid.lock" 2>/dev/null
    rm -f "$ROOTFS/tmp/"*.sock 2>/dev/null
    # Ensure /run exists for PID files
    mkdir -p "$ROOTFS/run" 2>/dev/null

    # Check if ankd service manager is installed
    if [ -x "$ROOTFS/usr/ankd/core/ankd.sh" ]; then
        # Update ankd.sh from host (in case of upgrades)
        local ANKD_SRC="$SCRIPTS_DIR/ankd/ankd.sh"
        [ -f "$ANKD_SRC" ] && cp "$ANKD_SRC" "$ROOTFS/usr/ankd/core/ankd.sh" 2>/dev/null
        echo "  Using ankd service manager"
        local INSTANCE_UUID=$(grep -o '"instance_uuid": *"[^"]*"' "$CONFIG" 2>/dev/null | cut -d'"' -f4)
        CONTAINER_INIT="export PATH=/bin:/sbin:/usr/bin:/usr/sbin; ANKD_CONTAINER=$NAME ANKD_SSHD_PORT=$SSHD_PORT ANKD_INSTANCE_UUID=${INSTANCE_UUID:-$NAME} /usr/ankd/core/ankd.sh daemon"
    else
        # Fallback: legacy inline init
        echo "  WARN: ankd not installed, using legacy init"
        CONTAINER_INIT='
            export PATH=/bin:/sbin:/usr/bin:/usr/sbin
            trap "" HUP PIPE
            _ank_exit=0
            trap "_ank_exit=1" TERM INT
            echo "[ANK-INIT] Mounting filesystems..."
            mkdir -p /dev/pts /dev/shm /run/sshd 2>/dev/null
            mount -t proc proc /proc 2>/dev/null
            mount -t sysfs sysfs /sys 2>/dev/null
            mount -t devpts devpts /dev/pts 2>/dev/null || true
            hostname CONTAINER_NAME_PLACEHOLDER 2>/dev/null
            cd /root 2>/dev/null || cd /
            echo "[ANK-INIT] Starting sshd on port CONTAINER_SSHD_PORT..."
            if [ -x /usr/sbin/sshd ]; then
                ssh-keygen -A 2>/dev/null
                /usr/sbin/sshd -D -p CONTAINER_SSHD_PORT -o PasswordAuthentication=yes -o PermitRootLogin=yes -o PidFile=/run/sshd.pid -e 2>/dev/null &
                _sshd_pid=$!
                echo "[ANK-INIT] sshd started (PID: $_sshd_pid)"
            else
                echo "[ANK-INIT] WARN: sshd not found"
            fi
            if [ -f /etc/ank/service ]; then
                _svc=$(cat /etc/ank/service 2>/dev/null)
                echo "[ANK-INIT] Starting service: $_svc"
                case "$_svc" in
                    nginx)  mkdir -p /run/nginx 2>/dev/null; nginx 2>/dev/null & ;;
                    apache) httpd -f -p 80 -h /var/www/localhost/htdocs 2>/dev/null & ;;
                    php)    php -S 0.0.0.0:80 -t /var/www/php 2>/dev/null & ;;
                    node)   cd /var/www/app 2>/dev/null; node server.js 2>/dev/null & ;;
                    python) cd /var/www/app 2>/dev/null; python3 server.py 2>/dev/null & ;;
                    *)      echo "[ANK-INIT] Unknown service: $_svc" ;;
                esac
            fi
            echo "[ANK-INIT] Container ready"
            while [ "$_ank_exit" = "0" ]; do
                if [ -n "$_sshd_pid" ] && ! kill -0 "$_sshd_pid" 2>/dev/null; then
                    echo "[ANK-INIT] sshd died, exiting..."
                    break
                fi
                /bin/busybox sleep 5 2>/dev/null || /bin/sleep 5 2>/dev/null || true
            done
        '
        CONTAINER_INIT=$(echo "$CONTAINER_INIT" | sed "s/CONTAINER_NAME_PLACEHOLDER/$NAME/g")
        CONTAINER_INIT=$(echo "$CONTAINER_INIT" | sed "s/CONTAINER_SSHD_PORT/$SSHD_PORT/g")
    fi

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

    # Setup service port forwarding (nginx=80, apache/php=80, node=3000, python=5000)
    local SVC_PORT=""
    local IMAGE=$(grep -o '"image":"[^"]*"' "$CONFIG" | cut -d'"' -f4)
    case "$IMAGE" in
        nginx*) SVC_PORT="80" ;;
        apache*|php*) SVC_PORT="80" ;;
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

    # Apply custom port_mappings from config.json (overrides hardcoded service ports)
    local HAS_CUSTOM_PORTS=$(grep -o '"host_port"' "$CONFIG" 2>/dev/null | head -1)
    if [ -n "$HAS_CUSTOM_PORTS" ]; then
        if [ "$MODE" = "isolated" ]; then
            sh "$SCRIPTS_DIR/network.sh" apply_ports "$NAME" 2>/dev/null
            echo "Custom port mappings applied from config.json"
        fi
    fi

    # Update config
    sed -i "s/\"status\": \"[^\"]*\"/\"status\": \"running\"/" "$CONFIG"
    sed -i "s/\"pid\": [^,]*/\"pid\": $PID/" "$CONFIG"

    # Scan and record all container processes in ank.procs
    sleep 1
    _scan_container_procs "$NAME"

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
    if [ "$STATUS" = "stopped" ] || [ "$STATUS" = "building" ] || [ "$STATUS" = "failed" ]; then
        echo "Container '$NAME' is not running (status: $STATUS)"
        return 0
    fi

    local SSH_PORT=$(grep -o '"ssh_port":[^,]*' "$CONFIG" | cut -d: -f2 | tr -d ' ')
    local PID=$(grep -o '"pid": [^,]*' "$CONFIG" | cut -d' ' -f2)

    echo "Stopping container: $NAME"

    # Write shutdown message to log
    local LOG_FILE="$ANK_DIR/logs/${NAME}.log"
    if [ -f "$LOG_FILE" ]; then
        local ts=$(date "+%H:%M:%S" 2>/dev/null || echo "??:??:??")
        echo "[boot] $ts Stopping services..." >> "$LOG_FILE"
    fi

    local ROOTFS="$CONTAINER_DIR/merged"
    local KILL_COUNT=0

    # ============================================================
    # PHASE 0: Kill ankd daemon FIRST to stop restart loop
    # ============================================================
    echo "  Stopping ankd daemon..."
    if [ -n "$PID" ] && [ "$PID" != "null" ]; then
        kill -9 "$PID" 2>/dev/null
        echo "    ankd daemon killed"
    fi

    # ============================================================
    # PHASE 1: Kill all services by PGID, read straight from the pgid
    # registry ankd keeps under the container's own rootfs
    # (containers/<name>/merged/etc/ankd/pids/*.pgid). That directory is
    # real disk (/etc), not tmpfs, so it's directly visible from the host
    # with no bind mount and no need to grep `ps` for a tag. Every ankd
    # service is started via setsid, so its recorded pid is simultaneously
    # its PGID: one "kill -9 -PGID" takes down the master and every forked
    # child (nginx workers included) in one shot.
    # ============================================================
    echo "  Stopping services..."

    local ANKD_PIDS_DIR="$ROOTFS/etc/ankd/pids"
    if [ -d "$ANKD_PIDS_DIR" ]; then
        for pgid_file in "$ANKD_PIDS_DIR"/*.pgid; do
            [ -f "$pgid_file" ] || continue
            local svc_uuid=$(basename "$pgid_file" .pgid)
            local pgid=$(cat "$pgid_file" 2>/dev/null)
            [ -z "$pgid" ] && continue
            kill -9 -- "-$pgid" 2>/dev/null && KILL_COUNT=$((KILL_COUNT+1))
            kill -9 "$pgid" 2>/dev/null
            rm -f "$pgid_file" 2>/dev/null
            echo "    Stopped service $svc_uuid (PGID $pgid)"
        done
    fi

    # ============================================================
    # PHASE 2: Safety-net sweep for anything that escaped its process
    # group (e.g. an interactive sshd login session that called its own
    # setsid). Uses readlink on /proc/*/root and /proc/*/exe only - cheap
    # single syscalls that hold up fine under Android's SELinux, unlike
    # reading /proc/*/cmdline or /proc/*/environ content which is what was
    # unreliable/slow before. Runs once here at teardown, not in any
    # polling loop, so the cost is a non-issue.
    # ============================================================
    echo "  Sweeping remaining processes..."
    local SWEEP_COUNT=0
    for pid_dir in /proc/[0-9]*; do
        local p=$(basename "$pid_dir" 2>/dev/null)
        [ -z "$p" ] && continue
        [ "$p" = "1" ] && continue
        local root=$(readlink "$pid_dir/root" 2>/dev/null)
        local exe=$(readlink "$pid_dir/exe" 2>/dev/null)
        local belongs=0
        case "$root" in ${ROOTFS}|${ROOTFS}/) belongs=1 ;; esac
        case "$exe" in ${ROOTFS}/*) belongs=1 ;; esac
        [ "$belongs" -eq 1 ] && {
            kill -9 "$p" 2>/dev/null && SWEEP_COUNT=$((SWEEP_COUNT+1))
        }
    done
    # Second pass: catch processes via mount namespace (handles SELinux readlink blocks)
    local MY_MNT=""
    [ -d "/proc/1/ns/mnt" ] && MY_MNT=$(readlink /proc/1/ns/mnt 2>/dev/null)
    if [ -n "$MY_MNT" ]; then
        for pid_dir in /proc/[0-9]*; do
            local p=$(basename "$pid_dir" 2>/dev/null)
            [ -z "$p" ] && continue
            [ "$p" = "1" ] && continue
            local their_mnt=$(readlink "$pid_dir/ns/mnt" 2>/dev/null)
            [ "$their_mnt" = "$MY_MNT" ] && continue
            local exe=$(readlink "$pid_dir/exe" 2>/dev/null)
            case "$exe" in
                */sshd|*/nginx|*/busybox*)
                    kill -9 "$p" 2>/dev/null && SWEEP_COUNT=$((SWEEP_COUNT+1))
                    ;;
            esac
        done
    fi
    [ "$SWEEP_COUNT" -gt 0 ] && echo "    Cleaned $SWEEP_COUNT remaining process(es)"

    # Brief wait for zombie reaping
    [ "$SWEEP_COUNT" -gt 0 ] && sleep 1

    # ============================================================
    # PHASE 3: Unmount ALL chroot mounts
    # ============================================================
    echo "  Unmounting filesystems..."
    _unmount_container "$NAME"
    echo "    Filesystems unmounted"

    # ============================================================
    # PHASE 4: Remove iptables rules
    # ============================================================
    echo "  Removing network rules..."
    _remove_container_rules "$NAME"
    echo "    Network rules removed"

    # ============================================================
    # PHASE 5: Destroy network namespace
    # ============================================================
    echo "  Destroying network namespace..."
    local MODE=$(get_mode)
    if [ "$MODE" = "isolated" ]; then
        sh "$SCRIPTS_DIR/network.sh" destroy "$NAME" 2>/dev/null
    else
        sh "$SCRIPTS_DIR/network.sh" destroy_compat "$NAME" 2>/dev/null
    fi
    echo "    Network namespace destroyed"

    # ============================================================
    # PHASE 6: Remove cgroup
    # ============================================================
    echo "  Cleaning cgroup..."
    rmdir "/sys/fs/cgroup/ank/$NAME" 2>/dev/null

    # ============================================================
    # PHASE 7: Cleanup
    # ============================================================
    echo "  Final cleanup..."
    rm -f "$CONTAINER_DIR/ank.procs"

    # Update config
    sed -i "s/\"status\": \"[^\"]*\"/\"status\": \"stopped\"/" "$CONFIG"
    sed -i "s/\"pid\": [^,]*/\"pid\": null/" "$CONFIG"

    echo ""
    echo "Container '$NAME' stopped"
    echo "  Total processes killed: $KILL_COUNT"
    return 0
}

# ============================================================
# Scan processes belonging to container and write ank.procs
# ============================================================
_scan_container_procs() {
    local NAME="$1"
    local CONTAINER_DIR="$CONTAINERS_DIR/$NAME"
    local ROOTFS="$CONTAINER_DIR/merged"
    local PROCS_FILE="$CONTAINER_DIR/ank.procs"
    local CONFIG="$CONTAINER_DIR/config.json"
    local SSH_PORT=$(grep -o '"ssh_port":[^,]*' "$CONFIG" 2>/dev/null | cut -d: -f2 | tr -d ' ')

    echo "# Autogenerated Ank Procs - DO NOT EDIT" > "$PROCS_FILE"

    # Scan /proc for processes belonging to this container
    for pid_dir in /proc/[0-9]*; do
        local pid=$(basename "$pid_dir" 2>/dev/null)
        [ -z "$pid" ] && continue

        # Method 1: Check if root link matches container rootfs
        local root=$(readlink "$pid_dir/root" 2>/dev/null)
        local exe=$(readlink "$pid_dir/exe" 2>/dev/null)
        local cmdline=$(tr '\0' ' ' < "$pid_dir/cmdline" 2>/dev/null)

        local belongs=0
        case "$root" in ${ROOTFS}|${ROOTFS}/) belongs=1 ;; esac
        case "$exe" in ${ROOTFS}/*) belongs=1 ;; esac
        # Also check sshd port pattern in cmdline
        if [ -n "$SSH_PORT" ] && echo "$cmdline" | grep -q "sshd.*-p.*${SSH_PORT}"; then
            belongs=1
        fi

        if [ "$belongs" -eq 1 ]; then
            local app_name=$(cat "$pid_dir/comm" 2>/dev/null || echo "unknown")
            echo "${pid}:${app_name}" >> "$PROCS_FILE"
        fi
    done

    local proc_count=$(tail -n +2 "$PROCS_FILE" 2>/dev/null | wc -l)
    echo "  ank.procs: $proc_count processes recorded"
}

# ============================================================
# Kill ALL processes from ank.procs
# ============================================================
_kill_container_procs() {
    local NAME="$1"
    local CONTAINER_DIR="$CONTAINERS_DIR/$NAME"
    local CONFIG="$CONTAINER_DIR/config.json"
    local SSH_PORT=$(grep -o '"ssh_port":[^,]*' "$CONFIG" 2>/dev/null | cut -d: -f2 | tr -d ' ')
    local PID=$(grep -o '"pid": [^,]*' "$CONFIG" 2>/dev/null | cut -d' ' -f2)
    local KILL_COUNT=0

    # Phase 1: Kill entire process tree from main PID (recursive)
    if [ -n "$PID" ] && [ "$PID" != "null" ] && kill -0 "$PID" 2>/dev/null; then
        # Get ALL descendant PIDs using recursive children scan
        local ALL_PIDS="$PID"
        local QUEUE="$PID"
        while [ -n "$QUEUE" ]; do
            local current=$(echo "$QUEUE" | head -1)
            QUEUE=$(echo "$QUEUE" | tail -n +2)
            local children=$(ps -o pid= --ppid "$current" 2>/dev/null)
            for child in $children; do
                ALL_PIDS="$ALL_PIDS $child"
                QUEUE="$QUEUE $child"
            done
        done
        for p in $ALL_PIDS; do
            kill -9 "$p" 2>/dev/null && KILL_COUNT=$((KILL_COUNT+1))
        done
        echo "  Killed PID tree from $PID ($KILL_COUNT processes)"
    fi

    # Phase 2: Kill by cgroup
    if [ -d "/sys/fs/cgroup/ank/$NAME" ]; then
        while read -r cpid; do
            [ -z "$cpid" ] && continue
            kill -9 "$cpid" 2>/dev/null && KILL_COUNT=$((KILL_COUNT+1))
        done < "/sys/fs/cgroup/ank/$NAME/cgroup.procs" 2>/dev/null
    fi

    # Phase 3: Kill ANK services by PGID registry (etc/ankd/pids/*.pgid on
    # real disk, host-visible, no /proc scanning needed - see cmd_stop)
    local ANKD_PIDS_DIR="$CONTAINER_DIR/merged/etc/ankd/pids"
    if [ -d "$ANKD_PIDS_DIR" ]; then
        for pgid_file in "$ANKD_PIDS_DIR"/*.pgid; do
            [ -f "$pgid_file" ] || continue
            local pgid=$(cat "$pgid_file" 2>/dev/null)
            [ -z "$pgid" ] && continue
            kill -9 -- "-$pgid" 2>/dev/null && KILL_COUNT=$((KILL_COUNT+1))
            kill -9 "$pgid" 2>/dev/null
            rm -f "$pgid_file" 2>/dev/null
        done
    fi

    # Phase 4: Sweep - kill any remaining process in container rootfs
    local ROOTFS="$CONTAINER_DIR/merged"
    for pid_dir in /proc/[0-9]*; do
        local pid=$(basename "$pid_dir" 2>/dev/null)
        [ -z "$pid" ] && continue
        local root=$(readlink "$pid_dir/root" 2>/dev/null)
        local exe=$(readlink "$pid_dir/exe" 2>/dev/null)
        local cwd=$(readlink "$pid_dir/cwd" 2>/dev/null)
        case "$root" in ${ROOTFS}|${ROOTFS}/) kill -9 "$pid" 2>/dev/null && KILL_COUNT=$((KILL_COUNT+1)) ;; esac
        case "$exe" in ${ROOTFS}/*) kill -9 "$pid" 2>/dev/null && KILL_COUNT=$((KILL_COUNT+1)) ;; esac
        case "$cwd" in ${ROOTFS}|${ROOTFS}/) kill -9 "$pid" 2>/dev/null && KILL_COUNT=$((KILL_COUNT+1)) ;; esac
    done

    echo "  Total killed: $KILL_COUNT processes"
}

# ============================================================
# Unmount ALL container mounts
# ============================================================
_unmount_container() {
    local NAME="$1"
    local CONTAINER_DIR="$CONTAINERS_DIR/$NAME"
    local ROOTFS="$CONTAINER_DIR/merged"

    echo "  Unmounting filesystems..."
    umount "$ROOTFS/dev/pts" 2>/dev/null
    umount "$ROOTFS/dev/shm" 2>/dev/null
    umount "$ROOTFS/dev" 2>/dev/null
    umount "$ROOTFS/proc" 2>/dev/null
    umount "$ROOTFS/sys" 2>/dev/null
    # Lazy unmount if still busy
    umount -l "$ROOTFS/dev/pts" 2>/dev/null
    umount -l "$ROOTFS/dev/shm" 2>/dev/null
    umount -l "$ROOTFS/dev" 2>/dev/null
    umount -l "$ROOTFS/proc" 2>/dev/null
    umount -l "$ROOTFS/sys" 2>/dev/null
    umount -l "$ROOTFS" 2>/dev/null
    echo "  Filesystems unmounted"
}

# ============================================================
# Remove ALL iptables rules for container
# ============================================================
_remove_container_rules() {
    local NAME="$1"
    local CONTAINER_DIR="$CONTAINERS_DIR/$NAME"
    local CONFIG="$CONTAINER_DIR/config.json"
    local SSH_PORT=$(grep -o '"ssh_port":[^,]*' "$CONFIG" 2>/dev/null | cut -d: -f2 | tr -d ' ')
    local IP=$(grep -o '"ip_address":[^,]*' "$CONFIG" 2>/dev/null | cut -d'"' -f4)
    local IMAGE=$(grep -o '"image":"[^"]*"' "$CONFIG" 2>/dev/null | cut -d'"' -f4)
    local MODE=$(get_mode)

    # SSH port forwarding
    if [ -n "$SSH_PORT" ] && [ "$SSH_PORT" != "null" ] && [ -n "$IP" ] && [ "$IP" != "none" ]; then
        if [ "$MODE" = "isolated" ]; then
            remove_ssh_forward "$IP" "$SSH_PORT" 2>/dev/null
        fi
        iptables -t nat -D PREROUTING -p tcp --dport "$SSH_PORT" -j REDIRECT --to-port 22 2>/dev/null
        iptables -t nat -D PREROUTING -p tcp --dport "$SSH_PORT" -j DNAT --to-destination "${IP}:22" 2>/dev/null
        iptables -D FORWARD -p tcp -d "$IP" --dport 22 -j ACCEPT 2>/dev/null
    fi

    # Service port forwarding
    local SVC_PORT=""
    case "$IMAGE" in
        nginx*) SVC_PORT="80" ;;
        apache*|php*) SVC_PORT="80" ;;
        node*) SVC_PORT="3000" ;;
        python*) SVC_PORT="5000" ;;
    esac
    if [ -n "$SVC_PORT" ] && [ -n "$IP" ] && [ "$IP" != "none" ]; then
        if [ "$MODE" = "isolated" ]; then
            iptables -t nat -D PREROUTING -p tcp --dport "$SVC_PORT" -j DNAT --to-destination "${IP}:${SVC_PORT}" 2>/dev/null
            iptables -D FORWARD -p tcp -d "$IP" --dport "$SVC_PORT" -j ACCEPT 2>/dev/null
        fi
    fi

    # Custom port mappings
    if [ "$MODE" = "isolated" ]; then
        sh "$SCRIPTS_DIR/network.sh" remove_ports "$NAME" 2>/dev/null
    fi
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
    _kill_container_procs "$NAME"

    # Unmount everything
    _unmount_container "$NAME"

    # Remove iptables rules
    _remove_container_rules "$NAME"

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
    create)  cmd_create "$NAME" "$3" "$4" "$5" "$6" "$7" ;;
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

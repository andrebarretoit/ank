#!/usr/bin/env python3
"""
ANK - Android Konteiner
API Server - runs on host via musl linker
"""

import os
import json
import subprocess
import time
import signal
import sys
import base64
import secrets
import hashlib
import ssl
import struct
import threading
import select
import glob
try:
    import pty
    HAS_PTY = True
except ImportError:
    HAS_PTY = False
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime, timedelta

_port_lock = threading.Lock()
_build_lock = threading.Lock()
_building = False

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
ANK_SDCARD = "/sdcard/AndroidKonteiner"
CONTAINERS_DIR = os.path.join(ANK_DIR, "containers")
IMAGES_DIR = os.path.join(ANK_DIR, "images")
SCRIPTS_DIR = os.path.join(ANK_DIR, "core")
CONFIG_FILE = os.path.join(ANK_DIR, "config.json")
STATIC_DIR = os.path.join(ANK_DIR, "ankfs/opt/ank/static")
PORT = 8001

_device_cache = None

_cpu_usage_cache = 0.0
_disk_usage_cache = {"total": 0, "used": 0, "free": 0}

def _cpu_sampler_loop():
    global _cpu_usage_cache
    while True:
        try:
            with open("/proc/stat", "r") as f:
                parts = f.readline().split()
            idle1 = int(parts[4])
            total1 = sum(int(x) for x in parts[1:])
            time.sleep(3)
            with open("/proc/stat", "r") as f:
                parts = f.readline().split()
            idle2 = int(parts[4])
            total2 = sum(int(x) for x in parts[1:])
            _cpu_usage_cache = round((1 - (idle2 - idle1) / (total2 - total1)) * 100, 1) if total2 > total1 else 0
        except Exception:
            time.sleep(10)

def _get_disk_usage():
    """Call disk.sh to get accurate disk usage (total/used/free in GB)."""
    script = os.path.join(SCRIPTS_DIR, "disk.sh")
    if not os.path.isfile(script):
        return {"total": 0, "used": 0, "free": 0}
    try:
        result = subprocess.run(
            ["/system/bin/sh", script],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            # Output: "229.6 GB|52.2 GB|177.3 GB"
            parts = result.stdout.strip().split("|")
            if len(parts) == 3:
                def parse_gb(s):
                    s = s.strip().replace(" GB", "")
                    return float(s)
                total = parse_gb(parts[0])
                used = parse_gb(parts[1])
                free = parse_gb(parts[2])
                return {"total": total, "used": used, "free": free}
    except Exception:
        pass
    return {"total": 0, "used": 0, "free": 0}

_cpu_thread = threading.Thread(target=_cpu_sampler_loop, daemon=True)
_cpu_thread.start()

# ============================================================
# Security: Token storage, rate limiting, client detection
# ============================================================

_tokens = {}  # {token: {"user": str, "expires": float}}
_tokens_lock = threading.Lock()
_login_attempts = {}  # {ip: [timestamp, ...]}
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = 300  # 5 minutes
TOKEN_EXPIRY_HOURS = 24

def _generate_token():
    return secrets.token_hex(32)

def _check_rate_limit(ip):
    now = time.time()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < RATE_LIMIT_WINDOW]
    _login_attempts[ip] = attempts
    if len(attempts) >= RATE_LIMIT_MAX:
        return False
    attempts.append(now)
    _login_attempts[ip] = attempts
    return True

def _create_token(user):
    token = _generate_token()
    expires = time.time() + (TOKEN_EXPIRY_HOURS * 3600)
    with _tokens_lock:
        _tokens[token] = {"user": user, "expires": expires}
    return token

def _validate_token(token):
    if not token:
        return False
    with _tokens_lock:
        info = _tokens.get(token)
        if not info:
            return False
        if time.time() > info["expires"]:
            del _tokens[token]
            return False
    return True

def _detect_client(handler):
    """Detect client type: browser, panel, cli, installer, unknown"""
    try:
        accept = handler.headers.get('Accept', '')
    except AttributeError:
        accept = ''
    try:
        x_client = handler.headers.get('X-ANK-Client', '')
    except AttributeError:
        x_client = ''
    if 'text/html' in accept and not x_client:
        return 'browser'
    clients = {'ank-panel': 'panel', 'ank-cli': 'cli', 'ank-installer': 'installer'}
    return clients.get(x_client, 'unknown')

def _get_client_token(handler):
    """Extract Bearer token from Authorization header"""
    auth = handler.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth[7:]
    return None

def _check_auth(handler):
    """Check authentication: token-based for API clients, reject browsers"""
    client = _detect_client(handler)
    if client == 'browser':
        return 'browser'
    token = _get_client_token(handler)
    if _validate_token(token):
        return 'authorized'
    return 'unauthorized'

def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"version": "2.0.0", "panel_port": 8001, "username": "admin",
                "password": "admin123", "first_boot": True,
                "network": {"bridge": "ank0", "subnet": "10.20.30.0", "gateway": "10.20.30.1", "nat": True}}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o666)
    except Exception:
        pass

def load_container_config(name):
    path = os.path.join(CONTAINERS_DIR, name, "config.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def save_container_config(name, config):
    path = os.path.join(CONTAINERS_DIR, name, "config.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
    try:
        os.chmod(path, 0o666)
    except Exception:
        pass

def run_script(script, *args, timeout=60):
    script_path = os.path.join(SCRIPTS_DIR, script)
    cmd_parts = ["/system/bin/sh", script_path] + list(args)
    cmd_str = " ".join(f"'{a}'" for a in cmd_parts)
    try:
        if os.geteuid() != 0:
            result = subprocess.run(
                ["su", "-c", cmd_str],
                capture_output=True, text=True, timeout=timeout
            )
        else:
            result = subprocess.run(
                cmd_parts,
                capture_output=True, text=True, timeout=timeout
            )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "Script timed out", 1
    except Exception as e:
        return str(e), 1

def get_container_stats(name):
    cgroup = f"/sys/fs/cgroup/ank/{name}"
    if not os.path.isdir(cgroup):
        return {"memory_bytes": 0, "memory_limit": 0, "cpu_usage": 0, "pids": 0}
    mem = 0; lim = 0; cpu = 0; pids = 0
    try:
        for f in ("memory.current", "memory.usage_in_bytes"):
            p = os.path.join(cgroup, f)
            if os.path.isfile(p):
                with open(p) as fh: mem = int(fh.read().strip())
                break
        for f in ("memory.max", "memory.limit_in_bytes"):
            p = os.path.join(cgroup, f)
            if os.path.isfile(p):
                with open(p) as fh: v = fh.read().strip()
                if v and v != "max":
                    lim = int(v)
                break
        p = os.path.join(cgroup, "cpu.stat")
        if os.path.isfile(p):
            with open(p) as fh:
                for line in fh:
                    if line.startswith("usage_usec"):
                        cpu = int(line.split()[1]) // 1000
                        break
        for f in ("pids.current", "pids.max"):
            p = os.path.join(cgroup, f)
            if os.path.isfile(p):
                with open(p) as fh: v = fh.read().strip()
                if v and v != "max":
                    pids = int(v)
                break
    except (ValueError, OSError):
        pass
    return {"memory_bytes": mem, "memory_limit": lim, "cpu_usage": cpu, "pids": pids}

def check_container_running(name):
    config = load_container_config(name)
    pid = config.get("pid") if config else None
    if pid:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            pass
    return False

def get_mode():
    try:
        with open(os.path.join(ANK_DIR, "mode"), "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"mode": "shared_host", "chroot": 1, "netns": 0, "pidns": 0, "overlay": 0, "cgroups": 0}

MODE_LABELS = {
    "isolated": {"color": "#22c55e", "label": "Isolated", "desc": "Namespace + overlay isolation"},
    "shared_network": {"color": "#3b82f6", "label": "Shared Network", "desc": "PID namespace + overlay (host network)"},
    "shared_host": {"color": "#eab308", "label": "Shared Host", "desc": "Chroot only (no namespace isolation)"},
    "native_host": {"color": "#94a3b8", "label": "Native Host", "desc": "No containerization"},
}

def get_subnet():
    config = load_config()
    net = config.get("network", {})
    return net.get("subnet", "10.20.30.0")

def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)

def log(msg):
    print(f"[ANK] {msg}", flush=True)

ANK_BRANDING = 'by <a href="https://github.com/andrebarretoit">andrebarretoit</a>'

ANK_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ANK - Android Konteiner</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:#1e293b;border-radius:16px;padding:48px;max-width:480px;width:90%%;text-align:center;box-shadow:0 25px 50px rgba(0,0,0,.4)}
.logo{font-size:48px;font-weight:800;background:linear-gradient(135deg,%s,%s);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}
.sub{color:#94a3b8;font-size:14px;margin-bottom:24px}
.badge{display:inline-block;background:rgba(34,197,94,.15);color:#22c55e;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}
.footer{margin-top:32px;color:#475569;font-size:12px}
.footer a{color:%s;text-decoration:none}
</style>
</head>
<body>
<div class="card">
<div class="logo">ANK</div>
<div class="sub">Android Konteiner</div>
<div class="badge">%s</div>
<p style="margin-top:24px;color:#94a3b8">%s</p>
<div class="footer">%s</div>
</div>
</body>
</html>"""

ANK_NGINX_HTML = ANK_PAGE_HTML % ('#3b82f6', '#06b6d4', '#3b82f6', 'Nginx Running', 'Upload your HTML content via the<br>ANK Web Panel file explorer.', ANK_BRANDING)
ANK_APACHE_HTML = ANK_PAGE_HTML % ('#d22128', '#f59e0b', '#d22128', 'Apache Running', 'Upload your HTML content via the<br>ANK Web Panel file explorer.', ANK_BRANDING)
ANK_PHP_HTML = ANK_PAGE_HTML % ('#777BB4', '#a855f7', '#777BB4', 'PHP Running', 'Edit index.php via the<br>ANK Web Panel file explorer.', ANK_BRANDING)
ANK_NODE_HTML = ANK_PAGE_HTML % ('#339933', '#22c55e', '#339933', 'Node.js Running', 'Edit server.js via the<br>ANK Web Panel file explorer.', ANK_BRANDING)
ANK_PYTHON_HTML = ANK_PAGE_HTML % ('#3776AB', '#ffd43b', '#3776AB', 'Python Running', 'Edit server.py via the<br>ANK Web Panel file explorer.', ANK_BRANDING)

ANK_NGINX_CONF = """events { worker_connections 1024; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    server {
        listen 8080;
        root /var/www/html;
        index index.html;
        location / { try_files $uri $uri/ =404; }
    }
}"""

ANK_PHP_INDEX = """<?php
$html = '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ANK - PHP</title>';
$html .= '<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center}.card{background:#1e293b;border-radius:16px;padding:48px;max-width:480px;width:90%;text-align:center;box-shadow:0 25px 50px rgba(0,0,0,.4)}.logo{font-size:48px;font-weight:800;background:linear-gradient(135deg,#777BB4,#a855f7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}.sub{color:#94a3b8;font-size:14px;margin-bottom:24px}.badge{display:inline-block;background:rgba(34,197,94,.15);color:#22c55e;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}.footer{margin-top:32px;color:#475569;font-size:12px}.footer a{color:#777BB4;text-decoration:none}</style>';
$html .= '</head><body><div class="card"><div class="logo">ANK</div><div class="sub">Android Konteiner</div>';
$html .= '<div class="badge">PHP ' . phpversion() . ' Running</div>';
$html .= '<p style="margin-top:24px;color:#94a3b8">Edit index.php via the<br>ANK Web Panel file explorer.</p>';
$html .= '<div class="footer">by <a href="https://github.com/andrebarretoit">andrebarretoit</a></div></div></body></html>';
echo $html;
?>"""

ANK_NODE_SERVER = """const http = require('http');
const srv = http.createServer((req, res) => {
    res.writeHead(200, {'Content-Type': 'text/html'});
    res.end('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ANK - Node.js</title><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center}.card{background:#1e293b;border-radius:16px;padding:48px;max-width:480px;width:90%;text-align:center;box-shadow:0 25px 50px rgba(0,0,0,.4)}.logo{font-size:48px;font-weight:800;background:linear-gradient(135deg,#339933,#22c55e);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}.sub{color:#94a3b8;font-size:14px;margin-bottom:24px}.badge{display:inline-block;background:rgba(34,197,94,.15);color:#22c55e;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}.footer{margin-top:32px;color:#475569;font-size:12px}.footer a{color:#339933;text-decoration:none}</style></head><body><div class="card"><div class="logo">ANK</div><div class="sub">Android Konteiner</div><div class="badge">Node.js ' + process.version + ' Running</div><p style="margin-top:24px;color:#94a3b8">Edit server.js via the<br>ANK Web Panel file explorer.</p><div class="footer">by <a href="https://github.com/andrebarretoit">andrebarretoit</a></div></div></body></html>');
});
srv.listen(3000, () => console.log('ANK Node.js listening on :3000'));"""

ANK_PYTHON_SERVER = """from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        html = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ANK - Python</title><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center}.card{background:#1e293b;border-radius:16px;padding:48px;max-width:480px;width:90%;text-align:center;box-shadow:0 25px 50px rgba(0,0,0,.4)}.logo{font-size:48px;font-weight:800;background:linear-gradient(135deg,#3776AB,#ffd43b);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}.sub{color:#94a3b8;font-size:14px;margin-bottom:24px}.badge{display:inline-block;background:rgba(34,197,94,.15);color:#22c55e;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}.footer{margin-top:32px;color:#475569;font-size:12px}.footer a{color:#3776AB;text-decoration:none}</style></head><body><div class="card"><div class="logo">ANK</div><div class="sub">Android Konteiner</div><div class="badge">Python ''' + '.'.join(map(str, __import__('sys').version_info[:3])) + ' Running</div><p style="margin-top:24px;color:#94a3b8">Edit server.py via the<br>ANK Web Panel file explorer.</p><div class="footer">by <a href="https://github.com/andrebarretoit">andrebarretoit</a></div></div></body></html>'''
        self.wfile.write(html.encode())

    def log_message(self, fmt, *args):
        pass

HTTPServer(('0.0.0.0', 8000), Handler).serve_forever()"""

# ============================================================
# S6 service definitions for templates
# ============================================================

S6_SERVICES = {
    "nginx": {
        "run": "#!/bin/sh\nexec nginx -g 'daemon off;'",
        "finish": "#!/bin/sh\ntrue"
    },
    "apache": {
        "run": "#!/bin/sh\nexec httpd -D FOREGROUND",
        "finish": "#!/bin/sh\ntrue"
    },
    "php": {
        "run": "#!/bin/sh\nexec php82-cgi -b 0.0.0.0:8000",
        "finish": "#!/bin/sh\ntrue"
    },
    "node": {
        "run": "#!/bin/sh\ncd /var/www/app && exec node server.js",
        "finish": "#!/bin/sh\ntrue"
    },
    "python": {
        "run": "#!/bin/sh\ncd /var/www/app && exec python3 server.py",
        "finish": "#!/bin/sh\ntrue"
    }
}

def _write_s6_service(merged, service_name):
    """Write s6 service definitions into merged dir."""
    import stat
    svc_dir = os.path.join(merged, "etc/services.d", service_name)
    os.makedirs(svc_dir, exist_ok=True)
    if service_name in S6_SERVICES:
        for script_name in ("run", "finish"):
            path = os.path.join(svc_dir, script_name)
            with open(path, "w") as f:
                f.write(S6_SERVICES[service_name][script_name])
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

def _write_portfwd(merged, container_port, protocol="tcp"):
    """Write portfwd.conf into merged dir for the container."""
    ank_dir = os.path.join(merged, "etc/ank")
    os.makedirs(ank_dir, exist_ok=True)
    with open(os.path.join(ank_dir, "portfwd.conf"), "w") as f:
        f.write(f"{container_port} {protocol}\n")

def _write_ank_config(merged, service, port, static_path="", s6="false"):
    """Write unified /etc/ank/config into merged dir."""
    ank_dir = os.path.join(merged, "etc/ank")
    os.makedirs(ank_dir, exist_ok=True)
    with open(os.path.join(ank_dir, "config"), "w") as f:
        f.write(f"service={service}\n")
        f.write(f"port={port}\n")
        f.write(f"static_path={static_path}\n")
        f.write(f"s6={s6}\n")

# check_auth replaced by _check_auth() token-based authentication (see security section above)

# ============================================================
# WebSocket support (RFC 6455) for interactive terminal
# ============================================================

def _ws_accept_key(key):
    """Compute Sec-WebSocket-Accept from client key."""
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()

def _ws_read_frame_rsock(rsock):
    """Read one WebSocket frame (RFC 6455) directly from raw socket."""
    try:
        data = _ws_recv_exact(rsock, 2)
        if not data:
            return None, None
        b0, b1 = struct.unpack("!BB", data)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        if length == 126:
            ext = _ws_recv_exact(rsock, 2)
            if not ext:
                return None, None
            length = struct.unpack("!H", ext)[0]
        elif length == 127:
            ext = _ws_recv_exact(rsock, 8)
            if not ext:
                return None, None
            length = struct.unpack("!Q", ext)[0]
        mask_key = None
        if masked:
            mask_key = _ws_recv_exact(rsock, 4)
            if not mask_key:
                return None, None
        payload = b""
        while len(payload) < length:
            chunk = _ws_recv_exact(rsock, min(length - len(payload), 4096))
            if not chunk:
                return None, None
            payload += chunk
        if mask_key:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return opcode, payload
    except Exception:
        return None, None


def _ws_recv_exact(sock, n):
    """Read exactly n bytes from a raw socket."""
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except Exception:
            return None
        if not chunk:
            return None
        buf += chunk
    return buf

def _ws_send_frame(sock, opcode, payload):
    """Send a WebSocket frame (RFC 6455 compliant length encoding)."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    length = len(payload)
    if length < 126:
        header = struct.pack("!BB", 0x80 | opcode, length)
    elif length <= 0xFFFF:
        header = struct.pack("!BBH", 0x80 | opcode, 126, length)
    else:
        header = struct.pack("!BBQ", 0x80 | opcode, 127, length)
    try:
        sock.sendall(header + payload)
    except Exception:
        pass

def _ws_send_text(sock, text):
    _ws_send_frame(sock, 0x1, text)

def _ws_send_close(sock):
    _ws_send_frame(sock, 0x8, b"")

def _ws_pty_session(handler, container_name, cols=80, rows=24):
    """Handle a PTY-based WebSocket terminal session."""
    merged = os.path.join(CONTAINERS_DIR, container_name, "merged")
    if not os.path.isdir(merged):
        _ws_send_close(handler.request)
        return

    # Find shell
    shell = "/bin/sh"
    for s in ["/bin/bash", "/bin/ash", "/bin/sh"]:
        cand = os.path.join(merged, s.lstrip("/"))
        if os.path.exists(cand) or os.path.islink(cand):
            shell = s
            break
    shell_abs_in_chroot = shell

    if not (os.path.exists(os.path.join(merged, shell_abs_in_chroot.lstrip("/"))) or
            os.path.islink(os.path.join(merged, shell_abs_in_chroot.lstrip("/")))):
        _ws_send_text(handler.request, f"\r\nERROR: no shell found in container rootfs ({shell_abs_in_chroot})\r\n")
        _ws_send_close(handler.request)
        return

    setup_script = (
        "export PATH=/bin:/sbin:/usr/bin:/usr/sbin; "
        "export TERM=xterm-256color; "
        "export HOME=/root; "
        "hostname " + container_name + " 2>/dev/null; "
        "cd /root 2>/dev/null || cd /; "
        "mkdir -p /dev/pts /dev/shm 2>/dev/null; "
        "mount -t devtmpfs devtmpfs /dev 2>/dev/null || true; "
        "for n in null:1:3 zero:1:5 random:1:8 urandom:1:9 tty:5:0 ptmx:5:2 console:5:1; do "
        "  nn=$(echo $n | cut -d: -f1); tt=$(echo $n | cut -d: -f2); mm=$(echo $n | cut -d: -f3); "
        "  [ -e /dev/$nn ] || mknod /dev/$nn c $tt $mm 2>/dev/null; "
        "  chmod 666 /dev/$nn 2>/dev/null; "
        "done; "
        "mount -t devpts devpts /dev/pts 2>/dev/null || true; "
        "exec " + shell_abs_in_chroot
    )

    master_fd = None
    child_pid = None

    try:
        if not HAS_PTY:
            _ws_send_text(handler.request, "ERROR: PTY not available on this system\r\n")
            _ws_send_close(handler.request)
            return

        child_pid, master_fd = pty.fork()
        if child_pid == 0:
            # Child process
            os.chroot(merged)
            os.chdir("/root")
            for var, val in [("PATH", "/bin:/sbin:/usr/bin:/usr/sbin"), ("TERM", "xterm-256color"), ("HOME", "/root")]:
                os.environ[var] = val
            os.execv(shell_abs_in_chroot, [shell_abs_in_chroot, "-c", setup_script])
        else:
            # Parent: set initial window size
            import fcntl
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(master_fd, 21523, winsize)  # TIOCSWINSZ

            # Read thread
            running = [True]
            def read_pty():
                while running[0]:
                    try:
                        r, _, _ = select.select([master_fd], [], [], 0.1)
                        if r:
                            data = os.read(master_fd, 4096)
                            if data:
                                _ws_send_text(handler.request, data.decode("utf-8", errors="replace"))
                            else:
                                break
                    except Exception:
                        break
                running[0] = False

            t = threading.Thread(target=read_pty, daemon=True)
            t.start()

            # Main loop: read WebSocket frames and write to PTY
            while running[0]:
                opcode, payload = _ws_read_frame_rsock(handler.request)
                if opcode is None:
                    break
                if opcode == 0x8:  # Close
                    break
                if opcode == 0x1:  # Text
                    try:
                        msg = json.loads(payload.decode("utf-8"))
                        if msg.get("type") == "resize":
                            cols = msg.get("cols", 80)
                            rows = msg.get("rows", 24)
                            winsize = struct.pack("HHHH", rows, cols, 0, 0)
                            fcntl.ioctl(master_fd, 21523, winsize)
                            continue
                        elif msg.get("type") == "input":
                            data = msg.get("data", "")
                            os.write(master_fd, data.encode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        os.write(master_fd, payload)
                elif opcode == 0x2:  # Binary
                    os.write(master_fd, payload)

            running[0] = False
            try:
                os.close(master_fd)
            except Exception:
                pass
            try:
                os.kill(child_pid, 9)
                os.waitpid(child_pid, 0)
            except Exception:
                pass
            try:
                _ws_send_close(handler.request)
            except Exception:
                pass

    except Exception as e:
        try:
            _ws_send_text(handler.request, f"\r\nERROR: {str(e)}\r\n")
        except Exception:
            pass
        if master_fd:
            try:
                os.close(master_fd)
            except Exception:
                pass
        if child_pid:
            try:
                os.kill(child_pid, 9)
                os.waitpid(child_pid, 0)
            except Exception:
                pass
        _ws_send_close(handler.request)


def _ws_shell_session(handler, cols=80, rows=24):
    """Handle a PTY-based WebSocket shell session on the HOST (not container).
    Uses raw socket directly — bypasses BaseHTTPRequestHandler's rfile/wfile."""
    rsock = handler.request
    try:
        if not HAS_PTY:
            log("WS_SHELL: PTY module not available")
            _ws_send_text(rsock, "ERROR: PTY not available\r\n")
            _ws_send_close(rsock)
            return

        shell = "/system/bin/sh"
        for s in ["/system/bin/sh", "/system/xbin/sh", "/bin/sh", "/vendor/bin/sh"]:
            if os.path.exists(s) and os.access(s, os.X_OK):
                shell = s
                break

        ank_shell = os.path.join(ANK_DIR, "ankfs/ank-shell.sh")
        has_ank_shell = os.path.isfile(ank_shell) and os.access(ank_shell, os.X_OK)

        if has_ank_shell:
            log(f"WS_SHELL: fork (ank-shell={ank_shell})")
        else:
            profile = os.path.join(ANK_DIR, "ankfs/opt/ank/ank-profile.sh")
            has_profile = os.path.isfile(profile)
            log(f"WS_SHELL: fork (shell={shell}, profile={has_profile})")

        pid, master_fd = pty.fork()
        if pid == 0:
            for k in ("TERM", "PATH", "HOME", "LANG", "USER", "SHELL"):
                os.environ.pop(k, None)
            os.environ["TERM"] = "xterm-256color"
            os.environ["PATH"] = f"{ANK_DIR}/ankfs/opt/ank/bin:/system/bin:/system/xbin:/sbin:/vendor/bin:/bin:/usr/bin"
            os.environ["HOME"] = "/root"
            os.environ["USER"] = "root"
            os.environ["SHELL"] = shell
            os.environ["ANK_DIR"] = ANK_DIR
            try:
                if has_ank_shell:
                    os.execv(shell, [shell, ank_shell])
                elif has_profile:
                    os.execl(shell, shell, "-c", f". {profile}; exec {shell}")
                else:
                    os.execv(shell, [shell])
            except Exception:
                os.execv("/system/bin/sh", ["/system/bin/sh"])
        else:
            log(f"WS_SHELL: child pid={pid}, master_fd={master_fd}")
            import fcntl
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(master_fd, 21523, winsize)
            running = [True]
            def read_pty():
                while running[0]:
                    try:
                        r, _, _ = select.select([master_fd], [], [], 0.1)
                        if r:
                            data = os.read(master_fd, 4096)
                            if data:
                                _ws_send_text(rsock, data.decode("utf-8", errors="replace"))
                            else:
                                break
                    except Exception:
                        break
                running[0] = False
            t = threading.Thread(target=read_pty, daemon=True)
            t.start()
            while running[0]:
                opcode, payload = _ws_read_frame_rsock(rsock)
                if opcode is None:
                    break
                if opcode == 0x8:
                    break
                if opcode == 0x1:
                    try:
                        msg = json.loads(payload.decode("utf-8"))
                        if msg.get("type") == "resize":
                            cols = msg.get("cols", 80)
                            rows = msg.get("rows", 24)
                            winsize = struct.pack("HHHH", rows, cols, 0, 0)
                            fcntl.ioctl(master_fd, 21523, winsize)
                            continue
                        elif msg.get("type") == "input":
                            os.write(master_fd, msg.get("data", "").encode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        os.write(master_fd, payload)
                elif opcode == 0x2:
                    os.write(master_fd, payload)
            running[0] = False
            try:
                os.close(master_fd)
            except Exception:
                pass
            try:
                os.kill(pid, 9)
                os.waitpid(pid, 0)
            except Exception:
                pass
            _ws_send_close(rsock)
    except Exception as e:
        try:
            _ws_send_text(handler.request, f"\r\nERROR: {str(e)}\r\n")
        except Exception:
            pass
        _ws_send_close(handler.request)


class AnkHandler(BaseHTTPRequestHandler):

    def _find_free_port(self, start=2200):
        """Find a free port starting from 'start', checking existing containers. Thread-safe."""
        with _port_lock:
            used = set()
            for cfg_file in glob.glob(os.path.join(CONTAINERS_DIR, "*/config.json")):
                try:
                    with open(cfg_file) as f:
                        cfg = json.load(f)
                        p = cfg.get("ssh_port")
                        if p:
                            used.add(int(p))
                        for pm in cfg.get("port_mappings", []):
                            hp = pm.get("host_port")
                            if hp:
                                used.add(int(hp))
                except Exception:
                    pass
            port = start
            while port < 65000:
                if port not in used:
                    import socket
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(0.1)
                        result = s.connect_ex(('127.0.0.1', port))
                        s.close()
                        if result != 0:
                            return port
                    except Exception:
                        return port
                port += 1
            return start

    def send_security_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-XSS-Protection', '1; mode=block')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')

    def send_404_html(self):
        html = '''<!DOCTYPE html>
<html><head><title>ANK — Acesso Negado</title>
<style>
body{background:#0f172a;color:#94a3b8;font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
.box{text-align:center}
h1{font-size:96px;color:#1e293b;margin:0}
p{color:#64748b}
a{color:#3b82f6;text-decoration:none}
small{color:#334155}
</style></head>
<body>
<div class="box">
<h1>404</h1>
<p>Esta rota nao existe ou requer um cliente autorizado.</p>
<p><small>ANK — Android Konteiner Engine</small></p>
<a href="/">← Voltar ao painel</a>
</div>
</body></html>'''.encode('utf-8')
        self.send_response(404)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(html)))
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(html)

    def send_error(self, code, message=None):
        try:
            if message is None:
                try:
                    message = self.responses.get(code, ("Error",))[0]
                except (AttributeError, IndexError, KeyError):
                    message = "Error"
            encoded = json.dumps({"error": message}).encode("utf-8")
            try:
                self.send_response(code)
            except Exception:
                try:
                    self.wfile.write(f"HTTP/1.1 {code} Error\r\nContent-Type: application/json\r\nContent-Length: {len(encoded)}\r\n\r\n".encode())
                except Exception:
                    return
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_security_headers()
            self.end_headers()
            self.wfile.write(encoded)
            self.wfile.flush()
        except Exception:
            pass

    def _ws_send_error(self, code, message):
        """Send error response during WebSocket upgrade (raw HTTP)."""
        try:
            body = json.dumps({"error": message}).encode("utf-8")
            resp = (
                f"HTTP/1.1 {code} Error\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode() + body
            self.request.sendall(resp)
        except Exception:
            pass

    def send_json(self, data, code=200):
        encoded = json.dumps(data, separators=(',', ':')).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(encoded)
        self.wfile.flush()

    def send_file(self, path, content_type):
        with open(path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(content))
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(content)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-ANK-Client")
        self.send_security_headers()
        self.end_headers()

    def do_GET(self):
        self._is_websocket = False
        parsed = urlparse(self.path)
        path = parsed.path

        # WebSocket upgrade for shell on host
        if path == "/ws/shell":
            self._is_websocket = True
            upgrade = self.headers.get("Upgrade", "").lower()
            ws_key = self.headers.get("Sec-WebSocket-Key", "")
            if upgrade != "websocket" or not ws_key:
                self._ws_send_error(400, "Invalid WebSocket upgrade request")
                return
            # Auth: validate token from query param
            qs = parse_qs(parsed.query)
            ws_token = qs.get("token", [None])[0]
            if not _validate_token(ws_token):
                log(f"WS_SHELL: auth failed from {self.client_address[0]} token={ws_token[:8] if ws_token else 'None'}...")
                self._ws_send_error(401, "Unauthorized")
                return
            accept = _ws_accept_key(ws_key)
            log(f"WS_SHELL: upgrade from {self.client_address[0]}")
            rsock = self.request
            resp = (
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: Upgrade\r\n"
                b"Sec-WebSocket-Accept: " + accept.encode() + b"\r\n"
                b"X-Content-Type-Options: nosniff\r\n"
                b"\r\n"
            )
            rsock.sendall(resp)
            log(f"WS_SHELL: 101 sent")
            cols = 80
            rows = 24
            try:
                qs = parse_qs(parsed.query)
                cols = int(qs.get("cols", [80])[0])
                rows = int(qs.get("rows", [24])[0])
            except Exception:
                pass
            _ws_shell_session(self, cols, rows)
            return

        # WebSocket upgrade for terminal
        if path.startswith("/ws/terminal/"):
            self._is_websocket = True
            upgrade = self.headers.get("Upgrade", "").lower()
            ws_key = self.headers.get("Sec-WebSocket-Key", "")
            if upgrade != "websocket" or not ws_key:
                self._ws_send_error(400, "Invalid WebSocket upgrade request")
                return
            # Auth: validate token from query param
            qs = parse_qs(parsed.query)
            ws_token = qs.get("token", [None])[0]
            if not _validate_token(ws_token):
                log(f"WS_TERMINAL: auth failed from {self.client_address[0]} token={ws_token[:8] if ws_token else 'None'}...")
                self._ws_send_error(401, "Unauthorized")
                return
            container_name = path.split("/")[3]
            # Verify container is actually running
            config = load_container_config(container_name)
            if not config:
                self._ws_send_error(404, f"Container '{container_name}' not found")
                return
            if config.get("status") == "running" and not check_container_running(container_name):
                config["status"] = "stopped"
                config["pid"] = None
                save_container_config(container_name, config)
            if config.get("status") != "running":
                self._ws_send_error(400, f"Container '{container_name}' is not running (status: {config.get('status', 'unknown')})")
                return
            # Accept WebSocket — send 101 on raw socket
            accept = _ws_accept_key(ws_key)
            rsock = self.request
            resp = (
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: Upgrade\r\n"
                b"Sec-WebSocket-Accept: " + accept.encode() + b"\r\n"
                b"X-Content-Type-Options: nosniff\r\n"
                b"\r\n"
            )
            rsock.sendall(resp)
            # Start PTY session (blocks until done)
            cols = 80
            rows = 24
            try:
                qs = parse_qs(parsed.query)
                cols = int(qs.get("cols", [80])[0])
                rows = int(qs.get("rows", [24])[0])
            except Exception:
                pass
            _ws_pty_session(self, container_name, cols, rows)
            return

        if path == "/api/protocol":
            proto = "http"
            try:
                with open(os.path.join(ANK_DIR, "protocol"), "r") as f:
                    proto = f.read().strip()
            except Exception:
                pass
            self.send_json({"protocol": proto})
            return

        if path.startswith("/api/"):
            auth = _check_auth(self)
            if auth == 'browser':
                self.send_404_html()
                return
            if auth != 'authorized':
                self.send_error(401, "Unauthorized")
                return
            try:
                self.route_get(path, parsed)
            except Exception as e:
                self.send_error(500, str(e))
            return
        self.serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            if path != "/api/auth/login":
                auth = _check_auth(self)
                if auth == 'browser':
                    self.send_404_html()
                    return
                if auth != 'authorized':
                    self.send_error(401, "Unauthorized")
                    return
            try:
                self.route_post(path, parsed)
            except Exception as e:
                self.send_error(500, str(e))
            return
        self.send_404_html()

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            auth = _check_auth(self)
            if auth == 'browser':
                self.send_404_html()
                return
            if auth != 'authorized':
                self.send_error(401, "Unauthorized")
                return
            if "/upload" in path:
                try:
                    self.api_upload_file(path)
                except Exception as e:
                    self.send_error(500, str(e))
                return
        self.send_error(404, "Not Found")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            auth = _check_auth(self)
            if auth == 'browser':
                self.send_404_html()
                return
            if auth != 'authorized':
                self.send_error(401, "Unauthorized")
                return
            self.route_delete(path, parsed)
            return
        self.send_404_html()

    # ============================================================
    # Routing
    # ============================================================

    def route_get(self, path, parsed):
        if path == "/api/status":
            self.api_status()
        elif path == "/api/protocol":
            proto = "http"
            try:
                with open(os.path.join(ANK_DIR, "protocol"), "r") as f:
                    proto = f.read().strip()
            except Exception:
                pass
            self.send_json({"protocol": proto})
        elif path == "/api/containers":
            self.api_list_containers()
        elif path.endswith("/files") and path.startswith("/api/containers/"):
            parts = path.split("/")
            name = parts[3]
            qs = parsed.query
            self.api_files_list(name, qs)
        elif "/files/content" in path and path.startswith("/api/containers/"):
            parts = path.split("/")
            name = parts[3]
            qs = parsed.query
            self.api_files_read(name, qs)
        elif "/files/download" in path and path.startswith("/api/containers/"):
            parts = path.split("/")
            name = parts[3]
            qs = parsed.query
            self.api_files_download(name, qs)
        elif "/files/stat" in path and path.startswith("/api/containers/"):
            parts = path.split("/")
            name = parts[3]
            qs = parsed.query
            self.api_files_stat(name, qs)
        elif path.startswith("/api/containers/") and path.endswith("/logs"):
            self.api_container_logs(path.split("/")[3])
        elif path.startswith("/api/containers/"):
            self.api_container_inspect(path.split("/")[3])
        elif path == "/api/images":
            self.api_list_images()
        elif path == "/api/images/templates":
            self.api_image_templates()
        elif path == "/api/system/info":
            self.api_system_info()
        elif path == "/api/networks":
            self.api_list_networks()
        elif path == "/api/networks/info":
            self.api_network_info()
        elif path == "/api/logs":
            self.api_get_logs(parsed)
        elif path == "/api/config":
            self.api_get_config()
        elif path == "/api/stacks":
            self.api_list_stacks()
        elif path.startswith("/api/stacks/") and path.endswith("/logs"):
            self.api_stack_logs(path.split("/")[3], parsed)
        elif path.startswith("/api/stacks/") and path.endswith("/metrics"):
            self.api_stack_metrics(path.split("/")[3])
        elif path.startswith("/api/stacks/"):
            self.api_stack_inspect(path.split("/")[3])
        elif path == "/api/backups":
            self.api_list_backups()
        elif path.startswith("/api/backups/") and "browse" in path:
            qs = parsed.query
            self.api_backup_browse(path.split("/")[3], qs)
        elif path.startswith("/api/backups/"):
            self.api_backup_inspect(path.split("/")[3])
        elif path == "/api/nodes":
            self.api_list_nodes()
        elif path.startswith("/api/nodes/") and path.endswith("/containers"):
            self.api_node_containers(path.split("/")[3])
        elif path.startswith("/api/nodes/") and path.endswith("/stacks"):
            self.api_node_stacks(path.split("/")[3])
        elif path.startswith("/api/nodes/"):
            self.api_node_inspect(path.split("/")[3])
        elif path == "/api/system/dashboard":
            self.api_system_dashboard()
        else:
            self.send_error(404, "Not Found")

    def route_post(self, path, parsed):
        data = self.read_body()
        if data is None:
            self.send_error(400, "Invalid JSON")
            return

        if path == "/api/auth/login":
            self.api_login(data)
        elif path == "/api/auth/password":
            self.api_change_password(data)
        elif path == "/api/containers":
            self.api_create_container(data)
        elif path.startswith("/api/containers/") and path.endswith("/start"):
            self.api_start_container(path.split("/")[3])
        elif path.startswith("/api/containers/") and path.endswith("/stop"):
            self.api_stop_container(path.split("/")[3])
        elif path.startswith("/api/containers/") and path.endswith("/restart"):
            self.api_restart_container(path.split("/")[3])
        elif path.startswith("/api/containers/") and path.endswith("/exec"):
            self.api_exec_container(path.split("/")[3], data)
        elif path.startswith("/api/containers/") and path.endswith("/update"):
            self.api_update_container(path.split("/")[3], data)
        elif "/files/write" in path and path.startswith("/api/containers/"):
            name = path.split("/")[3]
            self.api_files_write(name, data)
        elif "/files/mkdir" in path and path.startswith("/api/containers/"):
            name = path.split("/")[3]
            self.api_files_mkdir(name, data)
        elif "/files/rename" in path and path.startswith("/api/containers/"):
            name = path.split("/")[3]
            self.api_files_rename(name, data)
        elif path == "/api/images/pull":
            self.api_pull_image(data)
        elif path == "/api/images/templates":
            self.api_image_templates()
        elif path == "/api/images/deploy":
            self.api_deploy_template(data)
        elif path == "/api/images/ankfile":
            self.api_build_ankfile(data)
        elif path == "/api/containers/" and "upload" in path:
            pass
        elif path == "/api/system/shell":
            self.api_shell(data)
        elif path == "/api/system/restart-device":
            self.api_restart_device()
        elif path == "/api/system/restart-server":
            self.api_restart_server()
        elif path == "/api/networks":
            self.api_create_network(data)
        elif path == "/api/system/config":
            self.api_update_config(data)
        elif path == "/api/config":
            self.api_update_config(data)
        elif path == "/api/system/uninstall":
            self.api_uninstall()
        elif path == "/api/stacks":
            self.api_create_stack(data)
        elif path.startswith("/api/stacks/") and path.endswith("/scale"):
            self.api_scale_stack(path.split("/")[3], data)
        elif path.startswith("/api/stacks/") and path.endswith("/scale-down"):
            self.api_scale_down_stack(path.split("/")[3], data)
        elif path.startswith("/api/stacks/") and path.endswith("/delete"):
            self.api_delete_stack(path.split("/")[3])
        elif path.startswith("/api/stacks/") and path.endswith("/update"):
            self.api_update_stack(path.split("/")[3], data)
        elif path == "/api/backups":
            self.api_create_backup_routine(data)
        elif path.startswith("/api/backups/") and path.endswith("/execute"):
            self.api_execute_backup(path.split("/")[3])
        elif path.startswith("/api/backups/") and path.endswith("/delete"):
            self.api_delete_backup_routine(path.split("/")[3])
        elif path == "/api/nodes":
            self.api_add_node(data)
        elif path.startswith("/api/nodes/") and path.endswith("/delete"):
            self.api_delete_node(path.split("/")[3])
        elif path.startswith("/api/nodes/") and path.endswith("/refresh"):
            self.api_refresh_node(path.split("/")[3])
        else:
            self.send_error(404, "Not Found")

    def route_delete(self, path, parsed=None):
        if "/files" in path and path.startswith("/api/containers/"):
            parts = path.split("/")
            name = parts[3]
            qs = parsed.query if parsed else ""
            self.api_files_delete(name, qs)
            return
        parts = path.split("/")
        if len(parts) >= 4 and parts[2] == "containers":
            self.api_delete_container(parts[3])
        elif len(parts) >= 4 and parts[2] == "networks":
            self.api_delete_network(parts[3])
        elif len(parts) >= 4 and parts[2] == "backups":
            self.api_delete_backup_routine(parts[3])
        elif len(parts) >= 4 and parts[2] == "nodes":
            self.api_delete_node(parts[3])
        elif len(parts) >= 4 and parts[2] == "stacks":
            self.api_delete_stack(parts[3])
        else:
            self.send_error(404, "Not Found")

    # ============================================================
    # Auth
    # ============================================================

    def api_login(self, data):
        # Rate limiting
        client_ip = self.client_address[0]
        if not _check_rate_limit(client_ip):
            self.send_error(429, "Too many login attempts. Try again later.")
            return

        config = load_config()
        user = data.get("username", "")
        pwd = data.get("password", "")
        if user == config.get("username") and pwd == config.get("password"):
            token = _create_token(user)
            self.send_json({
                "success": True,
                "token": token,
                "expires": (datetime.now() + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat(),
                "first_boot": config.get("first_boot", False),
                "force_change": config.get("first_boot", False)
            })
        else:
            self.send_error(401, "Invalid credentials")

    def api_change_password(self, data):
        config = load_config()
        current = data.get("current_password", "")
        if current != config.get("password"):
            self.send_error(401, "Current password incorrect")
            return
        new_user = data.get("username") or config.get("username")
        new_pass = data.get("new_password", "")
        if not new_pass or len(new_pass) < 6:
            self.send_error(400, "Password must be at least 6 characters")
            return
        config["username"] = new_user
        config["password"] = new_pass
        config["first_boot"] = False
        save_config(config)
        try:
            os.makedirs(ANK_DIR, exist_ok=True)
            with open(os.path.join(ANK_SDCARD, "CREDENCIAIS.txt"), "w") as f:
                f.write(f"ANK - Android Konteiner\n")
                f.write(f"=======================\n")
                f.write(f"Painel: https://localhost:8001\n")
                f.write(f"Usuario: {new_user}\n")
                f.write(f"Senha: {new_pass}\n")
        except Exception:
            pass
        self.send_json({"success": True, "message": "Password changed"})

    # ============================================================
    # Container API
    # ============================================================

    def api_list_containers(self):
        containers = []
        if os.path.exists(CONTAINERS_DIR):
            for name in os.listdir(CONTAINERS_DIR):
                if not os.path.isdir(os.path.join(CONTAINERS_DIR, name)):
                    continue
                try:
                    config = load_container_config(name)
                except Exception:
                    continue
                if config:
                    if config.get("status") == "running" and not check_container_running(name):
                        config["status"] = "stopped"
                        config["pid"] = None
                        save_container_config(name, config)
                    config["stats"] = get_container_stats(name)
                    containers.append(config)
        self.send_json(containers)

    def api_container_inspect(self, name):
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return
        config["stats"] = get_container_stats(name)
        self.send_json(config)

    def api_container_logs(self, name):
        log_path = os.path.join(ANK_DIR, "logs", f"{name}.log")
        logs = ""
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                logs = f.read()
        self.send_json({"logs": logs})

    def api_create_container(self, data):
        name = data.get("name")
        if not name:
            self.send_error(400, "Container name required")
            return
        if not all(c.isalnum() or c in "-_" for c in name):
            self.send_error(400, "Invalid container name")
            return
        if os.path.exists(os.path.join(CONTAINERS_DIR, name)):
            self.send_error(409, f"Container '{name}' already exists")
            return

        image = data.get("image", "alpine-3.20")
        root_password = data.get("root_password", "")
        if not root_password:
            self.send_error(400, "Root password required")
            return

        ssh_port = data.get("ssh_port")
        if not ssh_port:
            ssh_port = self._find_free_port(2200)
        else:
            ssh_port = int(ssh_port)

        # Write stub config with "building" status immediately so UI shows it
        stub_dir = os.path.join(CONTAINERS_DIR, name)
        os.makedirs(stub_dir, exist_ok=True)
        stub_config = {
            "name": name,
            "status": "building",
            "image": image,
            "mode": get_mode().get("mode", "shared_host"),
            "autostart": data.get("autostart", False),
            "ip_address": "",
            "ssh_port": ssh_port,
            "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pid": None,
            "policies": data.get("policies", {}),
            "resources": data.get("resources", {"memory_limit": "256M", "cpu_limit_percent": 50}),
            "port_mappings": data.get("port_mappings", []),
            "root_password": root_password
        }
        save_container_config(name, stub_config)

        # Run actual creation in background thread
        def _do_create():
            log_path = os.path.join(ANK_DIR, "logs", f"{name}.log")
            try:
                # Map alpine-X.XX -> ank-alpinebase-X.XX
                mapped_image = image
                if image.startswith("alpine-"):
                    mapped_image = f"ank-alpinebase-{image[7:]}"

                template = None
                for t in self.IMAGE_TEMPLATES:
                    if t["base"] == image or t["image"] == image or t["base"] == mapped_image or t["image"] == mapped_image:
                        template = t
                        break
                pkgs = " ".join(template.get("packages", [])) if template else ""
                with open(log_path, "w") as lf:
                    lf.write(f"Creating container '{name}' (image: {mapped_image})...\n")
                    lf.flush()
                output, code = run_script("container.sh", "create", name, mapped_image, root_password, str(ssh_port), pkgs)
                with open(log_path, "a") as lf:
                    lf.write(output + "\n")
                cfg = load_container_config(name)
                if cfg:
                    if code != 0:
                        log(f"ERROR: create {name}: {output}")
                        cfg["status"] = "failed"
                    else:
                        log(f"Container {name} created")
                        cfg["status"] = "stopped"
                        cfg["image"] = mapped_image
                        if template:
                            cfg["template"] = template["id"]
                            cfg["template_name"] = template["name"]
                    save_container_config(name, cfg)
            except Exception as e:
                log(f"ERROR: create thread {name}: {e}")
                try:
                    with open(log_path, "a") as lf:
                        lf.write(f"FATAL: {e}\n")
                except Exception:
                    pass
                cfg = load_container_config(name)
                if cfg:
                    cfg["status"] = "failed"
                    save_container_config(name, cfg)

        threading.Thread(target=_do_create, daemon=True).start()
        self.send_json({"message": f"Container '{name}' creating", "name": name, "ssh_port": ssh_port}, 201)

    def api_start_container(self, name):
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return
        # Write status BEFORE spawning thread to avoid race condition
        config["status"] = "starting"
        save_container_config(name, config)
        def do_start():
            try:
                output, code = run_script("container.sh", "start", name)
                cfg = load_container_config(name)
                if cfg:
                    if code != 0:
                        log(f"ERROR: start {name}: {output}")
                        cfg["status"] = "stopped"
                        cfg["pid"] = None
                    else:
                        log(f"Container {name} started")
                        cfg["status"] = "running"
                    save_container_config(name, cfg)
            except Exception as e:
                log(f"ERROR: start thread {name}: {e}")
                cfg = load_container_config(name)
                if cfg:
                    cfg["status"] = "stopped"
                    cfg["pid"] = None
                    save_container_config(name, cfg)
        import threading
        threading.Thread(target=do_start, daemon=True).start()
        self.send_json({"message": f"Container '{name}' starting"})

    def api_stop_container(self, name):
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return
        # Write status BEFORE spawning thread
        config["status"] = "stopping"
        save_container_config(name, config)
        def do_stop():
            try:
                output, code = run_script("container.sh", "stop", name)
                cfg = load_container_config(name)
                if cfg:
                    if code != 0:
                        log(f"ERROR: stop {name}: {output}")
                    else:
                        log(f"Container {name} stopped")
                        cfg["status"] = "stopped"
                    save_container_config(name, cfg)
            except Exception as e:
                log(f"ERROR: stop thread {name}: {e}")
                cfg = load_container_config(name)
                if cfg:
                    cfg["status"] = "stopped"
                    save_container_config(name, cfg)
        import threading
        threading.Thread(target=do_stop, daemon=True).start()
        config["status"] = "stopping"
        save_container_config(name, config)
        self.send_json({"message": f"Container '{name}' stopping"})

    def api_delete_container(self, name):
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return
        output, code = run_script("container.sh", "delete", name)
        if code != 0:
            self.send_error(500, f"Failed to delete: {output}")
            return
        self.send_json({"message": f"Container '{name}' deleted"})

    def api_restart_container(self, name):
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return
        def do_restart():
            try:
                config["status"] = "stopping"
                save_container_config(name, config)
                run_script("container.sh", "stop", name)
                import time; time.sleep(2)
                output, code = run_script("container.sh", "start", name)
                cfg = load_container_config(name)
                if cfg:
                    if code != 0:
                        log(f"ERROR: restart {name}: {output}")
                        cfg["status"] = "stopped"
                        cfg["pid"] = None
                    else:
                        log(f"Container {name} restarted")
                        cfg["status"] = "running"
                    save_container_config(name, cfg)
            except Exception as e:
                log(f"ERROR: restart thread {name}: {e}")
                cfg = load_container_config(name)
                if cfg:
                    cfg["status"] = "stopped"
                    cfg["pid"] = None
                    save_container_config(name, cfg)
        import threading
        threading.Thread(target=do_restart, daemon=True).start()
        self.send_json({"message": f"Container '{name}' restarting"})

    def api_exec_container(self, name, data):
        cmd = data.get("command", "")
        if not cmd:
            self.send_error(400, "Command required")
            return
        config = load_container_config(name)
        if not config or config.get("status") != "running":
            self.send_error(400, "Container not running")
            return
        merged = os.path.join(CONTAINERS_DIR, name, "merged")
        try:
            proc_mounted = os.path.exists(os.path.join(merged, "proc", "self"))
            dev_null = os.path.exists(os.path.join(merged, "dev", "null"))
            pre_cmds = "export PATH=/bin:/sbin:/usr/bin:/usr/sbin; "
            if not proc_mounted:
                pre_cmds += "mount -t proc proc /proc 2>/dev/null; "
            if not dev_null:
                pre_cmds += (
                    "mkdir -p /dev/pts /dev/shm 2>/dev/null; "
                    "mount -t devtmpfs devtmpfs /dev 2>/dev/null || true; "
                    "mknod /dev/null c 1 3 2>/dev/null && chmod 666 /dev/null; "
                    "mknod /dev/zero c 1 5 2>/dev/null && chmod 666 /dev/zero; "
                    "mknod /dev/random c 1 8 2>/dev/null && chmod 666 /dev/random; "
                    "mknod /dev/urandom c 1 9 2>/dev/null && chmod 666 /dev/urandom; "
                    "mknod /dev/tty c 5 0 2>/dev/null && chmod 666 /dev/tty; "
                    "mount -t devpts devpts /dev/pts 2>/dev/null || true; "
                )
            wrapped = (
                pre_cmds
                + 'hostname ' + name + ' 2>/dev/null; '
                + 'cd /root 2>/dev/null || cd /; '
                + cmd
            )
            shell_cmd = 'chroot ' + merged + ' /bin/sh -c ' + repr(wrapped)
            result = subprocess.run(
                ["/system/bin/sh", "-c", shell_cmd],
                capture_output=True, text=True, timeout=30
            )
            self.send_json({"stdout": result.stdout, "stderr": result.stderr, "code": result.returncode})
        except Exception as e:
            self.send_error(500, str(e))

    def api_upload_file(self, path):
        parts = path.split("/")
        if len(parts) < 5:
            self.send_error(400, "Usage: /api/containers/<name>/upload")
            return
        name = parts[3]
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return
        static_path = config.get("static_path", "/var/www/html")
        merged = os.path.join(CONTAINERS_DIR, name, "merged")
        dest = os.path.join(merged, static_path.lstrip("/"))

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_error(400, "Expected multipart/form-data")
            return

        boundary = content_type.split("boundary=")[1].strip()
        if boundary.startswith('"'):
            boundary = boundary[1:-1]
        boundary_bytes = boundary.encode()

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        parts_raw = body.split(b"--" + boundary_bytes)
        files_saved = []
        for part in parts_raw:
            if b"Content-Disposition" not in part:
                continue
            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                continue
            header = part[:header_end].decode("utf-8", errors="replace")
            file_data = part[header_end + 4:]
            if file_data.endswith(b"\r\n"):
                file_data = file_data[:-2]

            filename = None
            for token in header.split(";"):
                token = token.strip()
                if token.startswith("filename="):
                    filename = token.split("=", 1)[1].strip('"')
            if not filename:
                continue

            if filename.lower().endswith(".zip"):
                import zipfile, io, tempfile
                try:
                    with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
                        for info in zf.infolist():
                            if info.is_dir():
                                continue
                            out_path = os.path.join(dest, info.filename)
                            os.makedirs(os.path.dirname(out_path), exist_ok=True)
                            with open(out_path, "wb") as f:
                                f.write(zf.read(info.filename))
                            files_saved.append(info.filename)
                except Exception as e:
                    self.send_error(500, f"Failed to extract zip: {e}")
                    return
            else:
                out_path = os.path.join(dest, filename)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(file_data)
                files_saved.append(filename)

        self.send_json({"message": f"Uploaded {len(files_saved)} file(s)", "files": files_saved})

    # ============================================================
    # File Explorer API
    # ============================================================

    def _get_merged_path(self, name):
        config = load_container_config(name)
        if not config:
            return None, None
        merged = os.path.join(CONTAINERS_DIR, name, "merged")
        return merged, config

    def _safe_path(self, merged, rel_path):
        rel_path = rel_path.lstrip("/")
        full = os.path.normpath(os.path.join(merged, rel_path))
        if not full.startswith(merged):
            return None
        return full

    def _file_info(self, full_path, rel_path):
        try:
            st = os.stat(full_path)
            is_dir = os.path.isdir(full_path)
            return {
                "name": os.path.basename(rel_path),
                "path": "/" + rel_path,
                "type": "directory" if is_dir else "file",
                "size": st.st_size if not is_dir else 0,
                "modified": int(st.st_mtime),
                "permissions": oct(st.st_mode)[-3:]
            }
        except Exception:
            return None

    def api_files_list(self, name, qs):
        merged, config = self._get_merged_path(name)
        if not merged:
            self.send_error(404, f"Container '{name}' not found")
            return
        rel_path = ""
        for param in qs.split("&"):
            if param.startswith("path="):
                rel_path = unquote(param.split("=", 1)[1])
        full = self._safe_path(merged, rel_path)
        if not full or not os.path.isdir(full):
            self.send_error(400, "Invalid path")
            return
        items = []
        try:
            for entry in sorted(os.listdir(full)):
                entry_rel = os.path.join(rel_path, entry) if rel_path else entry
                entry_full = os.path.join(merged, entry_rel)
                info = self._file_info(entry_full, entry_rel)
                if info:
                    items.append(info)
        except PermissionError:
            self.send_error(403, "Permission denied")
            return
        self.send_json({"path": "/" + rel_path.lstrip("/"), "items": items})

    def api_files_read(self, name, qs):
        merged, config = self._get_merged_path(name)
        if not merged:
            self.send_error(404, f"Container '{name}' not found")
            return
        rel_path = ""
        for param in qs.split("&"):
            if param.startswith("path="):
                rel_path = unquote(param.split("=", 1)[1])
        full = self._safe_path(merged, rel_path)
        if not full or not os.path.isfile(full):
            self.send_error(400, "Invalid file path")
            return
        try:
            size = os.path.getsize(full)
            if size > 2 * 1024 * 1024:
                self.send_error(400, "File too large (>2MB)")
                return
            with open(full, "rb") as f:
                data = f.read()
            try:
                content = data.decode("utf-8")
                is_binary = False
            except UnicodeDecodeError:
                import base64
                content = base64.b64encode(data).decode("ascii")
                is_binary = True
            self.send_json({"path": "/" + rel_path.lstrip("/"), "content": content, "binary": is_binary, "size": size})
        except Exception as e:
            self.send_error(500, str(e))

    def api_files_write(self, name, data):
        merged, config = self._get_merged_path(name)
        if not merged:
            self.send_error(404, f"Container '{name}' not found")
            return
        rel_path = data.get("path", "")
        content = data.get("content", "")
        if not rel_path:
            self.send_error(400, "path required")
            return
        full = self._safe_path(merged, rel_path)
        if not full:
            self.send_error(400, "Invalid path")
            return
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(content)
            self.send_json({"message": f"File '{rel_path}' saved"})
        except Exception as e:
            self.send_error(500, str(e))

    def api_files_mkdir(self, name, data):
        merged, config = self._get_merged_path(name)
        if not merged:
            self.send_error(404, f"Container '{name}' not found")
            return
        rel_path = data.get("path", "")
        if not rel_path:
            self.send_error(400, "path required")
            return
        full = self._safe_path(merged, rel_path)
        if not full:
            self.send_error(400, "Invalid path")
            return
        try:
            os.makedirs(full, exist_ok=True)
            self.send_json({"message": f"Directory '{rel_path}' created"})
        except Exception as e:
            self.send_error(500, str(e))

    def api_files_delete(self, name, qs):
        merged, config = self._get_merged_path(name)
        if not merged:
            self.send_error(404, f"Container '{name}' not found")
            return
        rel_path = ""
        for param in qs.split("&"):
            if param.startswith("path="):
                rel_path = unquote(param.split("=", 1)[1])
        if not rel_path or rel_path == "/":
            self.send_error(400, "Cannot delete root")
            return
        full = self._safe_path(merged, rel_path)
        if not full or not os.path.exists(full):
            self.send_error(404, "File not found")
            return
        try:
            if os.path.isdir(full):
                import shutil
                shutil.rmtree(full)
            else:
                os.remove(full)
            self.send_json({"message": f"Deleted '{rel_path}'"})
        except Exception as e:
            self.send_error(500, str(e))

    def api_files_rename(self, name, data):
        merged, config = self._get_merged_path(name)
        if not merged:
            self.send_error(404, f"Container '{name}' not found")
            return
        old_path = data.get("old_path", "")
        new_path = data.get("new_path", "")
        if not old_path or not new_path:
            self.send_error(400, "old_path and new_path required")
            return
        full_old = self._safe_path(merged, old_path)
        full_new = self._safe_path(merged, new_path)
        if not full_old or not full_new:
            self.send_error(400, "Invalid path")
            return
        if not os.path.exists(full_old):
            self.send_error(404, "Source not found")
            return
        try:
            os.rename(full_old, full_new)
            self.send_json({"message": f"Renamed '{old_path}' to '{new_path}'"})
        except Exception as e:
            self.send_error(500, str(e))

    def api_files_download(self, name, qs):
        merged, config = self._get_merged_path(name)
        if not merged:
            self.send_error(404, f"Container '{name}' not found")
            return
        rel_path = ""
        for param in qs.split("&"):
            if param.startswith("path="):
                rel_path = unquote(param.split("=", 1)[1])
        full = self._safe_path(merged, rel_path)
        if not full or not os.path.isfile(full):
            self.send_error(400, "Invalid file")
            return
        try:
            with open(full, "rb") as f:
                data = f.read()
            fname = os.path.basename(rel_path)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()
        except Exception as e:
            self.send_error(500, str(e))

    def api_files_stat(self, name, qs):
        merged, config = self._get_merged_path(name)
        if not merged:
            self.send_error(404, f"Container '{name}' not found")
            return
        rel_path = ""
        for param in qs.split("&"):
            if param.startswith("path="):
                rel_path = unquote(param.split("=", 1)[1])
        full = self._safe_path(merged, rel_path)
        if not full or not os.path.exists(full):
            self.send_error(404, "Not found")
            return
        info = self._file_info(full, rel_path)
        if info:
            self.send_json(info)
        else:
            self.send_error(500, "Could not stat file")

    def api_update_container(self, name, data):
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return
        if "resources" in data:
            config.setdefault("resources", {}).update(data["resources"])
        if "policies" in data:
            config.setdefault("policies", {}).update(data["policies"])
        if "port_mappings" in data:
            config["port_mappings"] = data["port_mappings"]
        if "ip_address" in data:
            config["ip_address"] = data["ip_address"]
        if "autostart" in data:
            config["autostart"] = data["autostart"]
        if "serves_static" in data:
            config["serves_static"] = data["serves_static"]
        if "static_path" in data:
            config["static_path"] = data["static_path"]
        if "s6" in data:
            config["s6"] = data["s6"]
        if "root_password" in data and data["root_password"]:
            new_pass = data["root_password"]
            if len(new_pass) < 4:
                self.send_error(400, "Password must be at least 4 characters")
                return
            config["root_password"] = new_pass
            save_container_config(name, config)
            merged = os.path.join(CONTAINERS_DIR, name, "merged")
            if os.path.isdir(merged):
                rootfs = merged
                # Set password via shadow directly (most reliable)
                enc = ""
                for op in [os.path.join(rootfs, "usr/bin/openssl"), os.path.join(rootfs, "usr/sbin/openssl")]:
                    try:
                        r = subprocess.run([op, "passwd", "-1", new_pass], capture_output=True, text=True, timeout=10)
                        if r.returncode == 0:
                            enc = r.stdout.strip()
                            break
                    except Exception:
                        pass
                if enc and os.path.isfile(os.path.join(rootfs, "etc/shadow")):
                    try:
                        with open(os.path.join(rootfs, "etc/shadow"), "r") as f:
                            shadow = f.read()
                        import re
                        shadow = re.sub(r"^root:[^:]*:", f"root:{enc}:", shadow, count=1, flags=re.MULTILINE)
                        with open(os.path.join(rootfs, "etc/shadow"), "w") as f:
                            f.write(shadow)
                    except Exception:
                        pass
                elif os.path.isfile(os.path.join(rootfs, "usr/bin/chpasswd")):
                    try:
                        subprocess.run(
                            ["su", "-c", f"echo 'root:{new_pass}' | chroot {rootfs} /usr/bin/chpasswd"],
                            capture_output=True, timeout=10
                        )
                    except Exception:
                        pass
        save_container_config(name, config)
        merged = os.path.join(CONTAINERS_DIR, name, "merged")
        if os.path.isdir(merged):
            _service = config.get("template", "")
            _port = ""
            _pm = config.get("port_mappings", [])
            if _pm:
                _port = str(_pm[0].get("container_port", ""))
            _sp = config.get("static_path", "")
            _s6 = "true" if config.get("s6", False) else "false"
            _write_ank_config(merged, _service, _port, _sp, _s6)
        self.send_json({"message": f"Container '{name}' updated"})

    def api_pull_image(self, data):
        version = data.get("version", "3.20")
        output, code = run_script("download-rootfs.sh", version)
        if code != 0:
            self.send_error(500, f"Failed to pull image: {output}")
            return
        # Generate ank-alpinebase-{version} from downloaded alpine
        alpine_dir = os.path.join(IMAGES_DIR, f"alpine-{version}")
        ankbase_dir = os.path.join(IMAGES_DIR, f"ank-alpinebase-{version}")
        if os.path.isdir(alpine_dir) and not os.path.isdir(ankbase_dir):
            try:
                import shutil
                shutil.copytree(alpine_dir, ankbase_dir)
                # Install basic packages into the new ank-alpinebase
                merged = ankbase_dir
                _merged_write = os.path.join(merged, "etc/resolv.conf")
                os.makedirs(os.path.dirname(_merged_write), exist_ok=True)
                with open(_merged_write, "w") as f:
                    f.write("nameserver 8.8.8.8\nnameserver 8.8.4.4\n")
                # Install openssh/bash/busybox/shadow/s6 via chroot
                merged_dev = os.path.join(merged, "dev")
                merged_proc = os.path.join(merged, "proc")
                try:
                    os.makedirs(merged_dev, exist_ok=True)
                    os.makedirs(merged_proc, exist_ok=True)
                    subprocess.run(["mount", "-t", "tmpfs", "-o", "size=16m", "tmpfs", merged_dev], timeout=5)
                    subprocess.run(["mount", "-t", "proc", "proc", merged_proc], timeout=5)
                    subprocess.run(["mknod", os.path.join(merged_dev, "null"), "c", "1", "3"], timeout=5)
                    subprocess.run(["chmod", "666", os.path.join(merged_dev, "null")], timeout=5)
                    subprocess.run(["mknod", os.path.join(merged_dev, "urandom"), "c", "1", "9"], timeout=5)
                    subprocess.run(["chmod", "666", os.path.join(merged_dev, "urandom")], timeout=5)
                    subprocess.run(["chroot", merged, "/sbin/apk", "add", "--no-cache",
                                    "busybox", "bash", "shadow", "openssh", "openssl", "s6"],
                                   capture_output=True, timeout=120)
                except Exception:
                    pass
                finally:
                    for m in [merged_proc, merged_dev]:
                        try: subprocess.run(["umount", m], timeout=5)
                        except Exception: pass
                # Mark as ank-alpinebase
                with open(os.path.join(merged, ".ank-base"), "w") as f:
                    f.write(f"ank-alpinebase-{version}\n")
            except Exception:
                pass
        self.send_json({"message": f"Image 'ank-alpinebase-{version}' ready"})

    # ============================================================
    # Image Templates
    # ============================================================

    IMAGE_TEMPLATES = [
        {
            "id": "alpine",
            "name": "Alpine 3.20",
            "description": "Minimal Linux rootfs (~8MB). Base for all containers.",
            "icon": "bi-hdd-stack",
            "color": "#06b6d4",
            "image": "alpine-3.20",
            "base": "alpine-3.20",
            "packages": [],
            "port": None,
            "category": "base"
        },
        {
            "id": "python",
            "name": "Python 3.12",
            "description": "Alpine + Python 3.12. Ready for scripts and APIs.",
            "icon": "bi-filetype-py",
            "color": "#3776AB",
            "image": "python-3.20",
            "base": "python-3.20",
            "packages": ["python3", "py3-pip"],
            "port": 5000,
            "category": "runtime",
            "serves_static": True,
            "static_path": "/var/www/app"
        },
        {
            "id": "nginx",
            "name": "Nginx Static",
            "description": "Web server for static sites. Upload HTML/ZIP and it's live.",
            "icon": "bi-globe2",
            "color": "#009639",
            "image": "nginx-3.20",
            "base": "nginx-3.20",
            "packages": ["nginx", "curl"],
            "port": 8080,
            "category": "server",
            "serves_static": True,
            "static_path": "/var/www/html"
        },
        {
            "id": "apache",
            "name": "Apache Static",
            "description": "Apache web server. Upload HTML/ZIP and serve static content.",
            "icon": "bi-globe",
            "color": "#d22128",
            "image": "apache-3.20",
            "base": "apache-3.20",
            "packages": ["apache2", "curl"],
            "port": 9090,
            "category": "server",
            "serves_static": True,
            "static_path": "/var/www/localhost/htdocs"
        },
        {
            "id": "php",
            "name": "PHP 8.2",
            "description": "Alpine + PHP 8.2. For dynamic PHP apps (built-in server :8000).",
            "icon": "bi-filetype-php",
            "color": "#777BB4",
            "image": "php-3.20",
            "base": "php-3.20",
            "packages": ["php82", "php82-mbstring", "php82-json", "php82-cgi"],
            "port": 8000,
            "category": "runtime",
            "serves_static": True,
            "static_path": "/var/www/php"
        },
        {
            "id": "node",
            "name": "Node.js 20",
            "description": "Alpine + Node.js. For JavaScript/TypeScript apps.",
            "icon": "bi-filetype-js",
            "color": "#339933",
            "image": "node-3.20",
            "base": "node-3.20",
            "packages": ["nodejs", "npm"],
            "port": 3000,
            "category": "runtime",
            "serves_static": True,
            "static_path": "/var/www/app"
        }
    ]

    def api_image_templates(self):
        templates = []
        alpine_ready = os.path.isdir(os.path.join(IMAGES_DIR, "ank-alpinebase-3.20")) and os.path.lexists(os.path.join(IMAGES_DIR, "ank-alpinebase-3.20", "bin/sh"))
        for t in self.IMAGE_TEMPLATES:
            tpl = dict(t)
            if t["category"] == "base":
                tpl["base_ready"] = alpine_ready
            else:
                tpl["base_ready"] = alpine_ready
                tpl["image_ready"] = os.path.isdir(os.path.join(IMAGES_DIR, t["base"]))
            templates.append(tpl)
        self.send_json(templates)

    def api_deploy_template(self, data):
        global _building
        template_id = data.get("template")
        container_name = data.get("name")
        if not template_id or not container_name:
            self.send_error(400, "template and name required")
            return
        if _building:
            self.send_error(409, "A build is already in progress. Please wait for it to finish.")
            return

        template = None
        for t in self.IMAGE_TEMPLATES:
            if t["id"] == template_id:
                template = t
                break
        if not template:
            self.send_error(404, f"Template '{template_id}' not found")
            return

        base_img = os.path.join(IMAGES_DIR, "ank-alpinebase-3.20")
        if not os.path.isdir(base_img):
            self.send_error(400, "Base ank-alpinebase-3.20 image not found. Reinstall the module.")
            return

        root_password = data.get("root_password", "admin123")

        # Write stub config with "building" status immediately
        stub_dir = os.path.join(CONTAINERS_DIR, container_name)
        os.makedirs(stub_dir, exist_ok=True)
        ssh_port = self._find_free_port(2200)
        stub_config = {
            "name": container_name,
            "status": "building",
            "image": "ank-alpinebase-3.20",
            "mode": get_mode().get("mode", "shared_host"),
            "autostart": False,
            "ip_address": "",
            "ssh_port": ssh_port,
            "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pid": None,
            "policies": {"inter_container_p2p": False, "allow_host_access": False, "allow_internet": True},
            "resources": {"memory_limit": "256M", "cpu_limit_percent": 50},
            "port_mappings": [],
            "root_password": root_password,
            "template": template_id,
            "template_name": template["name"],
            "s6": False
        }
        save_container_config(container_name, stub_config)

        def _do_deploy():
            global _building
            _building = True
            log_path = os.path.join(ANK_DIR, "logs", f"{container_name}.log")
            try:
                with open(log_path, "w") as lf:
                    lf.write(f"Deploying template '{template['name']}' as '{container_name}'...\n")
                    lf.flush()

                pkgs = " ".join(template.get("packages", []))
                output, code = run_script("container.sh", "create", container_name, "ank-alpinebase-3.20", str(root_password), str(ssh_port), pkgs, timeout=300)
                with open(log_path, "a") as lf:
                    lf.write(output + "\n")
                    lf.flush()

                merged = os.path.join(CONTAINERS_DIR, container_name, "merged")

                # Check if container was actually created
                if not os.path.isdir(merged):
                    log(f"ERROR: container.sh create failed for {container_name} (code={code})")
                    with open(log_path, "a") as lf:
                        lf.write(f"ERROR: Container creation failed (merged dir not found)\n")
                    cfg = load_container_config(container_name)
                    if cfg:
                        cfg["status"] = "failed"
                        save_container_config(container_name, cfg)
                    return

                def _chroot(cmd, timeout=30):
                    wrapped = "export PATH=/bin:/sbin:/usr/bin:/usr/sbin; " + cmd
                    full = f"chroot {merged} /bin/sh -c '{wrapped}'"
                    try:
                        return subprocess.run(
                            ["/system/bin/sh", "-c", full],
                            capture_output=True, text=True, timeout=timeout
                        )
                    except subprocess.TimeoutExpired as e:
                        partial_out = (e.stdout or "") + (e.stderr or "")
                        class _Result:
                            pass
                        r = _Result()
                        r.returncode = -1
                        r.stdout = partial_out
                        r.stderr = f"TIMEOUT after {timeout}s"
                        return r

                def _chroot_bg(cmd):
                    """Run command in chroot without waiting (for daemons)."""
                    wrapped = "export PATH=/bin:/sbin:/usr/bin:/usr/sbin; " + cmd
                    full = f"chroot {merged} /bin/sh -c '{wrapped}'"
                    try:
                        p = subprocess.Popen(
                            ["/system/bin/sh", "-c", full],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True
                        )
                        log(f"Background chroot PID: {p.pid} cmd: {cmd}")
                    except Exception as e:
                        log(f"WARNING: _chroot_bg failed: {e}")

                _chroot('mkdir -p /etc; echo "nameserver 8.8.8.8" > /etc/resolv.conf; echo "nameserver 8.8.4.4" >> /etc/resolv.conf')

                config = load_container_config(container_name)
                _s6_enabled = config.get("s6", False) if config else False
                if config:
                    config["template"] = template_id
                    config["template_name"] = template["name"]
                    config["image"] = f"{template['name'].lower().replace(' ', '-')}"
                    if template.get("port"):
                        desired_port = template["port"]
                        actual_port = self._find_free_port(desired_port)
                        port_warnings = []
                        if actual_port != desired_port:
                            port_warnings.append(f"Port {desired_port} in use, using {actual_port} instead")
                            log(f"Port {desired_port} busy for {container_name}, using {actual_port}")
                        config["port_mappings"] = [{"host_port": actual_port, "container_port": desired_port, "protocol": "tcp"}]
                        if port_warnings:
                            config["port_warning"] = "; ".join(port_warnings)
                    if template.get("serves_static"):
                        config["serves_static"] = True
                        config["static_path"] = template["static_path"]
                    save_container_config(container_name, config)

                if template.get("packages"):
                    pkg_list = " ".join(template["packages"])
                    log(f"Installing packages: {pkg_list} in {container_name}")
                    r = _chroot(f"apk update && apk add --allow-untrusted {pkg_list}", timeout=180)
                    output = (r.stdout or "") + (r.stderr or "")
                    if r.returncode != 0:
                        log(f"WARNING: apk install output: {output[-500:]}")

                if template_id == "nginx":
                    static_dir = template["static_path"]
                    _chroot(f'mkdir -p {static_dir} /run/nginx')
                    _write_file(os.path.join(merged, static_dir.lstrip('/'), 'index.html'), ANK_NGINX_HTML)
                    _write_file(os.path.join(merged, 'etc/nginx/nginx.conf'), ANK_NGINX_CONF)
                    _write_ank_config(merged, 'nginx', 8080, static_dir, "true" if _s6_enabled else "false")

                elif template_id == "apache":
                    static_dir = template["static_path"]
                    _chroot(f'mkdir -p {static_dir}')
                    _write_file(os.path.join(merged, static_dir.lstrip('/'), 'index.html'), ANK_APACHE_HTML)
                    _write_ank_config(merged, 'apache', 9090, static_dir, "true" if _s6_enabled else "false")

                elif template_id == "php":
                    php_dir = "/var/www/php"
                    _chroot(f'mkdir -p {php_dir}')
                    _write_file(os.path.join(merged, php_dir.lstrip('/'), 'index.php'), ANK_PHP_INDEX)
                    _write_ank_config(merged, 'php', 8000, php_dir, "true" if _s6_enabled else "false")

                elif template_id == "node":
                    node_dir = "/var/www/app"
                    _chroot(f'mkdir -p {node_dir}')
                    _write_file(os.path.join(merged, node_dir.lstrip('/'), 'server.js'), ANK_NODE_SERVER)
                    _write_file(os.path.join(merged, node_dir.lstrip('/'), 'package.json'), '{"name":"ank-node-app","version":"1.0.0","main":"server.js"}')
                    _write_ank_config(merged, 'node', 3000, node_dir, "true" if _s6_enabled else "false")

                elif template_id == "python":
                    py_dir = "/var/www/app"
                    _chroot(f'mkdir -p {py_dir}')
                    _write_file(os.path.join(merged, py_dir.lstrip('/'), 'server.py'), ANK_PYTHON_SERVER)
                    _write_ank_config(merged, 'python', 5000, py_dir, "true" if _s6_enabled else "false")

                cfg = load_container_config(container_name)
                if cfg:
                    cfg["status"] = "stopped"
                    save_container_config(container_name, cfg)
                log(f"Template '{template['name']}' deployed as '{container_name}'")
                with open(log_path, "a") as lf:
                    lf.write(f"Deploy complete.\n")

            except Exception as e:
                log(f"ERROR: deploy thread {container_name}: {e}")
                try:
                    with open(log_path, "a") as lf:
                        lf.write(f"FATAL: {e}\n")
                except Exception:
                    pass
                cfg = load_container_config(container_name)
                if cfg:
                    cfg["status"] = "failed"
                    save_container_config(container_name, cfg)
            finally:
                _building = False

        threading.Thread(target=_do_deploy, daemon=True).start()
        self.send_json({"message": f"Deploying template '{template['name']}' as '{container_name}'...", "name": container_name}, 201)

    def api_build_ankfile(self, data):
        global _building
        ankfile_content = data.get("content", "")
        container_name = data.get("name", "")
        if not ankfile_content:
            self.send_error(400, "Ankfile content required")
            return
        if _building:
            self.send_error(409, "A build is already in progress. Please wait for it to finish.")
            return
        if not container_name:
            import re
            m = re.search(r'^FROM\s+(\S+)', ankfile_content, re.MULTILINE)
            container_name = m.group(1).split("/")[-1].replace(":", "-") if m else "ank-build"

        lines = ankfile_content.strip().split('\n')
        base_image = None
        commands = []
        ports = []
        workdir = "/"
        volumes = []
        root_password = ""
        cmd_line = ""

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('FROM '):
                base_image = line.split(' ', 1)[1].strip()
            elif line.startswith('PASSWD '):
                root_password = line[7:].strip()
            elif line.startswith('RUN '):
                commands.append(line[4:].strip())
            elif line.startswith('CMD '):
                cmd_line = line[4:].strip().strip('"').strip("'")
            elif line.startswith('EXPOSE '):
                try:
                    ports.append(int(line[7:].strip()))
                except ValueError:
                    pass
            elif line.startswith('WORKDIR '):
                workdir = line[8:].strip()
            elif line.startswith('VOLUME '):
                volumes.append(line[7:].strip())

        if not base_image:
            self.send_error(400, "Ankfile must have a FROM instruction")
            return

        if not root_password:
            root_password = "ank123"

        # Write stub config with "building" status immediately
        ssh_port = self._find_free_port(2200)
        stub_dir = os.path.join(CONTAINERS_DIR, container_name)
        os.makedirs(stub_dir, exist_ok=True)
        stub_config = {
            "name": container_name,
            "status": "building",
            "image": base_image,
            "mode": get_mode().get("mode", "shared_host"),
            "autostart": False,
            "ip_address": "",
            "ssh_port": ssh_port,
            "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pid": None,
            "policies": {"inter_container_p2p": False, "allow_host_access": False, "allow_internet": True},
            "resources": {"memory_limit": "256M", "cpu_limit_percent": 50},
            "port_mappings": [],
            "root_password": root_password
        }
        save_container_config(container_name, stub_config)

        def _do_build():
            global _building
            _building = True
            log_path = os.path.join(ANK_DIR, "logs", f"{container_name}.log")
            try:
                with open(log_path, "w") as lf:
                    lf.write(f"Building Ankfile ({base_image}) as '{container_name}'...\n")
                    lf.flush()

                # Map alpine-X.XX -> ank-alpinebase-X.XX
                mapped_image = base_image
                if base_image.startswith("alpine-"):
                    mapped_image = f"ank-alpinebase-{base_image[7:]}"

                pkgs = ""
                for t in self.IMAGE_TEMPLATES:
                    if t["base"] == base_image or t["image"] == base_image or t["base"] == mapped_image or t["image"] == mapped_image:
                        pkgs = " ".join(t.get("packages", []))
                        break

                output, code = run_script("container.sh", "create", container_name, mapped_image, root_password, str(ssh_port), pkgs, timeout=300)
                with open(log_path, "a") as lf:
                    lf.write(output + "\n")
                    lf.flush()

                merged = os.path.join(CONTAINERS_DIR, container_name, "merged")

                # Check if container was actually created
                if not os.path.isdir(merged):
                    log(f"ERROR: container.sh create failed for {container_name} (code={code})")
                    with open(log_path, "a") as lf:
                        lf.write(f"ERROR: Container creation failed (merged dir not found)\n")
                    cfg = load_container_config(container_name)
                    if cfg:
                        cfg["status"] = "failed"
                        save_container_config(container_name, cfg)
                    return

                def _chroot(cmd, timeout=60):
                    wrapped = "export PATH=/bin:/sbin:/usr/bin:/usr/sbin; " + cmd
                    full = f"chroot {merged} /bin/sh -c '{wrapped}'"
                    try:
                        return subprocess.run(
                            ["/system/bin/sh", "-c", full],
                            capture_output=True, text=True, timeout=timeout
                        )
                    except subprocess.TimeoutExpired as e:
                        # Return partial output so user can see what happened
                        partial_out = (e.stdout or "") + (e.stderr or "")
                        class _Result:
                            pass
                        r = _Result()
                        r.returncode = -1
                        r.stdout = partial_out
                        r.stderr = f"TIMEOUT after {timeout}s"
                        return r

                _chroot('mkdir -p /etc; echo "nameserver 8.8.8.8" > /etc/resolv.conf; echo "nameserver 8.8.4.4" >> /etc/resolv.conf')

                for cmd in commands:
                    log(f"Ankfile RUN: {cmd}")
                    with open(log_path, "a") as lf:
                        lf.write(f"RUN: {cmd}\n")
                        lf.flush()
                    r = _chroot(cmd, timeout=300)
                    output = (r.stdout or "") + (r.stderr or "")
                    if r.returncode != 0:
                        log(f"Ankfile RUN failed: {output[-500:]}")
                        with open(log_path, "a") as lf:
                            lf.write(f"FAILED (rc={r.returncode}): {output[-500:]}\n")
                    else:
                        with open(log_path, "a") as lf:
                            lf.write(f"OK: {output[-300:]}\n")

                if cmd_line:
                    _write_ank_config(merged, cmd_line, ports[0] if ports else "", "", "false")
                    log(f"Ankfile CMD: {cmd_line}")
                    with open(log_path, "a") as lf:
                        lf.write(f"CMD: {cmd_line}\n")

                config = load_container_config(container_name)
                if config:
                    config["image"] = mapped_image
                    config["template"] = "ankfile"
                    config["template_name"] = f"Ankfile ({base_image})"
                    config["status"] = "stopped"
                    if ports:
                        config["port_mappings"] = [{"host_port": port, "container_port": port, "protocol": "tcp"} for port in ports]
                        for p in ports:
                            _write_portfwd(merged, p)
                    save_container_config(container_name, config)
                log(f"Ankfile built as '{container_name}'")
                with open(log_path, "a") as lf:
                    lf.write(f"Build complete.\n")

            except Exception as e:
                log(f"ERROR: build thread {container_name}: {e}")
                try:
                    with open(log_path, "a") as lf:
                        lf.write(f"FATAL: {e}\n")
                except Exception:
                    pass
                cfg = load_container_config(container_name)
                if cfg:
                    cfg["status"] = "failed"
                    save_container_config(container_name, cfg)
            finally:
                _building = False

        threading.Thread(target=_do_build, daemon=True).start()
        self.send_json({"message": f"Building Ankfile as '{container_name}'...", "name": container_name}, 201)

    def api_shell(self, data):
        cmd = data.get("command", "")
        if not cmd:
            self.send_error(400, "Command required")
            return
        parts = cmd.strip().split()
        if not parts:
            self.send_json({"stdout": "", "stderr": "", "code": 0})
            return

        if parts[0] == "ank":
            self._run_ank_command(parts[1:])
        elif parts[0] == "ank-core":
            self._run_ank_core_command(parts[1:])
        else:
            try:
                result = subprocess.run(
                    ["/system/bin/sh", "-c", cmd],
                    capture_output=True, text=True, timeout=30
                )
                self.send_json({"stdout": result.stdout, "stderr": result.stderr, "code": result.returncode})
            except subprocess.TimeoutExpired:
                self.send_json({"stdout": "", "stderr": "Command timed out", "code": 1})
            except Exception as e:
                self.send_error(500, str(e))

    def _run_ank_command(self, args):
        if not args or args[0] in ("-h", "--help", "help"):
            self.send_json({"stdout":
                "ANK - Android Konteiner CLI\n\n"
                "Usage: ank <command> [args]\n\n"
                "Container commands:\n"
                "  ank ps                    List all containers\n"
                "  ank start <name>          Start a container\n"
                "  ank stop <name>           Stop a container\n"
                "  ank restart <name>        Restart a container\n"
                "  ank rm <name>             Delete a container\n"
                "  ank logs <name>           View container logs\n"
                "  ank exec <name> <cmd>     Execute command in container\n"
                "  ank inspect <name>        Show container details\n"
                "  ank images                List available images\n"
                "  ank templates             List deploy templates\n"
                "  ank deploy <tpl> <name>   Deploy a template\n"
                "  ank ankfile <name> <file> Build from Ankfile\n\n"
                "Options:\n"
                "  ank --help, -h            Show this help\n"
                "  ank --man <command>       Show detailed help for a command\n",
                "stderr": "", "code": 0})
            return

        if args[0] == "--man":
            cmd_name = args[1] if len(args) > 1 else ""
            man = self._get_man_page(cmd_name)
            self.send_json({"stdout": man, "stderr": "", "code": 0})
            return

        if args[0] == "ps":
            containers = []
            if os.path.exists(CONTAINERS_DIR):
                for name in sorted(os.listdir(CONTAINERS_DIR)):
                    if os.path.isdir(os.path.join(CONTAINERS_DIR, name)):
                        c = load_container_config(name)
                        if c:
                            containers.append(c)
            if not containers:
                self.send_json({"stdout": "No containers found.", "stderr": "", "code": 0})
                return
            lines = [f"{'NAME':<20} {'STATUS':<10} {'IP':<16} {'IMAGE':<15} {'PID':<8}"]
            lines.append("-" * 70)
            for c in containers:
                lines.append(f"{c.get('name','?'):<20} {c.get('status','?'):<10} {c.get('ip_address','N/A'):<16} {c.get('image','?'):<15} {c.get('pid','?'):<8}")
            self.send_json({"stdout": "\n".join(lines), "stderr": "", "code": 0})
            return

        if args[0] == "start":
            name = args[1] if len(args) > 1 else ""
            if not name:
                self.send_json({"stdout": "", "stderr": "Usage: ank start <name>", "code": 1})
                return
            output, code = run_script("container.sh", "start", name)
            status = "started" if code == 0 else "failed"
            self.send_json({"stdout": f"Container '{name}' {status}", "stderr": output if code != 0 else "", "code": code})
            return

        if args[0] == "stop":
            name = args[1] if len(args) > 1 else ""
            if not name:
                self.send_json({"stdout": "", "stderr": "Usage: ank stop <name>", "code": 1})
                return
            output, code = run_script("container.sh", "stop", name)
            status = "stopped" if code == 0 else "failed"
            self.send_json({"stdout": f"Container '{name}' {status}", "stderr": output if code != 0 else "", "code": code})
            return

        if args[0] == "restart":
            name = args[1] if len(args) > 1 else ""
            if not name:
                self.send_json({"stdout": "", "stderr": "Usage: ank restart <name>", "code": 1})
                return
            output, code = run_script("container.sh", "stop", name)
            import time; time.sleep(1)
            output2, code2 = run_script("container.sh", "start", name)
            status = "restarted" if code2 == 0 else "failed"
            self.send_json({"stdout": f"Container '{name}' {status}", "stderr": output2 if code2 != 0 else "", "code": code2})
            return

        if args[0] == "rm":
            name = args[1] if len(args) > 1 else ""
            if not name:
                self.send_json({"stdout": "", "stderr": "Usage: ank rm <name>", "code": 1})
                return
            output, code = run_script("container.sh", "delete", name)
            status = "deleted" if code == 0 else "failed"
            self.send_json({"stdout": f"Container '{name}' {status}", "stderr": output if code != 0 else "", "code": code})
            return

        if args[0] == "logs":
            name = args[1] if len(args) > 1 else ""
            if not name:
                self.send_json({"stdout": "", "stderr": "Usage: ank logs <name>", "code": 1})
                return
            log_path = os.path.join(ANK_DIR, "logs", f"{name}.log")
            if os.path.exists(log_path):
                with open(log_path, "r", errors="replace") as f:
                    lines = f.readlines()[-50:]
                self.send_json({"stdout": "".join(lines), "stderr": "", "code": 0})
            else:
                self.send_json({"stdout": f"No logs for '{name}'", "stderr": "", "code": 0})
            return

        if args[0] == "exec":
            if len(args) < 3:
                self.send_json({"stdout": "", "stderr": "Usage: ank exec <name> <command>", "code": 1})
                return
            name = args[1]
            cmd = " ".join(args[2:])
            config = load_container_config(name)
            if not config or config.get("status") != "running":
                self.send_json({"stdout": "", "stderr": f"Container '{name}' not running", "code": 1})
                return
            merged = os.path.join(CONTAINERS_DIR, name, "merged")
            try:
                wrapped = f"export PATH=/bin:/sbin:/usr/bin:/usr/sbin; hostname {name} 2>/dev/null; {cmd}"
                result = subprocess.run(
                    ["/system/bin/sh", "-c", f"chroot {merged} /bin/sh -c '{wrapped}'"],
                    capture_output=True, text=True, timeout=30
                )
                self.send_json({"stdout": result.stdout, "stderr": result.stderr, "code": result.returncode})
            except Exception as e:
                self.send_json({"stdout": "", "stderr": str(e), "code": 1})
            return

        if args[0] == "inspect":
            name = args[1] if len(args) > 1 else ""
            if not name:
                self.send_json({"stdout": "", "stderr": "Usage: ank inspect <name>", "code": 1})
                return
            c = load_container_config(name)
            if not c:
                self.send_json({"stdout": "", "stderr": f"Container '{name}' not found", "code": 1})
                return
            lines = [
                f"Name:       {c.get('name','?')}",
                f"Status:     {c.get('status','?')}",
                f"Image:      {c.get('image','?')}",
                f"Mode:       {c.get('mode','?')}",
                f"IP:         {c.get('ip_address','N/A')}",
                f"PID:        {c.get('pid','N/A')}",
                f"Template:   {c.get('template_name','none')}",
                f"Autostart:  {c.get('autostart',False)}",
                f"Memory:     {c.get('resources',{}).get('memory_limit','N/A')}",
                f"CPU:        {c.get('resources',{}).get('cpu_limit_percent','N/A')}%",
                f"Created:    {c.get('created_at','?')}",
            ]
            self.send_json({"stdout": "\n".join(lines), "stderr": "", "code": 0})
            return

        if args[0] == "images":
            images = []
            if os.path.exists(IMAGES_DIR):
                for name in sorted(os.listdir(IMAGES_DIR)):
                    p = os.path.join(IMAGES_DIR, name)
                    if os.path.isdir(p):
                        images.append(name)
            self.send_json({"stdout": "\n".join(images) if images else "No images found.", "stderr": "", "code": 0})
            return

        if args[0] == "templates":
            lines = []
            for t in self.IMAGE_TEMPLATES:
                status = "ready" if os.path.lexists(os.path.join(IMAGES_DIR, t["base"], "bin/sh")) else "need base"
                lines.append(f"{t['id']:<12} {t['name']:<20} {status}")
            self.send_json({"stdout": "\n".join(lines), "stderr": "", "code": 0})
            return

        if args[0] == "deploy":
            if len(args) < 3:
                self.send_json({"stdout": "", "stderr": "Usage: ank deploy <template> <name>", "code": 1})
                return
            self.api_deploy_template({"template": args[1], "name": args[2]})
            return

        if args[0] == "ankfile":
            if len(args) < 3:
                self.send_json({"stdout": "", "stderr": "Usage: ank ankfile <name> <path-to-ankfile>", "code": 1})
                return
            try:
                with open(args[2], "r") as f:
                    content = f.read()
                self.api_build_ankfile({"content": content, "name": args[1]})
            except FileNotFoundError:
                self.send_json({"stdout": "", "stderr": f"File not found: {args[2]}", "code": 1})
            return

        self.send_json({"stdout": "", "stderr": f"Unknown ank command: {args[0]}. Type 'ank --help' for usage.", "code": 1})

    def _run_ank_core_command(self, args):
        if not args or args[0] in ("-h", "--help", "help"):
            self.send_json({"stdout":
                "ANK-Core - Android Konteiner System Management\n\n"
                "Usage: ank-core <command> [args]\n\n"
                "System commands:\n"
                "  ank-core status            Show system status\n"
                "  ank-core restart           Restart server + all containers\n"
                "  ank-core shell             Open host shell (full access)\n"
                "  ank-core info              Show device info\n"
                "  ank-core network           Show network config\n"
                "  ank-core clean             Cleanup orphaned resources\n"
                "  ank-core logs              Show server logs\n\n"
                "Options:\n"
                "  ank-core --help, -h        Show this help\n"
                "  ank-core --man <command>   Show detailed help\n",
                "stderr": "", "code": 0})
            return

        if args[0] == "--man":
            cmd_name = args[1] if len(args) > 1 else ""
            man = self._get_core_man_page(cmd_name)
            self.send_json({"stdout": man, "stderr": "", "code": 0})
            return

        if args[0] == "status":
            config = load_config()
            total = running = stopped = 0
            if os.path.exists(CONTAINERS_DIR):
                for n in os.listdir(CONTAINERS_DIR):
                    if os.path.isdir(os.path.join(CONTAINERS_DIR, n)):
                        total += 1
                        c = load_container_config(n)
                        if c and c.get("status") == "running": running += 1
                        else: stopped += 1
            uptime_sec = 0
            try:
                with open("/proc/uptime", "r") as f: uptime_sec = float(f.read().split()[0])
            except: pass
            lines = [
                f"ANK Engine v{config.get('version','0.1')}",
                f"Uptime:     {int(uptime_sec//3600)}h {int((uptime_sec%3600)//60)}m",
                f"Containers: {running} running, {stopped} stopped, {total} total",
                f"Mode:       {get_mode().get('mode','compat')}",
                f"Network:    {config.get('network',{}).get('subnet','?')}/24",
                f"Port:       {PORT}",
            ]
            self.send_json({"stdout": "\n".join(lines), "stderr": "", "code": 0})
            return

        if args[0] == "restart":
            self.send_json({"stdout": "Restarting ANK server...", "stderr": "", "code": 0})
            import threading
            def do_restart():
                import time; time.sleep(1)
                os.system(f"fuser -k 8001/tcp 2>/dev/null; sleep 1; setsid sh {ANK_DIR}/ankfs/opt/ank/start-server.sh </dev/null >{ANK_DIR}/logs/server.log 2>&1 &")
            threading.Thread(target=do_restart, daemon=True).start()
            return

        if args[0] == "shell":
            self.send_json({"stdout": "Host shell access. Commands run directly on Android host.\nUse with caution.", "stderr": "", "code": 0,
                "shell": True})
            return

        if args[0] == "info":
            device = os.popen("getprop ro.product.model 2>/dev/null").read().strip() or "unknown"
            kernel = os.popen("uname -r 2>/dev/null").read().strip() or "unknown"
            mem_total = 0
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        parts = line.split()
                        if parts[0] == "MemTotal:": mem_total = int(parts[1])
            except: pass
            lines = [
                f"Device:     {device}",
                f"Kernel:     {kernel}",
                f"Memory:     {mem_total // 1024} MB total",
                f"Root:       {ANK_DIR}",
            ]
            self.send_json({"stdout": "\n".join(lines), "stderr": "", "code": 0})
            return

        if args[0] == "network":
            config = load_config()
            net = config.get("network", {})
            lines = [
                f"Bridge:     {net.get('bridge','ank0')}",
                f"Subnet:     {net.get('subnet','?')}/24",
                f"Gateway:    {net.get('gateway','?')}",
                f"NAT:        {'enabled' if net.get('nat',True) else 'disabled'}",
            ]
            self.send_json({"stdout": "\n".join(lines), "stderr": "", "code": 0})
            return

        if args[0] == "clean":
            output, code = run_script("cleanup.sh")
            self.send_json({"stdout": output or "Cleanup complete", "stderr": "", "code": code})
            return

        if args[0] == "logs":
            log_path = os.path.join(ANK_DIR, "logs", "server.log")
            if os.path.exists(log_path):
                with open(log_path, "r", errors="replace") as f:
                    lines = f.readlines()[-30:]
                self.send_json({"stdout": "".join(lines), "stderr": "", "code": 0})
            else:
                self.send_json({"stdout": "No server logs", "stderr": "", "code": 0})
            return

        if args[0] == "exec":
            cmd = " ".join(args[1:]) if len(args) > 1 else "sh"
            try:
                result = subprocess.run(
                    ["/system/bin/sh", "-c", cmd],
                    capture_output=True, text=True, timeout=30
                )
                self.send_json({"stdout": result.stdout, "stderr": result.stderr, "code": result.returncode})
            except Exception as e:
                self.send_json({"stdout": "", "stderr": str(e), "code": 1})
            return

        self.send_json({"stdout": "", "stderr": f"Unknown ank-core command: {args[0]}. Type 'ank-core --help' for usage.", "code": 1})

    def _get_man_page(self, cmd):
        man_pages = {
            "ps": "ank ps\n\nList all containers with their status, IP, image, and PID.\n\nUsage: ank ps\n\nExample:\n  ank ps\n  NAME                 STATUS     IP               IMAGE\n  my-site              running    10.20.30.3       alpine-3.20",
            "start": "ank start <name>\n\nStart a stopped container.\n\nUsage: ank start <name>\n\nExample:\n  ank start my-site",
            "stop": "ank stop <name>\n\nStop a running container.\n\nUsage: ank stop <name>",
            "restart": "ank restart <name>\n\nRestart a container (stop + start).\n\nUsage: ank restart <name>",
            "rm": "ank rm <name>\n\nDelete a container and its data permanently.\n\nUsage: ank rm <name>",
            "logs": "ank logs <name>\n\nView the last 50 lines of container logs.\n\nUsage: ank logs <name>",
            "exec": "ank exec <name> <command>\n\nExecute a command inside a running container.\n\nUsage: ank exec <name> <command>\n\nExample:\n  ank exec my-site ls /var/www/html",
            "inspect": "ank inspect <name>\n\nShow detailed container configuration.\n\nUsage: ank inspect <name>",
            "images": "ank images\n\nList all downloaded base images.\n\nUsage: ank images",
            "templates": "ank templates\n\nList available deployment templates.\n\nUsage: ank templates",
            "deploy": "ank deploy <template> <name>\n\nDeploy a container from a template.\n\nUsage: ank deploy <template> <name>\n\nTemplates: alpine, python, nginx, apache, php, node\n\nExample:\n  ank deploy nginx my-site",
        }
        return man_pages.get(cmd, f"No manual entry for 'ank {cmd}'. Available commands: {', '.join(man_pages.keys())}")

    def _get_core_man_page(self, cmd):
        man_pages = {
            "status": "ank-core status\n\nShow system status including uptime, container count, and mode.\n\nUsage: ank-core status",
            "restart": "ank-core restart\n\nRestart the ANK server. All running containers stay alive.\n\nUsage: ank-core restart",
            "shell": "ank-core shell\n\nFull host shell access. Commands run directly on the Android host.\n\nUsage: ank-core shell\n\nWarning: Use with caution. You have root access.",
            "info": "ank-core info\n\nShow device information (model, kernel, memory).\n\nUsage: ank-core info",
            "network": "ank-core network\n\nShow network configuration (bridge, subnet, gateway).\n\nUsage: ank-core network",
            "clean": "ank-core clean\n\nClean up orphaned resources (network namespaces, temp files).\n\nUsage: ank-core clean",
            "logs": "ank-core logs\n\nShow the last 30 lines of server logs.\n\nUsage: ank-core logs",
        }
        return man_pages.get(cmd, f"No manual entry for 'ank-core {cmd}'. Available commands: {', '.join(man_pages.keys())}")

    # ============================================================
    # Network API
    # ============================================================

    def api_list_networks(self):
        config = load_config()
        net = config.get("network", {})
        subnet = net.get("subnet", "10.20.30.0")
        prefix = subnet.rsplit(".", 1)[0]

        containers = []
        if os.path.exists(CONTAINERS_DIR):
            for name in os.listdir(CONTAINERS_DIR):
                c = load_container_config(name)
                if c and c.get("ip_address"):
                    containers.append({"name": c["name"], "ip": c["ip_address"], "status": c.get("status", "stopped")})

        networks = [{
            "id": "ank0",
            "name": net.get("bridge", "ank0"),
            "subnet": subnet + "/24",
            "gateway": net.get("gateway", prefix + ".1"),
            "nat": net.get("nat", True),
            "containers": containers,
            "mode": get_mode().get("mode", "shared_host")
        }]
        self.send_json(networks)

    def api_network_info(self):
        config = load_config()
        net = config.get("network", {})
        subnet = net.get("subnet", "10.20.30.0")
        prefix = subnet.rsplit(".", 1)[0]

        wan_if = "wlan0"
        for iface in ["rmnet0", "rmnet_data0", "ppp0"]:
            try:
                r = subprocess.run(["/system/bin/ip", "link", "show", iface],
                                   capture_output=True, text=True, timeout=5)
                if "UP" in r.stdout:
                    wan_if = iface
                    break
            except Exception:
                pass

        iptables_nat = []
        try:
            r = subprocess.run(["/system/bin/iptables", "-t", "nat", "-L", "POSTROUTING", "-n", "--line-numbers"],
                               capture_output=True, text=True, timeout=5)
            iptables_nat = r.stdout.strip().split("\n") if r.stdout.strip() else []
        except Exception:
            pass

        self.send_json({
            "bridge": net.get("bridge", "ank0"),
            "subnet": subnet + "/24",
            "gateway": net.get("gateway", prefix + ".1"),
            "wan_interface": wan_if,
            "nat_enabled": net.get("nat", True),
            "ip_forward": os.popen("cat /proc/sys/net/ipv4/ip_forward 2>/dev/null").read().strip() or "0",
            "iptables_nat": iptables_nat,
            "mode": get_mode().get("mode", "shared_host")
        })

    def api_create_network(self, data):
        subnet = data.get("subnet", "")
        if not subnet:
            self.send_error(400, "Subnet required (e.g. 10.20.30.0)")
            return

        parts = subnet.split(".")
        if len(parts) != 4 or parts[3] != "0":
            self.send_error(400, "Subnet must be a /24 network (e.g. 10.20.30.0)")
            return

        for p in parts[:3]:
            if not p.isdigit() or int(p) > 255:
                self.send_error(400, "Invalid subnet")
                return

        prefix = ".".join(parts[:3])
        gateway = data.get("gateway", prefix + ".1")
        bridge = data.get("bridge", "ank0")
        nat = data.get("nat", True)

        config = load_config()
        config["network"] = {
            "bridge": bridge,
            "subnet": subnet,
            "gateway": gateway,
            "nat": nat
        }
        save_config(config)

        # Apply network changes
        run_script("network.sh", "setup_bridge")

        self.send_json({"message": f"Network {subnet}/24 configured", "subnet": subnet, "gateway": gateway})

    def api_delete_network(self, net_id):
        self.send_error(400, "Cannot delete the primary network")

    # ============================================================
    # System API
    # ============================================================

    def api_get_config(self):
        config = load_config()
        self.send_json(config)

    def api_update_config(self, data):
        config = load_config()
        if "network" in data:
            config.setdefault("network", {}).update(data["network"])
        if "panel_port" in data:
            config["panel_port"] = data["panel_port"]
        if "bind_address" in data:
            config["bind_address"] = data["bind_address"]
        if "refresh_interval" in data:
            config["refresh_interval"] = data["refresh_interval"]
        if "autostart_on_boot" in data:
            config["autostart_on_boot"] = data["autostart_on_boot"]
        save_config(config)
        self.send_json({"message": "Configuration updated"})

    def api_restart_device(self):
        """Reboot the Android device."""
        log("RESTART_DEVICE: Rebooting device...")
        self.send_json({"message": "Device rebooting..."})
        import threading
        def _reboot():
            import time
            time.sleep(1)
            os.system("svc power reboot 2>/dev/null || reboot 2>/dev/null || su -c reboot 2>/dev/null")
        threading.Thread(target=_reboot, daemon=True).start()

    def api_restart_server(self):
        """Stop everything ANK and restart the server."""
        log("RESTART_SERVER: Stopping all containers and restarting...")
        import threading
        def _restart():
            import time
            # Stop all running containers
            for cfg_file in glob.glob(os.path.join(CONTAINERS_DIR, "*/config.json")):
                try:
                    with open(cfg_file) as f:
                        cfg = json.load(f)
                    if cfg.get("status") == "running":
                        name = cfg.get("name")
                        if name:
                            log(f"RESTART_SERVER: Stopping {name}...")
                            run_script("container.sh", "stop", name)
                except Exception:
                    pass
            # Kill server processes
            log("RESTART_SERVER: Killing server process...")
            time.sleep(2)
            os.system(f"fuser -k 8001/tcp 2>/dev/null")
            time.sleep(1)
            # Restart server
            log("RESTART_SERVER: Starting server...")
            ank_dir = os.path.dirname(ANK_DIR) if ANK_DIR.endswith("/ankfs") else ANK_DIR
            os.system(f"setsid sh {ANK_DIR}/opt/ank/start-server.sh </dev/null >{ANK_DIR}/logs/server.log 2>&1 &")
            log("RESTART_SERVER: Done")
        threading.Thread(target=_restart, daemon=True).start()
        self.send_json({"message": "Server restarting..."})

    def api_uninstall(self):
        import threading
        def do_uninstall():
            log("UNINSTALL: Starting complete ANK removal...")
            try:
                for name in os.listdir(CONTAINERS_DIR):
                    cdir = os.path.join(CONTAINERS_DIR, name)
                    if os.path.isdir(cdir):
                        config = load_container_config(name)
                        if config and config.get("pid"):
                            try:
                                os.kill(config["pid"], 9)
                            except OSError:
                                pass
                        merged = os.path.join(cdir, "merged")
                        for m in ["proc", "sys", "dev"]:
                            subprocess.run(["umount", os.path.join(merged, m)], capture_output=True, timeout=5)
                        subprocess.run(["umount", merged], capture_output=True, timeout=5)
            except Exception as e:
                log(f"UNINSTALL: cleanup error: {e}")
            try:
                # Only remove ANK-specific iptables rules, not all NAT rules
                result = subprocess.run(["iptables", "-t", "nat", "-S"], capture_output=True, text=True, timeout=5)
                for line in result.stdout.splitlines():
                    if "ank" in line.lower():
                        rule = line.replace("-A", "-D")
                        subprocess.run(["iptables", "-t", "nat"] + rule.split(), capture_output=True, timeout=5)
                subprocess.run(["ip", "link", "set", "ank0", "down"], capture_output=True, timeout=5)
                subprocess.run(["ip", "link", "delete", "ank0"], capture_output=True, timeout=5)
            except Exception:
                pass
            try:
                subprocess.run(["rm", "-rf", ANK_DIR], capture_output=True, timeout=30)
            except Exception:
                pass
            log("UNINSTALL: Removing Magisk module...")
            try:
                subprocess.run(["magisk", "--remove-module", "ank"], capture_output=True, timeout=15)
            except Exception as e:
                log(f"UNINSTALL: magisk --remove-module error: {e}")
            log("UNINSTALL: ANK removed. Reboot to complete.")
            import time; time.sleep(2)
            os._exit(0)
        threading.Thread(target=do_uninstall, daemon=True).start()
        self.send_json({"message": "Uninstalling ANK... Reboot to complete removal."})

    def api_status(self):
        config = load_config()
        total = 0
        running = 0
        stopped = 0
        if os.path.exists(CONTAINERS_DIR):
            for name in os.listdir(CONTAINERS_DIR):
                if os.path.isdir(os.path.join(CONTAINERS_DIR, name)):
                    c = load_container_config(name)
                    if not c:
                        continue
                    total += 1
                    if c.get("status") == "running":
                        running += 1
                    else:
                        stopped += 1

        uptime_sec = 0
        try:
            with open("/proc/uptime", "r") as f:
                uptime_sec = float(f.read().split()[0])
        except Exception:
            pass

        cpu_usage = _cpu_usage_cache

        cpu_cores = 0
        try:
            with open("/proc/cpuinfo", "r") as f:
                cpu_cores = sum(1 for line in f if line.startswith("processor"))
        except Exception:
            try:
                cpu_cores = os.cpu_count() or 0
            except Exception:
                pass

        disk_info = _get_disk_usage()

        self.send_json({
            "version": config.get("version", "0.1"),
            "uptime": uptime_sec,
            "cpu_usage": cpu_usage,
            "cpu_cores": cpu_cores,
            "containers_total": total,
            "containers_running": running,
            "containers_stopped": stopped,
            "disk": disk_info,
            "building": _building
        })

    def api_list_images(self):
        images = []
        if os.path.exists(IMAGES_DIR):
            for name in os.listdir(IMAGES_DIR):
                if name == "ankfs" or name.startswith("alpine-"):
                    continue
                p = os.path.join(IMAGES_DIR, name)
                if os.path.isdir(p):
                    has_python = os.path.isfile(os.path.join(p, "usr/bin/python3"))
                    has_sh = os.path.isfile(os.path.join(p, "bin/sh"))
                    size = 0
                    try:
                        out = subprocess.run(["du", "-sb", p], capture_output=True, text=True, timeout=5)
                        size = int(out.stdout.split("\t")[0]) if out.returncode == 0 else 0
                    except Exception:
                        pass
                    images.append({
                        "name": name,
                        "complete": has_python and has_sh,
                        "has_python": has_python,
                        "size": size,
                        "size_human": self._fmt_size(size)
                    })
        self.send_json(images)

    def api_system_info(self):
        global _device_cache
        mode = get_mode()
        config = load_config()
        net = config.get("network", {})

        if _device_cache is None:
            kernel = "unknown"
            try:
                kernel = os.popen("uname -r 2>/dev/null").read().strip() or "unknown"
            except Exception:
                pass
            device = "unknown"
            try:
                device = os.popen("getprop ro.product.model 2>/dev/null").read().strip() or "unknown"
            except Exception:
                pass
            _device_cache = {"kernel": kernel, "device": device}

        mem_total = 0
        mem_available = 0
        mem_free = 0
        mem_buffers = 0
        mem_cached = 0
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split()
                    if parts[0] == "MemTotal:":
                        mem_total = int(parts[1])
                    elif parts[0] == "MemAvailable:":
                        mem_available = int(parts[1])
                    elif parts[0] == "MemFree:":
                        mem_free = int(parts[1])
                    elif parts[0] == "Buffers:":
                        mem_buffers = int(parts[1])
                    elif parts[0] == "Cached:":
                        mem_cached = int(parts[1])
        except Exception:
            pass

        if mem_available == 0 and mem_total > 0:
            mem_available = mem_free + mem_buffers + mem_cached

        cpu_usage = _cpu_usage_cache

        cpu_cores = 0
        try:
            with open("/proc/cpuinfo", "r") as f:
                cpu_cores = sum(1 for line in f if line.startswith("processor"))
        except Exception:
            try:
                cpu_cores = os.cpu_count() or 0
            except Exception:
                pass

        battery_level = -1
        try:
            with open("/sys/class/power_supply/battery/capacity", "r") as f:
                battery_level = int(f.read().strip())
        except Exception:
            try:
                out = os.popen("dumpsys battery 2>/dev/null | grep level").read().strip()
                for line in out.splitlines():
                    if "level" in line:
                        battery_level = int(line.split(":")[1].strip())
                        break
            except Exception:
                pass

        self.send_json({
            "mode": mode,
            "kernel": _device_cache["kernel"],
            "memory": {"total_kb": mem_total, "available_kb": mem_available},
            "device": _device_cache["device"],
            "cpu_usage": cpu_usage,
            "cpu_cores": cpu_cores,
            "battery": battery_level,
            "version": config.get("version", "0.1"),
            "panel_port": PORT,
            "network": {
                "subnet": net.get("subnet", "10.20.30.0"),
                "gateway": net.get("gateway", "10.20.30.1"),
                "bridge": net.get("bridge", "ank0")
            },
            "device_free": f"{_disk_usage_cache['free']:.1f} GB" if _disk_usage_cache.get("free") else "-"
        })

    def _fmt_size(self, size):
        try:
            if size > 1073741824:
                return f"{size/1073741824:.1f} GB"
            elif size > 1048576:
                return f"{size/1048576:.1f} MB"
            elif size > 1024:
                return f"{size/1024:.0f} KB"
            return f"{size} B"
        except Exception:
            return "-"

    def _du_human(self, path):
        try:
            if not os.path.exists(path):
                return "-"
            out = os.popen(f'du -sb "{path}" 2>/dev/null').read().strip()
            size = int(out.split()[0])
            if size > 1073741824:
                return f"{size/1073741824:.1f} GB"
            elif size > 1048576:
                return f"{size/1048576:.1f} MB"
            elif size > 1024:
                return f"{size/1024:.0f} KB"
            return f"{size} B"
        except Exception:
            return "-"

    def _df_free(self):
        try:
            out = os.popen("df -h /data 2>/dev/null").read().strip().split("\n")[1].split()
            return out[3] if len(out) >= 4 else "-"
        except Exception:
            return "-"

    # ============================================================
    # Stacks API
    # ============================================================

    def _get_stack_manager(self):
        try:
            from stack_manager import StackManager
            return StackManager()
        except Exception:
            return None

    def api_list_stacks(self):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"stacks": [], "error": "stack_manager not available"})
            return
        stacks = sm.list_stacks()
        self.send_json({"stacks": stacks})

    def api_stack_inspect(self, name):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"error": "stack_manager not available"}, 500)
            return
        stack = sm.get_stack(name)
        if not stack:
            self.send_json({"error": f"Stack '{name}' not found"}, 404)
            return
        self.send_json(stack)

    def api_stack_logs(self, name, parsed):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"lines": []})
            return
        lines = sm.get_stack_logs(name, 200)
        self.send_json({"lines": lines})

    def api_stack_metrics(self, name):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"error": "stack_manager not available"}, 500)
            return
        metrics = sm.get_stack_metrics(name)
        self.send_json(metrics)

    def api_create_stack(self, data):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"error": "stack_manager not available"}, 500)
            return
        name = data.get("name", "").strip()
        template = data.get("template", data.get("image", "nginx"))
        ankfile = data.get("ankfile", "")
        if not name:
            self.send_json({"error": "name required"}, 400)
            return
        if not template and not ankfile:
            self.send_json({"error": "template or ankfile required"}, 400)
            return
        try:
            config = {
                "name": name,
                "template": template or "nginx",
                "ankfile": ankfile,
                "min": data.get("min", data.get("instances", 1)),
                "max": data.get("max", 10),
                "port": data.get("lb_port", data.get("port")),
                "trigger": data.get("trigger", "requests"),
                "root_password": data.get("root_password", "ankstack"),
                "load_balance": data.get("load_balance", "least_conn")
            }
            result = sm.create_stack(config)
            self.send_json(result)
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    def api_scale_stack(self, name, data):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"error": "stack_manager not available"}, 500)
            return
        count = data.get("count", 1)
        result = sm.scale_up(name, count)
        if "error" in result:
            self.send_json(result, 400)
        else:
            self.send_json(result)

    def api_scale_down_stack(self, name, data):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"error": "stack_manager not available"}, 500)
            return
        count = data.get("count", 1)
        result = sm.scale_down(name, count)
        if "error" in result:
            self.send_json(result, 400)
        else:
            self.send_json(result)

    def api_delete_stack(self, name):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"error": "stack_manager not available"}, 500)
            return
        result = sm.delete_stack(name)
        if "error" in result:
            self.send_json(result, 400)
        else:
            self.send_json(result)

    def api_update_stack(self, name, data):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"error": "stack_manager not available"}, 500)
            return
        result = sm.update_stack(name, data)
        if "error" in result:
            self.send_json(result, 400)
        else:
            self.send_json(result)

    # ============================================================
    # Backups API
    # ============================================================

    def _get_backup_manager(self):
        try:
            from backup_manager import BackupManager
            return BackupManager()
        except Exception:
            return None

    def api_list_backups(self):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"routines": []})
            return
        routines = bm.list_routines()
        self.send_json({"routines": routines})

    def api_backup_inspect(self, routine_id):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"error": "backup_manager not available"}, 500)
            return
        routine = bm.get_routine(routine_id)
        if not routine:
            self.send_json({"error": "Routine not found"}, 404)
            return
        self.send_json(routine)

    def api_backup_browse(self, routine_id, query):
        from urllib.parse import parse_qs
        params = parse_qs(query)
        remote_path = params.get("path", ["/"])[0]
        try:
            bm = self._get_backup_manager()
            if not bm:
                self.send_json({"error": "backup_manager not available"}, 500)
                return
            files = bm.list_remote_files(routine_id, remote_path)
            self.send_json({"files": files, "path": remote_path})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_create_backup_routine(self, data):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"error": "backup_manager not available"}, 500)
            return
        name = data.get("name", "").strip()
        if not name:
            self.send_json({"error": "name required"}, 400)
            return
        result = bm.create_routine(name, data)
        if "error" in result:
            self.send_json(result, 400)
        else:
            self.send_json(result)

    def api_execute_backup(self, routine_id):
        try:
            bm = self._get_backup_manager()
            if not bm:
                self.send_json({"error": "backup_manager not available"}, 500)
                return
            routine = bm.get_routine(routine_id)
            if not routine:
                self.send_json({"error": "Routine not found"}, 404)
                return
            from backup_runner import BackupRunner
            log_file = os.path.join(ANK_DIR, "logs", f"backup-{routine_id}.log")
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            br = BackupRunner(routine, log_file)
            result = br.run()
            self.send_json(result)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_delete_backup_routine(self, routine_id):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"error": "backup_manager not available"}, 500)
            return
        result = bm.delete_routine(routine_id)
        if "error" in result:
            self.send_json(result, 400)
        else:
            self.send_json(result)

    # ============================================================
    # Nodes API
    # ============================================================

    def _get_node_manager(self):
        try:
            from node_manager import NodeManager
            return NodeManager()
        except Exception:
            return None

    def api_list_nodes(self):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"nodes": []})
            return
        nodes = nm.list_nodes()
        self.send_json({"nodes": nodes})

    def api_node_inspect(self, node_id):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        node = nm.get_node(node_id)
        if not node:
            self.send_json({"error": "Node not found"}, 404)
            return
        self.send_json(node)

    def api_node_containers(self, node_id):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"containers": []})
            return
        try:
            from node_proxy import NodeProxy
            proxy = NodeProxy(nm)
            containers = proxy.get_containers(node_id)
            self.send_json(containers)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_node_stacks(self, node_id):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"stacks": []})
            return
        try:
            from node_proxy import NodeProxy
            proxy = NodeProxy(nm)
            stacks = proxy.get_stacks(node_id)
            self.send_json(stacks)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_add_node(self, data):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        ip = data.get("ip", "").strip()
        if not ip:
            self.send_json({"error": "ip required"}, 400)
            return
        try:
            node = nm.add_node(data)
            self.send_json(node)
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    def api_delete_node(self, node_id):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        result = nm.remove_node(node_id)
        if result:
            self.send_json({"ok": True, "message": f"Node {node_id} removed"})
        else:
            self.send_json({"error": "Node not found"}, 404)

    def api_refresh_node(self, node_id):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        result = nm.get_node(node_id)
        if not result:
            self.send_json({"error": "Node not found"}, 404)
            return
        self.send_json(result)

    # ============================================================
    # System Dashboard (aggregate across nodes)
    # ============================================================

    def api_system_dashboard(self):
        nm = self._get_node_manager()
        sm = self._get_stack_manager()
        dashboard = {
            "total_containers": 0,
            "running_containers": 0,
            "stopped_containers": 0,
            "total_stacks": 0,
            "nodes": []
        }
        try:
            containers = self._list_containers_dict()
            dashboard["total_containers"] = len(containers)
            dashboard["running_containers"] = sum(1 for c in containers if c.get("status") == "running")
            dashboard["stopped_containers"] = sum(1 for c in containers if c.get("status") != "running")
        except Exception:
            pass
        try:
            stacks = sm.list_stacks() if sm else []
            dashboard["total_stacks"] = len(stacks)
        except Exception:
            pass
        try:
            nodes = nm.list_nodes() if nm else []
            for n in nodes:
                dashboard["nodes"].append({
                    "id": n.get("id", ""),
                    "hostname": n.get("hostname", ""),
                    "status": n.get("status", "unknown"),
                    "containers": n.get("containers", 0),
                    "cpu": n.get("cpu", "-"),
                    "ram": n.get("ram", "-"),
                    "disk": n.get("disk", "-"),
                    "uptime": n.get("uptime", "-")
                })
        except Exception:
            pass
        self.send_json(dashboard)

    def _list_containers_dict(self):
        containers_dir = os.path.join(ANK_DIR, "containers")
        result = []
        if not os.path.isdir(containers_dir):
            return result
        for name in os.listdir(containers_dir):
            config_path = os.path.join(containers_dir, name, "config.json")
            if os.path.isfile(config_path):
                try:
                    with open(config_path, "r") as f:
                        cfg = json.load(f)
                    cfg["name"] = name
                    result.append(cfg)
                except Exception:
                    pass
        return result

    # ============================================================
    # Logs API
    # ============================================================

    def api_get_logs(self, parsed):
        params = parse_qs(parsed.query)
        filter_type = params.get("filter", ["all"])[0]
        offset = int(params.get("offset", ["0"])[0])

        logs_dir = os.path.join(ANK_DIR, "logs")
        all_lines = []

        try:
            if filter_type in ("all", "server"):
                for log_name in ("server.log", "service.log"):
                    log_path = os.path.join(logs_dir, log_name)
                    if os.path.exists(log_path):
                        prefix = log_name.replace(".log", "").upper()
                        with open(log_path, "r", errors="replace") as f:
                            for line in f:
                                all_lines.append(f"[{prefix}] " + line.rstrip("\n"))

            if filter_type in ("all", "container"):
                if os.path.isdir(logs_dir):
                    for fname in sorted(os.listdir(logs_dir)):
                        if fname.endswith(".log") and fname not in ("server.log", "service.log", "install.log"):
                            fpath = os.path.join(logs_dir, fname)
                            try:
                                with open(fpath, "r", errors="replace") as f:
                                    for line in f:
                                        prefix = fname.replace(".log", "")
                                        all_lines.append(f"[{prefix}] " + line.rstrip("\n"))
                            except Exception:
                                pass
        except Exception as e:
            all_lines.append(f"[ERROR] Failed to read logs: {e}")

        total = len(all_lines)
        if offset >= total:
            body = json.dumps({"lines": [], "total": total, "new_offset": total})
        else:
            batch = all_lines[offset:offset+500]
            body = json.dumps({"lines": batch, "total": total, "new_offset": offset + len(batch)})

        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
        self.wfile.flush()

    # ============================================================
    # Static files
    # ============================================================

    MIME = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".woff2": "font/woff2",
    }

    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        file_path = os.path.join(STATIC_DIR, path.lstrip("/"))
        if not os.path.exists(file_path):
            file_path = os.path.join(STATIC_DIR, "index.html")
        if not os.path.exists(file_path):
            self.send_error(404, "Not Found")
            return
        ext = os.path.splitext(file_path)[1]
        ct = self.MIME.get(ext, "application/octet-stream")
        with open(file_path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", len(content))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, fmt, *args):
        sys.stdout.write(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}\n")
        sys.stdout.flush()

    def handle_one_request(self):
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                return
            mname = 'do_' + self.command
            if not hasattr(self, mname):
                self.send_error(501, "Not Implemented")
                return
            method = getattr(self, mname)
            method()
            if not getattr(self, '_is_websocket', False):
                self.wfile.flush()
        except TimeoutError:
            self.close_connection = True
        except Exception:
            pass

    def finish(self):
        if getattr(self, '_is_websocket', False):
            return
        try:
            super().finish()
        except Exception:
            pass


def _setup_https():
    """Generate self-signed certificate and setup SSL context"""
    cert_dir = ANK_DIR
    cert_path = os.path.join(cert_dir, "cert.pem")
    key_path = os.path.join(cert_dir, "key.pem")

    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        os.makedirs(cert_dir, exist_ok=True)
        generated = False
        # Try openssl from rootfs first, then system PATH
        _ankfs = os.path.join(ANK_DIR, "ankfs")
        openssl_bin = "openssl"
        for candidate in [os.path.join(_ankfs, "usr", "bin", "openssl"), os.path.join(_ankfs, "usr", "sbin", "openssl"), "openssl"]:
            if os.path.exists(candidate) or candidate == "openssl":
                openssl_bin = candidate
                break
        try:
            subprocess.run([
                openssl_bin, "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", key_path, "-out", cert_path,
                "-days", "365", "-nodes",
                "-subj", "/CN=ank-local/O=ANK"
            ], capture_output=True, timeout=30)
            os.chmod(key_path, 0o600)
            generated = True
        except Exception:
            pass
        # Fallback: generate with Python
        if not generated:
            try:
                from cryptography import x509
                from cryptography.x509.oid import NameOID
                from cryptography.hazmat.primitives import hashes, serialization
                from cryptography.hazmat.primitives.asymmetric import rsa
                import datetime
                key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ank-local")])
                cert = (
                    x509.CertificateBuilder()
                    .subject_name(subject).issuer_name(issuer)
                    .public_key(key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(datetime.datetime.utcnow())
                    .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
                    .sign(key, hashes.SHA256())
                )
                with open(key_path, "wb") as f:
                    f.write(key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.TraditionalOpenSSL,
                        serialization.NoEncryption()
                    ))
                with open(cert_path, "wb") as f:
                    f.write(cert.public_bytes(serialization.Encoding.PEM))
                os.chmod(key_path, 0o600)
                generated = True
            except Exception:
                pass
        if not generated:
            return None

    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        return ctx
    except Exception:
        return None


def main():
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"Ank Container Engine v2.0.0")
    print(f"Starting server on 0.0.0.0:{PORT}...")

    # Ensure server directory is in sys.path for module imports
    _server_dir = os.path.dirname(os.path.abspath(__file__))
    if _server_dir not in sys.path:
        sys.path.insert(0, _server_dir)

    # Start auto-scaling orchestrator
    try:
        from ank_orchestrator import Orchestrator as _Orchestrator
        from stack_manager import StackManager as _StackManager
        _sm = _StackManager()
        _orch = _Orchestrator(_sm)
        _orch.start(interval=10)
        print("Orchestrator started (auto-scaling enabled)")
    except Exception as _oe:
        print(f"Orchestrator not started: {_oe}")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), AnkHandler)

    use_https = False
    ssl_ctx = _setup_https()
    if ssl_ctx:
        try:
            server.socket = ssl_ctx.wrap_socket(server.socket, server_side=True)
            use_https = True
            print(f"HTTPS enabled (self-signed certificate)")
        except Exception as e:
            print(f"WARNING: SSL wrap failed: {e} — falling back to HTTP")

    if not use_https:
        print(f"Running HTTP only on port {PORT}")

    _protocol_file = os.path.join(ANK_DIR, "protocol")
    try:
        with open(_protocol_file, "w") as f:
            f.write("https" if use_https else "http")
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()

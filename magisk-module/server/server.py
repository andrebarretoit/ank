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

try:
    import ank_lite
    HAS_LITE = True
except ImportError:
    HAS_LITE = False

_port_lock = threading.Lock()
_ankd_heal_lock = threading.Lock()
_build_lock = threading.Lock()
_building = False

# ============================================================
# Password hashing (pbkdf2-sha256)
# ============================================================

def _hash_password(password):
    """Hash password with pbkdf2-sha256. Returns hash string for storage."""
    import hashlib as _hl
    salt = secrets.token_bytes(16)
    dk = _hl.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return f"$pbkdf2$100000${salt.hex()}${dk.hex()}"

def _verify_password(password, stored):
    """Verify password against stored hash. Falls back to plaintext comparison for backward compat."""
    if not stored:
        return password == ""
    if stored.startswith("$pbkdf2$"):
        try:
            parts = stored.split("$")
            iterations = int(parts[2])
            salt = bytes.fromhex(parts[3])
            expected = bytes.fromhex(parts[4])
            import hashlib as _hl
            dk = _hl.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
            import hmac as _hmac
            return _hmac.compare_digest(dk, expected)
        except Exception:
            return False
    return password == stored

_pull_status = {}  # version -> {"state": "pulling|building|done|error", "output": [...], "error": ""}

# --- Container status debouncing -------------------------------------------
# check_container_running() is a single best-effort snapshot; any one of its
# signals (cgroup, marker file, pid) can independently glitch for a tick on
# Android (SELinux, overlayfs mount timing, a service respawn) without the
# container actually having died. To satisfy "status never flips to stopped
# while the container is alive", the poller only trusts should_mark_stopped(),
# which requires several *consecutive* failed snapshots (spread over multiple
# 15s poll cycles) and ignores everything during a short grace window right
# after a container reports "running".
_status_lock = threading.Lock()
_status_fail_counts = {}     # name -> consecutive failed-check count
_status_grace_until = {}     # name -> monotonic() time before which checks are skipped
_container_state_locks = {}  # name -> threading.Lock for serializing start/stop/restart
_container_state_locks_lock = threading.Lock()  # protects _container_state_locks dict
STATUS_FAIL_THRESHOLD = 5    # consecutive failures required before flipping to stopped
STATUS_GRACE_SECONDS = 30    # skip checks for this long right after a start
ANKD_HEALTH_FILE_MAX_AGE = 60  # ankd rewrites /tmp/ank-health every ~3s; older = stale

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
ANK_SDCARD = "/sdcard/AndroidKonteiner"
CONTAINERS_DIR = os.path.join(ANK_DIR, "containers")
IMAGES_DIR = os.path.join(ANK_DIR, "images")
SCRIPTS_DIR = os.path.join(ANK_DIR, "core")
CONFIG_FILE = os.path.join(ANK_DIR, "config.json")
STATIC_DIR = os.path.join(ANK_DIR, "ankfs/opt/ank/static")
PORT = 8001

def _load_port_from_config():
    """Read panel_port from config.json if present (migrate/remap writes it)."""
    global PORT
    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
        p = cfg.get("panel_port") or cfg.get("server_port")
        if isinstance(p, int) and 1 <= p <= 65535:
            PORT = p
    except Exception:
        pass
_load_port_from_config()

# --- Shell detection ---------------------------------------------------------
# Rooted/host Android always has /system/bin/sh.  In Lite mode the server runs
# inside a PRoot guest where only the rootfs busybox exists.  Existence check
# means: rooted behavior is unchanged; lite automatically gets /bin/sh.
HOST_SH = next((s for s in ("/system/bin/sh", "/system/xbin/sh", "/bin/sh")
                if os.path.exists(s)), "/bin/sh")

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
    """Get disk usage via os.statvfs (no subprocess, works in chroot)."""
    try:
        st = os.statvfs("/data")
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = total - free
        def fmt_gb(b):
            return round(b / (1024**3), 1)
        return {"total": fmt_gb(total), "used": fmt_gb(used), "free": fmt_gb(free)}
    except Exception:
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

def _check_rate_limit(ip, record=True):
    now = time.time()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < RATE_LIMIT_WINDOW]
    _login_attempts[ip] = attempts
    if len(attempts) >= RATE_LIMIT_MAX:
        return False
    if record:
        attempts.append(now)
        _login_attempts[ip] = attempts
    return True

def _record_failed_login(ip):
    now = time.time()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < RATE_LIMIT_WINDOW]
    attempts.append(now)
    _login_attempts[ip] = attempts

def _create_token(user):
    token = _generate_token()
    expires = time.time() + (TOKEN_EXPIRY_HOURS * 3600)
    with _tokens_lock:
        _tokens[token] = {"user": user, "expires": expires}
    return token

def _validate_token(token):
    """Return 'admin' | 'node' | False."""
    if not token:
        return False
    with _tokens_lock:
        info = _tokens.get(token)
        if info:
            if time.time() > info["expires"]:
                del _tokens[token]
                return False
            return info.get("role", "admin")
    try:
        nodes_dir = os.path.join(ANK_DIR, "nodes")
        if os.path.isdir(nodes_dir):
            for fname in os.listdir(nodes_dir):
                if not fname.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(nodes_dir, fname)) as f:
                        cfg = json.load(f)
                    if cfg.get("token") == token:
                        # Node tokens are NOT admin — only valid for node-scoped proxy
                        return "node"
                except Exception:
                    pass
    except Exception:
        pass
    return False

def _is_admin_token(token):
    return _validate_token(token) == "admin"

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

def _ip_in_range(ip, ip_range):
    if not ip_range or ip_range == "0.0.0.0":
        return True
    if "/" not in ip_range:
        return ip == ip_range
    try:
        import ipaddress
        return ipaddress.ip_address(ip) in ipaddress.ip_network(ip_range, strict=False)
    except Exception:
        return ip == ip_range

def _check_manager_ip(handler):
    config = load_config()
    if not config.get("enable_remote_management"):
        return True
    mgr_ip = config.get("manager_ip", "")
    if not mgr_ip:
        return True
    client_ip = handler.client_address[0]
    if client_ip in ("127.0.0.1", "::1"):
        return True
    return _ip_in_range(client_ip, mgr_ip)

def _check_auth(handler):
    """Check authentication: token-based for API clients, reject browsers"""
    client = _detect_client(handler)
    if client == 'browser':
        return 'browser'
    token = _get_client_token(handler)
    role = _validate_token(token)
    if role == 'admin':
        return 'authorized'
    if role == 'node':
        return 'node'
    return 'unauthorized'

def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"version": "2.0.0", "panel_port": 8001, "username": "ank",
                "password": "ank123", "first_boot": True,
                "ssh_enabled": True, "ssh_port": 2200,
                "default_container_password": "ank123",
                "network": {"bridge": "ank0", "subnet": "10.20.30.0", "gateway": "10.20.30.1", "nat": True}}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    try:
        # Owner-only: config holds password hash/secrets (was 666)
        os.chmod(CONFIG_FILE, 0o600)
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

def _ank_find_service_uuid(container_name, service_name):
    """Find a service's uuid by scanning generated scripts in
    merged/etc/ankd/services/ for '<uuid>-<service_name>.sh'.
    Service definitions live in merged/etc/ankd/services.d/ named
    'NN-<name>.ankd' (numeric order prefix, e.g. 01-sshd.ankd) or
    '<name>.ankd'; the prefix is stripped and the NAME= field is
    compared so this can never resolve a different service's (or a
    stale/legacy) pgid file."""
    merged = os.path.join(CONTAINERS_DIR, container_name, "merged")
    generated_dir = os.path.join(merged, "etc", "ankd", "services")
    services_d = os.path.join(merged, "etc", "ankd", "services.d")
    pids_dir = os.path.join(merged, "etc", "ankd", "pids")
    # Candidate uuids: generated scripts whose filename is
    # '<uuid>-<service_name>.sh' (uuids are hex, service names may
    # contain dashes, so split on the FIRST dash only).
    candidates = []
    try:
        for f in sorted(os.listdir(generated_dir)):
            if f.endswith(f"-{service_name}.sh"):
                candidates.append(f.split("-", 1)[0])
    except OSError:
        pass
    if not candidates:
        return None
    # Is the service still defined in services.d? Match by stripping
    # the numeric order prefix ('01-sshd.ankd' -> 'sshd') or by the
    # NAME= field, so 'sshd' resolves to 01-sshd.ankd.
    defined = False
    try:
        for ank_file in sorted(os.listdir(services_d)):
            if not ank_file.endswith(".ankd"):
                continue
            stem = ank_file[:-len(".ankd")]
            stripped = stem.split("-", 1)[1] if "-" in stem else stem
            if stripped == service_name or stem == service_name:
                defined = True
                break
            try:
                with open(os.path.join(services_d, ank_file)) as af:
                    for line in af:
                        if line.startswith("NAME=") and line.split("=", 1)[1].strip() == service_name:
                            defined = True
                            break
            except OSError:
                continue
            if defined:
                break
    except OSError:
        pass
    if not defined:
        # Definition already deleted (service delete leaves generated
        # scripts behind until the ankd daemon cleans them up) — the
        # suffix match is all we have for a cleanup kill.
        return candidates[0]
    if len(candidates) == 1:
        return candidates[0]
    # Multiple generations of generated scripts for the same name:
    # prefer a uuid whose recorded pgid is alive so a stale script
    # (whose pgid file may hold a recycled pid) never wins.
    for uuid in candidates:
        try:
            with open(os.path.join(pids_dir, f"{uuid}.pgid")) as pf:
                pgid = int(pf.read().strip())
            os.kill(pgid, 0)
            return uuid
        except (OSError, ValueError, ProcessLookupError, PermissionError):
            continue
    return candidates[0]

def _ank_stop_service_pgid(container_name, service_name, mark_stopped=True):
    """Host-side FALLBACK stop for a single service: reads its pgid from
    the registry ankd keeps at merged/etc/ankd/pids/<uuid>.pgid and
    killpgs it. Guarded, because the old blind killpg took whole
    containers down:
      * writes a stop-flag (merged/etc/ankd/stopped/<name>) so the ankd
        daemon's RESTART_POLICY=always loop doesn't resurrect the
        service, unless mark_stopped=False (restart fallback relies on
        the daemon restarting it);
      * refuses to kill unless the recorded pgid is alive AND its
        /proc/<pid>/root resolves inside this container's merged
        rootfs — a recycled pid or a PID-namespace-local pgid
        (isolated/shared_network containers record namespaced pids,
        which mean something entirely different on the host) is never
        signalled. The primary stop path is the in-container signal
        mode (ankd.sh ankd.servicestart/servicestop)."""
    merged = os.path.join(CONTAINERS_DIR, container_name, "merged")
    if mark_stopped:
        try:
            stopped_dir = os.path.join(merged, "etc", "ankd", "stopped")
            os.makedirs(stopped_dir, exist_ok=True)
            with open(os.path.join(stopped_dir, service_name), "w") as f:
                f.write("manual-stop\n")
        except OSError:
            pass
    uuid = _ank_find_service_uuid(container_name, service_name)
    if not uuid:
        return False
    pgid_file = os.path.join(merged, "etc", "ankd", "pids", f"{uuid}.pgid")
    try:
        with open(pgid_file) as f:
            pgid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    # Guard 1: the recorded pgid must be alive at all.
    alive = False
    try:
        os.kill(pgid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    except PermissionError:
        alive = True  # exists but not probed by us; try the kill anyway
    except OSError:
        alive = False  # e.g. EINVAL/EPERM oddities — refuse to guess
    if not alive:
        # dead entry — clean the registry so future lookups don't reuse it
        try:
            os.remove(pgid_file)
        except OSError:
            pass
        return False
    # Guard 2: a live pid must be a process of THIS container (services
    # run chrooted into merged/). Anything else means the pid was
    # recycled or is a namespaced pid misread from the host — killpg
    # on it could hit the container init group and take the whole
    # container down. The in-container signal path handles those cases.
    try:
        proc_root = os.path.realpath(f"/proc/{pgid}/root")
    except OSError:
        proc_root = None
    if proc_root:
        merged_real = os.path.realpath(merged)
        if proc_root != merged_real and not proc_root.startswith(merged_real + os.sep):
            return False  # refused — not provably ours
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        pass
    try:
        os.kill(pgid, signal.SIGKILL)  # belt-and-suspenders on the leader itself
    except (ProcessLookupError, PermissionError):
        pass
    try:
        os.remove(pgid_file)
    except OSError:
        pass
    return True

def run_script(script, *args, timeout=60):
    script_path = os.path.join(SCRIPTS_DIR, script)
    cmd_parts = [HOST_SH, script_path] + list(args)
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

def run_script_stream(script, *args, output_list=None, timeout=300):
    """Run a script line-by-line, appending each line to output_list. Returns return code."""
    script_path = os.path.join(SCRIPTS_DIR, script)
    cmd_parts = [HOST_SH, script_path] + list(args)
    cmd_str = " ".join(f"'{a}'" for a in cmd_parts)
    try:
        if os.geteuid() != 0:
            proc = subprocess.Popen(
                ["su", "-c", cmd_str],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True
            )
        else:
            proc = subprocess.Popen(
                cmd_parts,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True
            )
        for line in iter(proc.stdout.readline, ""):
            if output_list is not None:
                output_list.append(line.rstrip("\n"))
        proc.wait(timeout=timeout)
        return proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        if output_list is not None:
            output_list.append("ERROR: Script timed out")
        return 1
    except Exception as e:
        if output_list is not None:
            output_list.append(f"ERROR: {e}")
        return 1

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

def _pid_alive(name):
    """Check if the container's main process is still alive via PID file."""
    config = load_container_config(name)
    if not config:
        return None
    pid = config.get("pid")
    if not pid:
        return None
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except (ValueError, TypeError):
        return None


def _health_file_status(name):
    """Health file written by ankd (UP/DOWN) every ~3s. Runs inside container.
    A file older than ANKD_HEALTH_FILE_MAX_AGE is stale (daemon stopped
    writing) and is treated as unknown, not as proof of life."""
    health_path = os.path.join(CONTAINERS_DIR, name, "merged", "tmp", "ank-health")
    try:
        if time.time() - os.path.getmtime(health_path) > ANKD_HEALTH_FILE_MAX_AGE:
            return None
        with open(health_path, "r") as f:
            status = f.read().strip()
        return status == "UP"
    except (OSError, IOError):
        return None


def _sshd_port_open(name):
    """TCP check: can we connect to the container's SSH port?"""
    config = load_container_config(name)
    if not config:
        return None
    port = config.get("ssh_port")
    if not port:
        return None
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex(("127.0.0.1", int(port)))
        s.close()
        return result == 0
    except (OSError, ValueError):
        return None


def _ankd_port_open(name):
    """TCP check: can we connect to the container's ankd health port?"""
    config = load_container_config(name)
    if not config:
        return None
    port = config.get("ankd_port")
    if not port:
        return None
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex(("127.0.0.1", int(port)))
        s.close()
        return result == 0
    except (OSError, ValueError):
        return None


def check_container_running(name):
    """Check if a container is alive using TCP ports ONLY.
    SSH port open OR ankd port open = running.
    No PID checks, no health files — purely network-based."""
    ssh = _sshd_port_open(name)
    if ssh:
        return True
    ankd = _ankd_port_open(name)
    if ankd:
        return True
    # Both ports closed = stopped
    if ssh is False and ankd is False:
        return False
    # Both ports unknown (no config) = stopped
    if ssh is None and ankd is None:
        return False
    # One unknown, one closed = stopped
    if (ssh is False and ankd is None) or (ssh is None and ankd is False):
        return False
    return True


def should_mark_stopped(name):
    """Debounced decision used by anything that's about to persist a
    "running" -> "stopped" transition. Requires STATUS_FAIL_THRESHOLD
    consecutive failed check_container_running() snapshots, and never fires
    during the STATUS_GRACE_SECONDS window right after a container was last
    (re)started, so a single transient signal glitch can never flip status.
    """
    now = time.monotonic()
    with _status_lock:
        if now < _status_grace_until.get(name, 0):
            return False
        if check_container_running(name):
            _status_fail_counts[name] = 0
            return False
        count = _status_fail_counts.get(name, 0) + 1
        _status_fail_counts[name] = count
        return count >= STATUS_FAIL_THRESHOLD


def _get_container_lock(name):
    """Get or create a per-container threading lock to serialize state transitions."""
    with _container_state_locks_lock:
        if name not in _container_state_locks:
            _container_state_locks[name] = threading.Lock()
        return _container_state_locks[name]


def note_container_started(name):
    """Reset debounce state and open a grace window. Call whenever a
    container's status is set to "running"."""
    with _status_lock:
        _status_fail_counts[name] = 0
        _status_grace_until[name] = time.monotonic() + STATUS_GRACE_SECONDS


def note_container_stopped(name):
    """Clear debounce state. Call whenever a container's status is set to
    anything other than "running" (stopped, stopping, failed, building)."""
    with _status_lock:
        _status_fail_counts.pop(name, None)
        _status_grace_until.pop(name, None)

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

def is_lite():
    return HAS_LITE and get_mode().get("mode") == "lite"

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
<title>%s</title>
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

ANK_NGINX_HTML = ANK_PAGE_HTML % ('ANK - Nginx', '#3b82f6', '#06b6d4', '#3b82f6', 'Nginx Running', 'Upload your HTML content via the<br>ANK Web Panel file explorer.', ANK_BRANDING)
ANK_APACHE_HTML = ANK_PAGE_HTML % ('ANK - Apache', '#d22128', '#f59e0b', '#d22128', 'Apache Running', 'Upload your HTML content via the<br>ANK Web Panel file explorer.', ANK_BRANDING)
ANK_PHP_HTML = ANK_PAGE_HTML % ('ANK - PHP', '#777BB4', '#a855f7', '#777BB4', 'PHP Running', 'Edit index.php via the<br>ANK Web Panel file explorer.', ANK_BRANDING)
ANK_NODE_HTML = ANK_PAGE_HTML % ('ANK - Node.js', '#339933', '#22c55e', '#339933', 'Node.js Running', 'Edit server.js via the<br>ANK Web Panel file explorer.', ANK_BRANDING)
ANK_PYTHON_HTML = ANK_PAGE_HTML % ('ANK - Python', '#3776AB', '#ffd43b', '#3776AB', 'Python Running', 'Edit server.py via the<br>ANK Web Panel file explorer.', ANK_BRANDING)

ANK_NGINX_CONF = r"""daemon off;
events { worker_connections 1024; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    server {
        listen {port};
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

ANK_NODE_SERVER = r"""const http = require('http');
const srv = http.createServer((req, res) => {
    res.writeHead(200, {'Content-Type': 'text/html'});
    res.end('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ANK - Node.js</title><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center}.card{background:#1e293b;border-radius:16px;padding:48px;max-width:480px;width:90%;text-align:center;box-shadow:0 25px 50px rgba(0,0,0,.4)}.logo{font-size:48px;font-weight:800;background:linear-gradient(135deg,#339933,#22c55e);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}.sub{color:#94a3b8;font-size:14px;margin-bottom:24px}.badge{display:inline-block;background:rgba(34,197,94,.15);color:#22c55e;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}.footer{margin-top:32px;color:#475569;font-size:12px}.footer a{color:#339933;text-decoration:none}</style></head><body><div class="card"><div class="logo">ANK</div><div class="sub">Android Konteiner</div><div class="badge">Node.js ' + process.version + ' Running</div><p style="margin-top:24px;color:#94a3b8">Edit server.js via the<br>ANK Web Panel file explorer.</p><div class="footer">by <a href="https://github.com/andrebarretoit">andrebarretoit</a></div></div></body></html>');
});
const PORT = process.env.ANK_PORT || {port};
srv.listen(PORT, () => console.log('ANK Node.js listening on :' + PORT));"""

ANK_PYTHON_SERVER = r"""from http.server import HTTPServer, BaseHTTPRequestHandler
import os

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        html = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ANK - Python</title><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center}.card{background:#1e293b;border-radius:16px;padding:48px;max-width:480px;width:90%;text-align:center;box-shadow:0 25px 50px rgba(0,0,0,.4)}.logo{font-size:48px;font-weight:800;background:linear-gradient(135deg,#3776AB,#ffd43b);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}.sub{color:#94a3b8;font-size:14px;margin-bottom:24px}.badge{display:inline-block;background:rgba(34,197,94,.15);color:#22c55e;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}.footer{margin-top:32px;color:#475569;font-size:12px}.footer a{color:#3776AB;text-decoration:none}</style></head><body><div class="card"><div class="logo">ANK</div><div class="sub">Android Konteiner</div><div class="badge">Python ''' + '.'.join(map(str, __import__('sys').version_info[:3])) + ' Running</div><p style="margin-top:24px;color:#94a3b8">Edit server.py via the<br>ANK Web Panel file explorer.</p><div class="footer">by <a href="https://github.com/andrebarretoit">andrebarretoit</a></div></div></body></html>'''
        self.wfile.write(html.encode())

    def log_message(self, fmt, *args):
        pass

HTTPServer(('0.0.0.0', int(os.environ.get('ANK_PORT', '{port}'))), Handler).serve_forever()"""

def _write_portfwd(merged, container_port, protocol="tcp"):
    """Write portfwd.conf into merged dir for the container."""
    ank_dir = os.path.join(merged, "etc/ank")
    os.makedirs(ank_dir, exist_ok=True)
    with open(os.path.join(ank_dir, "portfwd.conf"), "w") as f:
        f.write(f"{container_port} {protocol}\n")

def _write_ank_config(merged, service, port, static_path=""):
    """Write unified /etc/ank/config into merged dir."""
    ank_dir = os.path.join(merged, "etc/ank")
    os.makedirs(ank_dir, exist_ok=True)
    with open(os.path.join(ank_dir, "config"), "w") as f:
        f.write(f"service={service}\n")
        f.write(f"port={port}\n")
        f.write(f"static_path={static_path}\n")

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

def _ws_node_shell_relay(handler, node_id, cols=80, rows=24):
    """Relay a browser WebSocket shell session through to a remote node's own
    /ws/shell endpoint, so the Shell tab's node selector can actually attach to a
    remote node instead of just showing a toast (previously a stub)."""
    client_sock = handler.request
    nm = handler._get_node_manager()
    conn = nm.get_node_connection(node_id) if nm else None
    if not conn or not conn.get("ip"):
        _ws_send_text(client_sock, f"\r\nERROR: Node '{node_id}' not found\r\n")
        _ws_send_close(client_sock)
        return
    if conn.get("status") != "online":
        _ws_send_text(client_sock, f"\r\nERROR: Node '{node_id}' is offline\r\n")
        _ws_send_close(client_sock)
        return

    import socket as _socket

    remote_sock = None
    try:
        ip = conn["ip"]
        port = int(conn.get("port", 8001))
        token = conn.get("token", "")

        remote_sock = _socket.create_connection((ip, port), timeout=10)
        ws_key = base64.b64encode(secrets.token_bytes(16)).decode()
        path = f"/ws/shell?cols={cols}&rows={rows}&token={token}"
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {ip}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {ws_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        remote_sock.sendall(handshake.encode("utf-8"))

        # Read the HTTP response headers up to the blank line.
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = remote_sock.recv(4096)
            if not chunk:
                raise ConnectionError("Remote node closed connection during handshake")
            buf += chunk
        header_part, _, leftover = buf.partition(b"\r\n\r\n")
        status_line = header_part.split(b"\r\n", 1)[0].decode("utf-8", "replace")
        if " 101 " not in status_line:
            raise ConnectionError(f"Remote node rejected WebSocket upgrade: {status_line}")

        running = [True]

        # Any bytes already read past the header belong to the first frame(s).
        pending = bytearray(leftover)

        def _remote_recv_exact(n):
            while len(pending) < n:
                chunk = remote_sock.recv(max(4096, n - len(pending)))
                if not chunk:
                    return None
                pending.extend(chunk)
            data = bytes(pending[:n])
            del pending[:n]
            return data

        def _read_remote_frame():
            head = _remote_recv_exact(2)
            if not head:
                return None, None
            b0, b1 = struct.unpack("!BB", head)
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            length = b1 & 0x7F
            if length == 126:
                ext = _remote_recv_exact(2)
                if not ext:
                    return None, None
                length = struct.unpack("!H", ext)[0]
            elif length == 127:
                ext = _remote_recv_exact(8)
                if not ext:
                    return None, None
                length = struct.unpack("!Q", ext)[0]
            mask_key = _remote_recv_exact(4) if masked else None
            payload = _remote_recv_exact(length) if length else b""
            if payload is None:
                return None, None
            if mask_key:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            return opcode, payload

        def relay_remote_to_client():
            while running[0]:
                try:
                    opcode, payload = _read_remote_frame()
                except Exception:
                    break
                if opcode is None:
                    break
                if opcode == 0x8:
                    break
                if opcode in (0x1, 0x2):
                    try:
                        _ws_send_frame(client_sock, opcode, payload)
                    except Exception:
                        break
            running[0] = False

        t = threading.Thread(target=relay_remote_to_client, daemon=True)
        t.start()

        # Client -> remote: forward whatever the browser sends (resize/input JSON messages).
        while running[0]:
            opcode, payload = _ws_read_frame_rsock(client_sock)
            if opcode is None:
                break
            if opcode == 0x8:
                break
            if opcode in (0x1, 0x2):
                try:
                    _ws_send_frame(remote_sock, opcode, payload)
                except Exception:
                    break
        running[0] = False
    except Exception as e:
        try:
            _ws_send_text(client_sock, f"\r\nERROR: {str(e)}\r\n")
        except Exception:
            pass
    finally:
        if remote_sock:
            try:
                remote_sock.close()
            except Exception:
                pass
        try:
            _ws_send_close(client_sock)
        except Exception:
            pass

def _ws_node_container_terminal_relay(handler, node_id, container_name, cols=80, rows=24):
    """Relay a browser WebSocket terminal session to a remote node's container terminal."""
    client_sock = handler.request
    nm = handler._get_node_manager()
    conn = nm.get_node_connection(node_id) if nm else None
    if not conn or not conn.get("ip"):
        _ws_send_text(client_sock, f"\r\nERROR: Node '{node_id}' not found\r\n")
        _ws_send_close(client_sock)
        return
    if conn.get("status") != "online":
        _ws_send_text(client_sock, f"\r\nERROR: Node '{node_id}' is offline\r\n")
        _ws_send_close(client_sock)
        return

    import socket as _socket

    remote_sock = None
    try:
        ip = conn["ip"]
        port = int(conn.get("port", 8001))
        token = conn.get("token", "")

        remote_sock = _socket.create_connection((ip, port), timeout=10)
        ws_key = base64.b64encode(secrets.token_bytes(16)).decode()
        path = f"/ws/terminal/{container_name}?cols={cols}&rows={rows}&token={token}"
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {ip}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {ws_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        remote_sock.sendall(handshake.encode("utf-8"))

        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = remote_sock.recv(4096)
            if not chunk:
                raise ConnectionError("Remote node closed connection during handshake")
            buf += chunk
        header_part, _, leftover = buf.partition(b"\r\n\r\n")
        status_line = header_part.split(b"\r\n", 1)[0].decode("utf-8", "replace")
        if " 101 " not in status_line:
            raise ConnectionError(f"Remote node rejected WebSocket upgrade: {status_line}")

        running = [True]
        pending = bytearray(leftover)

        def _remote_recv_exact(n):
            while len(pending) < n:
                chunk = remote_sock.recv(max(4096, n - len(pending)))
                if not chunk:
                    return None
                pending.extend(chunk)
            data = bytes(pending[:n])
            del pending[:n]
            return data

        def _read_remote_frame():
            head = _remote_recv_exact(2)
            if not head:
                return None, None
            b0, b1 = struct.unpack("!BB", head)
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            length = b1 & 0x7F
            if length == 126:
                ext = _remote_recv_exact(2)
                if not ext:
                    return None, None
                length = struct.unpack("!H", ext)[0]
            elif length == 127:
                ext = _remote_recv_exact(8)
                if not ext:
                    return None, None
                length = struct.unpack("!Q", ext)[0]
            mask_key = _remote_recv_exact(4) if masked else None
            payload = _remote_recv_exact(length) if length else b""
            if payload is None:
                return None, None
            if mask_key:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            return opcode, payload

        def relay_remote_to_client():
            while running[0]:
                try:
                    opcode, payload = _read_remote_frame()
                except Exception:
                    break
                if opcode is None:
                    break
                if opcode == 0x8:
                    break
                if opcode in (0x1, 0x2):
                    try:
                        _ws_send_frame(client_sock, opcode, payload)
                    except Exception:
                        break
            running[0] = False

        t = threading.Thread(target=relay_remote_to_client, daemon=True)
        t.start()

        while running[0]:
            opcode, payload = _ws_read_frame_rsock(client_sock)
            if opcode is None:
                break
            if opcode == 0x8:
                break
            if opcode in (0x1, 0x2):
                try:
                    _ws_send_frame(remote_sock, opcode, payload)
                except Exception:
                    break
        running[0] = False
    except Exception as e:
        try:
            _ws_send_text(client_sock, f"\r\nERROR: {str(e)}\r\n")
        except Exception:
            pass
    finally:
        if remote_sock:
            try:
                remote_sock.close()
            except Exception:
                pass
        try:
            _ws_send_close(client_sock)
        except Exception:
            pass

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
                os.execv(HOST_SH, [HOST_SH])
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

    def _find_free_port(self, start=2201):
        """Find a free port starting from 'start', checking configs AND actual TCP ports. Thread-safe."""
        with _port_lock:
            used = set()
            for cfg_file in glob.glob(os.path.join(CONTAINERS_DIR, "*/config.json")):
                try:
                    with open(cfg_file) as f:
                        cfg = json.load(f)
                        p = cfg.get("ssh_port")
                        if p:
                            used.add(int(p))
                        p2 = cfg.get("ankd_port")
                        if p2:
                            used.add(int(p2))
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

    def _find_free_ankd_port(self):
        """Find a free ankd health-check port starting from 50000. Thread-safe."""
        return self._find_free_port(50000)

    def _find_base_image(self):
        """Find best available ank-alpinebase image. Prefers 3.20 > highest version."""
        preferred = "ank-alpinebase-3.20"
        if os.path.isdir(os.path.join(IMAGES_DIR, preferred)) and os.path.lexists(os.path.join(IMAGES_DIR, preferred, "bin/sh")):
            return preferred
        candidates = []
        if os.path.exists(IMAGES_DIR):
            for name in os.listdir(IMAGES_DIR):
                if name.startswith("ank-alpinebase-") and os.path.lexists(os.path.join(IMAGES_DIR, name, "bin/sh")):
                    try:
                        ver = name.split("ank-alpinebase-")[1]
                        candidates.append((ver, name))
                    except Exception:
                        pass
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]
        return preferred

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
        origin = self.headers.get("Origin", "")
        host = self.headers.get("Host", "")
        # Only reflect same-origin (or host-matching) origins — never arbitrary sites
        same_origin = False
        if origin and host:
            try:
                from urllib.parse import urlparse as _uop
                o = _uop(origin)
                same_origin = (o.netloc == host)
            except Exception:
                same_origin = False
        if same_origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
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
            # Auth: host shell requires admin token (not node token)
            qs = parse_qs(parsed.query)
            ws_token = qs.get("token", [None])[0]
            if _validate_token(ws_token) != "admin":
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

        # WebSocket node-shell relay
        if path.startswith("/ws/node-shell/"):
            self._is_websocket = True
            upgrade = self.headers.get("Upgrade", "").lower()
            ws_key = self.headers.get("Sec-WebSocket-Key", "")
            if upgrade != "websocket" or not ws_key:
                self._ws_send_error(400, "Invalid WebSocket upgrade request")
                return
            qs = parse_qs(parsed.query)
            ws_token = qs.get("token", [None])[0]
            if _validate_token(ws_token) != "admin":
                log(f"WS_NODE_SHELL: auth failed from {self.client_address[0]}")
                self._ws_send_error(401, "Unauthorized")
                return
            node_id = path.split("/")[3]
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
            cols = 80
            rows = 24
            try:
                cols = int(qs.get("cols", [80])[0])
                rows = int(qs.get("rows", [24])[0])
            except Exception:
                pass
            _ws_node_shell_relay(self, node_id, cols, rows)
            return

        # WebSocket relay for remote container terminal
        if path.startswith("/ws/node-terminal/"):
            self._is_websocket = True
            upgrade = self.headers.get("Upgrade", "").lower()
            ws_key = self.headers.get("Sec-WebSocket-Key", "")
            if upgrade != "websocket" or not ws_key:
                self._ws_send_error(400, "Invalid WebSocket upgrade request")
                return
            qs = parse_qs(parsed.query)
            ws_token = qs.get("token", [None])[0]
            if _validate_token(ws_token) != "admin":
                log(f"WS_NODE_TERMINAL: auth failed from {self.client_address[0]}")
                self._ws_send_error(401, "Unauthorized")
                return
            parts = path.split("/")
            node_id = parts[3]
            container_name = parts[4] if len(parts) > 4 else ""
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
            cols = 80
            rows = 24
            try:
                cols = int(qs.get("cols", [80])[0])
                rows = int(qs.get("rows", [24])[0])
            except Exception:
                pass
            _ws_node_container_terminal_relay(self, node_id, container_name, cols, rows)
            return

        # WebSocket upgrade for terminal
        if path.startswith("/ws/terminal/"):
            self._is_websocket = True
            upgrade = self.headers.get("Upgrade", "").lower()
            ws_key = self.headers.get("Sec-WebSocket-Key", "")
            if upgrade != "websocket" or not ws_key:
                self._ws_send_error(400, "Invalid WebSocket upgrade request")
                return
            # Auth: host terminal requires admin token (not node token)
            qs = parse_qs(parsed.query)
            ws_token = qs.get("token", [None])[0]
            if _validate_token(ws_token) != "admin":
                log(f"WS_TERMINAL: auth failed from {self.client_address[0]} token={ws_token[:8] if ws_token else 'None'}...")
                self._ws_send_error(401, "Unauthorized")
                return
            container_name = path.split("/")[3]
            # Verify container is actually running
            config = load_container_config(container_name)
            if not config:
                self._ws_send_error(404, f"Container '{container_name}' not found")
                return
            # Don't flip status on-demand here — the background poller handles that
            if config.get("status") not in ("running", "starting"):
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
            # Readiness/health probes used by the restart modal — must work
            # without a token (tokens are in-memory and die with the process).
            if path in ("/api/status", "/api/system/status", "/api/health"):
                try:
                    self.route_get(path, parsed)
                except Exception as e:
                    try:
                        self.send_json({"error": str(e)}, 500)
                    except Exception:
                        self.send_error(500, str(e))
                return
            auth = _check_auth(self)
            if auth == 'browser':
                self.send_404_html()
                return
            if auth != 'authorized':
                self.send_error(401, "Unauthorized")
                return
            if not _check_manager_ip(self):
                self.send_error(403, "Forbidden: IP not allowed")
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
            if path != "/api/auth/login" and path != "/api/nodes/pairing/request":
                auth = _check_auth(self)
                if auth == 'browser':
                    self.send_404_html()
                    return
                if auth != 'authorized':
                    self.send_error(401, "Unauthorized")
                    return
                if not _check_manager_ip(self):
                    self.send_error(403, "Forbidden: IP not allowed")
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
            if not _check_manager_ip(self):
                self.send_error(403, "Forbidden: IP not allowed")
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
            if not _check_manager_ip(self):
                self.send_error(403, "Forbidden: IP not allowed")
                return
            try:
                self.route_delete(path, parsed)
            except Exception as e:
                try:
                    self.send_json({"error": str(e)}, 500)
                except Exception:
                    self.send_error(500, str(e))
            return
        self.send_404_html()

    # ============================================================
    # Routing
    # ============================================================

    def route_get(self, path, parsed):
        if path == "/api/status":
            self.api_status()
        elif path == "/api/system/status":
            self.api_status()
        elif path == "/api/mode":
            self.api_get_mode()
        elif path == "/api/health":
            self.send_json({"status": "ok"})
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
        elif path == "/api/containers/all":
            self.api_all_containers()
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
        elif path.startswith("/api/containers/") and "/services/" in path and path.endswith("/logs"):
            parts = path.split("/")
            qs = parse_qs(parsed.query)
            lines = int(qs.get("lines", ["50"])[0])
            self.api_svc_logs(parts[3], parts[5], lines)
        elif path.endswith("/services") and path.startswith("/api/containers/"):
            name = path.split("/")[3]
            self.api_list_services(name)
        elif path.endswith("/health") and path.startswith("/api/containers/"):
            self.api_container_health(path.split("/")[3])
        elif path.startswith("/api/containers/") and path.endswith("/logs"):
            self.api_container_logs(path.split("/")[3])
        elif path.startswith("/api/containers/"):
            self.api_container_inspect(path.split("/")[3])
        elif path == "/api/images":
            self.api_list_images()
        elif path == "/api/images/all":
            self.api_all_images()
        elif path == "/api/images/templates":
            self.api_image_templates()
        elif path == "/api/images/pull/status":
            qs = parsed.query
            version = "3.20"
            if qs:
                for part in qs.split("&"):
                    if part.startswith("version="):
                        version = part.split("=", 1)[1]
            self.api_pull_image_status({"version": version})
        elif path == "/api/images/alpine-versions":
            self.api_alpine_versions()
        elif path == "/api/system/info":
            self.api_system_info()
        elif path == "/api/system/cache":
            self.api_system_cache()
        elif path == "/api/networks":
            self.api_list_networks()
        elif path == "/api/networks/info":
            self.api_network_info()
        elif path == "/api/logs":
            self.api_get_logs(parsed)
        elif path == "/api/ank-manager/status":
            self.api_ank_manager_status()
        elif path == "/api/ank-manager/logs":
            self.api_ank_manager_logs(parsed)
        elif path == "/api/config":
            self.api_get_config()
        elif path == "/api/stacks":
            self.api_list_stacks()
        elif path == "/api/stacks/all":
            self.api_all_stacks()
        elif path.startswith("/api/stacks/") and path.endswith("/logs"):
            self.api_stack_logs(path.split("/")[3], parsed)
        elif path.startswith("/api/stacks/") and path.endswith("/metrics"):
            self.api_stack_metrics(path.split("/")[3])
        elif path.startswith("/api/stacks/"):
            self.api_stack_inspect(path.split("/")[3])
        elif path == "/api/backups":
            self.api_list_backups()
        elif path == "/api/backups/history":
            qs = parse_qs(parsed.query)
            rid = qs.get("routine_id", [None])[0]
            limit = int(qs.get("limit", ["50"])[0])
            self.api_backup_history(rid, limit)
        elif path == "/api/backups/battery":
            self.api_backup_battery()
        elif path.startswith("/api/backups/") and "/browse" in path:
            qs = parsed.query
            self.api_backup_browse(path.split("/")[3], qs)
        elif path.startswith("/api/backups/") and "/preview" in path:
            data = self.read_body()
            self.api_backup_preview(path.split("/")[3], data)
        elif path.startswith("/api/backups/") and "/log" in path:
            self.api_backup_log(path.split("/")[3])
        elif path.startswith("/api/backups/"):
            self.api_backup_inspect(path.split("/")[3])
        elif path == "/api/nodes":
            self.api_list_nodes()
        elif path == "/api/nodes/manager":
            self.api_get_manager()
        elif path == "/api/nodes/pairing":
            self.api_list_pairing_requests()
        elif path.startswith("/api/nodes/") and path.endswith("/containers"):
            self.api_node_containers(path.split("/")[3])
        elif path.startswith("/api/nodes/") and path.endswith("/stacks"):
            self.api_node_stacks(path.split("/")[3])
        elif path.startswith("/api/nodes/") and path.endswith("/images"):
            self.api_node_images(path.split("/")[3])
        elif path.startswith("/api/nodes/") and path.endswith("/status"):
            self.api_node_status(path.split("/")[3])
        elif path.startswith("/api/nodes/") and path.endswith("/system/info"):
            self.api_node_system_info(path.split("/")[3])
        elif path.startswith("/api/nodes/") and "/containers/" in path and path.endswith("/logs"):
            parts = path.split("/")
            self.api_node_container_logs(parts[3], parts[5])
        elif path.startswith("/api/nodes/") and "/containers/" in path and path.endswith("/services"):
            parts = path.split("/")
            self.api_node_container_services(parts[3], parts[5])
        elif path.startswith("/api/nodes/") and "/containers/" in path and path.endswith("/health"):
            parts = path.split("/")
            self.api_node_container_health(parts[3], parts[5])
        elif path.startswith("/api/nodes/") and path.endswith("/logs"):
            self.api_node_logs(path.split("/")[3])
        elif path.startswith("/api/nodes/") and "/containers/" in path:
            parts = path.split("/")
            if len(parts) >= 6 and parts[5]:
                self.api_node_container_detail(parts[3], parts[5])
            else:
                self.api_node_containers(parts[3])
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
        elif "/services" in path and path.startswith("/api/containers/"):
            parts = path.split("/")
            name = parts[3]
            if path.endswith("/services"):
                self.api_add_service(name, data)
            elif "/services/" in path and path.endswith("/start"):
                self.api_service_action(name, parts[5], "start")
            elif "/services/" in path and path.endswith("/stop"):
                self.api_service_action(name, parts[5], "stop")
            elif "/services/" in path and path.endswith("/restart"):
                self.api_service_action(name, parts[5], "restart")
            elif "/services/" in path and path.endswith("/enable"):
                self.api_service_action(name, parts[5], "enable")
            elif "/services/" in path and path.endswith("/disable"):
                self.api_service_action(name, parts[5], "disable")
            elif "/services/" in path and path.endswith("/tail"):
                self.api_service_tail(name, parts[5], data)
            else:
                self.send_error(404, "Not Found")
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
        elif path == "/api/images/upload":
            self.api_receive_image_upload()
        elif path == "/api/images/pull":
            self.api_pull_image(data)
        elif path == "/api/images/templates":
            self.api_image_templates()
        elif path == "/api/images/deploy":
            self.api_deploy_template(data)
        elif path == "/api/images/ankfile":
            self.api_build_ankfile(data)
        elif path.startswith("/api/images/") and path.endswith("/delete"):
            self.api_delete_image(path.split("/")[3])
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
        elif path == "/api/ank-manager/stop":
            self.api_ank_manager_stop()
        elif path == "/api/ank-manager/restart-server":
            self.api_ank_manager_restart_server()
        elif path == "/api/ank-manager/restart-device":
            self.api_ank_manager_restart_device()
        elif path == "/api/ank-manager/uninstall":
            self.api_ank_manager_uninstall()
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
        elif path.startswith("/api/stacks/") and path.endswith("/rolling-update"):
            self.api_rolling_update(path.split("/")[3], data)
        elif path.startswith("/api/stacks/") and path.endswith("/healing"):
            self.api_start_healing(path.split("/")[3])
        elif path == "/api/backups/test-connection":
            self.api_backup_test_connection(data)
        elif path == "/api/backups":
            self.api_create_backup_routine(data)
        elif path.startswith("/api/backups/") and path.endswith("/execute"):
            self.api_execute_backup(path.split("/")[3])
        elif path.startswith("/api/backups/") and path.endswith("/restore"):
            self.api_backup_restore(path.split("/")[3], data)
        elif path.startswith("/api/backups/") and path.endswith("/preview"):
            self.api_backup_preview(path.split("/")[3], data)
        elif path.startswith("/api/backups/") and path.endswith("/rename"):
            self.api_backup_rename(path.split("/")[3], data)
        elif path.startswith("/api/backups/") and path.endswith("/delete"):
            self.api_backup_delete_file(path.split("/")[3], data)
        elif path.startswith("/api/backups/") and path.endswith("/update"):
            self.api_update_backup_routine(path.split("/")[3], data)
        elif path == "/api/nodes":
            self.api_add_node(data)
        elif path == "/api/nodes/pairing/send":
            self.api_send_pairing_request(data)
        elif path == "/api/nodes/pairing/request":
            self.api_receive_pairing_request(data)
        elif path.startswith("/api/nodes/pairing/") and path.endswith("/approve"):
            self.api_approve_pairing(path.split("/")[4])
        elif path.startswith("/api/nodes/pairing/") and path.endswith("/reject"):
            self.api_reject_pairing(path.split("/")[4])
        elif path.startswith("/api/nodes/") and path.endswith("/delete"):
            self.api_delete_node(path.split("/")[3])
        elif path.startswith("/api/nodes/") and path.endswith("/refresh"):
            self.api_refresh_node(path.split("/")[3])
        elif path.startswith("/api/nodes/") and "/containers/" in path and path.endswith("/start"):
            parts = path.split("/")
            self.api_node_container_action(parts[3], parts[5], "start")
        elif path.startswith("/api/nodes/") and "/containers/" in path and path.endswith("/stop"):
            parts = path.split("/")
            self.api_node_container_action(parts[3], parts[5], "stop")
        elif path.startswith("/api/nodes/") and "/containers/" in path and path.endswith("/restart"):
            parts = path.split("/")
            self.api_node_container_action(parts[3], parts[5], "restart")
        elif path.startswith("/api/nodes/") and "/containers/" in path and path.endswith("/exec"):
            parts = path.split("/")
            self.api_node_container_exec(parts[3], parts[5], data)
        elif path.startswith("/api/nodes/") and path.endswith("/images/pull"):
            parts = path.split("/")
            self.api_node_image_pull(parts[3], data)
        elif path.startswith("/api/nodes/") and path.endswith("/images/transfer"):
            parts = path.split("/")
            self.api_node_image_transfer(parts[3], data)
        elif path.startswith("/api/nodes/") and path.endswith("/restart"):
            self.api_node_restart(path.split("/")[3])
        elif path.startswith("/api/nodes/") and path.endswith("/containers"):
            parts = path.split("/")
            self.api_node_container_create(parts[3], data)
        else:
            self.send_error(404, "Not Found")

    def route_delete(self, path, parsed=None):
        if path == "/api/nodes/manager":
            self.api_revoke_manager()
            return
        if "/files" in path and path.startswith("/api/containers/"):
            parts = path.split("/")
            name = parts[3]
            qs = parsed.query if parsed else ""
            self.api_files_delete(name, qs)
            return
        parts = path.split("/")
        if len(parts) >= 6 and parts[2] == "containers" and parts[4] == "services":
            # DELETE /api/containers/<name>/services/<service> — must be
            # routed to the service delete, NOT to api_delete_container
            # (which used to swallow it and delete the WHOLE container).
            self.api_service_action(parts[3], parts[5], "delete")
        elif len(parts) >= 4 and parts[2] == "containers":
            self.api_delete_container(parts[3])
        elif len(parts) >= 4 and parts[2] == "images":
            self.api_delete_image(parts[3])
        elif len(parts) >= 4 and parts[2] == "networks":
            self.api_delete_network(parts[3])
        elif len(parts) >= 4 and parts[2] == "backups":
            self.api_delete_backup_routine(parts[3])
        elif len(parts) >= 4 and parts[2] == "nodes":
            if len(parts) >= 6 and parts[4] == "containers":
                self.api_node_container_delete(parts[3], parts[5])
            else:
                self.api_delete_node(parts[3])
        elif len(parts) >= 4 and parts[2] == "stacks":
            self.api_delete_stack(parts[3])
        else:
            self.send_error(404, "Not Found")

    # ============================================================
    # Auth
    # ============================================================

    def api_login(self, data):
        # Rate limiting (only checks threshold; failures are recorded below)
        client_ip = self.client_address[0]
        if not _check_rate_limit(client_ip, record=False):
            self.send_error(429, "Too many login attempts. Try again later.")
            return

        if not isinstance(data, dict):
            self.send_error(400, "Request body must be a JSON object")
            return

        config = load_config()
        user = data.get("username", "")
        pwd = data.get("password", "")
        if not user or not pwd:
            self.send_error(400, "Username and password are required")
            return
        if user == config.get("username") and _verify_password(pwd, config.get("password", "")):
            token = _create_token(user)
            self.send_json({
                "success": True,
                "token": token,
                "expires": (datetime.now() + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat(),
                "first_boot": config.get("first_boot", False),
                "force_change": config.get("first_boot", False)
            })
        else:
            _record_failed_login(client_ip)
            self.send_error(401, "Invalid credentials")

    def api_change_password(self, data):
        config = load_config()
        current = data.get("current_password", "")
        if not _verify_password(current, config.get("password", "")):
            self.send_error(401, "Current password incorrect")
            return
        new_pass = data.get("new_password", "")
        if not new_pass or len(new_pass) < 6:
            self.send_error(400, "Password must be at least 6 characters")
            return
        config["password"] = new_pass
        config["first_boot"] = False
        save_config(config)
        # Sync password to ankfs sshd
        self._sync_ankfs_password(new_pass)
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
                    config["stats"] = get_container_stats(name)
                    containers.append(config)
        self.send_json(containers)

    def api_all_containers(self):
        """Unified containers view: local containers plus every online node's containers,
        each tagged with which node it lives on."""
        result = []
        # Get local containers (reuse api_list_containers logic)
        containers = []
        if os.path.exists(CONTAINERS_DIR):
            for cname in os.listdir(CONTAINERS_DIR):
                if not os.path.isdir(os.path.join(CONTAINERS_DIR, cname)):
                    continue
                try:
                    config = load_container_config(cname)
                except Exception:
                    continue
                if config:
                    config["stats"] = get_container_stats(cname)
                    containers.append(config)
        for c in containers:
            c = dict(c)
            c["node"] = "local"
            c["node_alias"] = "Local"
            result.append(c)
        nm = self._get_node_manager()
        if nm:
            try:
                from node_proxy import NodeProxy
                proxy = NodeProxy(nm)
                for n in nm.list_nodes():
                    if n.get("status") != "online":
                        continue
                    try:
                        for c in (proxy.get_containers(n["id"]) or []):
                            c = dict(c)
                            c["node"] = n["id"]
                            c["node_alias"] = n.get("alias") or n["id"]
                            result.append(c)
                    except Exception as e:
                        log(f"[AGGREGATE] containers on {n.get('id')} failed: {e}")
            except Exception as e:
                log(f"[AGGREGATE] node_proxy unavailable: {e}")
        self.send_json(result)

    def api_container_health(self, name):
        """Health check: SSH port + ankd port + ankd health file.
        Returns status and which probes responded."""
        config = load_container_config(name)
        if not config:
            self.send_json({"error": "not found"}, 404)
            return
        ssh_ok = _sshd_port_open(name)
        ankd_port = config.get("ankd_port")
        ankd_ok = _ankd_port_open(name)
        ankd_port_probed = ankd_ok is True
        health_up = _health_file_status(name)
        pid_alive = _pid_alive(name)

        if not ankd_port and (ankd_ok or ssh_ok or health_up or pid_alive):
            ankd_port = self._heal_ankd_port(name)

        if ankd_ok is None:
            # No ankd port configured: infer daemon liveness from host-visible
            # evidence. The health file is written by ankd itself every ~3s;
            # pid alive + ssh answering means the init process ankd started
            # is still up.
            if health_up:
                ankd_ok = True
            elif pid_alive and ssh_ok:
                ankd_ok = True
            elif health_up is False and pid_alive is False:
                ankd_ok = False
            else:
                ankd_ok = bool(pid_alive) if pid_alive is not None else False
        elif not ankd_ok:
            # Port configured but TCP probe failed. The listener can be
            # unreachable from host loopback (isolated netns without port
            # forwarding, nc restart gap, non-busybox nc) while the daemon
            # itself is alive: the health file is secondary evidence.
            if health_up and (ssh_ok or pid_alive):
                ankd_ok = True

        if ssh_ok and ankd_ok:
            status = "running"
        elif ankd_ok:
            status = "running_degraded_ssh"
        elif ssh_ok:
            status = "running_degraded_ankd"
        elif pid_alive:
            status = "running_degraded_both"
        else:
            status = "stopped"
        self.send_json({
            "name": name,
            "status": status,
            "ssh_port": config.get("ssh_port"),
            "ssh_alive": ssh_ok,
            "ankd_port": ankd_port,
            "ankd_alive": ankd_ok,
            "ankd_port_probed": ankd_port_probed,
            "ankd_health_file": health_up,
            "pid_alive": pid_alive
        })

    def _heal_ankd_port(self, name):
        """Self-heal legacy containers created before per-container ankd ports
        existed: allocate a free port and persist it to config.json so future
        starts pass it into the container (container.sh reads it) and health
        checks can probe TCP directly. Serialized to keep two concurrent
        health checks from allocating the same port."""
        with _ankd_heal_lock:
            try:
                config = load_container_config(name)
                if not config:
                    return None
                if config.get("ankd_port"):
                    return config["ankd_port"]
                port = int(self._find_free_ankd_port())
                config["ankd_port"] = port
                save_container_config(name, config)
                log(f"[HEALTH] {name}: allocated ankd_port {port} (legacy container)")
                return port
            except Exception as e:
                log(f"[HEALTH] {name}: ankd_port self-heal failed: {e}")
                return None

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
            _ex = load_container_config(name)
            _ex_status = (_ex or {}).get("status", "")
            if _ex_status not in ("building", "failed"):
                self.send_error(409, f"Container '{name}' already exists")
                return

        image = data.get("image", "alpine-3.20")
        root_password = data.get("root_password", "")
        if not root_password:
            self.send_error(400, "Root password required")
            return

        ssh_port = data.get("ssh_port")
        if not ssh_port:
            ssh_port = self._find_free_port(2201)
        else:
            try:
                ssh_port = int(ssh_port)
                if ssh_port < 1 or ssh_port > 65535:
                    self.send_error(400, "ssh_port must be between 1 and 65535")
                    return
            except (ValueError, TypeError):
                self.send_error(400, "ssh_port must be a valid integer")
                return

        ankd_port = self._find_free_ankd_port()

        template_id = data.get("template", "")
        template_name = data.get("template_name", "")
        template = None
        if template_id:
            for t in self.IMAGE_TEMPLATES:
                if t["id"] == template_id:
                    template = t
                    break
            if template:
                template_name = template_name or template["name"]
                if not data.get("image") or data.get("image") == template_id:
                    image = template["image"]

        # --- LITE MODE ---
        if is_lite():
            mapped_image = image
            if image.startswith("alpine-"):
                mapped_image = f"ank-alpinebase-{image[7:]}"
            tpl = template
            if not tpl:
                for t in self.IMAGE_TEMPLATES:
                    if t["base"] == image or t["image"] == image or t["base"] == mapped_image or t["image"] == mapped_image:
                        tpl = t
                        break
            tpl_id = template_id or (tpl["id"] if tpl else "")
            tpl_name = template_name or (tpl["name"] if tpl else "")

            stub_dir = os.path.join(CONTAINERS_DIR, name)
            os.makedirs(stub_dir, exist_ok=True)
            stub_config = {
                "name": name,
                "status": "building",
                "image": mapped_image,
                "mode": get_mode().get("mode", "lite"),
                "autostart": data.get("autostart", False),
                "ip_address": "",
                "ssh_port": ssh_port,
                "ankd_port": ankd_port,
                "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pid": None,
                "policies": data.get("policies", {}),
                "resources": data.get("resources", {"memory_limit": "256M", "cpu_limit_percent": 50}),
                "port_mappings": data.get("port_mappings", []),
                "root_password": root_password
            }
            if tpl_id:
                stub_config["template"] = tpl_id
                stub_config["template_name"] = tpl_name
            save_container_config(name, stub_config)

            def _do_lite_create():
                log_path = os.path.join(ANK_DIR, "logs", f"{name}.log")
                try:
                    with open(log_path, "w") as lf:
                        lf.write(f"Creating container '{name}' (image: {mapped_image})...\n")
                        lf.flush()
                    ok, result = ank_lite.create_container(
                        name, mapped_image, root_password, ssh_port, ankd_port,
                        template_id=tpl_id)
                    if not ok:
                        with open(log_path, "a") as lf:
                            lf.write(f"ERROR: {result}\n")
                        log(f"ERROR: lite create {name}: {result}")
                        cfg = load_container_config(name)
                        if cfg:
                            cfg["status"] = "failed"
                            save_container_config(name, cfg)
                    else:
                        cfg = load_container_config(name)
                        if cfg:
                            cfg["status"] = "stopped"
                            cfg["image"] = mapped_image
                            if tpl_id:
                                cfg["template"] = tpl_id
                                cfg["template_name"] = tpl_name
                            save_container_config(name, cfg)
                        log(f"Container {name} created (lite)")
                except Exception as e:
                    log(f"ERROR: lite create thread {name}: {e}")
                    cfg = load_container_config(name)
                    if cfg:
                        cfg["status"] = "failed"
                        save_container_config(name, cfg)
            threading.Thread(target=_do_lite_create, daemon=True).start()
            self.send_json({"message": f"Container '{name}' creating", "name": name, "ssh_port": ssh_port}, 201)
            return

        # --- ROOT MODE ---

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
            "ankd_port": ankd_port,
            "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pid": None,
            "policies": data.get("policies", {}),
            "resources": data.get("resources", {"memory_limit": "256M", "cpu_limit_percent": 50}),
            "port_mappings": data.get("port_mappings", []),
            "root_password": root_password
        }
        if template_id:
            stub_config["template"] = template_id
            stub_config["template_name"] = template_name
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
                if not template and template_id:
                    for t in self.IMAGE_TEMPLATES:
                        if t["id"] == template_id:
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
                        elif template_id:
                            cfg["template"] = template_id
                            cfg["template_name"] = template_name or template_id
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
        state_lock = _get_container_lock(name)
        with state_lock:
            config = load_container_config(name)
            if not config:
                self.send_error(404, f"Container '{name}' not found")
                return
            if config.get("status") in ("starting", "stopping"):
                self.send_error(409, f"Container '{name}' is already {config.get('status')}")
                return
            config["status"] = "starting"
            save_container_config(name, config)

        # --- LITE MODE ---
        if is_lite():
            def do_lite_start():
                try:
                    ok, result = ank_lite.start_container(name)
                    cfg = load_container_config(name)
                    if cfg:
                        if not ok:
                            log(f"ERROR: lite start {name}: {result}")
                            cfg["status"] = "failed"
                            cfg["pid"] = None
                            save_container_config(name, cfg)
                            note_container_stopped(name)
                        else:
                            log(f"Container {name} started (lite)")
                            cfg2 = load_container_config(name)
                            if cfg2:
                                cfg2["status"] = "running"
                                save_container_config(name, cfg2)
                            note_container_started(name)
                except Exception as e:
                    log(f"ERROR: lite start thread {name}: {e}")
                    cfg = load_container_config(name)
                    if cfg:
                        cfg["status"] = "failed"
                        cfg["pid"] = None
                        save_container_config(name, cfg)
                        note_container_stopped(name)
            threading.Thread(target=do_lite_start, daemon=True).start()
            self.send_json({"message": f"Container '{name}' starting"})
            return

        # --- ROOT MODE ---
        def do_start():
            try:
                output, code = run_script("container.sh", "start", name)
                cfg = load_container_config(name)
                if cfg:
                    if code != 0:
                        log(f"ERROR: start {name}: {output}")
                        cfg["status"] = "stopped"
                        cfg["pid"] = None
                        save_container_config(name, cfg)
                        note_container_stopped(name)
                    else:
                        log(f"Container {name} started")
                        # Re-read config — container.sh updated PID and status
                        cfg2 = load_container_config(name)
                        if cfg2:
                            cfg2["status"] = "running"
                            save_container_config(name, cfg2)
                        else:
                            cfg["status"] = "running"
                            save_container_config(name, cfg)
                        note_container_started(name)
            except Exception as e:
                log(f"ERROR: start thread {name}: {e}")
                cfg = load_container_config(name)
                if cfg:
                    cfg["status"] = "stopped"
                    cfg["pid"] = None
                    save_container_config(name, cfg)
                    note_container_stopped(name)
        threading.Thread(target=do_start, daemon=True).start()
        self.send_json({"message": f"Container '{name}' starting"})

    def api_stop_container(self, name):
        state_lock = _get_container_lock(name)
        with state_lock:
            config = load_container_config(name)
            if not config:
                self.send_error(404, f"Container '{name}' not found")
                return
            if config.get("status") in ("starting", "stopping"):
                self.send_error(409, f"Container '{name}' is already {config.get('status')}")
                return
            config["status"] = "stopping"
            save_container_config(name, config)
            note_container_stopped(name)

        # --- LITE MODE ---
        if is_lite():
            def do_lite_stop():
                try:
                    ank_lite.stop_container(name)
                    cfg = load_container_config(name)
                    if cfg:
                        log(f"Container {name} stopped (lite)")
                        cfg["status"] = "stopped"
                        cfg["pid"] = None
                        save_container_config(name, cfg)
                        note_container_stopped(name)
                except Exception as e:
                    log(f"ERROR: lite stop thread {name}: {e}")
                    cfg = load_container_config(name)
                    if cfg:
                        cfg["status"] = "stopped"
                        cfg["pid"] = None
                        save_container_config(name, cfg)
                        note_container_stopped(name)
            threading.Thread(target=do_lite_stop, daemon=True).start()
            self.send_json({"message": f"Container '{name}' stopping"})
            return

        # --- ROOT MODE ---
        def do_stop():
            try:
                log_path = os.path.join(ANK_DIR, "logs", f"{name}.log")
                from datetime import datetime
                ts = datetime.now().strftime("%H:%M:%S")
                with open(log_path, "a") as lf:
                    lf.write(f"[boot] {ts} Stopping services...\n")
                    lf.flush()
                output, code = run_script("container.sh", "stop", name, timeout=90)
                # Write stop output to log
                try:
                    ts2 = datetime.now().strftime("%H:%M:%S")
                    with open(log_path, "a") as lf:
                        for line in output.strip().split("\n"):
                            lf.write(f"[stop] {ts2} {line}\n")
                        lf.write(f"[stop] {ts2} Container stopped\n")
                        lf.flush()
                except Exception:
                    pass
                # Verify container is actually dead before marking stopped
                import time
                for _ in range(10):
                    cfg = load_container_config(name)
                    if cfg:
                        pid = cfg.get("pid")
                        if pid:
                            try:
                                os.kill(pid, 0)
                                time.sleep(1)
                                continue
                            except OSError:
                                pass
                    break
                cfg = load_container_config(name)
                if cfg:
                    if code != 0 and "timed out" not in output:
                        log(f"ERROR: stop {name}: {output}")
                    log(f"Container {name} stopped")
                    cfg["status"] = "stopped"
                    cfg["pid"] = None
                    save_container_config(name, cfg)
                    note_container_stopped(name)
            except Exception as e:
                log(f"ERROR: stop thread {name}: {e}")
                cfg = load_container_config(name)
                if cfg:
                    cfg["status"] = "stopped"
                    cfg["pid"] = None
                    save_container_config(name, cfg)
                    note_container_stopped(name)
        threading.Thread(target=do_stop, daemon=True).start()
        self.send_json({"message": f"Container '{name}' stopping"})

    def api_delete_container(self, name):
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return

        # --- LITE MODE ---
        if is_lite():
            ok, result = ank_lite.delete_container(name)
            if not ok:
                self.send_error(500, f"Failed to delete: {result}")
                return
            self.send_json({"message": f"Container '{name}' deleted"})
            return

        # --- ROOT MODE ---
        output, code = run_script("container.sh", "delete", name)
        if code != 0:
            self.send_error(500, f"Failed to delete: {output}")
            return
        self.send_json({"message": f"Container '{name}' deleted"})

    def api_list_services(self, name):
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return
        instance_uuid = config.get("instance_uuid", name)
        services_dir = os.path.join(CONTAINERS_DIR, name, "merged", "etc", "ankd", "services.d")
        services = []
        # If services.d is empty but container has a rootfs, generate .ankd files
        # (handles containers created with older code that didn't have ankd)
        if os.path.isdir(services_dir):
            ank_files = [f for f in os.listdir(services_dir) if f.endswith(".ankd")]
            if not ank_files:
                merged = os.path.join(CONTAINERS_DIR, name, "merged")
                template_id = config.get("template_id", config.get("image", ""))
                ssh_port = config.get("ssh_port", 22)
                # Generate default .ankd files inline
                self._generate_ankd_files(services_dir, merged, template_id, ssh_port)
                ank_files = [f for f in os.listdir(services_dir) if f.endswith(".ankd")] if os.path.isdir(services_dir) else []
        if os.path.isdir(services_dir):
            for f in sorted(os.listdir(services_dir)):
                if not f.endswith(".ankd"):
                    continue
                svc_name = f.replace(".ankd", "")
                if "-" in svc_name:
                    svc_name = svc_name.split("-", 1)[1]
                svc = {"name": svc_name, "file": f, "enabled": True, "restart_policy": "always", "cmd": ""}
                # Read .ankd config
                try:
                    with open(os.path.join(services_dir, f)) as fh:
                        for line in fh:
                            line = line.strip()
                            if line.startswith("CMD="):
                                svc["cmd"] = line[4:].strip('"')
                            elif line.startswith("ENABLED="):
                                svc["enabled"] = line[8:].strip('"') == "true"
                            elif line.startswith("RESTART_POLICY="):
                                svc["restart_policy"] = line[15:].strip('"')
                except Exception:
                    pass
                # Check if running via the pgid registry ankd keeps at
                # merged/etc/ankd/pids/<uuid>.pgid - real disk (not tmpfs),
                # so it's directly readable from here with no ps/tag
                # matching and no /proc scanning. ankd starts every service
                # with setsid, so the recorded pid is also its pgid/sid.
                svc["status"] = "stopped"
                svc["pid"] = None
                try:
                    uuid = None
                    # Method 1: look in generated scripts dir (ANKD_GENERATED)
                    generated_dir = os.path.join(CONTAINERS_DIR, name, "merged", "etc", "ankd", "services")
                    if os.path.isdir(generated_dir):
                        for gen_f in os.listdir(generated_dir):
                            if gen_f.endswith(f"-{svc_name}.sh"):
                                uuid = gen_f.split("-", 1)[0]
                                break
                    # Method 2: scan pids dir — find .pgid file whose uuid matches a generated script
                    if not uuid:
                        pids_dir = os.path.join(CONTAINERS_DIR, name, "merged", "etc", "ankd", "pids")
                        if os.path.isdir(pids_dir):
                            for pf_name in os.listdir(pids_dir):
                                if not pf_name.endswith(".pgid"):
                                    continue
                                candidate_uuid = pf_name.replace(".pgid", "")
                                # Check if this uuid has a matching generated script
                                if os.path.isdir(generated_dir):
                                    for gen_f in os.listdir(generated_dir):
                                        if gen_f.startswith(f"{candidate_uuid}-") and gen_f.endswith(f"-{svc_name}.sh"):
                                            uuid = candidate_uuid
                                            break
                                if uuid:
                                    break
                    # Method 3: scan pids dir and match by service name in .ankd
                    if not uuid:
                        pids_dir = os.path.join(CONTAINERS_DIR, name, "merged", "etc", "ankd", "pids")
                        if os.path.isdir(pids_dir):
                            for pf_name in os.listdir(pids_dir):
                                if not pf_name.endswith(".pgid"):
                                    continue
                                candidate_uuid = pf_name.replace(".pgid", "")
                                # Check if this uuid's pgid file is alive
                                try:
                                    with open(os.path.join(pids_dir, pf_name)) as pf:
                                        pgid = int(pf.read().strip())
                                    os.kill(pgid, 0)
                                    svc["status"] = "running"
                                    svc["pid"] = pgid
                                    break
                                except (OSError, ValueError, ProcessLookupError):
                                    pass
                    if uuid:
                        pgid_file = os.path.join(CONTAINERS_DIR, name, "merged", "etc", "ankd", "pids", f"{uuid}.pgid")
                        if os.path.isfile(pgid_file):
                            with open(pgid_file) as pf:
                                pgid = int(pf.read().strip())
                            os.kill(pgid, 0)  # raises if not alive
                            svc["status"] = "running"
                            svc["pid"] = pgid
                except (OSError, ValueError, ProcessLookupError):
                    pass
                except Exception:
                    pass
                services.append(svc)
        self.send_json({"services": services, "instance_uuid": instance_uuid})

    def api_add_service(self, name, data):
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return
        svc_name = data.get("name", "").strip()
        cmd = data.get("cmd", "").strip()
        if not svc_name or not cmd:
            self.send_error(400, "name and cmd required")
            return
        services_dir = os.path.join(CONTAINERS_DIR, name, "merged", "etc", "ankd", "services.d")
        os.makedirs(services_dir, exist_ok=True)
        ank_file = os.path.join(services_dir, f"{svc_name}.ankd")
        if os.path.exists(ank_file):
            self.send_error(409, f"Service '{svc_name}' already exists")
            return
        enabled = data.get("enabled", True)
        policy = data.get("restart_policy", "on-failure")
        delay = data.get("restart_delay", "2")
        with open(ank_file, "w") as f:
            f.write(f"NAME={svc_name}\n")
            f.write(f"CMD={cmd}\n")
            f.write(f"ENABLED={str(enabled).lower()}\n")
            f.write(f"RESTART_POLICY={policy}\n")
            f.write(f"RESTART_DELAY={delay}\n")
        self.send_json({"message": f"Service '{svc_name}' created", "name": svc_name}, 201)

    def api_service_action(self, name, service, action):
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return
        if not service or not all(c.isalnum() or c in "-_." for c in service):
            self.send_error(400, "Invalid service name")
            return
        services_dir = os.path.join(CONTAINERS_DIR, name, "merged", "etc", "ankd", "services.d")
        # Service definitions are named 'NN-<service>.ankd' (numeric
        # order prefix, e.g. 01-sshd.ankd) or plain '<service>.ankd' —
        # resolve by stripping the prefix. The old f"{service}.ankd"
        # lookup 404'd every prefixed service and sent stop down the
        # wrong path.
        ank_file = None
        if os.path.isdir(services_dir):
            for f in sorted(os.listdir(services_dir)):
                if not f.endswith(".ankd"):
                    continue
                stem = f[:-len(".ankd")]
                stripped = stem.split("-", 1)[1] if "-" in stem else stem
                if stripped == service or stem == service:
                    ank_file = os.path.join(services_dir, f)
                    break
        if action != "delete" and not ank_file:
            self.send_error(404, f"Service '{service}' not found")
            return
        if action == "delete":
            # Kill the service first (signal mode + guarded host kill),
            # THEN remove the definition. Generated scripts and pgid
            # files are left for the ankd daemon's ctl handler, which
            # may still need the pgid file to reach a service inside a
            # PID namespace; it cleans them up once the .ankd is gone.
            def _do_service_delete():
                try:
                    run_script("container.sh", "exec", name,
                               f"/usr/ankd/core/ankd.sh ankd.servicestop {service}", timeout=20)
                except Exception as e:
                    log(f"[SERVICE] delete {name}/{service}: stop failed: {e}")
                _ank_stop_service_pgid(name, service)
                try:
                    if ank_file and os.path.exists(ank_file):
                        os.remove(ank_file)
                    flag = os.path.join(CONTAINERS_DIR, name, "merged", "etc", "ankd", "stopped", service)
                    if os.path.exists(flag):
                        os.remove(flag)
                except OSError as e:
                    log(f"[SERVICE] delete {name}/{service}: cleanup failed: {e}")
            threading.Thread(target=_do_service_delete, daemon=True).start()
            self.send_json({"message": f"Service '{service}' deleted"})
            return
        if action == "enable":
            with open(ank_file, "r") as f:
                content = f.read()
            content = content.replace("ENABLED=false", "ENABLED=true")
            with open(ank_file, "w") as f:
                f.write(content)
            self.send_json({"message": f"Service '{service}' enabled"})
            return
        if action == "disable":
            with open(ank_file, "r") as f:
                content = f.read()
            content = content.replace("ENABLED=true", "ENABLED=false")
            with open(ank_file, "w") as f:
                f.write(content)
            self.send_json({"message": f"Service '{service}' disabled"})
            return
        if action == "stop":
            # Stop ONLY this service via the ankd signal mode inside the
            # container: it writes a stop-flag the daemon respects (no
            # RESTART_POLICY=always resurrection) and kills just this
            # service's process group. The old host-side killpg on the
            # pgid registry nuked the whole container whenever the
            # resolved uuid/pgid was stale or PID-namespace-local.
            def _do_service_stop():
                output, code = "", 1
                try:
                    output, code = run_script("container.sh", "exec", name,
                                              f"/usr/ankd/core/ankd.sh ankd.servicestop {service}", timeout=20)
                except Exception as e:
                    log(f"[SERVICE] stop {name}/{service} exec failed: {e}")
                if code != 0:
                    log(f"[SERVICE] stop {name}/{service}: signal mode failed "
                        f"(rc={code}: {output.strip()[:200] if output else ''})")
                    # Guarded host-side fallback (refuses unverifiable pids)
                    _ank_stop_service_pgid(name, service)
                else:
                    log(f"[SERVICE] stop {name}/{service}: {output.strip()[:200] if output else 'ok'}")
            threading.Thread(target=_do_service_stop, daemon=True).start()
            self.send_json({"message": f"Service '{service}' stopping"})
            return
        if action == "restart":
            # Restart ONLY this service: stop (flag + group kill), then
            # queue the start. Runs in a thread like stop/start; the
            # ankd daemon performs the spawn inside the PID namespace.
            def _do_service_restart():
                output, code = "", 1
                try:
                    output, code = run_script("container.sh", "exec", name,
                                              f"/usr/ankd/core/ankd.sh ankd.servicerestart {service}", timeout=20)
                except Exception as e:
                    log(f"[SERVICE] restart {name}/{service} exec failed: {e}")
                if code != 0:
                    log(f"[SERVICE] restart {name}/{service}: signal mode failed "
                        f"(rc={code}: {output.strip()[:200] if output else ''})")
                    # Fallback: kill without a stop-flag so the daemon's
                    # restart policy brings the service back up.
                    _ank_stop_service_pgid(name, service, mark_stopped=False)
            threading.Thread(target=_do_service_restart, daemon=True).start()
            self.send_json({"message": f"Service '{service}' restarting"})
            return
        if action == "start":
            # Start via the ankd signal mode — the daemon (inside the
            # container's PID namespace) does the actual spawn. Run in a
            # thread like before to avoid ever hanging the API.
            def _do_service_start():
                output, code = "", 1
                try:
                    output, code = run_script("container.sh", "exec", name,
                                              f"/usr/ankd/core/ankd.sh ankd.servicestart {service}", timeout=20)
                except Exception as e:
                    log(f"[SERVICE] start {name}/{service} exec failed: {e}")
                if code != 0:
                    log(f"[SERVICE] start {name}/{service}: signal mode failed "
                        f"(rc={code}: {output.strip()[:200] if output else ''})")
                    # Fallback: at least clear a stale stop-flag so the
                    # daemon's restart policy can bring the service back.
                    try:
                        flag = os.path.join(CONTAINERS_DIR, name, "merged", "etc", "ankd", "stopped", service)
                        if os.path.exists(flag):
                            os.remove(flag)
                    except OSError:
                        pass
            threading.Thread(target=_do_service_start, daemon=True).start()
            self.send_json({"message": f"Service '{service}' starting"})

    def api_service_tail(self, name, service, data=None):
        """Tail a service's log via ankd. Returns last N lines."""
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return
        lines = 50
        if data:
            lines = data.get("lines", 50)
        try:
            lines = int(lines)
        except (ValueError, TypeError):
            lines = 50
        if not all(c.isalnum() or c in "-_." for c in service):
            self.send_error(400, "Invalid service name")
            return
        merged = os.path.join(CONTAINERS_DIR, name, "merged")
        log_file = os.path.join(merged, "var", "log", "ankd", f"{service}.log")
        if os.path.isfile(log_file):
            try:
                import subprocess
                result = subprocess.run(
                    ["tail", "-n", str(lines), log_file],
                    capture_output=True, text=True, timeout=5
                )
                self.send_json({"logs": result.stdout, "service": service})
            except Exception as e:
                self.send_json({"logs": f"Error: {e}", "service": service})
        else:
            # Fallback: try via ankd exec
            output, code = run_script("container.sh", "exec", name, f"tail -n {lines} /var/log/ankd/{service}.log 2>/dev/null || echo 'No logs for {service}'")
            self.send_json({"logs": output, "service": service})

    def api_svc_logs(self, name, service, lines=50):
        config = load_container_config(name)
        if not config:
            self.send_error(404, f"Container '{name}' not found")
            return
        try:
            lines = int(lines)
        except (ValueError, TypeError):
            lines = 50
        if not all(c.isalnum() or c in "-_." for c in service):
            self.send_error(400, "Invalid service name")
            return
        merged = os.path.join(CONTAINERS_DIR, name, "merged")
        log_dir = os.path.join(merged, "var", "log", "ankd")
        # Try direct service name, then look up NAME from .ankd files
        candidates = [service]
        services_d = os.path.join(merged, "etc", "ankd", "services.d")
        try:
            for ank_file in os.listdir(services_d):
                if not ank_file.endswith(".ankd"):
                    continue
                try:
                    with open(os.path.join(services_d, ank_file)) as af:
                        for line in af:
                            if line.startswith("NAME="):
                                name_val = line.split("=", 1)[1].strip()
                                if name_val not in candidates:
                                    candidates.append(name_val)
                except OSError:
                    continue
        except OSError:
            pass
        # Also try ankd.log as fallback
        candidates.append("ankd")
        log_file = None
        for cand in candidates:
            path = os.path.join(log_dir, f"{cand}.log")
            if os.path.isfile(path):
                log_file = path
                break
        if log_file:
            try:
                import subprocess
                result = subprocess.run(
                    ["tail", "-n", str(lines), log_file],
                    capture_output=True, text=True, timeout=5
                )
                self.send_json({"logs": result.stdout, "service": service})
            except Exception as e:
                self.send_json({"logs": f"Error reading logs: {e}", "service": service})
        else:
            # Fallback: try via container exec
            output, code = run_script("container.sh", "exec", name,
                f"tail -n {lines} /var/log/ankd/{service}.log 2>/dev/null || "
                f"tail -n {lines} /var/log/ankd/ankd.log 2>/dev/null || "
                f"echo 'No logs for {service}'")
            self.send_json({"logs": output, "service": service})

    def api_restart_container(self, name):
        state_lock = _get_container_lock(name)
        with state_lock:
            config = load_container_config(name)
            if not config:
                self.send_error(404, f"Container '{name}' not found")
                return
            if config.get("status") in ("starting", "stopping"):
                self.send_error(409, f"Container '{name}' is already {config.get('status')}")
                return
        def do_restart():
            try:
                cfg = load_container_config(name)
                if cfg:
                    cfg["status"] = "stopping"
                    save_container_config(name, cfg)
                run_script("container.sh", "stop", name, timeout=90)
                import time; time.sleep(1)
                cfg2 = load_container_config(name)
                if cfg2:
                    cfg2["status"] = "starting"
                    save_container_config(name, cfg2)
                output, code = run_script("container.sh", "start", name, timeout=120)
                cfg3 = load_container_config(name)
                if cfg3:
                    if code != 0:
                        log(f"ERROR: restart {name}: {output}")
                        cfg3["status"] = "stopped"
                        cfg3["pid"] = None
                        save_container_config(name, cfg3)
                        note_container_stopped(name)
                    else:
                        log(f"Container {name} restarted")
                        cfg3["status"] = "running"
                        save_container_config(name, cfg3)
                        note_container_started(name)
            except Exception as e:
                log(f"ERROR: restart thread {name}: {e}")
                cfg = load_container_config(name)
                if cfg:
                    cfg["status"] = "stopped"
                    cfg["pid"] = None
                    save_container_config(name, cfg)
                    note_container_stopped(name)
        threading.Thread(target=do_restart, daemon=True).start()
        self.send_json({"message": f"Container '{name}' restarting"})

    def api_exec_container(self, name, data):
        cmd = data.get("command", "")
        if not cmd:
            self.send_error(400, "Command required")
            return
        if not isinstance(cmd, str):
            self.send_error(400, "Command must be a string")
            return
        if len(cmd) > 4096:
            self.send_error(400, "Command too long (max 4096 characters)")
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
                [HOST_SH, "-c", shell_cmd],
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
                        dest_real = os.path.realpath(dest)
                        for info in zf.infolist():
                            if info.is_dir():
                                continue
                            out_path = os.path.realpath(os.path.join(dest, info.filename))
                            if not out_path.startswith(dest_real):
                                self.send_error(400, f"ZipSlip: path traversal detected in {info.filename}")
                                return
                            os.makedirs(os.path.dirname(out_path), exist_ok=True)
                            with open(out_path, "wb") as f:
                                f.write(zf.read(info.filename))
                            files_saved.append(info.filename)
                except Exception as e:
                    self.send_error(500, f"Failed to extract zip: {e}")
                    return
            else:
                # Contain non-zip uploads inside dest (no path traversal)
                safe_name = os.path.basename(filename.replace("\\", "/"))
                if not safe_name or safe_name in (".", ".."):
                    self.send_error(400, f"Invalid filename: {filename}")
                    return
                out_path = os.path.realpath(os.path.join(dest, safe_name))
                dest_real = os.path.realpath(dest)
                if not (out_path == dest_real or out_path.startswith(dest_real + os.sep)):
                    self.send_error(400, f"Path traversal detected in {filename}")
                    return
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(file_data)
                files_saved.append(safe_name)

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
        rel_path = (rel_path or "").lstrip("/")
        merged_abs = os.path.abspath(merged)
        lexical = os.path.normpath(os.path.join(merged_abs, rel_path)) if rel_path else merged_abs
        if lexical != merged_abs and not lexical.startswith(merged_abs + os.sep):
            return None
        real_merged = os.path.realpath(merged)
        real_full = os.path.realpath(lexical)
        if real_full == real_merged or real_full.startswith(real_merged + os.sep):
            return lexical
        real_ank = os.path.realpath(ANK_DIR)
        real_containers = os.path.realpath(CONTAINERS_DIR)
        if real_full.startswith(real_ank + os.sep) and not real_full.startswith(real_containers + os.sep):
            return lexical
        return None

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
                rel_path = unquote(param.split("=", 1)[1]).lstrip("/")
        full = self._safe_path(merged, rel_path)
        if not full or not os.path.isdir(full):
            self.send_error(400, "Invalid path")
            return
        items = []
        try:
            for entry in sorted(os.listdir(full)):
                entry_rel = os.path.join(rel_path, entry) if rel_path else entry
                entry_full = os.path.join(full, entry)
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
                rel_path = unquote(param.split("=", 1)[1]).lstrip("/")
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
                rel_path = unquote(param.split("=", 1)[1]).lstrip("/")
        if not rel_path:
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
                rel_path = unquote(param.split("=", 1)[1]).lstrip("/")
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
                rel_path = unquote(param.split("=", 1)[1]).lstrip("/")
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
        if not isinstance(data, dict):
            self.send_error(400, "Request body must be a JSON object")
            return
        if "resources" in data:
            if not isinstance(data["resources"], dict):
                self.send_error(400, "resources must be an object")
                return
            config.setdefault("resources", {}).update(data["resources"])
        if "policies" in data:
            if not isinstance(data["policies"], dict):
                self.send_error(400, "policies must be an object")
                return
            config.setdefault("policies", {}).update(data["policies"])
        if "port_mappings" in data:
            if not isinstance(data["port_mappings"], list):
                self.send_error(400, "port_mappings must be an array")
                return
            for pm in data["port_mappings"]:
                if not isinstance(pm, dict):
                    self.send_error(400, "Each port mapping must be an object")
                    return
                if "host_port" in pm:
                    try:
                        pm["host_port"] = int(pm["host_port"])
                    except (ValueError, TypeError):
                        self.send_error(400, "host_port must be an integer")
                        return
            config["port_mappings"] = data["port_mappings"]
            # Port mirroring: update .ankd PORT= + config files
            new_port = data["port_mappings"][0]["host_port"] if data["port_mappings"] else None
            if new_port:
                merged = os.path.join(CONTAINERS_DIR, name, "merged")
                services_dir = os.path.join(merged, "etc", "ankd", "services.d")
                if os.path.isdir(services_dir):
                    for ank_file in os.listdir(services_dir):
                        if not ank_file.endswith(".ankd"):
                            continue
                        fpath = os.path.join(services_dir, ank_file)
                        try:
                            with open(fpath, "r") as f:
                                content = f.read()
                            import re
                            content = re.sub(r"^PORT=.*$", f"PORT={new_port}", content, flags=re.MULTILINE)
                            with open(fpath, "w") as f:
                                f.write(content)
                        except Exception:
                            pass
                # Update service config files
                if os.path.isdir(merged):
                    _service = config.get("template", "")
                    _sp = config.get("static_path", "")
                    _write_ank_config(merged, _service, str(new_port), _sp)
                    # Patch nginx.conf, httpd.conf, server.py, server.js
                    if _service == "nginx":
                        nginx_conf = os.path.join(merged, "etc/nginx/nginx.conf")
                        if os.path.isfile(nginx_conf):
                            with open(nginx_conf) as f: content = f.read()
                            import re
                            content = re.sub(r"listen\s+\d+", f"listen {new_port}", content)
                            with open(nginx_conf, "w") as f: f.write(content)
                    elif _service == "apache":
                        httpd_conf = os.path.join(merged, "etc/apache2/httpd.conf")
                        if os.path.isfile(httpd_conf):
                            with open(httpd_conf) as f: content = f.read()
                            import re
                            content = re.sub(r"^Listen\s+\d+", f"Listen {new_port}", content, flags=re.MULTILINE)
                            with open(httpd_conf, "w") as f: f.write(content)
                    elif _service == "python":
                        server_py = os.path.join(merged, "srv/server.py")
                        if os.path.isfile(server_py):
                            with open(server_py) as f: content = f.read()
                            import re
                            content = re.sub(r"PORT\s*=\s*\d+", f"PORT = {new_port}", content)
                            content = re.sub(r"0\.0\.0\.0:\d+", f"0.0.0.0:{new_port}", content)
                            with open(server_py, "w") as f: f.write(content)
                    elif _service == "node":
                        server_js = os.path.join(merged, "srv/server.js")
                        if os.path.isfile(server_js):
                            with open(server_js) as f: content = f.read()
                            import re
                            content = re.sub(r"listen\(\d+", f"listen({new_port}", content)
                            with open(server_js, "w") as f: f.write(content)
        if "ip_address" in data:
            config["ip_address"] = data["ip_address"]
        if "autostart" in data:
            config["autostart"] = data["autostart"]
        if "serves_static" in data:
            config["serves_static"] = data["serves_static"]
        if "static_path" in data:
            config["static_path"] = data["static_path"]
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
            _write_ank_config(merged, _service, _port, _sp)
        self.send_json({"message": f"Container '{name}' updated"})

    def api_pull_image(self, data):
        version = data.get("version", "3.20")
        if _pull_status.get(version, {}).get("state") in ("pulling", "building"):
            self.send_error(409, f"Pull already in progress for alpine-{version}")
            return
        _pull_status[version] = {"state": "pulling", "output": [], "error": ""}
        def _do_pull():
            try:
                dl_out = _pull_status[version]["output"]
                code = run_script_stream("download-rootfs.sh", version, output_list=dl_out, timeout=300)
                if code != 0:
                    _pull_status[version]["state"] = "error"
                    _pull_status[version]["error"] = "\n".join(dl_out)
                    return
                _pull_status[version]["state"] = "building"
                dl_out.append("Building ank-alpinebase (installing openssh, bash, openssl)...")
                code2 = run_script_stream("container.sh", "build-base", version, output_list=dl_out, timeout=300)
                if code2 != 0:
                    _pull_status[version]["state"] = "error"
                    _pull_status[version]["error"] = "\n".join(dl_out)
                    return
                _pull_status[version]["state"] = "done"
                dl_out.append(f"Image ank-alpinebase-{version} ready")
            except Exception as e:
                _pull_status[version]["state"] = "error"
                _pull_status[version]["error"] = str(e)
        threading.Thread(target=_do_pull, daemon=True).start()
        self.send_json({"message": f"Pulling alpine-{version}...", "version": version})

    def api_pull_image_status(self, data):
        version = data.get("version", "3.20")
        status = _pull_status.get(version, {"state": "idle", "output": [], "error": ""})
        self.send_json(status)

    def api_alpine_versions(self):
        try:
            import urllib.request
            req = urllib.request.Request("https://dl-cdn.alpinelinux.org/alpine/releases/", headers={"User-Agent": "ANK/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            import re
            versions = re.findall(r'href="v(\d+\.\d+)/"', html)
            versions.sort(key=lambda v: [int(x) for x in v.split('.')], reverse=True)
            self.send_json(versions[:10])
        except Exception as e:
            self.send_json(["3.20", "3.19", "3.18"])

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
        base_image = self._find_base_image()
        alpine_ready = os.path.isdir(os.path.join(IMAGES_DIR, base_image)) and os.path.lexists(os.path.join(IMAGES_DIR, base_image, "bin/sh"))
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

        base_image = self._find_base_image()
        base_img = os.path.join(IMAGES_DIR, base_image)
        if not os.path.isdir(base_img):
            self.send_error(400, f"Base {base_image} image not found. Reinstall the module.")
            return

        root_password = data.get("root_password") or load_config().get("default_container_password", "ank123")

        # Write stub config with "building" status immediately
        ssh_port = self._find_free_port(2201)
        ankd_port = self._find_free_ankd_port()

        # Stub for both modes so the container appears immediately (building)
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
            "ankd_port": ankd_port,
            "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pid": None,
            "policies": {"inter_container_p2p": False, "allow_host_access": False, "allow_internet": True},
            "resources": {"memory_limit": "256M", "cpu_limit_percent": 50},
            "port_mappings": [],
            "root_password": root_password,
            "template": template_id,
            "template_name": template["name"]
        }
        if is_lite():
            stub_config["mode"] = "lite"
        save_container_config(container_name, stub_config)

        def _do_deploy():
            global _building
            _building = True
            log_path = os.path.join(ANK_DIR, "logs", f"{container_name}.log")
            try:
                with open(log_path, "w") as lf:
                    lf.write(f"Deploying template '{template['name']}' as '{container_name}'...\n")
                    lf.flush()

                merged = os.path.join(CONTAINERS_DIR, container_name, "merged")
                is_lite_mode = is_lite()

                if is_lite_mode:
                    ok, result = ank_lite.create_container(
                        container_name, base_image, root_password, ssh_port, ankd_port,
                        template_id=template_id)
                    if not ok:
                        with open(log_path, "a") as lf:
                            lf.write(f"ERROR: {result}\n")
                            lf.flush()
                        log(f"ERROR: lite create {container_name}: {result}")
                        cfg = load_container_config(container_name)
                        if cfg:
                            cfg["status"] = "failed"
                            save_container_config(container_name, cfg)
                        return

                    cfg = load_container_config(container_name)
                    if cfg:
                        cfg["status"] = "building"
                        cfg["template"] = template_id
                        cfg["template_name"] = template["name"]
                        save_container_config(container_name, cfg)

                    def _proot(cmd, timeout=30):
                        return ank_lite.run_in_container(container_name, cmd, timeout=timeout)

                else:
                    pkgs = " ".join(template.get("packages", []))
                    output, code = run_script("container.sh", "create", container_name, base_image, str(root_password), str(ssh_port), pkgs, template_id, timeout=300)
                    with open(log_path, "a") as lf:
                        lf.write(output + "\n")
                        lf.flush()

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
                                [HOST_SH, "-c", full],
                                capture_output=True, text=True, timeout=timeout
                            )
                        except subprocess.TimeoutExpired as e:
                            out = e.stdout
                            err = e.stderr
                            if isinstance(out, bytes):
                                out = out.decode("utf-8", errors="replace")
                            if isinstance(err, bytes):
                                err = err.decode("utf-8", errors="replace")
                            partial_out = (out or "") + (err or "")
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
                                [HOST_SH, "-c", full],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True
                            )
                            log(f"Background chroot PID: {p.pid} cmd: {cmd}")
                        except Exception as e:
                            log(f"WARNING: _chroot_bg failed: {e}")

                    _chroot('mkdir -p /etc; echo "nameserver 8.8.8.8" > /etc/resolv.conf; echo "nameserver 8.8.4.4" >> /etc/resolv.conf')

                run_cmd = _proot if is_lite_mode else _chroot

                config = load_container_config(container_name)
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
                        config["port_mappings"] = [{"host_port": actual_port, "container_port": actual_port, "protocol": "tcp"}]
                        if port_warnings:
                            config["port_warning"] = "; ".join(port_warnings)
                    if template.get("serves_static"):
                        config["serves_static"] = True
                        config["static_path"] = template["static_path"]
                    save_container_config(container_name, config)

                if template.get("packages") and not is_lite_mode:
                    pkg_list = " ".join(template["packages"])
                    log(f"Installing packages: {pkg_list} in {container_name}")
                    apk_output = ""
                    apk_rc = 1
                    for attempt in range(1, 3):
                        log(f"apk add attempt {attempt}/2...")
                        r = run_cmd(f"apk update && apk add --allow-untrusted {pkg_list}", timeout=180)
                        apk_output = (r.stdout or "") + (r.stderr or "")
                        apk_rc = r.returncode
                        if apk_rc == 0:
                            log(f"OK: All packages installed")
                            break
                        if attempt < 2:
                            log(f"WARN: apk add failed (rc={apk_rc}), retrying in 15s...")
                            import time; time.sleep(15)
                    if apk_rc != 0:
                        log(f"FAIL: apk add failed after 2 attempts")
                        config["package_failure"] = {
                            "packages": template["packages"],
                            "error": apk_output[-500:],
                            "ssh_port": config.get("ssh_port", 22)
                        }
                        save_container_config(container_name, config)

                if template_id == "nginx":
                    static_dir = template["static_path"]
                    run_cmd(f'mkdir -p {static_dir} /run/nginx')
                    _write_file(os.path.join(merged, static_dir.lstrip('/'), 'index.html'), ANK_NGINX_HTML)
                    _write_file(os.path.join(merged, 'etc/nginx/nginx.conf'), ANK_NGINX_CONF.replace('{port}', str(actual_port)))
                    _write_ank_config(merged, 'nginx', actual_port, static_dir)

                elif template_id == "apache":
                    static_dir = template["static_path"]
                    run_cmd(f'mkdir -p {static_dir}')
                    run_cmd(f'sed -i "s/^Listen 80/Listen {actual_port}/" /etc/apache2/httpd.conf 2>/dev/null')
                    _write_file(os.path.join(merged, static_dir.lstrip('/'), 'index.html'), ANK_APACHE_HTML)
                    _write_ank_config(merged, 'apache', actual_port, static_dir)

                elif template_id == "php":
                    php_dir = "/var/www/php"
                    run_cmd(f'mkdir -p {php_dir}')
                    _write_file(os.path.join(merged, php_dir.lstrip('/'), 'index.php'), ANK_PHP_INDEX)
                    _write_ank_config(merged, 'php', actual_port, php_dir)

                elif template_id == "node":
                    node_dir = "/var/www/app"
                    run_cmd(f'mkdir -p {node_dir}')
                    _write_file(os.path.join(merged, node_dir.lstrip('/'), 'server.js'), ANK_NODE_SERVER.replace('{port}', str(actual_port)))
                    _write_file(os.path.join(merged, node_dir.lstrip('/'), 'package.json'), '{"name":"ank-node-app","version":"1.0.0","main":"server.js"}')
                    _write_ank_config(merged, 'node', actual_port, node_dir)

                elif template_id == "python":
                    py_dir = "/var/www/app"
                    run_cmd(f'mkdir -p {py_dir}')
                    _write_file(os.path.join(merged, py_dir.lstrip('/'), 'server.py'), ANK_PYTHON_SERVER.replace('{port}', str(actual_port)))
                    _write_ank_config(merged, 'python', actual_port, py_dir)

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
        target_node = data.get("target_node", "local")
        if target_node and target_node != "local":
            nm = self._get_node_manager()
            if not nm:
                self.send_json({"error": "node_manager not available"}, 500)
                return
            payload = {k: v for k, v in data.items() if k != "target_node"}
            result = nm._node_api_post(target_node, "/api/images/ankfile", payload)
            if isinstance(result, dict) and result.get("error"):
                code = result.get("status_code")
                if not isinstance(code, int) or code < 400:
                    code = 502
                self.send_json(result, code)
                return
            self.send_json(result if isinstance(result, dict) else {"message": "Build started"})
            return
        ankfile_content = data.get("content", "")
        container_name = data.get("name", "")
        save_as_image = data.get("save_as_image", False)
        image_name = data.get("image_name", "")
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
                # Map alpine-X.Y to ank-alpinebase-X.Y
                case_alpine = base_image
                if case_alpine.startswith("alpine-"):
                    base_image = f"ank-alpinebase-{case_alpine[7:]}"
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

        # Write stub config with "building" status immediately (both modes)
        ssh_port = self._find_free_port(2201)
        ankd_port = self._find_free_ankd_port()
        stub_dir = os.path.join(CONTAINERS_DIR, container_name)
        os.makedirs(stub_dir, exist_ok=True)
        stub_config = {
            "name": container_name,
            "status": "building",
            "image": base_image,
            "mode": "lite" if is_lite() else get_mode().get("mode", "shared_host"),
            "autostart": False,
            "ip_address": "",
            "ssh_port": ssh_port,
            "ankd_port": ankd_port,
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

                is_lite_mode = is_lite()
                if is_lite_mode:
                    ok, result = ank_lite.create_container(
                        container_name, mapped_image, root_password, ssh_port, ankd_port)
                    if not ok:
                        with open(log_path, "a") as lf:
                            lf.write(f"ERROR: {result}\n")
                            lf.flush()
                        log(f"ERROR: lite create {container_name}: {result}")
                        cfg = load_container_config(container_name)
                        if cfg:
                            cfg["status"] = "failed"
                            save_container_config(container_name, cfg)
                        return
                    # Verify merged tree exists before RUN phase
                    _merged_check = os.path.join(CONTAINERS_DIR, container_name, "merged")
                    if not os.path.isdir(_merged_check):
                        log(f"ERROR: lite create ok but merged missing for {container_name}")
                        with open(log_path, "a") as lf:
                            lf.write("ERROR: merged dir missing after create\n")
                        cfg = load_container_config(container_name)
                        if cfg:
                            cfg["status"] = "failed"
                            save_container_config(container_name, cfg)
                        return
                    code = 0
                    cfg = load_container_config(container_name)
                    if cfg:
                        cfg["status"] = "building"
                        save_container_config(container_name, cfg)
                else:
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
                            [HOST_SH, "-c", full],
                            capture_output=True, text=True, timeout=timeout
                        )
                    except subprocess.TimeoutExpired as e:
                        # Return partial output so user can see what happened
                        out = e.stdout
                        err = e.stderr
                        if isinstance(out, bytes):
                            out = out.decode("utf-8", errors="replace")
                        if isinstance(err, bytes):
                            err = err.decode("utf-8", errors="replace")
                        partial_out = (out or "") + (err or "")
                        class _Result:
                            pass
                        r = _Result()
                        r.returncode = -1
                        r.stdout = partial_out
                        r.stderr = f"TIMEOUT after {timeout}s"
                        return r

                if is_lite_mode:
                    def _proot(cmd, timeout=60):
                        return ank_lite.run_in_container(container_name, cmd, timeout=timeout)
                    run_cmd = _proot
                else:
                    run_cmd = _chroot

                config = load_container_config(container_name)

                run_cmd('mkdir -p /etc; echo "nameserver 8.8.8.8" > /etc/resolv.conf; echo "nameserver 8.8.4.4" >> /etc/resolv.conf')

                for cmd in commands:
                    log(f"Ankfile RUN: {cmd}")
                    with open(log_path, "a") as lf:
                        lf.write(f"RUN: {cmd}\n")
                        lf.flush()
                    r = run_cmd(cmd, timeout=300)
                    output = (r.stdout or "") + (r.stderr or "")
                    if r.returncode != 0:
                        # If it's an apk add command, retry once after 15s
                        if "apk add" in cmd:
                            log(f"Ankfile RUN apk failed, retrying in 15s...")
                            import time; time.sleep(15)
                            r = run_cmd(cmd, timeout=300)
                            output = (r.stdout or "") + (r.stderr or "")
                            if r.returncode != 0:
                                log(f"Ankfile RUN apk failed after retry")
                                if config:
                                    config["package_failure"] = {
                                        "packages": cmd,
                                        "error": output[-500:],
                                        "ssh_port": config.get("ssh_port", 22)
                                    }
                                    save_container_config(container_name, config)
                        else:
                            log(f"Ankfile RUN failed: {output[-500:]}")
                        with open(log_path, "a") as lf:
                            lf.write(f"FAILED (rc={r.returncode}): {output[-500:]}\n")
                    else:
                        with open(log_path, "a") as lf:
                            lf.write(f"OK: {output[-300:]}\n")

                if cmd_line:
                    _write_ank_config(merged, cmd_line, ports[0] if ports else "", "")
                    log(f"Ankfile CMD: {cmd_line}")
                    with open(log_path, "a") as lf:
                        lf.write(f"CMD: {cmd_line}\n")

                    svc_dir = os.path.join(merged, "etc/ankd/services.d")
                    os.makedirs(svc_dir, exist_ok=True)
                    app_port = ports[0] if ports else ""
                    svc_ankd = os.path.join(svc_dir, "02-app.ankd")
                    if not os.path.exists(svc_ankd):
                        with open(svc_ankd, "w") as f:
                            f.write(f"NAME=app\nCMD={cmd_line}\nDIR={workdir}\nPORT={app_port}\nPID_FILE=/run/app.pid\nSTOP_SIGNAL=TERM\nRESTART_POLICY=always\nRESTART_DELAY=3\n")
                        log(f"Generated .ankd: {svc_ankd}")
                        with open(log_path, "a") as lf:
                            lf.write(f"Generated .ankd: app -> {cmd_line} (dir: {workdir})\n")

                config = load_container_config(container_name)
                if config:
                    config["image"] = mapped_image
                    config["template"] = "ankfile"
                    config["template_name"] = f"Ankfile ({base_image})"
                    config["status"] = "stopped"
                    if cmd_line:
                        config["cmd"] = cmd_line
                    if workdir and workdir != "/":
                        config["workdir"] = workdir
                    if ports:
                        config["port_mappings"] = [{"host_port": port, "container_port": port, "protocol": "tcp"} for port in ports]
                        for p in ports:
                            _write_portfwd(merged, p)
                    save_container_config(container_name, config)
                # Save as image if requested
                if save_as_image and image_name:
                    try:
                        img_dir = os.path.join(IMAGES_DIR, image_name)
                        import shutil
                        if os.path.exists(img_dir):
                            shutil.rmtree(img_dir)
                        shutil.copytree(merged, img_dir, symlinks=True)
                        log(f"Saved image '{image_name}' from ankfile build")
                        with open(log_path, "a") as lf:
                            lf.write(f"Saved as image: {image_name}\n")
                    except Exception as e:
                        log(f"ERROR: save image {image_name}: {e}")
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
        if not isinstance(cmd, str):
            self.send_error(400, "Command must be a string")
            return
        if len(cmd) > 4096:
            self.send_error(400, "Command too long (max 4096 characters)")
            return
        # Guard: block catastrophic patterns (admin shell is intentional; this is belt-and-suspenders)
        import re as _re
        _deny = [
            r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+/(\s|$)",
            r"rm\s+-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\s+/(\s|$)",
            r">\s*/dev/(sd|mmcblk|block)",
            r"mkfs\.",
            r"dd\s+.*of=/dev/",
            r":\(\)\s*\{.*\};\s*:",  # fork bomb
            r"chmod\s+-R\s+777\s+/",
            r"chown\s+-R\s+.*/\s+/",
        ]
        for pat in _deny:
            if _re.search(pat, cmd):
                self.send_error(403, "Command blocked by safety policy")
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
                    [HOST_SH, "-c", cmd],
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
                "  ank build -i <file>       Build from Ankfile\n\n"
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
                    [HOST_SH, "-c", f"chroot {merged} /bin/sh -c '{wrapped}'"],
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
                self.send_json({"stdout": "", "stderr": "Usage: ank build -i <path-to-ankfile>", "code": 1})
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
            except (OSError, ValueError): pass
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
            device = load_config().get("device_model", "") or os.popen("getprop ro.product.model 2>/dev/null").read().strip() or "unknown"
            kernel = os.popen("uname -r 2>/dev/null").read().strip() or "unknown"
            mem_total = 0
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        parts = line.split()
                        if parts[0] == "MemTotal:": mem_total = int(parts[1])
            except (OSError, ValueError): pass
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
                    [HOST_SH, "-c", cmd],
                    capture_output=True, text=True, timeout=30
                )
                self.send_json({"stdout": result.stdout, "stderr": result.stderr, "code": result.returncode})
            except Exception as e:
                self.send_json({"stdout": "", "stderr": str(e), "code": 1})
            return

        self.send_json({"stdout": "", "stderr": f"Unknown ank-core command: {args[0]}. Type 'ank-core --help' for usage.", "code": 1})

    def _get_man_page(self, cmd):
        man_pages = {
            "ps": (
                "ANK PS - LIST CONTAINERS\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank ps - List all containers with status, IP, image, and PID.\n\n"
                "SYNOPSIS\n"
                "    ank ps\n\n"
                "DESCRIPTION\n"
                "    Displays a table of all containers. Each row shows:\n"
                "    - NAME: Container name (unique identifier)\n"
                "    - STATUS: running | stopped | error\n"
                "    - IP: Container IP on the ank0 bridge (e.g. 10.20.30.3)\n"
                "    - IMAGE: Base image used (e.g. alpine-3.20, nginx-3.20)\n"
                "    - PID: Main process ID (0 if not running)\n\n"
                "EXAMPLES\n"
                "    ank ps\n"
                "    NAME                 STATUS       IP               IMAGE\n"
                "    my-site              running      10.20.30.3       nginx-3.20\n"
                "    dev-server           stopped      -                python-3.20\n\n"
                "TIPS\n"
                "    - Use 'ank start <name>' to start a stopped container\n"
                "    - Use 'ank logs <name>' to view container logs\n"
                "    - Use 'ank inspect <name>' for detailed info"
            ),
            "start": (
                "ANK START - START CONTAINER\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank start - Start a stopped container.\n\n"
                "SYNOPSIS\n"
                "    ank start <name>\n\n"
                "DESCRIPTION\n"
                "    Starts a previously created or stopped container.\n"
                "    The container's filesystem is mounted, network is configured,\n"
                "    and services (sshd, nginx, etc.) are launched.\n\n"
                "    On start, ANK will:\n"
                "    1. Mount the overlay filesystem (merged dir)\n"
                "    2. Configure network (bridge, iptables, DNS)\n"
                "    3. Set root password from config.json\n"
                "    4. Start sshd on the configured port\n"
                "    5. Mark container as 'running' in config\n\n"
                "OPTIONS\n"
                "    <name>     Name of the container (from 'ank ps')\n\n"
                "EXAMPLES\n"
                "    ank start my-site\n"
                "    ank start dev-server\n\n"
                "EXIT STATUS\n"
                "    0    Container started successfully\n"
                "    1    Container not found or already running\n\n"
                "SEE ALSO\n"
                "    ank stop, ank restart, ank ps"
            ),
            "stop": (
                "ANK STOP - STOP CONTAINER\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank stop - Stop a running container.\n\n"
                "SYNOPSIS\n"
                "    ank stop <name>\n\n"
                "DESCRIPTION\n"
                "    Gracefully stops a running container. All processes inside\n"
                "    the container are terminated, SSH connections are closed,\n"
                "    and network rules are removed.\n\n"
                "    On stop, ANK will:\n"
                "    1. Kill the container's main process tree (recursive)\n"
                "    2. Kill all sshd processes on the container's port\n"
                "    3. Remove iptables rules and network namespace\n"
                "    4. Unmount overlay filesystems\n"
                "    5. Mark container as 'stopped' in config\n\n"
                "OPTIONS\n"
                "    <name>     Name of the container\n\n"
                "EXIT STATUS\n"
                "    0    Container stopped successfully\n"
                "    1    Container not found or not running\n\n"
                "SEE ALSO\n"
                "    ank start, ank restart, ank rm"
            ),
            "restart": (
                "ANK RESTART - RESTART CONTAINER\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank restart - Restart a container (stop + start).\n\n"
                "SYNOPSIS\n"
                "    ank restart <name>\n\n"
                "DESCRIPTION\n"
                "    Convenience command that performs 'ank stop' followed by\n"
                "    'ank start' on the specified container. Useful when you\n"
                "    need to reload configuration or apply changes.\n\n"
                "OPTIONS\n"
                "    <name>     Name of the container\n\n"
                "EXAMPLES\n"
                "    ank restart my-site\n\n"
                "SEE ALSO\n"
                "    ank start, ank stop"
            ),
            "rm": (
                "ANK RM - DELETE CONTAINER\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank rm - Delete a container and all its data.\n\n"
                "SYNOPSIS\n"
                "    ank rm <name>\n\n"
                "DESCRIPTION\n"
                "    Permanently removes a container. If the container is\n"
                "    running, it is stopped first. All data in the container\n"
                "    (filesystem, config, logs) is deleted.\n\n"
                "    WARNING: This action is irreversible!\n\n"
                "OPTIONS\n"
                "    <name>     Name of the container\n\n"
                "EXAMPLES\n"
                "    ank rm my-site\n"
                "    ank rm -f my-site    # Force delete\n\n"
                "SEE ALSO\n"
                "    ank stop, ank ps"
            ),
            "logs": (
                "ANK LOGS - VIEW CONTAINER LOGS\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank logs - Display the last lines of container logs.\n\n"
                "SYNOPSIS\n"
                "    ank logs <name>\n\n"
                "DESCRIPTION\n"
                "    Shows the last 50 lines from the container's log file.\n"
                "    Logs include boot messages, service starts, and any\n"
                "    output from processes inside the container.\n\n"
                "OPTIONS\n"
                "    <name>     Name of the container\n\n"
                "EXAMPLES\n"
                "    ank logs my-site\n"
                "    ank logs my-site | tail -20\n\n"
                "SEE ALSO\n"
                "    ank exec, ank start"
            ),
            "exec": (
                "ANK EXEC - EXECUTE COMMAND\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank exec - Execute a command inside a running container.\n\n"
                "SYNOPSIS\n"
                "    ank exec <name> <command> [args...]\n\n"
                "DESCRIPTION\n"
                "    Runs the specified command inside the container's\n"
                "    filesystem using chroot. The command runs as root.\n\n"
                "OPTIONS\n"
                "    <name>      Name of the container\n"
                "    <command>   Command to execute\n"
                "    [args...]   Optional arguments for the command\n\n"
                "EXAMPLES\n"
                "    ank exec my-site ls /var/www/html\n"
                "    ank exec my-site cat /etc/nginx/nginx.conf\n"
                "    ank exec my-site apk update\n\n"
                "SEE ALSO\n"
                "    ank ssh, ank start"
            ),
            "inspect": (
                "ANK INSPECT - INSPECT CONTAINER\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    inspect - Show detailed information about a container.\n\n"
                "SYNOPSIS\n"
                "    ank inspect <name>\n\n"
                "DESCRIPTION\n"
                "    Displays comprehensive details including:\n"
                "    - Name, status, image, PID\n"
                "    - IP address and SSH port\n"
                "    - Creation date and last start time\n"
                "    - Resource limits (RAM, CPU)\n"
                "    - Network configuration\n\n"
                "OPTIONS\n"
                "    <name>     Name of the container\n\n"
                "EXAMPLES\n"
                "    ank inspect my-site\n\n"
                "SEE ALSO\n"
                "    ank ps"
            ),
            "images": (
                "ANK IMAGES - LIST IMAGES\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank images - List all available container images.\n\n"
                "SYNOPSIS\n"
                "    ank images\n\n"
                "DESCRIPTION\n"
                "    Shows all container images available on this device.\n"
                "    Images are the base filesystems used to create containers.\n\n"
                "EXAMPLES\n"
                "    ank images\n\n"
                "SEE ALSO\n"
                "    ank pull, ank deploy"
            ),
            "templates": (
                "ANK TEMPLATES - LIST TEMPLATES\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank templates - List available deploy templates.\n\n"
                "SYNOPSIS\n"
                "    ank templates\n\n"
                "DESCRIPTION\n"
                "    Shows all pre-configured deployment templates:\n"
                "    alpine, python, nginx, apache, php, node\n\n"
                "EXAMPLES\n"
                "    ank templates\n\n"
                "SEE ALSO\n"
                "    ank deploy, ank images"
            ),
            "deploy": (
                "ANK DEPLOY - DEPLOY FROM TEMPLATE\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank deploy - Create and configure a container from a template.\n\n"
                "SYNOPSIS\n"
                "    ank deploy <template> <name>\n\n"
                "DESCRIPTION\n"
                "    Deploys a new container based on a pre-configured template.\n"
                "    The container is created with the default root password\n"
                "    configured in Settings (default: ank123).\n\n"
                "TEMPLATES\n"
                "    alpine    Base Alpine Linux (no extra packages)\n"
                "    python    Python 3.12 + pip\n"
                "    nginx     Nginx + curl (port 8080)\n"
                "    apache    Apache2 + curl (port 9090)\n"
                "    php       PHP 8.2 + mbstring + json + cgi\n"
                "    node      Node.js 20 + npm (port 3000)\n\n"
                "OPTIONS\n"
                "    <template>  Template ID (see 'ank templates')\n"
                "    <name>      Name for the new container (must be unique)\n\n"
                "EXAMPLES\n"
                "    ank deploy nginx my-site\n"
                "    ank deploy python ml-server\n\n"
                "SEE ALSO\n"
                "    ank templates, ank images, ank pull"
            ),
        }
        return man_pages.get(cmd, f"No manual entry for 'ank {cmd}'. Available commands: {', '.join(man_pages.keys())}")

    def _get_core_man_page(self, cmd):
        man_pages = {
            "status": (
                "ANK-CORE STATUS\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank-core status - Display ANK engine status and statistics.\n\n"
                "SYNOPSIS\n"
                "    ank-core status\n\n"
                "DESCRIPTION\n"
                "    Shows a comprehensive overview of the ANK engine including:\n"
                "    - Engine version\n"
                "    - Container counts (running / stopped / total)\n"
                "    - Operating mode (compat or isolated)\n"
                "    - Server port\n\n"
                "OUTPUT\n"
                "    ANK Engine v2.0.0\n"
                "    Containers: 3 running, 1 stopped, 4 total\n"
                "    Mode:       compat\n"
                "    Port:       8001\n\n"
                "MODES\n"
                "    compat      Traditional mode (full compatibility)\n"
                "    isolated    Enhanced isolation (uses PID namespaces)\n\n"
                "EXAMPLES\n"
                "    ank-core status\n\n"
                "SEE ALSO\n"
                "    ank-core info, ank ps"
            ),
            "restart": (
                "ANK-CORE RESTART\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank-core restart - Restart the ANK server process.\n\n"
                "SYNOPSIS\n"
                "    ank-core restart\n\n"
                "DESCRIPTION\n"
                "    Stops the ANK server and starts it again. Running containers\n"
                "    remain alive (they are not stopped).\n\n"
                "    Use this command when:\n"
                "    - You changed server configuration\n"
                "    - The web panel is not responding\n"
                "    - After installing/updating the ANK module\n\n"
                "    The restart process:\n"
                "    1. Kills the existing server process\n"
                "    2. Waits for cleanup\n"
                "    3. Starts a fresh server instance\n\n"
                "WARNING\n"
                "    Running containers stay alive but the web panel will be\n"
                "    briefly unavailable during restart.\n\n"
                "EXAMPLES\n"
                "    ank-core restart\n\n"
                "SEE ALSO\n"
                "    ank-core status, ank-core logs"
            ),
            "shell": (
                "ANK-CORE SHELL\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank-core shell - Open a full host shell.\n\n"
                "SYNOPSIS\n"
                "    ank-core shell\n\n"
                "DESCRIPTION\n"
                "    Opens an interactive shell with root access to the Android\n"
                "    host. Commands run directly on the host system.\n\n"
                "WARNING\n"
                "    This gives you ROOT access to the device.\n"
                "    Be very careful with what commands you run.\n"
                "    Mistakes can brick your device.\n\n"
                "USE CASES\n"
                "    - Debugging ANK internals\n"
                "    - Inspecting host network configuration\n"
                "    - Checking system-level processes\n"
                "    - Manual cleanup of stuck resources\n\n"
                "EXAMPLES\n"
                "    ank-core shell\n"
                "    # You are now in a root shell on the host\n"
                "    ls /data/ank/\n"
                "    ps aux | grep ank\n\n"
                "SEE ALSO\n"
                "    ank-core logs, ank-core clean"
            ),
            "info": (
                "ANK-CORE INFO\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank-core info - Show detailed device information.\n\n"
                "SYNOPSIS\n"
                "    ank-core info\n\n"
                "DESCRIPTION\n"
                "    Displays comprehensive system information about the host\n"
                "    device. This includes:\n\n"
                "    DEVICE INFO\n"
                "    - OS version (Android version)\n"
                "    - Device model\n"
                "    - Kernel version\n"
                "    - CPU model and core count\n"
                "    - RAM usage (used / total / percentage)\n"
                "    - Storage usage on /data partition\n"
                "    - System uptime\n"
                "    - CPU load average\n\n"
                "    ANK INFO\n"
                "    - Container count (running / total)\n"
                "    - Available images\n"
                "    - Operating mode\n\n"
                "EXAMPLES\n"
                "    ank-core info\n\n"
                "SEE ALSO\n"
                "    ank-core status, ank-core network"
            ),
            "network": (
                "ANK-CORE NETWORK\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank-core network - Show ANK network configuration.\n\n"
                "SYNOPSIS\n"
                "    ank-core network\n\n"
                "DESCRIPTION\n"
                "    Displays the virtual network configuration used by containers.\n"
                "    ANK creates an isolated bridge network for containers.\n\n"
                "FIELDS\n"
                "    Bridge     Virtual bridge interface (default: ank0)\n"
                "    Subnet     Container subnet (default: 10.20.30.0/24)\n"
                "    Gateway    Gateway IP for containers (default: 10.20.30.1)\n"
                "    NAT        Network address translation (true/false)\n\n"
                "NETWORK ARCHITECTURE\n"
                "    Containers get IPs in the 10.20.30.x range.\n"
                "    The bridge (ank0) connects containers to the host.\n"
                "    NAT allows containers to access the internet.\n"
                "    Port mapping (npad) enables host access to containers.\n\n"
                "EXAMPLES\n"
                "    ank-core network\n\n"
                "SEE ALSO\n"
                "    ank-core info, ank-core clean"
            ),
            "clean": (
                "ANK-CORE CLEAN\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank-core clean - Clean up orphaned resources.\n\n"
                "SYNOPSIS\n"
                "    ank-core clean\n\n"
                "DESCRIPTION\n"
                "    Removes orphaned resources left behind after crashes or\n"
                "    improper shutdowns. This includes:\n"
                "    - Orphaned network namespaces\n"
                "    - Leftover veth interfaces\n"
                "    - Unused cgroup hierarchies\n"
                "    - Stale PID files\n"
                "    - Temporary files\n\n"
                "    Safe to run at any time. Only removes resources not\n"
                "    currently in use by running containers.\n\n"
                "WHEN TO USE\n"
                "    - After a device crash or forced restart\n"
                "    - If containers show unexpected network errors\n"
                "    - If disk usage seems higher than expected\n"
                "    - As periodic maintenance\n\n"
                "EXAMPLES\n"
                "    ank-core clean\n\n"
                "SEE ALSO\n"
                "    ank-core network, ank-core status"
            ),
            "logs": (
                "ANK-CORE LOGS\n"
                "═══════════════════════════════════════════════════════════════\n\n"
                "NAME\n"
                "    ank-core logs - Show ANK server logs.\n\n"
                "SYNOPSIS\n"
                "    ank-core logs\n\n"
                "DESCRIPTION\n"
                "    Displays the last 30 lines of the ANK server log file.\n"
                "    The log contains startup messages, API requests, errors,\n"
                "    and other server events.\n\n"
                "LOG LOCATION\n"
                "    /data/ank/logs/server.log\n\n"
                "TIPS\n"
                "    - Use 'ank-core logs' to check for startup errors\n"
                "    - Look for 'ERROR' or 'WARN' messages\n"
                "    - Logs rotate automatically (oldest entries removed)\n\n"
                "EXAMPLES\n"
                "    ank-core logs\n"
                "    ank-core logs | grep ERROR\n\n"
                "SEE ALSO\n"
                "    ank logs <container>, ank-core status"
            ),
        }
        return man_pages.get(cmd, f"No manual entry for 'ank-core {cmd}'. Available commands: {', '.join(man_pages.keys())}")

    # ============================================================
    # Network API
    # ============================================================

    def api_list_networks(self):
        # --- LITE MODE: limited network info ---
        if is_lite():
            self.send_json([{
                "id": "shared",
                "name": "shared_host",
                "subnet": "N/A",
                "gateway": "N/A",
                "nat": False,
                "containers": [],
                "mode": "lite",
                "lite": True,
                "message": "Network isolation not available in lite mode"
            }])
            return

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
        # --- LITE MODE ---
        if is_lite():
            self.send_json({
                "bridge": "shared",
                "subnet": "N/A",
                "gateway": "N/A",
                "wan_interface": "N/A",
                "nat_enabled": False,
                "ip_forward": "N/A",
                "iptables_nat": [],
                "mode": "lite",
                "lite": True,
                "message": "Network isolation not available in lite mode"
            })
            return

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
        # --- LITE MODE ---
        if is_lite():
            self.send_error(400, "Network creation not available in lite mode")
            return

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
        # Never expose the admin password / tokens to the panel GET
        safe = {k: v for k, v in config.items()
                if k not in ("password", "token", "ssh_pass")}
        safe["has_password"] = bool(config.get("password"))
        self.send_json(safe)

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
        if "node_name" in data:
            config["node_name"] = data["node_name"]
        if "enable_remote_management" in data:
            config["enable_remote_management"] = data["enable_remote_management"]
        if "manager_ip" in data:
            config["manager_ip"] = data["manager_ip"]
        if "default_container_password" in data:
            config["default_container_password"] = data["default_container_password"]
        if "ssh_enabled" in data:
            config["ssh_enabled"] = data["ssh_enabled"]
        if "ssh_port" in data:
            config["ssh_port"] = int(data["ssh_port"])
        save_config(config)
        # Sync sshd if SSH settings changed
        if "ssh_enabled" in data or "ssh_port" in data:
            self._sync_sshd(config)
        self.send_json({"message": "Configuration updated"})

    def api_restart_device(self):
        """Reboot the Android device."""
        client_ip = self.client_address[0] if self.client_address else "unknown"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log(f"RESTART_DEVICE: [RESTART-DEVICE] {ts} from {client_ip} - Rebooting device...")
        self.send_json({"message": "Device rebooting..."})
        def _reboot():
            import time
            time.sleep(1)
            rc = os.system("svc power reboot 2>/dev/null || reboot 2>/dev/null || su -c reboot 2>/dev/null")
            if rc == 0:
                log(f"RESTART_DEVICE: [RESTART-DEVICE] {ts} from {client_ip} - Reboot command sent successfully")
            else:
                log(f"RESTART_DEVICE: [RESTART-DEVICE] {ts} from {client_ip} - Reboot command failed (rc={rc})")
        threading.Thread(target=_reboot, daemon=True).start()

    def api_restart_server(self):
        """Stop everything ANK and restart the server."""
        log("RESTART_SERVER: Stopping all containers and restarting...")
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
                            if is_lite():
                                ank_lite.stop_container(name)
                            else:
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
            if is_lite():
                os.system(f"setsid sh {ANK_DIR}/start-lite.sh </dev/null >{ANK_DIR}/logs/server.log 2>&1 &")
            else:
                os.system(f"setsid sh {ANK_DIR}/opt/ank/start-server.sh </dev/null >{ANK_DIR}/logs/server.log 2>&1 &")
            log("RESTART_SERVER: Done")
        threading.Thread(target=_restart, daemon=True).start()
        self.send_json({"message": "Server restarting..."})

    # ── ANK Manager API ──────────────────────────────────────────────────────

    def api_ank_manager_status(self):
        """Get server status, PID, uptime, container count."""
        import subprocess
        result = {"running": True, "pid": os.getpid(), "uptime": "", "containers": 0, "mode": get_mode().get("mode", "unknown")}

        try:
            with open("/proc/uptime", "r") as f:
                uptime_secs = float(f.read().split()[0])
                days = int(uptime_secs // 86400)
                hours = int((uptime_secs % 86400) // 3600)
                mins = int((uptime_secs % 3600) // 60)
                result["uptime"] = f"{days}d {hours}h {mins}m" if days else f"{hours}h {mins}m"
        except Exception:
            result["uptime"] = "-"

        try:
            if os.path.isdir(CONTAINERS_DIR):
                result["containers"] = len([d for d in os.listdir(CONTAINERS_DIR) if os.path.isdir(os.path.join(CONTAINERS_DIR, d))])
        except Exception:
            pass

        # Check disk usage
        try:
            st = os.statvfs(ANK_DIR)
            used = (st.f_blocks - st.f_bavail) * st.f_frsize
            result["disk_used_mb"] = round(used / (1024 * 1024), 1)
        except Exception:
            result["disk_used_mb"] = 0

        self.send_json(result)

    def api_ank_manager_stop(self):
        """Gracefully stop the ankd service (server process) via SIGUSR1."""
        client_ip = self.client_address[0] if self.client_address else "unknown"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log(f"ANK_MANAGER: [STOP] {ts} from {client_ip} - Stopping ankd service...")
        try:
            os.kill(os.getpid(), signal.SIGUSR1)
            log(f"ANK_MANAGER: [STOP] {ts} from {client_ip} - SIGUSR1 sent successfully")
        except Exception as e:
            log(f"ANK_MANAGER: [STOP] {ts} from {client_ip} - FAILED: {e}")
        self.send_json({"message": "Stopping ankd service..."})

    def api_ank_manager_restart_server(self):
        """Graceful server restart via SIGHUP."""
        client_ip = self.client_address[0] if self.client_address else "unknown"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log(f"ANK_MANAGER: [RESTART-SERVER] {ts} from {client_ip} - Sending SIGHUP...")
        try:
            self.send_json({"message": "Server restarting..."})
            time.sleep(0.5)
            os.kill(os.getpid(), signal.SIGHUP)
            log(f"ANK_MANAGER: [RESTART-SERVER] {ts} from {client_ip} - SIGHUP sent successfully")
        except Exception as e:
            log(f"ANK_MANAGER: [RESTART-SERVER] {ts} from {client_ip} - FAILED: {e}")
            self.send_json({"error": str(e)}, 500)

    def api_ank_manager_restart_device(self):
        """Reboot the Android device."""
        client_ip = self.client_address[0] if self.client_address else "unknown"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log(f"ANK_MANAGER: [RESTART-DEVICE] {ts} from {client_ip} - Rebooting device...")
        self.send_json({"message": "Device rebooting..."})
        def _reboot():
            time.sleep(1)
            rc = os.system("svc power reboot 2>/dev/null || reboot 2>/dev/null || su -c reboot 2>/dev/null")
            if rc == 0:
                log(f"ANK_MANAGER: [RESTART-DEVICE] {ts} from {client_ip} - Reboot command sent successfully")
            else:
                log(f"ANK_MANAGER: [RESTART-DEVICE] {ts} from {client_ip} - Reboot command failed (rc={rc})")
        threading.Thread(target=_reboot, daemon=True).start()

    def api_ank_manager_uninstall(self):
        """Run the full uninstall.sh script."""
        client_ip = self.client_address[0] if self.client_address else "unknown"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log(f"ANK_MANAGER: [UNINSTALL] {ts} from {client_ip} - Starting full uninstall...")
        import subprocess
        if is_lite():
            log(f"ANK_MANAGER: [UNINSTALL] {ts} from {client_ip} - Rejected (lite mode)")
            self.send_json({"error": "Lite mode: uninstall is not available from the panel. Use the ANK Installer to uninstall ANK."}, 400)
            return
        # Find uninstall script
        candidates = [
            "/data/adb/modules/ank/scripts/uninstall.sh",
            os.path.join(ANK_DIR, "core", "uninstall.sh"),
            os.path.join(os.path.dirname(os.path.dirname(ANK_DIR)), "scripts", "uninstall.sh"),
            os.path.join(ANK_DIR, "scripts", "uninstall.sh"),
        ]
        script = None
        for c in candidates:
            if os.path.isfile(c):
                script = c
                break
        if not script:
            log(f"ANK_MANAGER: [UNINSTALL] {ts} from {client_ip} - FAILED: uninstall.sh not found")
            self.send_json({"error": "uninstall.sh not found"}, 404)
            return
        log(f"ANK_MANAGER: [UNINSTALL] {ts} from {client_ip} - Running {script}")
        self.send_json({"message": "Uninstalling ANK... device will reboot."})
        # Run in background — script will reboot device
        log_file = os.path.join(ANK_DIR, "logs", "uninstall.log")
        try:
            subprocess.Popen(["sh", script], stdout=open(log_file, "w"), stderr=subprocess.STDOUT)
            log(f"ANK_MANAGER: [UNINSTALL] {ts} from {client_ip} - Uninstall process started successfully")
        except Exception as e:
            log(f"ANK_MANAGER: [UNINSTALL] {ts} from {client_ip} - FAILED to start uninstall: {e}")

    def api_ank_manager_logs(self, parsed=None):
        """Get last N lines of ANK logs for real-time tail.

        Type mapping: "server" → logs/server.log (the LIVE server log — log() is
        print() and service.sh/start-server.sh redirect stdout to it),
        "service" → logs/service.log (legacy service wrapper log),
        "install" → logs/install.log, "uninstall" → logs/uninstall.log.
        Default type is "server".
        """
        params = parse_qs(parsed.query) if parsed else {}
        try:
            lines = max(1, min(int(params.get("lines", ["100"])[0]), 2000))
        except (ValueError, TypeError):
            lines = 100
        log_type = params.get("type", ["server"])[0]

        log_dir = os.path.join(ANK_DIR, "logs")
        log_type_files = {
            "server": "server.log",
            "service": "service.log",
            "install": "install.log",
            "uninstall": "uninstall.log",
        }
        fname = log_type_files.get(log_type, "server.log")
        log_file = os.path.join(log_dir, fname)

        if not os.path.isfile(log_file):
            if fname == "server.log":
                # Fall back to whatever this process is actually writing:
                # log() writes via print() to stdout; if stdout is redirected
                # to a file (service.sh/start-server.sh), tail that instead.
                alt = None
                try:
                    fd1 = os.readlink("/proc/self/fd/1")
                    if fd1 and not fd1.startswith(("pipe:", "socket:")) and os.path.isfile(fd1) and os.path.abspath(fd1) != os.path.abspath(log_file):
                        alt = fd1
                except (OSError, ValueError):
                    alt = None
                if alt:
                    try:
                        with open(alt, "r", errors="replace") as f:
                            tail = f.readlines()[-lines:]
                        self.send_json({"lines": [l.rstrip("\n") for l in tail], "type": log_type, "source": alt})
                        return
                    except OSError:
                        pass
                self.send_json({"lines": [f"[INFO] {log_file} not found yet — no live server log available (was the server started without output redirection?)"], "type": log_type})
            else:
                self.send_json({"lines": [], "type": log_type})
            return

        try:
            with open(log_file, "r", errors="replace") as f:
                all_lines = f.readlines()
            tail = all_lines[-lines:]
            self.send_json({"lines": [l.rstrip("\n") for l in tail], "type": log_type})
        except Exception as e:
            self.send_json({"lines": [f"[ERROR] {e}"], "type": log_type})

    def _generate_ankd_files(self, services_dir, rootfs, template_id, ssh_port):
        """Generate .ankd service files for containers created with older code."""
        os.makedirs(services_dir, exist_ok=True)
        # Always create sshd service
        sshd_ankd = os.path.join(services_dir, "01-sshd.ankd")
        if not os.path.exists(sshd_ankd):
            with open(sshd_ankd, "w") as f:
                f.write(f"NAME=sshd\nCMD=/usr/sbin/sshd -D -p {ssh_port} -o PasswordAuthentication=yes -o PermitRootLogin=yes -e\nDIR=/\nPID_FILE=/run/sshd.pid\nSTOP_SIGNAL=TERM\nRESTART_POLICY=always\nRESTART_DELAY=3\n")
        # Create service-specific .ankd based on template
        svc_map = {
            "nginx": ("nginx", "nginx", "/var/www/html", "8080"),
            "apache": ("apache", "httpd -D FOREGROUND", "/var/www/localhost/htdocs", "9090"),
            "php": ("php", "php82 -S 0.0.0.0:8000 -t /var/www/php", "/var/www/php", "8000"),
            "node": ("node", "node server.js", "/var/www/app", "3000"),
            "python": ("python", "python3 server.py", "/var/www/app", "5000"),
        }
        for key, (svc_name, cmd, svc_dir, port) in svc_map.items():
            if template_id.startswith(key):
                svc_ankd = os.path.join(services_dir, f"02-{svc_name}.ankd")
                if not os.path.exists(svc_ankd):
                    with open(svc_ankd, "w") as f:
                        f.write(f"NAME={svc_name}\nCMD={cmd}\nDIR={svc_dir}\nPORT={port}\nPID_FILE=/run/{svc_name}.pid\nSTOP_SIGNAL=TERM\nRESTART_POLICY=always\nRESTART_DELAY=3\n")
                # Inject daemon off + drop user directive for nginx
                if key == "nginx":
                    import re
                    nginx_conf = os.path.join(rootfs, "etc/nginx/nginx.conf")
                    if os.path.isfile(nginx_conf):
                        with open(nginx_conf) as fh:
                            content = fh.read()
                        if not content.startswith("daemon off"):
                            content = "daemon off;\n" + content
                        content = re.sub(r"^user\s+.*$", r"# ANK: \g<0>", content, flags=re.MULTILINE)
                        with open(nginx_conf, "w") as fh:
                            fh.write(content)
                break

    def _sync_sshd(self, config):
        """Start/stop/reconfigure sshd in ankfs based on config."""
        def _do():
            ankfs = os.path.join(ANK_DIR, "ankfs")
            ssh_enabled = config.get("ssh_enabled", False)
            ssh_port = config.get("ssh_port", 2200)
            ssh_pid = os.path.join(ankfs, "run/ankd/sshd.pid")
            sshd_conf = os.path.join(ankfs, "etc/ssh/sshd_config")
            if is_lite():
                if os.path.isfile(sshd_conf):
                    import re
                    with open(sshd_conf) as f:
                        content = f.read()
                    content = re.sub(r'^Port\s+\d+', f'Port {ssh_port}', content, flags=re.MULTILINE)
                    with open(sshd_conf, 'w') as f:
                        f.write(content)
                log(f"sshd config updated (lite, port {ssh_port})")
                return
            # Kill existing sshd
            try:
                with open(ssh_pid) as f:
                    old_pid = int(f.read().strip())
                os.kill(old_pid, 15)  # SIGTERM
                import time; time.sleep(1)
            except Exception:
                pass
            os.system(f"pkill -f 'sshd.*{ankfs}' 2>/dev/null")
            if not ssh_enabled:
                log(f"sshd disabled")
                return
            # Update port in sshd config
            if os.path.isfile(sshd_conf):
                import re
                with open(sshd_conf) as f:
                    content = f.read()
                content = re.sub(r'^Port\s+\d+', f'Port {ssh_port}', content, flags=re.MULTILINE)
                with open(sshd_conf, 'w') as f:
                    f.write(content)
            # Set root password from config
            password = config.get("password", "ank123")
            self._sync_ankfs_password(password)
            # Start sshd
            os.makedirs(os.path.join(ankfs, "run/ankd"), exist_ok=True)
            os.system(f"chroot {ankfs} /usr/sbin/sshd -D -p {ssh_port} -o PidFile=/run/ankd/sshd.pid </dev/null >/dev/null 2>&1 &")
            log(f"sshd started on port {ssh_port}")
        threading.Thread(target=_do, daemon=True).start()

    def _sync_ankfs_password(self, password):
        """Sync password to ankfs /etc/shadow for SSH auth.
        pfSense-style: both 'admin' and 'root' work with same password."""
        ankfs = os.path.join(ANK_DIR, "ankfs")
        shadow = os.path.join(ankfs, "etc/shadow")
        if not os.path.isfile(shadow):
            return
        try:
            import subprocess
            # Generate SHA-512 hash via chroot openssl (crypt compat)
            proc = subprocess.Popen(
                ["chroot", ankfs, "/usr/bin/openssl", "passwd", "-6", password],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            out, _ = proc.communicate(timeout=5)
            enc = out.decode().strip()
            if not enc or not enc.startswith("$6$"):
                return
            # Write shadow directly (sp_lstchg = today)
            import time
            sp_chg = int(time.time() / 86400)
            shadow_content = (
                f"root:{enc}:{sp_chg}:0:99999:7:::\n"
                f"admin:{enc}:{sp_chg}:0:99999:7:::\n"
            )
            with open(shadow, "w") as f:
                f.write(shadow_content)
            os.chmod(shadow, 0o644)
        except Exception:
            pass
        # Ensure admin user exists in /etc/passwd (uid 1000)
        passwd = os.path.join(ankfs, "etc/passwd")
        if os.path.isfile(passwd):
            try:
                with open(passwd, "r") as f:
                    lines = f.readlines()
                has_admin = any(l.startswith("admin:") for l in lines)
                if not has_admin:
                    with open(passwd, "a") as f:
                        f.write("admin:x:1000:1000::/root:/ankcoreshell.sh\n")
            except Exception:
                pass

    def api_uninstall(self):
        client_ip = self.client_address[0] if self.client_address else "unknown"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log(f"UNINSTALL: [UNINSTALL] {ts} from {client_ip} - Starting complete ANK removal...")
        def do_uninstall():
            log(f"UNINSTALL: [UNINSTALL] {ts} from {client_ip} - Stopping containers and cleaning up...")
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
                log(f"UNINSTALL: [UNINSTALL] {ts} from {client_ip} - cleanup error: {e}")
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
            log(f"UNINSTALL: [UNINSTALL] {ts} from {client_ip} - Removing Magisk module...")
            try:
                subprocess.run(["magisk", "--remove-module", "ank"], capture_output=True, timeout=15)
                log(f"UNINSTALL: [UNINSTALL] {ts} from {client_ip} - Magisk module removed successfully")
            except Exception as e:
                log(f"UNINSTALL: [UNINSTALL] {ts} from {client_ip} - magisk --remove-module error: {e}")
            log(f"UNINSTALL: [UNINSTALL] {ts} from {client_ip} - ANK removed. Reboot to complete.")
            import time; time.sleep(2)
            os._exit(0)
        threading.Thread(target=do_uninstall, daemon=True).start()
        self.send_json({"message": "Uninstalling ANK... Reboot to complete removal."})

    def api_get_mode(self):
        mode = get_mode()
        self.send_json({
            "mode": mode.get("mode", "shared_host"),
            "lite": is_lite(),
            "features": {
                "containers": True,
                "terminal": True,
                "files": True,
                "backups": True,
                "images": True,
                "stacks": True,
                "network_isolation": not is_lite(),
                "port_mapping": True,
                "resource_limits": not is_lite(),
                "port_proxy": is_lite(),
            }
        })

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
            "building": _building,
            "lite": is_lite(),
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
                    if size == 0:
                        try:
                            size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fn in os.walk(p) for f in fn)
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

    def api_all_images(self):
        """Unified images view: local images plus every online node's images, each tagged
        with which node it lives on."""
        result = []
        # Get local images (reuse api_list_images logic)
        images = []
        if os.path.exists(IMAGES_DIR):
            for img_name in os.listdir(IMAGES_DIR):
                if img_name == "ankfs" or img_name.startswith("alpine-"):
                    continue
                p = os.path.join(IMAGES_DIR, img_name)
                if os.path.isdir(p):
                    has_python = os.path.isfile(os.path.join(p, "usr/bin/python3"))
                    has_sh = os.path.isfile(os.path.join(p, "bin/sh"))
                    size = 0
                    try:
                        out = subprocess.run(["du", "-sb", p], capture_output=True, text=True, timeout=5)
                        size = int(out.stdout.split("\t")[0]) if out.returncode == 0 else 0
                    except Exception:
                        pass
                    if size == 0:
                        try:
                            size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fn in os.walk(p) for f in fn)
                        except Exception:
                            pass
                    images.append({
                        "name": img_name,
                        "complete": has_python and has_sh,
                        "has_python": has_python,
                        "size": size,
                        "size_human": self._fmt_size(size)
                    })
        for img in images:
            img = dict(img)
            img["node"] = "local"
            img["node_alias"] = "Local"
            result.append(img)
        nm = self._get_node_manager()
        if nm:
            try:
                for n in nm.list_nodes():
                    if n.get("status") != "online":
                        continue
                    try:
                        for img in (nm.get_node_images(n["id"]) or []):
                            img = dict(img)
                            img["node"] = n["id"]
                            img["node_alias"] = n.get("alias") or n["id"]
                            result.append(img)
                    except Exception as e:
                        log(f"[AGGREGATE] images on {n.get('id')} failed: {e}")
            except Exception as e:
                log(f"[AGGREGATE] node listing failed: {e}")
        self.send_json(result)

    def api_delete_image(self, name):
        if not name or name.startswith("/"):
            self.send_error(400, "Invalid image name")
            return
        image_dir = os.path.join(IMAGES_DIR, name)
        if not os.path.isdir(image_dir):
            self.send_error(404, f"Image '{name}' not found")
            return
        import shutil
        shutil.rmtree(image_dir)
        self.send_json({"message": f"Image '{name}' deleted"})

    def api_receive_image_upload(self):
        import tarfile, io
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error(400, "Empty body")
            return
        raw = self.rfile.read(content_length)
        try:
            tar = tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz")
        except Exception as e:
            self.send_error(400, f"Invalid tar.gz: {e}")
            return
        os.makedirs(IMAGES_DIR, exist_ok=True)
        images_real = os.path.realpath(IMAGES_DIR)
        extracted = []
        for member in tar.getmembers():
            if member.isdir():
                continue
            member_path = os.path.realpath(os.path.join(IMAGES_DIR, member.name))
            if not member_path.startswith(images_real):
                tar.close()
                self.send_error(400, f"TarSlip: path traversal detected in {member.name}")
                return
            top = member.name.split("/")[0]
            if top and top not in extracted:
                extracted.append(top)
            tar.extract(member, IMAGES_DIR)
        tar.close()
        self.send_json({"ok": True, "images": extracted, "count": len(extracted)})

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
                config = load_config()
                device = config.get("device_model", "")
                if not device:
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
            "node_name": config.get("node_name", ""),
            "enable_remote_management": config.get("enable_remote_management", False),
            "panel_port": PORT,
            "network": {
                "subnet": net.get("subnet", "10.20.30.0"),
                "gateway": net.get("gateway", "10.20.30.1"),
                "bridge": net.get("bridge", "ank0")
            },
            "device_free": f"{_disk_usage_cache['free']:.1f} GB" if _disk_usage_cache.get("free") else "-",
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
            out = os.popen(f'du -sk "{path}" 2>/dev/null').read().strip()
            size_kb = int(out.split()[0])
            size = size_kb * 1024
            if size > 1073741824:
                return f"{size/1073741824:.1f} GB"
            elif size > 1048576:
                return f"{size/1048576:.1f} MB"
            elif size > 1024:
                return f"{size/1024:.0f} KB"
            return f"{size} B"
        except Exception:
            return "-"

    def api_system_cache(self):
        rootfs_size = "-"
        containers_size = "-"
        total_size = "-"
        try:
            rootfs_size = self._du_human(os.path.join(ANK_DIR, "ankfs"))
            containers_size = self._du_human(os.path.join(ANK_DIR, "containers"))
            total_size = self._du_human(ANK_DIR)
        except Exception:
            pass
        self.send_json({
            "rootfs_size": rootfs_size,
            "containers_size": containers_size,
            "total_size": total_size
        })

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
        if getattr(AnkHandler, "_stack_manager_instance", None) is not None:
            return AnkHandler._stack_manager_instance
        try:
            from stack_manager import StackManager
            AnkHandler._stack_manager_instance = StackManager()
            return AnkHandler._stack_manager_instance
        except Exception:
            return None

    _stack_manager_instance = None
    _backup_manager_instance = None

    def api_list_stacks(self):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"stacks": [], "error": "stack_manager not available"})
            return
        stacks = sm.list_stacks()
        self.send_json({"stacks": stacks})

    def api_all_stacks(self):
        """Unified stacks view: local stacks plus every online node's stacks, each tagged
        with which node it lives on."""
        result = []
        sm = self._get_stack_manager()
        try:
            for s in (sm.list_stacks() if sm else []):
                s = dict(s)
                s["node"] = "local"
                s["node_alias"] = "Local"
                result.append(s)
        except Exception as e:
            log(f"[AGGREGATE] local stacks failed: {e}")
        nm = self._get_node_manager()
        if nm:
            try:
                from node_proxy import NodeProxy
                proxy = NodeProxy(nm)
                for n in nm.list_nodes():
                    if n.get("status") != "online":
                        continue
                    try:
                        for s in (proxy.get_stacks(n["id"]) or []):
                            s = dict(s)
                            s["node"] = n["id"]
                            s["node_alias"] = n.get("alias") or n["id"]
                            result.append(s)
                    except Exception as e:
                        log(f"[AGGREGATE] stacks on {n.get('id')} failed: {e}")
            except Exception as e:
                log(f"[AGGREGATE] node_proxy unavailable: {e}")
        self.send_json({"stacks": result})

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
        lines = []
        stack_config = sm._load_stack_config(name)
        if stack_config:
            for cname in stack_config.get("containers", []):
                log_path = os.path.join(CONTAINERS_DIR, cname, "logs", "ankd.log")
                if os.path.exists(log_path):
                    try:
                        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                            lines.extend(f.readlines()[-50:])
                    except Exception:
                        pass
        self.send_json({"lines": lines[-200:]})

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
        if not isinstance(data, dict):
            self.send_json({"error": "Request body must be a JSON object"}, 400)
            return
        name = data.get("name", "").strip()
        template = data.get("template", data.get("image", "nginx"))
        ankfile = data.get("ankfile", "")
        if not name:
            self.send_json({"error": "name required"}, 400)
            return
        if len(name) > 64:
            self.send_json({"error": "name must be 64 characters or less"}, 400)
            return
        if not all(c.isalnum() or c in "-_" for c in name):
            self.send_json({"error": "name must contain only alphanumeric characters, hyphens, or underscores"}, 400)
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
                "load_balance": data.get("load_balance", "least_conn"),
                "shared_volume": data.get("shared_volume", False),
                "threshold_up": data.get("threshold_up", 100),
                "threshold_down": data.get("threshold_down", 20),
                "scale_up_after": data.get("scale_up_after", 30),
                "scale_down_after": data.get("scale_down_after", 120),
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
        try:
            created = sm.scale_up(name, count)
            self.send_json({"status": "ok", "created": created})
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)

    def api_scale_down_stack(self, name, data):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"error": "stack_manager not available"}, 500)
            return
        count = data.get("count", 1)
        try:
            removed = sm.scale_down(name, count)
            self.send_json({"status": "ok", "removed": removed})
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)

    def api_delete_stack(self, name):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"error": "stack_manager not available"}, 500)
            return
        try:
            sm.delete_stack(name)
            self.send_json({"status": "ok"})
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)

    def api_update_stack(self, name, data):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"error": "stack_manager not available"}, 500)
            return
        try:
            result = sm.update_stack(name, data)
            self.send_json(result)
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)

    def api_rolling_update(self, name, data):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"error": "stack_manager not available"}, 500)
            return
        try:
            new_template = data.get("template")
            new_ankfile = data.get("ankfile")
            result = sm.rolling_update(name, new_template, new_ankfile)
            self.send_json(result)
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)

    def api_start_healing(self, name):
        sm = self._get_stack_manager()
        if not sm:
            self.send_json({"error": "stack_manager not available"}, 500)
            return
        try:
            sm.start_healing(name)
            self.send_json({"status": "ok", "message": f"Healing started for '{name}'"})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    # ============================================================
    # Backups API
    # ============================================================

    def _get_backup_manager(self):
        if AnkHandler._backup_manager_instance is not None:
            return AnkHandler._backup_manager_instance
        try:
            from backup_manager import BackupManager
            bm = BackupManager()
            AnkHandler._backup_manager_instance = bm
            # Scheduler only starts once, on first access
            try:
                bm.start_scheduler(interval=60)
                log("[BACKUP] Scheduler started (60s interval)")
            except Exception as se:
                log(f"[BACKUP] Scheduler start failed: {se}")
            return bm
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

    def api_create_backup_routine(self, data):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"error": "backup_manager not available"}, 500)
            return
        if not isinstance(data, dict):
            self.send_json({"error": "Request body must be a JSON object"}, 400)
            return
        name = data.get("name", "").strip()
        if not name:
            self.send_json({"error": "name required"}, 400)
            return
        if len(name) > 128:
            self.send_json({"error": "name must be 128 characters or less"}, 400)
            return
        config = {
            "name": name,
            "source_type": data.get("source_type", "container_full"),
            "containers": data.get("containers", []),
            "nodes": data.get("nodes", []),
            "custom_paths": data.get("custom_paths", {}),
            "backup_mode": data.get("backup_mode", "full"),
            "encryption": data.get("encryption", "none"),
            "immutable": data.get("immutable", False),
            "remote": {
                "host": data.get("remote_host", data.get("host", "")),
                "port": int(data.get("remote_port", data.get("port", 22))),
                "user": data.get("ssh_user", data.get("user", "root")),
                "password": data.get("ssh_pass", data.get("password", "")),
                "path": data.get("remote_path", data.get("path", "/backups/ank")),
            },
            "schedule": data.get("schedule", ""),
            "retention_days": int(data.get("retention", data.get("retention_days", 30))),
        }
        result = bm.create_routine(config)
        try:
            ensure = bm.ensure_remote_path(config["remote"])
            if ensure is not None:
                result["remote_path_ensured"] = ensure.get("ok", False)
                if not ensure.get("ok"):
                    result["remote_path_warning"] = ensure.get("reason", "could not create remote path")
        except Exception as e:
            result["remote_path_warning"] = str(e)
        self.send_json(result)

    def api_execute_backup(self, routine_id):
        try:
            bm = self._get_backup_manager()
            if not bm:
                self.send_json({"error": "backup_manager not available"}, 500)
                return
            result = bm.run_backup(routine_id)
            self.send_json(result)
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    def api_backup_history(self, routine_id=None, limit=50):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"history": []})
            return
        entries = bm.get_history(routine_id, limit)
        self.send_json({"history": entries})

    def api_backup_battery(self):
        from backup_runner import get_battery_status
        self.send_json(get_battery_status())

    def api_backup_test_connection(self, data):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"error": "backup_manager not available"}, 500)
            return
        if not isinstance(data, dict):
            data = {}
        try:
            port = int(data.get("remote_port", data.get("port", 22)))
        except (TypeError, ValueError):
            port = 22
        remote = {
            "host": str(data.get("remote_host", data.get("host", ""))).strip(),
            "port": port,
            "user": data.get("ssh_user", data.get("user", "root")),
            "password": data.get("ssh_pass", data.get("password", data.get("pass", ""))),
        }
        try:
            result = bm.test_connection(remote)
            if isinstance(result, dict):
                ok = bool(result.get("ok"))
                self.send_json({
                    "connected": ok,
                    "reason": result.get("reason", "connected" if ok else "connection failed"),
                    "exit_code": result.get("exit_code"),
                    "stderr_tail": result.get("stderr_tail", ""),
                })
            else:
                ok = bool(result)
                self.send_json({"connected": ok, "reason": "connected" if ok else "connection failed"})
        except Exception as e:
            self.send_json({"connected": False, "reason": f"test failed: {e}", "error": str(e)})

    def api_backup_browse(self, routine_id, query):
        from urllib.parse import parse_qs
        params = parse_qs(query)
        remote_path = params.get("path", ["/"])[0]
        try:
            bm = self._get_backup_manager()
            if not bm:
                self.send_json({"error": "backup_manager not available"}, 500)
                return
            routine = bm.get_routine(routine_id)
            if not routine:
                self.send_json({"error": "Routine not found"}, 404)
                return
            remote = routine.get("remote", {})
            files = bm.list_remote_files(remote, remote_path)
            self.send_json({"files": files, "path": remote_path})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_backup_preview(self, routine_id, data):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"error": "backup_manager not available"}, 500)
            return
        routine = bm.get_routine(routine_id)
        if not routine:
            self.send_json({"error": "Routine not found"}, 404)
            return
        remote_name = data.get("file", "")
        if not remote_name:
            self.send_json({"error": "file required"}, 400)
            return
        try:
            result = bm.preview_backup(routine.get("remote", {}), remote_name)
            self.send_json(result)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_backup_log(self, history_id):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"error": "backup_manager not available"}, 500)
            return
        log_content = bm.get_logs(history_id)
        self.send_json({"log": log_content, "id": history_id})

    def api_backup_restore(self, routine_id, data):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"error": "backup_manager not available"}, 500)
            return
        routine = bm.get_routine(routine_id)
        if not routine:
            self.send_json({"error": "Routine not found"}, 404)
            return
        remote_name = data.get("file", "")
        if not remote_name:
            self.send_json({"error": "file required"}, 400)
            return
        try:
            local_path = bm.restore_from_remote(routine.get("remote", {}), remote_name)
            self.send_json({"restored_to": local_path})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_backup_rename(self, routine_id, data):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"error": "backup_manager not available"}, 500)
            return
        routine = bm.get_routine(routine_id)
        if not routine:
            self.send_json({"error": "Routine not found"}, 404)
            return
        old_name = data.get("old_name", "")
        new_name = data.get("new_name", "")
        if not old_name or not new_name:
            self.send_json({"error": "old_name and new_name required"}, 400)
            return
        try:
            ok = bm.rename_remote_file(routine.get("remote", {}), old_name, new_name)
            self.send_json({"renamed": ok})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_backup_delete_file(self, routine_id, data):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"error": "backup_manager not available"}, 500)
            return
        routine = bm.get_routine(routine_id)
        if not routine:
            self.send_json({"error": "Routine not found"}, 404)
            return
        remote_name = (data or {}).get("file", "")
        if not remote_name:
            self.send_json({"error": "file required"}, 400)
            return
        try:
            ok = bm.delete_remote_file(routine.get("remote", {}), remote_name)
            self.send_json({"deleted": ok})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_delete_backup_routine(self, routine_id):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"error": "backup_manager not available"}, 500)
            return
        if not bm.get_routine(routine_id):
            self.send_json({"error": "Routine not found"}, 404)
            return
        try:
            ok = bm.delete_routine(routine_id)
            self.send_json({"success": ok})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_update_backup_routine(self, routine_id, data):
        bm = self._get_backup_manager()
        if not bm:
            self.send_json({"error": "backup_manager not available"}, 500)
            return
        if not isinstance(data, dict):
            self.send_json({"error": "Request body must be a JSON object"}, 400)
            return
        routine = bm.get_routine(routine_id)
        if not routine:
            self.send_json({"error": "Routine not found"}, 404)
            return
        updates = {}
        for key in ("name", "schedule", "containers", "source_type", "backup_mode", "encryption", "immutable", "enabled"):
            if key in data:
                updates[key] = data[key]
        if "retention" in data or "retention_days" in data:
            try:
                updates["retention_days"] = int(data.get("retention", data.get("retention_days", routine.get("retention_days", 30))))
            except (TypeError, ValueError):
                self.send_json({"error": "retention must be an integer"}, 400)
                return
        if "remote" in data and isinstance(data["remote"], dict):
            remote = dict(routine.get("remote", {}))
            remote.update(data["remote"])
            updates["remote"] = remote
        elif any(k in data for k in ("remote_host", "remote_port", "remote_path", "ssh_user", "ssh_pass", "host", "port", "path", "user", "password")):
            remote = dict(routine.get("remote", {}))
            if "remote_host" in data or "host" in data:
                remote["host"] = data.get("remote_host", data.get("host", remote.get("host", "")))
            if "remote_port" in data or "port" in data:
                try:
                    remote["port"] = int(data.get("remote_port", data.get("port", remote.get("port", 22))))
                except (TypeError, ValueError):
                    self.send_json({"error": "port must be an integer"}, 400)
                    return
            if "remote_path" in data or "path" in data:
                remote["path"] = data.get("remote_path", data.get("path", remote.get("path", "/backups/ank")))
            if "ssh_user" in data or "user" in data:
                remote["user"] = data.get("ssh_user", data.get("user", remote.get("user", "root")))
            if "ssh_pass" in data or "password" in data:
                remote["password"] = data.get("ssh_pass", data.get("password", remote.get("password", "")))
            updates["remote"] = remote
        if not updates:
            self.send_json({"error": "No fields to update"}, 400)
            return
        try:
            result = bm.update_routine(routine_id, updates)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)
            return
        if not result:
            self.send_json({"error": "Routine not found"}, 404)
            return
        self.send_json(result)

    # ============================================================
    # Nodes API
    # ============================================================

    _node_manager_instance = None

    def _get_node_manager(self):
        if AnkHandler._node_manager_instance is not None:
            return AnkHandler._node_manager_instance
        try:
            from node_manager import NodeManager
            nm = NodeManager()
            AnkHandler._node_manager_instance = nm
            nm.start_heartbeat(30)
            log("[NODE] Heartbeat started")
            return nm
        except Exception as e:
            log(f"[NODE] Failed to start NodeManager: {e}")
            return None

    def api_list_nodes(self):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"nodes": []})
            return
        nodes = nm.list_nodes()
        self.send_json({"nodes": nodes})

    def api_get_manager(self):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"manager": None})
            return
        info = nm.get_manager_info()
        self.send_json({"manager": info})

    def api_revoke_manager(self):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"ok": False, "error": "NodeManager unavailable"}, 500)
            return
        ok = nm.revoke_manager()
        self.send_json({"ok": ok})

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
        if not isinstance(data, dict):
            self.send_json({"error": "Request body must be a JSON object"}, 400)
            return
        ip = data.get("ip", "").strip()
        if not ip:
            self.send_json({"error": "ip required"}, 400)
            return
        if len(ip) > 255:
            self.send_json({"error": "ip address too long"}, 400)
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
    # Pairing API (Manager side)
    # ============================================================

    def api_send_pairing_request(self, data):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        ip = data.get("ip", "").strip()
        if not ip:
            self.send_json({"error": "ip required"}, 400)
            return
        try:
            data["manager_ip"] = self.client_address[0]
            node = nm.send_pairing_request(data)
            self.send_json(node)
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    # ============================================================
    # Pairing API (Remote side)
    # ============================================================

    def api_receive_pairing_request(self, data):
        client_ip = self.client_address[0] if self.client_address else "unknown"
        if not _check_rate_limit(f"pair:{client_ip}", record=False):
            self.send_json({"error": "Too many pairing requests"}, 429)
            return
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        if not nm.is_remote_management_enabled():
            self.send_json({"error": "Remote management is disabled"}, 403)
            return
        try:
            req = nm.receive_pairing_request(data)
        except Exception:
            _record_failed_login(f"pair:{client_ip}")
            raise
        self.send_json(req)

    def api_list_pairing_requests(self):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"requests": []})
            return
        requests = nm.list_pairing_requests()
        self.send_json({"requests": requests})

    def api_approve_pairing(self, req_id):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        result = nm.approve_pairing_request(req_id)
        if result:
            self.send_json(result)
        else:
            self.send_json({"error": "Request not found or already processed"}, 404)

    def api_reject_pairing(self, req_id):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        result = nm.reject_pairing_request(req_id)
        if result:
            self.send_json({"ok": True, "message": "Pairing rejected"})
        else:
            self.send_json({"error": "Request not found"}, 404)

    # ============================================================
    # Remote node container management
    # ============================================================

    def api_node_images(self, node_id):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"images": []})
            return
        images = nm.get_node_images(node_id)
        self.send_json(images if images else [])

    def api_node_status(self, node_id):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        status = nm.get_node_status(node_id)
        self.send_json(status if status else {})

    def api_node_system_info(self, node_id):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        info = nm.get_node_system_info(node_id)
        self.send_json(info if info else {})

    def api_node_restart(self, node_id):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        try:
            result = nm._node_api_post(node_id, "/api/system/restart-device", {})
            self.send_json(result if result else {"message": "Restart sent"})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_node_logs(self, node_id):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        try:
            logs = nm.get_node_logs(node_id)
            self.send_json(logs if logs else {"lines": []})
        except Exception as e:
            self.send_json({"lines": [], "error": str(e)})

    def api_node_container_logs(self, node_id, container_name):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"logs": []})
            return
        logs = nm.get_container_logs_on_node(node_id, container_name)
        self.send_json(logs if logs else {"logs": []})

    def api_node_container_detail(self, node_id, container_name):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        try:
            container = nm._node_api_get(node_id, f"/api/containers/{container_name}")
            if container:
                container["node"] = node_id
                node = nm.get_node(node_id)
                container["node_alias"] = node.get("alias", node_id) if node else node_id
            logs = nm._node_api_get(node_id, f"/api/containers/{container_name}/logs") or {}
            container["log"] = logs.get("logs", "")
            self.send_json(container)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_node_container_services(self, node_id, container_name):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"services": []})
            return
        try:
            result = nm._node_api_get(node_id, f"/api/containers/{container_name}/services")
            self.send_json(result if result else {"services": []})
        except Exception as e:
            self.send_json({"services": [], "error": str(e)})

    def api_node_container_health(self, node_id, container_name):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        try:
            result = nm._node_api_get(node_id, f"/api/containers/{container_name}/health")
            self.send_json(result if result else {"status": "unknown"})
        except Exception as e:
            self.send_json({"status": "unknown", "error": str(e)})

    def api_node_container_action(self, node_id, container_name, action):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        try:
            if action == "start":
                result = nm.start_container_on_node(node_id, container_name)
            elif action == "stop":
                result = nm.stop_container_on_node(node_id, container_name)
            elif action == "restart":
                result = nm.restart_container_on_node(node_id, container_name)
            else:
                self.send_json({"error": f"Unknown action: {action}"}, 400)
                return
            self.send_json(result if result else {"message": f"Container {action} sent"})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def api_node_container_exec(self, node_id, container_name, data):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        cmd = data.get("command", "")
        if not cmd:
            self.send_json({"error": "command required"}, 400)
            return
        result = nm.exec_container_on_node(node_id, container_name, cmd)
        self.send_json(result if result else {"stdout": "", "stderr": "No response", "code": 1})

    def api_node_container_delete(self, node_id, container_name):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        result = nm.delete_container_on_node(node_id, container_name)
        self.send_json(result if result else {"message": f"Container '{container_name}' delete sent"})

    def api_node_image_pull(self, node_id, data):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        version = data.get("version", "")
        if not version:
            self.send_json({"error": "version required"}, 400)
            return
        result = nm.pull_image_on_node(node_id, version)
        self.send_json(result if result else {"message": "Pull started"})

    def api_node_image_transfer(self, node_id, data):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        image_name = data.get("image", "")
        if not image_name:
            self.send_json({"error": "image name required"}, 400)
            return
        result = nm.transfer_image_to_node(node_id, image_name)
        self.send_json(result)

    def api_node_container_create(self, node_id, data):
        nm = self._get_node_manager()
        if not nm:
            self.send_json({"error": "node_manager not available"}, 500)
            return
        name = data.get("name", "")
        if not name:
            self.send_json({"error": "Container name required"}, 400)
            return
        template_id = data.get("template", "")
        if template_id:
            template = None
            for t in self.IMAGE_TEMPLATES:
                if t["id"] == template_id:
                    template = t
                    break
            if template:
                image = data.get("image", "")
                if not image or image == template_id:
                    data["image"] = template["image"]
                data["template"] = template_id
        result = nm.create_container_on_node(node_id, data)
        if not result:
            self.send_json({"message": f"Container '{name}' creation sent"})
            return
        if isinstance(result, dict) and result.get("error"):
            code = result.get("status_code")
            if not isinstance(code, int) or code < 400:
                code = 502
            self.send_json(result, code)
            return
        self.send_json(result, result.get("status_code", 200) if isinstance(result, dict) else 200)

    # ============================================================
    # System Dashboard (aggregate across nodes)
    # ============================================================

    def api_system_dashboard(self):
        nm = self._get_node_manager()
        sm = self._get_stack_manager()

        # Local stats
        local_containers = 0
        local_running = 0
        local_stopped = 0
        try:
            containers = self._list_containers_dict()
            local_containers = len(containers)
            local_running = sum(1 for c in containers if c.get("status") == "running")
            local_stopped = local_containers - local_running
        except Exception:
            pass

        local_stacks = 0
        try:
            stacks = sm.list_stacks() if sm else []
            local_stacks = len(stacks)
        except Exception:
            pass

        # Node data + aggregated cluster stats
        is_manager = False
        cluster_cpu_sum = 0.0
        cluster_cpu_count = 0
        cluster_cores = 0
        cluster_ram_used = 0
        cluster_ram_total = 0
        cluster_ram_pct_sum = 0.0
        cluster_disk_used = 0
        cluster_disk_total = 0
        cluster_disk_pct_sum = 0.0
        cluster_containers = local_containers
        cluster_containers_running = local_running
        cluster_stacks = local_stacks
        nodes_list = []

        try:
            nodes = nm.list_nodes() if nm else []
            is_manager = nm is not None
            for n in nodes:
                is_online = n.get("status") == "online"
                n_cores = n.get("cpu_cores", 0) if is_online else 0
                n_cpu = n.get("cpu_percent", 0) if is_online else 0
                n_ram_total = n.get("mem_total_gb", 0) if is_online else 0
                n_ram_used = n.get("mem_used_gb", 0) if is_online else 0
                n_disk_total = n.get("disk_total_gb", 0) if is_online else 0
                n_disk_used = n.get("disk_used_gb", 0) if is_online else 0
                nodes_list.append({
                    "id": n.get("id", ""),
                    "hostname": n.get("hostname", ""),
                    "alias": n.get("alias", ""),
                    "status": n.get("status", "unknown"),
                    "containers": n.get("containers", 0),
                    "containers_running": n.get("containers_running", 0),
                    "cpu_cores": n_cores,
                    "cpu_percent": n_cpu,
                    "mem_used_gb": n_ram_used,
                    "mem_total_gb": n_ram_total,
                    "disk_used_gb": n_disk_used,
                    "disk_total_gb": n_disk_total,
                    "stacks_count": n.get("stacks_count", 0) if is_online else 0,
                })
                if is_online:
                    cluster_cores += n_cores
                    cluster_cpu_sum += n_cpu
                    cluster_cpu_count += 1
                    cluster_ram_used += n_ram_used
                    cluster_ram_total += n_ram_total
                    if n_ram_total > 0:
                        cluster_ram_pct_sum += (n_ram_used / n_ram_total) * 100
                    cluster_disk_used += n_disk_used
                    cluster_disk_total += n_disk_total
                    if n_disk_total > 0:
                        cluster_disk_pct_sum += (n_disk_used / n_disk_total) * 100
                    cluster_containers += n.get("containers", 0) or 0
                    cluster_containers_running += n.get("containers_running", 0) or 0
                    cluster_stacks += n.get("stacks_count", 0) or 0
        except Exception:
            pass

        # Local device resource usage
        local_cpu = _cpu_usage_cache
        local_ram_used = 0
        local_ram_total = 0
        local_cores = 0
        try:
            with open("/proc/stat", "r") as f:
                for line in f:
                    if line.startswith("processor"):
                        local_cores += 1
        except Exception:
            pass
        if local_cores == 0:
            try:
                import multiprocessing
                local_cores = multiprocessing.cpu_count() or 1
            except Exception:
                local_cores = os.cpu_count() or 1
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split()
                    if parts[0] == "MemTotal:":
                        local_ram_total = int(parts[1]) // 1024
                    elif parts[0] == "MemAvailable:":
                        local_ram_used = local_ram_total - (int(parts[1]) // 1024)
        except Exception:
            pass
        disk_info = _get_disk_usage()

        # Cluster averages
        cluster_cores += local_cores
        local_ram_used_gb = local_ram_used / 1024.0
        local_ram_total_gb = local_ram_total / 1024.0
        cluster_ram_used += local_ram_used_gb
        cluster_ram_total += local_ram_total_gb
        cluster_disk_used += disk_info.get("used", 0)
        cluster_disk_total += disk_info.get("total", 0)
        if local_ram_total > 0:
            cluster_ram_pct_sum += (local_ram_used / local_ram_total) * 100
        cluster_cpu_count += 1
        cluster_cpu_sum += local_cpu
        if disk_info.get("total", 0) > 0:
            cluster_disk_pct_sum += (disk_info.get("used", 0) / disk_info.get("total", 1)) * 100

        node_count = max(cluster_cpu_count, 1)
        cluster_avg_cpu = round(cluster_cpu_sum / node_count, 1)
        cluster_avg_ram_pct = round(cluster_ram_pct_sum / node_count, 1) if cluster_cpu_count > 0 else 0
        cluster_avg_disk_pct = round(cluster_disk_pct_sum / node_count, 1) if cluster_cpu_count > 0 else 0

        dashboard = {
            "is_manager": is_manager,
            "local": {
                "containers_total": local_containers,
                "containers_running": local_running,
                "containers_stopped": local_stopped,
                "stacks": local_stacks,
                "cpu_cores": local_cores,
                "cpu_percent": local_cpu,
                "ram_used_mb": local_ram_used,
                "ram_total_mb": local_ram_total,
                "disk_used_gb": disk_info.get("used", 0),
                "disk_total_gb": disk_info.get("total", 0),
            },
            "cluster": {
                "containers_total": cluster_containers,
                "containers_running": cluster_containers_running,
                "stacks": cluster_stacks,
                "cpu_cores": cluster_cores,
                "cpu_percent": cluster_avg_cpu,
                "ram_used_gb": round(cluster_ram_used, 2),
                "ram_total_gb": round(cluster_ram_total, 2),
                "ram_percent": cluster_avg_ram_pct,
                "disk_used_gb": round(cluster_disk_used, 2),
                "disk_total_gb": round(cluster_disk_total, 2),
                "disk_percent": cluster_avg_disk_pct,
                "nodes_count": node_count,
            } if is_manager else None,
            "nodes": nodes_list,
        }
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
        ".woff": "font/woff",
        ".woff2": "font/woff2",
    }

    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        if ".." in path or "\x00" in path:
            self.send_error(403, "Forbidden")
            return
        file_path = os.path.realpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        static_real = os.path.realpath(STATIC_DIR)
        if not file_path.startswith(static_real + os.sep) and file_path != static_real:
            self.send_error(403, "Forbidden")
            return
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
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
        self.send_header("Content-Length", str(len(content)))
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
        except (ConnectionResetError, BrokenPipeError, OSError):
            self.close_connection = True
        except TimeoutError:
            self.close_connection = True
        except Exception as e:
            try:
                log(f"[ERROR] Request handling error: {type(e).__name__}: {e}")
            except Exception:
                pass
            self.close_connection = True

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


def _status_poller():
    """Background thread: periodically check all containers and recover status.
    If a container has status 'running' but TCP checks fail, it will eventually
    flip to 'stopped'. But if a container has status 'stopped' and TCP checks
    succeed, we flip it BACK to 'running'. This prevents the one-way ratchet."""
    import time
    while True:
        try:
            time.sleep(20)  # Check every 20 seconds
            if not os.path.isdir(CONTAINERS_DIR):
                continue
            for name in os.listdir(CONTAINERS_DIR):
                cfg_path = os.path.join(CONTAINERS_DIR, name, "config.json")
                if not os.path.isfile(cfg_path):
                    continue
                try:
                    config = load_container_config(name)
                    if not config:
                        continue
                    status = config.get("status", "")
                    # Only act on containers that claim to be running or stopped
                    # Skip building, starting, stopping, failed
                    if status not in ("running", "stopped"):
                        continue
                    is_alive = check_container_running(name)
                    if status == "running" and not is_alive:
                        # Container claims running but TCP checks fail
                        # Use debounce — don't flip immediately
                        if should_mark_stopped(name):
                            config["status"] = "stopped"
                            config["pid"] = None
                            save_container_config(name, config)
                            note_container_stopped(name)
                            log(f"[POLLER] {name}: marked stopped (TCP checks failed)")
                    elif status == "stopped" and is_alive:
                        # Container claims stopped but TCP checks succeed — recover!
                        config["status"] = "running"
                        save_container_config(name, config)
                        note_container_started(name)
                        log(f"[POLLER] {name}: recovered to running (TCP checks pass)")
                except Exception as e:
                    log(f"[POLLER] Error checking {name}: {e}")
        except Exception as e:
            log(f"[POLLER] Fatal: {e}")


def main():
    def _handle_sigusr1(*_):
        """SIGUSR1 = graceful stop (Manager sends this)."""
        print("[SIGNAL] SIGUSR1 received — stopping server...")
        sys.exit(0)

    def _handle_sighup(*_):
        """SIGHUP = restart. Delegates to restart-server.sh which stops,
        waits, then starts the server cleanly."""
        print("[SIGNAL] SIGHUP received — launching restart script...")
        import subprocess
        candidates = [
            "/data/adb/modules/ank/scripts/restart-server.sh",
            os.path.join(ANK_DIR, "core", "restart-server.sh"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts", "restart-server.sh"),
            os.path.join(ANK_DIR, "restart-server.sh"),
        ]
        for script in candidates:
            if os.path.isfile(script):
                subprocess.Popen(
                    ["sh", script],
                    stdout=open(os.path.join(ANK_DIR, "logs", "restart.log"), "w"),
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                print(f"[SIGNAL] Restart script launched: {script}")
                time.sleep(2)
                os._exit(0)
        print("[SIGNAL] No restart script found — cannot restart")

    def _handle_sigusr2(*_):
        """SIGUSR2 = full uninstall (runs uninstall.sh)."""
        print("[SIGNAL] SIGUSR2 received — running uninstall script...")
        import subprocess
        uninstall_script = os.path.join(os.path.dirname(ANK_DIR), "ank", "scripts", "uninstall.sh")
        # Fallback: try known locations
        for candidate in [
            uninstall_script,
            "/data/adb/modules/ank/scripts/uninstall.sh",
            os.path.join(ANK_DIR, "core", "uninstall.sh"),
            os.path.join(ANK_DIR, "uninstall.sh"),
        ]:
            if os.path.isfile(candidate):
                subprocess.Popen(["sh", candidate], stdout=open(os.path.join(ANK_DIR, "logs", "uninstall.log"), "w"), stderr=subprocess.STDOUT)
                return
        print("[SIGNAL] No uninstall script found")

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, _handle_sigusr1)
    signal.signal(signal.SIGUSR1, _handle_sigusr1)
    signal.signal(signal.SIGUSR2, _handle_sigusr2)
    signal.signal(signal.SIGHUP, _handle_sighup)
    print(f"Ank Container Engine v2.0.0")
    print(f"Starting server on 0.0.0.0:{PORT}...")

    # Ensure server directory is in sys.path for module imports
    _server_dir = os.path.dirname(os.path.abspath(__file__))
    if _server_dir not in sys.path:
        sys.path.insert(0, _server_dir)

    # Start auto-scaling orchestrator (shares the singleton StackManager)
    try:
        from ank_orchestrator import Orchestrator as _Orchestrator
        if AnkHandler._stack_manager_instance is None:
            from stack_manager import StackManager as _SMCls
            AnkHandler._stack_manager_instance = _SMCls()
        _sm = AnkHandler._stack_manager_instance
        _orch = _Orchestrator(_sm)
        _orch.start(interval=10)
        print("Orchestrator started (auto-scaling enabled)")
        try:
            _sm.start_monitoring(interval=30)
            print("Stack auto-scale monitor started (30s interval)")
        except Exception as _me:
            print(f"Stack monitor not started: {_me}")
    except Exception as _oe:
        print(f"Orchestrator not started: {_oe}")

    # Start backup scheduler singleton (interval=60s)
    try:
        from backup_manager import BackupManager as _BMCls
        if AnkHandler._backup_manager_instance is None:
            _bm = _BMCls()
            AnkHandler._backup_manager_instance = _bm
            _bm.start_scheduler(interval=60)
            print("Backup scheduler started (60s interval)")
        else:
            AnkHandler._backup_manager_instance.start_scheduler(interval=60)
            print("Backup scheduler started (60s interval)")
    except Exception as _be:
        print(f"Backup scheduler not started: {_be}")

    # Start background status poller (recovers stopped→running when TCP checks pass)
    _poller = threading.Thread(target=_status_poller, daemon=True)
    _poller.start()
    print("Status poller started (20s interval)")

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

def _cli_command():
    """Handle CLI subcommands: ankengine.startserver, ankengine.stopserver, ankengine.restartserver."""
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if not arg.startswith("ankengine."):
        return False

    pid_file = os.path.join(ANK_DIR, "logs", "server.pid")

    def _read_pid():
        try:
            with open(pid_file, "r") as f:
                pid = f.read().strip()
            if pid and pid.isdigit():
                return int(pid)
        except Exception:
            pass
        return None

    cmd = arg.split(".", 1)[1] if "." in arg else ""

    if cmd == "startserver":
        return False  # let main() run normally

    if cmd == "stopserver":
        pid = _read_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGUSR1)
                print(f"[CLI] Sent SIGUSR1 to PID {pid} — server stopping")
            except ProcessLookupError:
                print(f"[CLI] PID {pid} not found — server already stopped")
            except PermissionError:
                print(f"[CLI] No permission to signal PID {pid}")
            except Exception as e:
                print(f"[CLI] Error sending signal: {e}")
        else:
            print("[CLI] No PID found — server not running")
        sys.exit(0)

    if cmd == "restartserver":
        pid = _read_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGHUP)
                print(f"[CLI] Sent SIGHUP to PID {pid} — server restarting")
            except ProcessLookupError:
                print(f"[CLI] PID {pid} not found — server not running")
            except PermissionError:
                print(f"[CLI] No permission to signal PID {pid}")
            except Exception as e:
                print(f"[CLI] Error sending signal: {e}")
        else:
            print("[CLI] No PID found — server not running")
        sys.exit(0)

    print(f"[CLI] Unknown command: {arg}")
    sys.exit(1)


if __name__ == "__main__":
    if _cli_command() is False:
        main()

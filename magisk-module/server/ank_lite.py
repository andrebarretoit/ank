#!/usr/bin/env python3
"""
ANK Lite Engine — Non-root container management via PRoot.
Replaces container.sh + iptables for non-rooted devices.
"""

import os
import json
import time
import signal
import shutil
import subprocess
import threading
import socket
import select
from datetime import datetime, timezone

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
CONTAINERS_DIR = os.path.join(ANK_DIR, "containers")
IMAGES_DIR = os.path.join(ANK_DIR, "images")
ROOTFS_DIR = os.path.join(ANK_DIR, "ankfs")
PROOT_BIN = os.path.join(ANK_DIR, "proot")
CONFIG_FILE = os.path.join(ANK_DIR, "config.json")
LOGS_DIR = os.path.join(ANK_DIR, "logs")

# Active TCP proxies: {container_name: [ProxyThread, ...]}
_port_proxies = {}
_proxy_lock = threading.Lock()


def _log(msg):
    print(f"[ANK-Lite] {msg}", flush=True)


def _load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_container_config(name):
    path = os.path.join(CONTAINERS_DIR, name, "config.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _save_container_config(name, config):
    path = os.path.join(CONTAINERS_DIR, name, "config.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def _setsid_safe():
    try:
        return os.setsid()
    except OSError:
        return None


def _is_proot_running(name):
    config = _load_container_config(name)
    if not config:
        return False
    pid = config.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            pass
    return False


def _find_free_port(start=2201):
    used = set()
    if os.path.exists(CONTAINERS_DIR):
        for d in os.listdir(CONTAINERS_DIR):
            c = _load_container_config(d)
            if c:
                used.add(c.get("ssh_port", 0))
                used.add(c.get("ankd_port", 0))
    for port in range(start, start + 200):
        if port not in used:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.1)
                s.bind(("0.0.0.0", port))
                s.close()
                return port
            except OSError:
                continue
    return start


def _find_free_ankd_port():
    used = set()
    if os.path.exists(CONTAINERS_DIR):
        for d in os.listdir(CONTAINERS_DIR):
            c = _load_container_config(d)
            if c:
                p = c.get("ankd_port")
                if p:
                    used.add(p)
    for port in range(50000, 50200):
        if port not in used:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.1)
                s.bind(("0.0.0.0", port))
                s.close()
                return port
            except OSError:
                continue
    return 50000


def _guess_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _ankd_source():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "ankd", "ankd.sh"),
        os.path.join(ANK_DIR, "ankd", "ankd.sh"),
        os.path.join(ANK_DIR, "core", "ankd", "ankd.sh"),
        os.path.join(ANK_DIR, "core", "server", "ankd", "ankd.sh"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _install_ankd(merged, image, ssh_port, template_id="", name=None):
    def _alog(msg):
        if name:
            _append_container_log(name, msg)

    _alog("  Installing ankd service manager...")
    ankd_core = os.path.join(merged, "usr/ankd/core")
    services_d = os.path.join(merged, "etc/ankd/services.d")
    os.makedirs(ankd_core, exist_ok=True)
    os.makedirs(services_d, exist_ok=True)
    os.makedirs(os.path.join(merged, "usr/ankd/services.d"), exist_ok=True)
    os.makedirs(os.path.join(merged, "usr/ankd/services"), exist_ok=True)
    os.makedirs(os.path.join(merged, "etc/ankd/services"), exist_ok=True)
    os.makedirs(os.path.join(merged, "var/run/ankd"), exist_ok=True)
    os.makedirs(os.path.join(merged, "var/log/ankd"), exist_ok=True)

    src = _ankd_source()
    if not src:
        _alog("  WARN: ankd.sh not found")
        return False
    dst = os.path.join(ankd_core, "ankd.sh")
    shutil.copyfile(src, dst)
    os.chmod(dst, 0o755)

    ankctl = os.path.join(merged, "bin/ankctl")
    os.makedirs(os.path.dirname(ankctl), exist_ok=True)
    with open(ankctl, "w") as f:
        f.write("#!/bin/sh\nexec /usr/ankd/core/ankd.sh \"$@\"\n")
    os.chmod(ankctl, 0o755)

    with open(os.path.join(services_d, "01-sshd.ankd"), "w") as f:
        f.write(
            f"NAME=sshd\n"
            f"CMD=/usr/sbin/sshd -D -p {ssh_port} -o PasswordAuthentication=yes -o PermitRootLogin=yes -e\n"
            f"DIR=/\n"
            f"PID_FILE=/run/sshd.pid\n"
            f"STOP_SIGNAL=TERM\n"
            f"RESTART_POLICY=always\n"
            f"RESTART_DELAY=3\n"
        )

    svc_map = {
        "nginx": ("nginx", "nginx", "/var/www/html", "8080"),
        "apache": ("apache", "httpd -D FOREGROUND", "/var/www/localhost/htdocs", "9090"),
        "php": ("php", "php82 -S 0.0.0.0:8000 -t /var/www/php", "/var/www/php", "8000"),
        "node": ("node", "node server.js", "/var/www/app", "3000"),
        "python": ("python", "python3 server.py", "/var/www/app", "5000"),
    }
    match = template_id or image
    svc = ""
    for key, (svc_name, cmd, svc_dir, port) in svc_map.items():
        if match.startswith(key):
            with open(os.path.join(services_d, f"02-{svc_name}.ankd"), "w") as f:
                f.write(
                    f"NAME={svc_name}\n"
                    f"CMD={cmd}\n"
                    f"DIR={svc_dir}\n"
                    f"PORT={port}\n"
                    f"PID_FILE=/run/{svc_name}.pid\n"
                    f"STOP_SIGNAL=TERM\n"
                    f"RESTART_POLICY=always\n"
                    f"RESTART_DELAY=3\n"
                )
            svc = svc_name
            break
    if svc:
        _alog(f"  Generated .ankd files: sshd + {svc}")
    else:
        _alog("  Generated .ankd files: sshd only")
    _alog("  ankd installed successfully")
    return True


# ============================================================
# Container Lifecycle
# ============================================================

def _append_container_log(name, msg):
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        path = os.path.join(LOGS_DIR, f"{name}.log")
        with open(path, "a") as f:
            f.write(f"{msg}\n")
    except Exception:
        pass


def _set_root_password_shadow(merged, password):
    """Write root password hash directly into etc/shadow (same as rooted
    container.sh). Avoids chpasswd inside nested proot which hangs."""
    shadow = os.path.join(merged, "etc/shadow")
    if not os.path.isfile(shadow):
        return False, "etc/shadow missing"
    enc = None
    openssl = None
    for cand in (
        os.path.join(ROOTFS_DIR, "usr/bin/openssl"),
        os.path.join(ROOTFS_DIR, "bin/openssl"),
        "openssl",
    ):
        if cand == "openssl" or os.path.isfile(cand):
            openssl = cand
            break
    if openssl:
        try:
            r = subprocess.run(
                [openssl, "passwd", "-1", password],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                enc = r.stdout.strip()
        except Exception:
            pass
    if not enc:
        try:
            import crypt
            enc = crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512))
        except Exception:
            pass
    if not enc:
        return False, "could not hash password (openssl/crypt failed)"
    try:
        with open(shadow, "r") as f:
            lines = f.readlines()
        out = []
        found = False
        for line in lines:
            if line.startswith("root:"):
                out.append(f"root:{enc}:19000:0:99999:7:::\n")
                found = True
            else:
                out.append(line)
        if not found:
            out.insert(0, f"root:{enc}:19000:0:99999:7:::\n")
        with open(shadow, "w") as f:
            f.writelines(out)
        try:
            os.chmod(shadow, 0o640)
        except OSError:
            pass
        return True, ""
    except Exception as e:
        return False, str(e)


def run_in_container(name, cmd, timeout=120):
    merged = os.path.join(CONTAINERS_DIR, name, "merged")
    if not os.path.exists(merged):
        return subprocess.CompletedProcess(cmd, 1, "", "Container rootfs missing")
    if not os.path.isfile(PROOT_BIN) or not os.access(PROOT_BIN, os.X_OK):
        msg = f"PRoot binary missing or not executable: {PROOT_BIN}"
        _append_container_log(name, f"ERROR: {msg}")
        return subprocess.CompletedProcess(cmd, 1, "", msg)
    wrapped = "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME=/root TERM=xterm-256color LANG=C.UTF-8; " + cmd
    env = dict(os.environ)
    proot_tmp = os.path.join(ANK_DIR, "tmp")
    try:
        os.makedirs(proot_tmp, exist_ok=True)
    except OSError:
        pass
    env["PROOT_TMP_DIR"] = proot_tmp
    argv = [
        PROOT_BIN, "-0", "-r", merged,
        "-b", "/dev", "-b", "/proc", "-b", "/sys",
        "-w", "/root",
        "/bin/sh", "-c", wrapped,
    ]
    try:
        r = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, env=env
        )
        if r.returncode != 0:
            _append_container_log(
                name,
                f"RUN fail rc={r.returncode}: {(r.stderr or r.stdout or '')[:300]}"
            )
        return r
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        err = e.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        _append_container_log(name, f"RUN timeout after {timeout}s: {cmd[:120]}")
        return subprocess.CompletedProcess(
            cmd, -1, (out or "") + (err or ""), f"TIMEOUT after {timeout}s"
        )
    except Exception as e:
        _append_container_log(name, f"RUN exception: {e}")
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def create_container(name, image="alpine-3.20", root_password="ank123",
                     ssh_port=None, ankd_port=None, packages="", template_id=""):
    existing = os.path.join(CONTAINERS_DIR, name)
    stub_cfg = None
    is_retry = False
    if os.path.exists(existing):
        existing_cfg = _load_container_config(name)
        existing_status = (existing_cfg or {}).get("status", "")
        if existing_status not in ("building", "failed"):
            return False, f"Container '{name}' already exists"
        # Keep stub config.json so UI keeps showing "building" during create;
        # only wipe filesystem trees for a clean retry.
        stub_cfg = existing_cfg
        is_retry = os.path.isdir(os.path.join(existing, "merged"))
        for sub in ("merged", "upper", "work"):
            p = os.path.join(existing, sub)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)

    if not ssh_port:
        ssh_port = _find_free_port(2201)
    if not ankd_port:
        ankd_port = _find_free_ankd_port()

    if image.startswith("alpine-"):
        image = f"ank-alpinebase-{image[7:]}"

    def _fail(msg):
        _append_container_log(name, f"ERROR: {msg}")
        try:
            os.makedirs(existing, exist_ok=True)
            cfg = dict(stub_cfg) if stub_cfg else {}
            cfg.update({
                "name": name,
                "status": "failed",
                "image": image,
                "mode": "lite",
                "ssh_port": int(ssh_port),
                "ankd_port": int(ankd_port),
                "created_at": (stub_cfg or {}).get("created_at")
                    or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pid": None,
                "error": str(msg)[:500],
            })
            _save_container_config(name, cfg)
        except Exception:
            pass
        return False, msg

    orig_port = int(ssh_port)
    while True:
        port_in_use = False
        if os.path.isdir(CONTAINERS_DIR):
            for d in os.listdir(CONTAINERS_DIR):
                if is_retry and d == name:
                    continue
                c = _load_container_config(d)
                if c and int(c.get("ssh_port") or 0) == int(ssh_port):
                    port_in_use = True
                    break
        if not port_in_use:
            break
        ssh_port = int(ssh_port) + 1
        if ssh_port > 65000:
            ssh_port = orig_port
            break
    if int(ssh_port) != orig_port:
        _append_container_log(
            name, f"WARN: Port {orig_port} in use, using {int(ssh_port)} instead"
        )

    _append_container_log(name, f"Creating container: {name} (mode: lite, port: {ssh_port})")

    if not os.path.isfile(PROOT_BIN):
        return _fail(f"PRoot not found at {PROOT_BIN}")

    base = None
    image_dir = os.path.join(IMAGES_DIR, image)
    if os.path.lexists(os.path.join(image_dir, "bin", "sh")):
        base = image_dir
    else:
        fallback_dir = os.path.join(IMAGES_DIR, "ank-alpinebase-3.20")
        if os.path.lexists(os.path.join(fallback_dir, "bin", "sh")):
            base = fallback_dir
    if not base:
        try:
            listing = os.listdir(IMAGES_DIR) if os.path.isdir(IMAGES_DIR) else []
        except Exception:
            listing = []
        return _fail(
            f"No usable base image for '{image}' "
            f"(need {image_dir} or {os.path.join(IMAGES_DIR, 'ank-alpinebase-3.20')} with bin/sh); "
            f"IMAGES_DIR listing={listing[:20]}"
        )

    merged = os.path.join(existing, "merged")
    os.makedirs(merged, exist_ok=True)

    _log(f"Creating '{name}' from {base}...")
    try:
        shutil.copytree(base, merged, dirs_exist_ok=True, symlinks=True)
    except Exception as e:
        return _fail(f"Failed to copy rootfs: {e}")

    _append_container_log(
        name,
        "WARN: Failed to create cgroup (cgroups may not be available) - continuing without resource limits",
    )
    _append_container_log(name, f"Setting up container: {name}...")

    dev_dir = os.path.join(merged, "dev")
    os.makedirs(dev_dir, exist_ok=True)
    os.makedirs(os.path.join(merged, "run/sshd"), exist_ok=True)

    ank_dir = os.path.join(merged, "etc/ank")
    os.makedirs(ank_dir, exist_ok=True)

    resolv = os.path.join(merged, "etc/resolv.conf")
    with open(resolv, "w") as f:
        f.write("nameserver 8.8.8.8\nnameserver 8.8.4.4\n")

    hosts = os.path.join(merged, "etc/hosts")
    with open(hosts, "w") as f:
        f.write("127.0.0.1 localhost\n")

    if not os.path.isfile(os.path.join(merged, "etc/ssh/ssh_host_rsa_key")):
        for kg in ("usr/bin/ssh-keygen", "bin/ssh-keygen"):
            if os.path.isfile(os.path.join(merged, kg)):
                run_in_container(name, "ssh-keygen -A 2>/dev/null || true", timeout=30)
                break

    _install_ankd(merged, image, int(ssh_port), template_id, name)

    if root_password:
        ok_pw, err_pw = _set_root_password_shadow(merged, root_password)
        if ok_pw:
            _append_container_log(name, "Password set via shadow")
        else:
            _append_container_log(name, f"WARN: password via shadow failed: {err_pw}")

    ip_addr = _guess_ip()
    config = dict(stub_cfg) if stub_cfg else {}
    config.update({
        "name": name,
        "instance_uuid": os.urandom(3).hex(),
        "status": "stopped",
        "image": image,
        "mode": "lite",
        "autostart": config.get("autostart", False),
        "ip_address": ip_addr,
        "ssh_port": int(ssh_port),
        "ankd_port": int(ankd_port),
        "created_at": config.get("created_at")
            or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pid": None,
        "policies": config.get("policies")
            or {"inter_container_p2p": False, "allow_host_access": False, "allow_internet": True},
        "resources": config.get("resources")
            or {"memory_limit": "256M", "cpu_limit_percent": 50},
        "port_mappings": config.get("port_mappings", []),
        "root_password": root_password,
    })
    if stub_cfg:
        for k in ("template", "template_name", "template_id"):
            if k in stub_cfg and k not in config:
                config[k] = stub_cfg[k]
        if stub_cfg.get("template"):
            config["template"] = stub_cfg["template"]
        if stub_cfg.get("template_name"):
            config["template_name"] = stub_cfg["template_name"]
    _save_container_config(name, config)
    _append_container_log(name, f"Container ready: {name}")
    _append_container_log(
        name,
        f"Container '{name}' created (IP: {ip_addr}, SSH port: {ssh_port}, mode: lite)"
    )
    _log(f"Container '{name}' created (ssh={ssh_port}, ankd={ankd_port})")
    return True, config


def start_container(name):
    config = _load_container_config(name)
    if not config:
        return False, "Container not found"

    if _is_proot_running(name):
        return True, "Already running"

    merged = os.path.join(CONTAINERS_DIR, name, "merged")
    if not os.path.exists(merged):
        return False, "Container rootfs missing"

    _log(f"Starting '{name}'...")

    if not os.path.isfile(PROOT_BIN):
        msg = f"PRoot not found at {PROOT_BIN}"
        _append_container_log(name, f"ERROR: {msg}")
        return False, msg

    ssh_port = int(config.get("ssh_port") or 2201)
    ankd_port = int(config.get("ankd_port") or 50000)
    instance_uuid = config.get("instance_uuid") or name

    ankd_sh = os.path.join(merged, "usr/ankd/core/ankd.sh")
    if os.path.exists(ankd_sh):
        inner = (
            "export PATH=/bin:/sbin:/usr/bin:/usr/sbin HOME=/root TERM=xterm-256color "
            "LANG=C.UTF-8 LD_LIBRARY_PATH=/lib:/usr/lib:/lib64:/usr/lib64; "
            f"ANKD_CONTAINER={name} ANKD_SSHD_PORT={ssh_port} ANKD_PORT={ankd_port} "
            f"ANKD_INSTANCE_UUID={instance_uuid} ANK_HEALTH_FILE=/tmp/ank-health "
            "/usr/ankd/core/ankd.sh daemon"
        )
    else:
        inner = (
            "export PATH=/bin:/sbin:/usr/bin:/usr/sbin HOME=/root TERM=xterm-256color "
            "LANG=C.UTF-8 LD_LIBRARY_PATH=/lib:/usr/lib:/lib64:/usr/lib64; "
            "trap '' HUP PIPE; _ank_exit=0; trap '_ank_exit=1' TERM INT; "
            "mkdir -p /run/sshd 2>/dev/null; "
            f"hostname {name} 2>/dev/null; "
            "cd /root 2>/dev/null || cd /; "
            "if [ -x /usr/sbin/sshd ]; then "
            "ssh-keygen -A 2>/dev/null; "
            f"/usr/sbin/sshd -D -p {ssh_port} -o PasswordAuthentication=yes "
            "-o PermitRootLogin=yes -o PidFile=/run/sshd.pid -e 2>/dev/null & "
            "_sshd_pid=$!; fi; "
            "if [ -f /etc/ank/service ]; then "
            "_svc=$(cat /etc/ank/service 2>/dev/null); "
            "case \"$_svc\" in "
            "nginx) mkdir -p /run/nginx 2>/dev/null; nginx 2>/dev/null & ;; "
            "apache) httpd -f -p 80 -h /var/www/localhost/htdocs 2>/dev/null & ;; "
            "php) php -S 0.0.0.0:80 -t /var/www/php 2>/dev/null & ;; "
            "node) cd /var/www/app 2>/dev/null; node server.js 2>/dev/null & ;; "
            "python) cd /var/www/app 2>/dev/null; python3 server.py 2>/dev/null & ;; "
            "esac; fi; "
            "while [ \"$_ank_exit\" = \"0\" ]; do "
            "if [ -n \"$_sshd_pid\" ] && ! kill -0 \"$_sshd_pid\" 2>/dev/null; then break; fi; "
            "sleep 5 2>/dev/null || true; done"
        )

    cmd = [
        PROOT_BIN,
        "-0",
        "-r", merged,
        "-b", "/dev",
        "-b", "/proc",
        "-b", "/sys",
        "-w", "/",
        "/bin/sh", "-c", inner,
    ]

    log_path = os.path.join(LOGS_DIR, f"{name}.log")
    os.makedirs(LOGS_DIR, exist_ok=True)
    proot_tmp = os.path.join(ANK_DIR, "tmp")
    os.makedirs(proot_tmp, exist_ok=True)

    env = dict(os.environ)
    env["PROOT_TMP_DIR"] = proot_tmp

    try:
        with open(log_path, "w") as lf:
            lf.write(f"Starting container: {name} (mode: lite, port: {ssh_port})\n")

        proc = subprocess.Popen(
            cmd,
            stdout=open(log_path, "a"),
            stderr=subprocess.STDOUT,
            preexec_fn=_setsid_safe,
            env=env,
        )

        time.sleep(2)
        if proc.poll() is not None:
            _log(f"ERROR: start '{name}': process died immediately after start")
            _append_container_log(name, "ERROR: Container process died immediately after start")
            config["pid"] = None
            config["status"] = "failed"
            _save_container_config(name, config)
            return False, "Container process died immediately after start"

        config["pid"] = proc.pid
        config["status"] = "running"
        _save_container_config(name, config)

        _start_port_proxies(name, config)

        _log(f"Container '{name}' started (pid={proc.pid})")
        return True, config

    except Exception as e:
        _log(f"ERROR: start '{name}': {e}")
        _append_container_log(name, f"START exception: {e}")
        config["pid"] = None
        config["status"] = "failed"
        _save_container_config(name, config)
        return False, str(e)


def stop_container(name, timeout=15):
    config = _load_container_config(name)
    if not config:
        return False, "Container not found"

    _log(f"Stopping '{name}'...")

    # Stop port proxies
    _stop_port_proxies(name)

    pid = config.get("pid")
    killed = False
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            killed = True
        except OSError:
            pass

    if killed:
        # Wait for process to exit
        for _ in range(timeout * 2):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except OSError:
                break
        # Force kill if still alive
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    # Also kill any orphan proot processes for this container
    merged = os.path.join(CONTAINERS_DIR, name, "merged")
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"proot.*-r.*{merged}"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line and line.isdigit():
                try:
                    os.kill(int(line), signal.SIGKILL)
                except OSError:
                    pass
    except Exception:
        pass

    config["status"] = "stopped"
    config["pid"] = None
    _save_container_config(name, config)
    _log(f"Container '{name}' stopped")
    return True, "stopped"


def delete_container(name):
    config = _load_container_config(name)
    if not config:
        return False, "Container not found"

    if _is_proot_running(name):
        stop_container(name)

    _stop_port_proxies(name)

    merged = os.path.join(CONTAINERS_DIR, name)
    try:
        shutil.rmtree(merged)
    except Exception as e:
        return False, f"Failed to remove: {e}"

    _log(f"Container '{name}' deleted")
    return True, "deleted"


def exec_container(name, command, timeout=30):
    config = _load_container_config(name)
    if not config:
        return None, "Container not found"

    if not _is_proot_running(name):
        return None, "Container not running"

    merged = os.path.join(CONTAINERS_DIR, name, "merged")

    cmd = [
        PROOT_BIN,
        "-0",
        "-r", merged,
        "-b", "/dev",
        "-b", "/proc",
        "-w", "/root",
        "/bin/sh", "-c", command
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "Command timed out", 1
    except Exception as e:
        return str(e), 1


def inspect_container(name):
    config = _load_container_config(name)
    if not config:
        return None

    config["running"] = _is_proot_running(name)
    return config


def list_containers():
    containers = []
    if os.path.exists(CONTAINERS_DIR):
        for name in os.listdir(CONTAINERS_DIR):
            if os.path.isdir(os.path.join(CONTAINERS_DIR, name)):
                c = _load_container_config(name)
                if c:
                    c["running"] = _is_proot_running(name)
                    containers.append(c)
    return containers


def container_logs(name, lines=100):
    log_path = os.path.join(LOGS_DIR, f"{name}.log")
    if not os.path.exists(log_path):
        return ""
    try:
        with open(log_path, "r") as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])
    except Exception:
        return ""


# ============================================================
# Port Mapping — Python TCP Proxy (replaces iptables)
# ============================================================

class PortProxy(threading.Thread):
    def __init__(self, name, host_port, container_port, container_ip="127.0.0.1"):
        super().__init__(daemon=True)
        self.name = f"proxy-{name}-{host_port}-{container_port}"
        self.container_name = name
        self.host_port = int(host_port)
        self.container_port = int(container_port)
        self.container_ip = container_ip
        self._running = True
        self._server = None

    def run(self):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.settimeout(1)
        try:
            self._server.bind(("0.0.0.0", self.host_port))
            self._server.listen(16)
            _log(f"Port proxy: 0.0.0.0:{self.host_port} -> {self.container_ip}:{self.container_port}")

            while self._running:
                try:
                    client, addr = self._server.accept()
                    t = threading.Thread(target=self._forward, args=(client,), daemon=True)
                    t.start()
                except socket.timeout:
                    continue
                except OSError:
                    break
        except Exception as e:
            _log(f"Port proxy error ({self.host_port}): {e}")
        finally:
            try:
                self._server.close()
            except Exception:
                pass

    def _forward(self, client):
        remote = None
        try:
            remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote.settimeout(30)
            remote.connect((self.container_ip, self.container_port))

            sockets = [client, remote]
            while self._running:
                readable, _, exceptional = select.select(sockets, [], sockets, 10)
                if exceptional:
                    break
                for s in readable:
                    data = s.recv(8192)
                    if not data:
                        self._running = False
                        break
                    if s is client:
                        remote.sendall(data)
                    else:
                        client.sendall(data)
        except Exception:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                remote.close()
            except Exception:
                pass

    def stop(self):
        self._running = False
        try:
            if self._server:
                self._server.close()
        except Exception:
            pass


def _start_port_proxies(name, config):
    mappings = config.get("port_mappings", [])
    with _proxy_lock:
        if name in _port_proxies:
            for p in _port_proxies[name]:
                p.stop()
            _port_proxies[name] = []

        for m in mappings:
            host_port = m.get("host_port") or m.get("hostPort")
            container_port = m.get("container_port") or m.get("containerPort")
            if host_port and container_port:
                if int(host_port) == int(container_port):
                    continue
                proxy = PortProxy(name, host_port, container_port)
                proxy.start()
                _port_proxies.setdefault(name, []).append(proxy)


def _stop_port_proxies(name):
    with _proxy_lock:
        if name in _port_proxies:
            for p in _port_proxies[name]:
                p.stop()
            del _port_proxies[name]


def add_port_mapping(name, host_port, container_port):
    config = _load_container_config(name)
    if not config:
        return False, "Container not found"

    mappings = config.get("port_mappings", [])
    mappings.append({
        "host_port": int(host_port),
        "container_port": int(container_port),
        "protocol": "tcp"
    })
    config["port_mappings"] = mappings
    _save_container_config(name, config)

    # Start proxy if container is running (shared netns: skip when ports are equal)
    if _is_proot_running(name) and int(host_port) != int(container_port):
        proxy = PortProxy(name, host_port, container_port)
        proxy.start()
        with _proxy_lock:
            _port_proxies.setdefault(name, []).append(proxy)

    return True, "added"


def remove_port_mapping(name, host_port):
    config = _load_container_config(name)
    if not config:
        return False, "Container not found"

    mappings = config.get("port_mappings", [])
    mappings = [m for m in mappings if m.get("host_port") != int(host_port)]
    config["port_mappings"] = mappings
    _save_container_config(name, config)

    # Stop proxy for this port
    with _proxy_lock:
        if name in _port_proxies:
            _port_proxies[name] = [p for p in _port_proxies[name] if p.host_port != int(host_port)]

    return True, "removed"


# ============================================================
# Health Check
# ============================================================

def check_container_health(name):
    config = _load_container_config(name)
    if not config:
        return {"name": name, "status": "not_found"}

    running = _is_proot_running(name)
    status = "running" if running else "stopped"

    return {
        "name": name,
        "status": status,
        "ssh_port": config.get("ssh_port"),
        "ankd_port": config.get("ankd_port"),
        "pid_alive": running,
        "ssh_alive": None,
        "ankd_alive": None,
    }

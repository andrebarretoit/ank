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


# ============================================================
# Container Lifecycle
# ============================================================

def create_container(name, image="alpine-3.20", root_password="ank123",
                     ssh_port=None, ankd_port=None, packages=""):
    if os.path.exists(os.path.join(CONTAINERS_DIR, name)):
        return False, f"Container '{name}' already exists"

    if not ssh_port:
        ssh_port = _find_free_port(2201)
    if not ankd_port:
        ankd_port = _find_free_ankd_port()

    merged = os.path.join(CONTAINERS_DIR, name, "merged")
    os.makedirs(merged, exist_ok=True)

    # Find base rootfs (ankfs) or image
    base = ROOTFS_DIR
    image_dir = os.path.join(IMAGES_DIR, image)
    if os.path.exists(os.path.join(image_dir, "bin", "sh")):
        base = image_dir

    # Copy rootfs
    _log(f"Creating '{name}' from {base}...")
    try:
        shutil.copytree(base, merged, dirs_exist_ok=True, symlinks=True)
    except Exception as e:
        return False, f"Failed to copy rootfs: {e}"

    # Bind mount points for /dev
    dev_dir = os.path.join(merged, "dev")
    os.makedirs(dev_dir, exist_ok=True)

    # Write portfwd config
    ank_dir = os.path.join(merged, "etc/ank")
    os.makedirs(ank_dir, exist_ok=True)

    # Setup resolv.conf
    resolv = os.path.join(merged, "etc/resolv.conf")
    with open(resolv, "w") as f:
        f.write("nameserver 8.8.8.8\nnameserver 8.8.4.4\n")

    # Install ankd.sh inside container
    ankd_dir = os.path.join(merged, "usr/ankd/core")
    os.makedirs(ankd_dir, exist_ok=True)

    # Save config
    config = {
        "name": name,
        "status": "stopped",
        "image": image,
        "mode": "lite",
        "ssh_port": int(ssh_port),
        "ankd_port": int(ankd_port),
        "pid": None,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root_password": root_password,
        "port_mappings": [],
        "autostart": False,
    }
    _save_container_config(name, config)
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

    # Build PRoot command
    env = (
        f"HOME=/root "
        f"TERM=xterm-256color "
        f"LANG=C.UTF-8 "
        f"PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
        f"LD_LIBRARY_PATH={merged}/lib:{merged}/usr/lib"
    )

    cmd = [
        PROOT_BIN,
        "-0",
        "-r", merged,
        "-b", "/dev",
        "-b", "/proc",
        "-b", "/sys",
        "-w", "/root",
        "/bin/sh", "-c",
        f"{env} /usr/bin/python3 /opt/ank/server.py"
    ]

    # Start via PRoot (background)
    log_path = os.path.join(LOGS_DIR, f"{name}.log")
    os.makedirs(LOGS_DIR, exist_ok=True)

    try:
        with open(log_path, "a") as lf:
            lf.write(f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting container via PRoot...\n")

        proc = subprocess.Popen(
            cmd,
            stdout=open(log_path, "a"),
            stderr=subprocess.STDOUT,
            preexec_fn=_setsid_safe,
        )

        config["pid"] = proc.pid
        config["status"] = "running"
        _save_container_config(name, config)

        # Start port proxies
        _start_port_proxies(name, config)

        _log(f"Container '{name}' started (pid={proc.pid})")
        return True, config

    except Exception as e:
        _log(f"ERROR: start '{name}': {e}")
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

    # Start proxy if container is running
    if _is_proot_running(name):
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

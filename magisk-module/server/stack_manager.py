#!/usr/bin/env python3
"""
ANK Stack Manager - Manages groups of identical containers with load balancing,
auto-scaling, healing, rolling updates, and hybrid (multi-node) support.

A stack is a group of N identical containers created from the same template,
with a Python reverse proxy load balancer distributing traffic between them.
"""

import os
import json
import re
import socket
import time
import threading
import subprocess
import glob
import shutil

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
STACKS_DIR = os.path.join(ANK_DIR, "stacks")
CONTAINERS_DIR = os.path.join(ANK_DIR, "containers")
SCRIPTS_DIR = os.path.join(ANK_DIR, "core")
LB_PORT_RANGE = (30000, 39999)
SERVICE_PORT_RANGE = (40000, 49999)
ANKD_PORT_BASE = 50000
ANKD_PORT_END = 59999
REPLICA_PORT_BASE = 50000

try:
    from server import run_script, load_container_config, save_container_config, load_config, get_nodes
except ImportError:
    def run_script(script, *args, timeout=60):
        script_path = os.path.join(SCRIPTS_DIR, script)
        cmd_parts = ["/system/bin/sh", script_path] + list(args)
        cmd_str = " ".join(f"'{a}'" for a in cmd_parts)
        try:
            if os.geteuid() != 0:
                result = subprocess.run(["su", "-c", cmd_str], capture_output=True, text=True, timeout=timeout)
            else:
                result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=timeout)
            return result.stdout.strip(), result.returncode
        except subprocess.TimeoutExpired:
            return "Script timed out", 1
        except Exception as e:
            return str(e), 1

    def load_container_config(name):
        path = os.path.join(CONTAINERS_DIR, name, "config.json")
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def save_container_config(name, config):
        path = os.path.join(CONTAINERS_DIR, name, "config.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(config, f, indent=2)

    def load_config():
        config_file = os.path.join(ANK_DIR, "config.json")
        try:
            with open(config_file) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def get_nodes():
        return []


def _log(msg):
    print(f"[STACK] {msg}", flush=True)


# Template specs mirroring server.py IMAGE_TEMPLATES: image name, packages
# installed at create time and the static path the service serves.
_TEMPLATE_SPECS = {
    "nginx":  {"pkgs": "nginx curl", "static_path": "/var/www/html"},
    "apache": {"pkgs": "apache2 curl", "static_path": "/var/www/localhost/htdocs"},
    "php":    {"pkgs": "php82 php82-mbstring php82-json php82-cgi", "static_path": "/var/www/php"},
    "node":   {"pkgs": "nodejs npm", "static_path": "/var/www/app"},
    "python": {"pkgs": "python3 py3-pip", "static_path": "/var/www/app"},
}


def _port_busy(port):
    """True when something already accepts connections on 127.0.0.1:port."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.1)
        result = s.connect_ex(("127.0.0.1", int(port)))
        s.close()
        return result == 0
    except Exception:
        return False


def _collect_used_ports():
    used = set()
    for cfg_file in glob.glob(os.path.join(CONTAINERS_DIR, "*/config.json")):
        try:
            with open(cfg_file) as f:
                cfg = json.load(f)
            for key in ("ssh_port", "ankd_port"):
                if cfg.get(key):
                    try:
                        used.add(int(cfg[key]))
                    except (ValueError, TypeError):
                        pass
            for pm in cfg.get("port_mappings", []):
                if pm.get("host_port"):
                    try:
                        used.add(int(pm["host_port"]))
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass
    for cfg_file in glob.glob(os.path.join(STACKS_DIR, "*/config.json")):
        try:
            with open(cfg_file) as f:
                cfg = json.load(f)
            if cfg.get("port"):
                try:
                    used.add(int(cfg["port"]))
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass
    return used


def _find_free_port(start=LB_PORT_RANGE[0], end=LB_PORT_RANGE[1], extra_used=()):
    used = _collect_used_ports()
    used.update(int(p) for p in extra_used)
    for port in range(start, end):
        if port not in used and not _port_busy(port):
            return port
    return start


def _get_free_ssh_port():
    return _find_free_port(2200, 65000)


def _get_free_service_port(extra_used=()):
    """Host/container service port for a stack replica (40000-49999)."""
    return _find_free_port(SERVICE_PORT_RANGE[0], SERVICE_PORT_RANGE[1], extra_used)


def _get_free_ankd_port(extra_used=()):
    """ankd health-listener port for a stack replica (50000-59999)."""
    return _find_free_port(ANKD_PORT_BASE, ANKD_PORT_END, extra_used)


def _get_free_replica_port():
    used = set()
    for cfg_file in glob.glob(os.path.join(CONTAINERS_DIR, "*/config.json")):
        try:
            with open(cfg_file) as f:
                cfg = json.load(f)
            for pm in cfg.get("port_mappings", []):
                hp = pm.get("host_port")
                if hp:
                    try:
                        used.add(int(hp))
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass
    for port in range(REPLICA_PORT_BASE, 60000):
        if port not in used:
            return port
    return REPLICA_PORT_BASE


class StackManager:
    def __init__(self):
        os.makedirs(STACKS_DIR, exist_ok=True)
        self._lock = threading.Lock()
        self._lb_instances = {}
        self._heal_timers = {}
        self._rolling_in_progress = set()

    def list_stacks(self):
        stacks = []
        if not os.path.isdir(STACKS_DIR):
            return stacks
        for name in sorted(os.listdir(STACKS_DIR)):
            config = self._load_stack_config(name)
            if config:
                config["running_count"] = self._count_running(config)
                stacks.append(config)
        return stacks

    def get_stack(self, name):
        config = self._load_stack_config(name)
        if not config:
            return None
        containers = []
        for cname in config.get("containers", []):
            cinfo = self._get_container_info(cname)
            if cinfo:
                containers.append(cinfo)
        config["container_details"] = containers
        config["running_count"] = self._count_running(config)
        config["lb_status"] = self._get_lb_status(name)
        return config

    def create_stack(self, config):
        name = config.get("name", "")
        if not name or not all(c.isalnum() or c in "-_" for c in name):
            raise ValueError("Invalid stack name")
        if self._load_stack_config(name):
            raise ValueError(f"Stack '{name}' already exists")

        template = config.get("template", "nginx")
        ankfile = config.get("ankfile", "")
        min_instances = max(1, config.get("min", 1))
        max_instances = max(min_instances, config.get("max", 10))
        lb_port = config.get("lb_port") or config.get("port")
        port_warning = None
        if lb_port:
            try:
                lb_port = int(lb_port)
            except (ValueError, TypeError):
                lb_port = None
        if lb_port:
            if _port_busy(lb_port):
                new_port = _find_free_port()
                port_warning = f"LB port {lb_port} in use, using {new_port} instead"
                _log(f"WARN: {port_warning}")
                lb_port = new_port
        else:
            lb_port = _find_free_port()
        root_password = config.get("root_password", "ankstack")
        trigger = config.get("trigger", "requests")
        threshold_up = config.get("threshold_up", 100)
        threshold_down = config.get("threshold_down", 20)
        scale_up_after = config.get("scale_up_after", 30)
        scale_down_after = config.get("scale_down_after", 120)
        load_balance = config.get("load_balance", "least_conn")
        shared_volume = config.get("shared_volume", False)

        stack_config = {
            "name": name,
            "template": template,
            "ankfile": ankfile,
            "port": lb_port,
            "min": min_instances,
            "max": max_instances,
            "trigger": trigger,
            "threshold_up": threshold_up,
            "threshold_down": threshold_down,
            "scale_up_after": scale_up_after,
            "scale_down_after": scale_down_after,
            "load_balance": load_balance,
            "shared_volume": shared_volume,
            "root_password": root_password,
            "containers": [],
            "status": "active",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "metrics": {"requests_total": 0, "last_scale_event": 0},
        }
        if port_warning:
            stack_config["port_warning"] = port_warning

        stack_dir = os.path.join(STACKS_DIR, name)
        data_dir = os.path.join(stack_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        self._save_stack_config(name, stack_config)

        created = []
        for i in range(min_instances):
            cname = f"stack-{name}-{i + 1}"
            if self._create_stack_container(name, cname, template, root_password, ankfile=ankfile, shared_volume=shared_volume):
                created.append(cname)
                stack_config["containers"].append(cname)

        self._save_stack_config(name, stack_config)

        if created:
            self._start_lb(name, stack_config)
            _log(f"Stack '{name}': created {len(created)} containers, LB on port {lb_port}")

        return stack_config

    def delete_stack(self, name):
        stack_config = self._load_stack_config(name)
        if not stack_config:
            raise ValueError(f"Stack '{name}' not found")
        self._stop_lb(name)
        for cname in list(stack_config.get("containers", [])):
            self._destroy_container(cname)
        heal = self._heal_timers.pop(name, None)
        if heal:
            heal.cancel()
        stack_dir = os.path.join(STACKS_DIR, name)
        try:
            shutil.rmtree(stack_dir, ignore_errors=True)
        except Exception:
            pass
        _log(f"Stack '{name}' deleted")
        return True

    def update_stack(self, name, data):
        stack_config = self._load_stack_config(name)
        if not stack_config:
            raise ValueError(f"Stack '{name}' not found")
        allowed = ("min", "max", "trigger", "threshold_up", "threshold_down",
                    "scale_up_after", "scale_down_after", "load_balance", "shared_volume")
        for key in allowed:
            if key in data:
                stack_config[key] = data[key]
        if "min" in data or "max" in data:
            stack_config["max"] = max(stack_config["min"], stack_config["max"])
        self._save_stack_config(name, stack_config)
        self._start_lb(name, stack_config)
        _log(f"Stack '{name}' updated")
        return stack_config

    def scale_up(self, stack_name, count=1):
        stack_config = self._load_stack_config(stack_name)
        if not stack_config:
            raise ValueError(f"Stack '{stack_name}' not found")
        created = []
        for _ in range(count):
            current = len(stack_config.get("containers", []))
            if current >= stack_config.get("max", 10):
                _log(f"Stack '{stack_name}' at max capacity ({stack_config['max']})")
                break
            idx = current + 1
            cname = f"stack-{stack_name}-{idx}"
            root_password = stack_config.get("root_password", "ankstack")
            if self._create_stack_container(stack_name, cname, stack_config["template"], root_password,
                                            ankfile=stack_config.get("ankfile", ""),
                                            shared_volume=stack_config.get("shared_volume", False)):
                stack_config["containers"].append(cname)
                created.append(cname)
        if created:
            self._save_stack_config(stack_name, stack_config)
            self._start_lb(stack_name, stack_config)
            _log(f"Stack '{stack_name}' scaled up: +{len(created)} ({', '.join(created)})")
        return len(created)

    def scale_down(self, stack_name, count=1):
        stack_config = self._load_stack_config(stack_name)
        if not stack_config:
            raise ValueError(f"Stack '{stack_name}' not found")
        containers = stack_config.get("containers", [])
        min_c = stack_config.get("min", 1)
        removed = []
        for _ in range(count):
            if len(containers) <= min_c:
                _log(f"Stack '{stack_name}' at min capacity ({min_c})")
                break
            target = self._pick_least_loaded(containers)
            if target is None:
                target = containers[-1]
            self._destroy_container(target)
            if target in stack_config["containers"]:
                stack_config["containers"].remove(target)
                containers = stack_config["containers"]
            removed.append(target)
        if removed:
            self._save_stack_config(stack_name, stack_config)
            self._start_lb(stack_name, stack_config)
            _log(f"Stack '{stack_name}' scaled down: -{len(removed)} ({', '.join(removed)})")
        return len(removed)

    def rolling_update(self, stack_name, new_template=None, new_ankfile=None):
        stack_config = self._load_stack_config(stack_name)
        if not stack_config:
            raise ValueError(f"Stack '{stack_name}' not found")
        if stack_name in self._rolling_in_progress:
            raise ValueError(f"Rolling update already in progress for '{stack_name}'")
        self._rolling_in_progress.add(stack_name)
        thread = threading.Thread(
            target=self._do_rolling_update,
            args=(stack_name, stack_config, new_template, new_ankfile),
            daemon=True
        )
        thread.start()
        return {"status": "rolling_update_started", "containers": stack_config.get("containers", [])}

    def _do_rolling_update(self, stack_name, stack_config, new_template, new_ankfile):
        try:
            containers = list(stack_config.get("containers", []))
            template = new_template or stack_config.get("template", "nginx")
            ankfile = new_ankfile or stack_config.get("ankfile", "")
            root_password = stack_config.get("root_password", "ankstack")

            for cname in containers:
                _log(f"Rolling update: replacing {cname}")
                self._destroy_container(cname)

                try:
                    idx = stack_config["containers"].index(cname) + 1
                except ValueError:
                    _log(f"Rolling update: {cname} no longer in container list, appending")
                    idx = len(stack_config["containers"]) + 1
                    stack_config["containers"].append(f"stack-{stack_name}-{idx}")
                new_cname = f"stack-{stack_name}-{idx}"
                if self._create_stack_container(stack_name, new_cname, template, root_password,
                                                ankfile=ankfile,
                                                shared_volume=stack_config.get("shared_volume", False)):
                    stack_config["containers"][idx - 1] = new_cname
                    self._save_stack_config(stack_name, stack_config)
                    self._start_lb(stack_name, stack_config)
                    time.sleep(5)
                else:
                    _log(f"Rolling update: FAILED to create {new_cname}")

            _log(f"Rolling update complete for '{stack_name}'")
        except Exception as e:
            _log(f"Rolling update error: {e}")
        finally:
            self._rolling_in_progress.discard(stack_name)

    def start_healing(self, stack_name, interval=15):
        def _heal_loop():
            while True:
                try:
                    self._check_healing(stack_name)
                except Exception as e:
                    _log(f"Healing error for '{stack_name}': {e}")
                time.sleep(interval)
        t = threading.Thread(target=_heal_loop, daemon=True)
        t.start()
        self._heal_timers[stack_name] = t
        _log(f"Healing started for '{stack_name}' (interval={interval}s)")

    def _check_healing(self, stack_name):
        stack_config = self._load_stack_config(stack_name)
        if not stack_config or stack_config.get("status") != "active":
            return
        containers = list(stack_config.get("containers", []))
        for cname in containers:
            info = self._get_container_info(cname)
            if not info or info.get("status") != "running":
                _log(f"Healing: {cname} is down, recreating...")
                self._destroy_container(cname)
                idx = containers.index(cname) + 1
                new_cname = f"stack-{stack_name}-{idx}"
                root_password = stack_config.get("root_password", "ankstack")
                if self._create_stack_container(stack_name, new_cname, stack_config["template"], root_password,
                                                ankfile=stack_config.get("ankfile", ""),
                                                shared_volume=stack_config.get("shared_volume", False)):
                    stack_config["containers"][idx - 1] = new_cname
                    self._save_stack_config(stack_name, stack_config)
                    self._start_lb(stack_name, stack_config)
                    _log(f"Healing: {cname} replaced with {new_cname}")
                else:
                    _log(f"Healing: FAILED to recreate {cname}")

    def get_metrics(self, stack_name):
        stack_config = self._load_stack_config(stack_name)
        if not stack_config:
            raise ValueError(f"Stack '{stack_name}' not found")
        metrics = {
            "stack_name": stack_name,
            "total_containers": len(stack_config.get("containers", [])),
            "running_containers": self._count_running(stack_config),
            "containers": {},
        }
        for cname in stack_config.get("containers", []):
            cmetrics = self._get_container_metrics(cname)
            if cmetrics:
                metrics["containers"][cname] = cmetrics
        metrics["lb"] = self._get_lb_status(stack_name)
        return metrics

    def auto_scale_check(self):
        for stack in self.list_stacks():
            if stack.get("status") != "active":
                continue
            self._evaluate_scaling(stack["name"])

    def start_monitoring(self, interval=30):
        def _monitor_loop():
            while True:
                try:
                    self.auto_scale_check()
                except Exception as e:
                    _log(f"Monitor error: {e}")
                time.sleep(interval)
        t = threading.Thread(target=_monitor_loop, daemon=True)
        t.start()
        _log(f"Auto-scaling monitor started (interval={interval}s)")
        return t

    def _evaluate_scaling(self, stack_name):
        stack_config = self._load_stack_config(stack_name)
        if not stack_config or stack_config.get("status") != "active":
            return
        trigger = stack_config.get("trigger", "requests")
        threshold_up = stack_config.get("threshold_up", 100)
        threshold_down = stack_config.get("threshold_down", 20)
        scale_up_after = stack_config.get("scale_up_after", 30)
        scale_down_after = stack_config.get("scale_down_after", 120)
        metrics = self.get_metrics(stack_name)
        value = self._get_trigger_value(trigger, metrics)
        now = time.time()
        last_event = stack_config.get("metrics", {}).get("last_scale_event", 0)
        if value > threshold_up and (now - last_event) > scale_up_after:
            if self.scale_up(stack_name):
                stack_config = self._load_stack_config(stack_name)
                if stack_config:
                    stack_config.setdefault("metrics", {})["last_scale_event"] = now
                    self._save_stack_config(stack_name, stack_config)
        elif value < threshold_down and (now - last_event) > scale_down_after:
            if self.scale_down(stack_name):
                stack_config = self._load_stack_config(stack_name)
                if stack_config:
                    stack_config.setdefault("metrics", {})["last_scale_event"] = now
                    self._save_stack_config(stack_name, stack_config)

    def _get_trigger_value(self, trigger, metrics):
        containers = metrics.get("containers", {})
        if not containers:
            return 0
        if trigger == "cpu":
            values = [c.get("cpu_percent", 0) for c in containers.values()]
            return sum(values) / len(values) if values else 0
        elif trigger == "mem":
            values = [c.get("mem_percent", 0) for c in containers.values()]
            return sum(values) / len(values) if values else 0
        else:
            values = [c.get("requests_per_sec", 0) for c in containers.values()]
            return sum(values) if values else 0

    def _start_lb(self, stack_name, stack_config):
        self._stop_lb(stack_name)
        port = stack_config.get("port")
        containers = stack_config.get("containers", [])
        algo = stack_config.get("load_balance", "least_conn")
        if not port or not containers:
            return

        backends = []
        for cname in containers:
            info = self._get_container_info(cname)
            if info and info.get("status") == "running":
                svc_port = self._get_service_port(cname)
                # Isolated mode: the container service is reachable on the
                # host through ank_portproxy at 127.0.0.1:host_port.
                backends.append(f"127.0.0.1:{svc_port}")

        if not backends:
            _log(f"WARN: No running backends for '{stack_name}'")
            return

        try:
            from ank_lb import LoadBalancer
            lb = LoadBalancer(port=int(port), backends=backends, algo=algo, stack_name=stack_name)
            lb.start()
            self._lb_instances[stack_name] = lb
            _log(f"LB started for '{stack_name}' on port {port} ({len(backends)} backends, algo={algo})")
        except Exception as e:
            _log(f"LB start failed for '{stack_name}': {e}")

    def _stop_lb(self, stack_name):
        lb = self._lb_instances.pop(stack_name, None)
        if lb:
            try:
                lb.stop()
            except Exception:
                pass

    def _get_lb_status(self, stack_name):
        lb = self._lb_instances.get(stack_name)
        if lb:
            return lb.get_metrics()
        return {"running": False}

    def _get_service_port(self, cname):
        config = load_container_config(cname)
        if not config:
            return 80
        for pm in config.get("port_mappings", []):
            if pm.get("container_port"):
                try:
                    return int(pm["container_port"])
                except (ValueError, TypeError):
                    pass
        ank_dir = os.path.join(CONTAINERS_DIR, cname, "merged", "etc", "ankd", "services.d")
        for f in glob.glob(os.path.join(ank_dir, "*.ankd")):
            try:
                with open(f) as fh:
                    for line in fh:
                        if line.startswith("PORT="):
                            try:
                                return int(line.split("=", 1)[1].strip())
                            except (ValueError, TypeError):
                                pass
            except (OSError, ValueError):
                continue
        return 80

    def _load_stack_config(self, name):
        path = os.path.join(STACKS_DIR, name, "config.json")
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _save_stack_config(self, name, config):
        stack_dir = os.path.join(STACKS_DIR, name)
        os.makedirs(stack_dir, exist_ok=True)
        path = os.path.join(stack_dir, "config.json")
        with open(path, "w") as f:
            json.dump(config, f, indent=2)

    def _count_running(self, stack_config):
        count = 0
        for cname in stack_config.get("containers", []):
            info = self._get_container_info(cname)
            if info and info.get("status") == "running":
                count += 1
        return count

    def _get_container_info(self, cname):
        config = load_container_config(cname)
        if not config:
            return None
        if config.get("status") == "running":
            try:
                pid = config.get("pid")
                if pid:
                    os.kill(int(pid), 0)
                else:
                    config["status"] = "stopped"
            except (OSError, ValueError):
                config["status"] = "stopped"
                config["pid"] = None
        return {
            "name": cname,
            "status": config.get("status", "unknown"),
            "ip": config.get("ip_address", ""),
            "ssh_port": config.get("ssh_port"),
            "pid": config.get("pid"),
            "image": config.get("image", ""),
        }

    def _get_container_metrics(self, cname):
        config = load_container_config(cname)
        if not config or config.get("status") != "running":
            return None
        return {
            "cpu_percent": 0,
            "mem_percent": 0,
            "mem_bytes": 0,
            "mem_limit": 0,
            "pids": 0,
            "requests_per_sec": 0,
        }

    def _pick_least_loaded(self, containers):
        best = None
        best_load = float("inf")
        for cname in containers:
            metrics = self._get_container_metrics(cname)
            if not metrics:
                continue
            load = metrics.get("cpu_percent", 0) + metrics.get("mem_percent", 0)
            if load < best_load:
                best_load = load
                best = cname
        return best

    def _create_stack_container(self, stack_name, cname, template, root_password, ankfile="", shared_volume=False):
        parsed = None
        if ankfile:
            parsed = self._parse_ankfile(ankfile)
            template_id = "ankfile"
            image = parsed.get("base_image", "ank-alpinebase-3.20")
            pkgs = parsed.get("pkgs", "")
        else:
            template_id = template
            spec = _TEMPLATE_SPECS.get(template)
            if spec:
                # Distinct image name so container.sh builds it with pkgs
                # (same mechanism as the deploy path in server.py).
                image = f"{template}-3.20"
                pkgs = spec["pkgs"]
            else:
                image = "ank-alpinebase-3.20"
                pkgs = ""
        spec = _TEMPLATE_SPECS.get(template_id)

        ssh_port = _get_free_ssh_port()
        service_port = _get_free_service_port(extra_used={ssh_port})
        ankd_port = _get_free_ankd_port(extra_used={ssh_port, service_port})

        _log(f"Creating container '{cname}' (template={template_id}, ssh={ssh_port}, "
             f"service={service_port}, ankd={ankd_port})")
        output, code = run_script("container.sh", "create", cname, image, root_password,
                                  str(ssh_port), pkgs, template_id)
        if code != 0:
            _log(f"ERROR: Failed to create '{cname}': {output}")
            return False

        config = load_container_config(cname) or {}
        config["template"] = template_id
        config["template_id"] = template_id
        config["image"] = image
        config["ankd_port"] = ankd_port
        if spec:
            config["port_mappings"] = [{"host_port": service_port,
                                        "container_port": service_port,
                                        "protocol": "tcp"}]
            config["serves_static"] = True
            config["static_path"] = spec["static_path"]
        save_container_config(cname, config)

        if parsed:
            self._apply_ankfile_config(cname, parsed)
        if spec:
            self._apply_stack_service(cname, template_id, service_port)

        if shared_volume:
            stack_data_dir = os.path.join(STACKS_DIR, stack_name, "data")
            merged_dir = os.path.join(CONTAINERS_DIR, cname, "merged")
            data_mount = parsed.get("volumes", ["/var/www/data"])[0] if parsed else "/var/www/data"
            if os.path.isdir(stack_data_dir) and os.path.isdir(merged_dir):
                target = os.path.join(merged_dir, data_mount.lstrip("/"))
                os.makedirs(target, exist_ok=True)

        output, code = run_script("container.sh", "start", cname)
        if code != 0:
            _log(f"ERROR: Failed to start '{cname}': {output}")
            return False
        return True

    @staticmethod
    def _stack_index_html(template_id, port):
        return ('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
                f'<title>ANK Stack - {template_id}</title>'
                '<style>*{margin:0;padding:0;box-sizing:border-box}'
                'body{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;'
                'min-height:100vh;display:flex;align-items:center;justify-content:center}'
                '.card{background:#1e293b;border-radius:16px;padding:48px;text-align:center}'
                'h1{font-weight:800}</style></head><body><div class="card">'
                '<h1>ANK Stack</h1>'
                f'<p>{template_id} replica listening on :{port}</p>'
                '</div></body></html>')

    def _apply_stack_service(self, cname, template_id, port):
        """Mirror the deploy-time service setup (server.py template deploy)
        so the replica actually listens on the mapped port."""
        merged = os.path.join(CONTAINERS_DIR, cname, "merged")
        spec = _TEMPLATE_SPECS.get(template_id, {})
        static_path = spec.get("static_path", "")
        html = self._stack_index_html(template_id, port)

        def _write(rel, content):
            path = os.path.join(merged, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)

        try:
            _write(os.path.join("etc", "ank", "config"),
                   f"service={template_id}\nport={port}\nstatic_path={static_path}\n")

            if template_id == "nginx":
                os.makedirs(os.path.join(merged, "run", "nginx"), exist_ok=True)
                _write(os.path.join("var", "www", "html", "index.html"), html)
                _write(os.path.join("etc", "nginx", "nginx.conf"),
                       "daemon off;\nuser root;\n"
                       "events { worker_connections 1024; }\n"
                       "http {\n    include /etc/nginx/mime.types;\n"
                       "    default_type application/octet-stream;\n"
                       "    server {\n"
                       f"        listen {port};\n"
                       "        root /var/www/html;\n"
                       "        index index.html;\n"
                       "        location / { try_files $uri $uri/ =404; }\n"
                       "    }\n}\n")
            elif template_id == "apache":
                _write(os.path.join("var", "www", "localhost", "htdocs", "index.html"), html)
                httpd = os.path.join(merged, "etc", "apache2", "httpd.conf")
                if os.path.isfile(httpd):
                    with open(httpd) as f:
                        conf = f.read()
                    conf2, n = re.subn(r"(?m)^Listen\s+\d+", f"Listen {port}", conf, count=1)
                    if n:
                        with open(httpd, "w") as f:
                            f.write(conf2)
            elif template_id == "php":
                _write(os.path.join("var", "www", "php", "index.php"),
                       "<?php echo '<!DOCTYPE html><html><head><meta charset=\"UTF-8\">"
                       "<title>ANK Stack - PHP</title></head><body>"
                       "<h1>ANK Stack</h1><p>PHP replica listening on :" + str(port) +
                       "</p></body></html>'; ?>\n")
            elif template_id == "node":
                _write(os.path.join("var", "www", "app", "server.js"),
                       "const http = require('http');\n"
                       "const srv = http.createServer((req, res) => {\n"
                       "    res.writeHead(200, {'Content-Type': 'text/html'});\n"
                       f"    res.end({json.dumps(html)});\n"
                       "});\n"
                       f"const PORT = process.env.ANK_PORT || {port};\n"
                       "srv.listen(PORT, () => console.log('ANK stack replica on :' + PORT));\n")
                _write(os.path.join("var", "www", "app", "package.json"),
                       '{"name":"ank-stack-app","version":"1.0.0","main":"server.js"}\n')
            elif template_id == "python":
                _write(os.path.join("var", "www", "app", "server.py"),
                       "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
                       "import os\n"
                       f"HTML = {html!r}\n"
                       "class Handler(BaseHTTPRequestHandler):\n"
                       "    def do_GET(self):\n"
                       "        self.send_response(200)\n"
                       "        self.send_header('Content-Type', 'text/html')\n"
                       "        self.end_headers()\n"
                       "        self.wfile.write(HTML.encode())\n"
                       "    def log_message(self, fmt, *args):\n"
                       "        pass\n"
                       f"HTTPServer(('0.0.0.0', int(os.environ.get('ANK_PORT', '{port}'))), "
                       "Handler).serve_forever()\n")

            # Point the generated service definition at the mapped port so
            # ankd health checks match (php also needs its CMD port patched:
            # the built-in server port lives in the command line).
            svc_dir = os.path.join(merged, "etc", "ankd", "services.d")
            for fn in sorted(os.listdir(svc_dir)) if os.path.isdir(svc_dir) else []:
                if not fn.endswith(".ankd") or "sshd" in fn:
                    continue
                path = os.path.join(svc_dir, fn)
                with open(path) as f:
                    lines = f.readlines()
                with open(path, "w") as f:
                    for line in lines:
                        if line.startswith("PORT="):
                            f.write(f"PORT={port}\n")
                        elif template_id == "php" and line.startswith("CMD="):
                            f.write(f"CMD=php82 -S 0.0.0.0:{port} -t /var/www/php\n")
                        else:
                            f.write(line)
            _log(f"Service config applied for '{cname}' ({template_id} on port {port})")
        except Exception as e:
            _log(f"WARN: service config for '{cname}' failed: {e}")

    def _parse_ankfile(self, content):
        result = {
            "base_image": "ank-alpinebase-3.20", "pkgs": "", "workdir": "/",
            "cmd": "", "ports": [], "volumes": [], "root_password": "", "run_commands": [],
        }
        pkgs = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("FROM "):
                base = line.split(" ", 1)[1].strip()
                if base.startswith("alpine-"):
                    base = f"ank-alpinebase-{base[7:]}"
                elif not base.startswith("ank-"):
                    base = f"ank-alpinebase-{base}"
                result["base_image"] = base
            elif line.startswith("PASSWD "):
                result["root_password"] = line[7:].strip()
            elif line.startswith("RUN "):
                cmd = line[4:].strip()
                result["run_commands"].append(cmd)
                for pkg in cmd.replace("apk add", "").replace("--no-cache", "").split():
                    if not pkg.startswith("-") and pkg not in ("apk", "add", "&&", "||"):
                        pkgs.append(pkg)
            elif line.startswith("CMD "):
                result["cmd"] = line[4:].strip().strip('"').strip("'")
            elif line.startswith("EXPOSE "):
                try:
                    result["ports"].append(int(line[7:].strip()))
                except ValueError:
                    pass
            elif line.startswith("WORKDIR "):
                result["workdir"] = line[8:].strip()
            elif line.startswith("VOLUME "):
                result["volumes"].append(line[7:].strip())
        result["pkgs"] = " ".join(pkgs)
        return result

    def _apply_ankfile_config(self, cname, parsed):
        config = load_container_config(cname)
        if not config:
            return
        if parsed.get("workdir"):
            config["workdir"] = parsed["workdir"]
        if parsed.get("cmd"):
            config["cmd"] = parsed["cmd"]
        if parsed.get("ports"):
            config["exposed_ports"] = parsed["ports"]
        config["source"] = "ankfile"
        save_container_config(cname, config)

    def _destroy_container(self, cname):
        config = load_container_config(cname)
        if config and config.get("status") == "running":
            run_script("container.sh", "stop", cname)
        run_script("container.sh", "delete", cname)
        _log(f"Container '{cname}' destroyed")

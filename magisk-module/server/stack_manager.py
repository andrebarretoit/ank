#!/usr/bin/env python3
"""
ANK Stack Manager - Manages groups of identical containers with load balancing and auto-scaling.

A stack is a group of N identical containers created from the same template,
with a load balancer distributing traffic between them.
"""

import os
import json
import time
import threading
import subprocess
import glob

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
STACKS_DIR = os.path.join(ANK_DIR, "stacks")
CONTAINERS_DIR = os.path.join(ANK_DIR, "containers")
LB_PORT_RANGE = (30000, 39999)
SCRIPTS_DIR = os.path.join(ANK_DIR, "core")

try:
    from server import run_script, load_container_config, save_container_config, load_config
except ImportError:
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

    def load_config():
        config_file = os.path.join(ANK_DIR, "config.json")
        try:
            with open(config_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"version": "2.0.0", "panel_port": 8001, "username": "admin",
                    "password": "admin123", "first_boot": True,
                    "network": {"bridge": "ank0", "subnet": "10.20.30.0",
                                "gateway": "10.20.30.1", "nat": True}}


def _log(msg):
    print(f"[STACK] {msg}", flush=True)


def _find_free_port(start=LB_PORT_RANGE[0], end=LB_PORT_RANGE[1]):
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
    for cfg_file in glob.glob(os.path.join(STACKS_DIR, "*/config.json")):
        try:
            with open(cfg_file) as f:
                cfg = json.load(f)
            p = cfg.get("port")
            if p:
                used.add(int(p))
        except Exception:
            pass
    for port in range(start, end):
        if port not in used:
            try:
                s = __import__("socket").socket(__import__("socket").AF_INET, __import__("socket").SOCK_STREAM)
                s.settimeout(0.1)
                result = s.connect_ex(("127.0.0.1", port))
                s.close()
                if result != 0:
                    return port
            except Exception:
                return port
    return start


def _get_free_ssh_port():
    return _find_free_port(2200, 65000)


class StackManager:
    def __init__(self):
        os.makedirs(STACKS_DIR, exist_ok=True)
        self._lock = threading.Lock()
        self._scale_timers = {}

    def list_stacks(self):
        stacks = []
        if not os.path.isdir(STACKS_DIR):
            return stacks
        for name in sorted(os.listdir(STACKS_DIR)):
            stack_dir = os.path.join(STACKS_DIR, name)
            if not os.path.isdir(stack_dir):
                continue
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
        return config

    def create_stack(self, config):
        name = config.get("name", "")
        if not name or not all(c.isalnum() or c in "-_" for c in name):
            raise ValueError("Invalid stack name")
        if self._load_stack_config(name):
            raise ValueError(f"Stack '{name}' already exists")
        template = config.get("template", "nginx")
        ankfile = config.get("ankfile", "")
        min_containers = max(1, config.get("min", 1))
        max_containers = max(min_containers, config.get("max", 10))
        port = config.get("port") or _find_free_port()
        port = int(port)
        root_password = config.get("root_password", "ankstack")
        trigger = config.get("trigger", "requests")
        threshold_up = config.get("threshold_up", 100)
        threshold_down = config.get("threshold_down", 20)
        scale_up_after = config.get("scale_up_after", 30)
        scale_down_after = config.get("scale_down_after", 120)
        load_balance = config.get("load_balance", "least_conn")
        stack_config = {
            "name": name,
            "template": template,
            "ankfile": ankfile,
            "port": port,
            "min": min_containers,
            "max": max_containers,
            "trigger": trigger,
            "threshold_up": threshold_up,
            "threshold_down": threshold_down,
            "scale_up_after": scale_up_after,
            "scale_down_after": scale_down_after,
            "load_balance": load_balance,
            "containers": [],
            "status": "active",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "metrics": {"requests_total": 0, "last_scale_event": 0}
        }
        stack_dir = os.path.join(STACKS_DIR, name)
        data_dir = os.path.join(stack_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        self._save_stack_config(name, stack_config)
        _log(f"Stack '{name}' created (template={template}, port={port})")
        created = []
        for i in range(min_containers):
            cname = f"stack-{name}-{i + 1}"
            if self._create_stack_container(name, cname, template, root_password, ankfile=ankfile):
                created.append(cname)
                stack_config["containers"].append(cname)
        self._save_stack_config(name, stack_config)
        if created:
            self._setup_load_balancer(name, stack_config)
            _log(f"Stack '{name}': created {len(created)} containers, LB on port {port}")
        return stack_config

    def update_stack(self, name, config):
        stack_config = self._load_stack_config(name)
        if not stack_config:
            raise ValueError(f"Stack '{name}' not found")
        allowed = ("min", "max", "trigger", "threshold_up", "threshold_down",
                    "scale_up_after", "scale_down_after", "load_balance")
        for key in allowed:
            if key in config:
                stack_config[key] = config[key]
        if "min" in config or "max" in config:
            stack_config["max"] = max(stack_config["min"], stack_config["max"])
        self._save_stack_config(name, stack_config)
        self._setup_load_balancer(name, stack_config)
        _log(f"Stack '{name}' updated")
        return stack_config

    def delete_stack(self, name):
        stack_config = self._load_stack_config(name)
        if not stack_config:
            raise ValueError(f"Stack '{name}' not found")
        for cname in list(stack_config.get("containers", [])):
            self._destroy_container(cname)
        self._remove_load_balancer(name, stack_config)
        timer = self._scale_timers.pop(name, None)
        if timer:
            timer.cancel()
        stack_dir = os.path.join(STACKS_DIR, name)
        try:
            import shutil
            shutil.rmtree(stack_dir, ignore_errors=True)
        except Exception:
            pass
        _log(f"Stack '{name}' deleted")
        return True

    def scale_up(self, stack_name):
        stack_config = self._load_stack_config(stack_name)
        if not stack_config:
            raise ValueError(f"Stack '{stack_name}' not found")
        current = len(stack_config.get("containers", []))
        max_c = stack_config.get("max", 10)
        if current >= max_c:
            _log(f"Stack '{stack_name}' at max capacity ({max_c})")
            return False
        idx = current + 1
        cname = f"stack-{stack_name}-{idx}"
        root_password = stack_config.get("root_password", "ankstack")
        ankfile = stack_config.get("ankfile", "")
        if self._create_stack_container(stack_name, cname, stack_config["template"], root_password, ankfile=ankfile):
            stack_config["containers"].append(cname)
            self._save_stack_config(stack_name, stack_config)
            self._setup_load_balancer(stack_name, stack_config)
            _log(f"Stack '{stack_name}' scaled up: {cname} added")
            return True
        return False

    def scale_down(self, stack_name):
        stack_config = self._load_stack_config(stack_name)
        if not stack_config:
            raise ValueError(f"Stack '{stack_name}' not found")
        containers = stack_config.get("containers", [])
        min_c = stack_config.get("min", 1)
        if len(containers) <= min_c:
            _log(f"Stack '{stack_name}' at min capacity ({min_c})")
            return False
        target = self._pick_least_loaded(container_name=containers)
        if target is None:
            target = containers[-1]
        self._destroy_container(target)
        if target in stack_config["containers"]:
            stack_config["containers"].remove(target)
        self._save_stack_config(stack_name, stack_config)
        self._setup_load_balancer(stack_name, stack_config)
        _log(f"Stack '{stack_name}' scaled down: {target} removed")
        return True

    def get_metrics(self, stack_name):
        stack_config = self._load_stack_config(stack_name)
        if not stack_config:
            raise ValueError(f"Stack '{stack_name}' not found")
        metrics = {
            "stack_name": stack_name,
            "total_containers": len(stack_config.get("containers", [])),
            "running_containers": self._count_running(stack_config),
            "containers": {}
        }
        for cname in stack_config.get("containers", []):
            cmetrics = self._get_container_metrics(cname)
            if cmetrics:
                metrics["containers"][cname] = cmetrics
        return metrics

    def auto_scale_check(self):
        for name in self.list_stacks():
            if name.get("status") != "active":
                continue
            stack_name = name["name"]
            self._evaluate_scaling(stack_name)

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

    def _load_stack_config(self, name):
        path = os.path.join(STACKS_DIR, name, "config.json")
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _save_stack_config(self, name, config):
        stack_dir = os.path.join(STACKS_DIR, name)
        os.makedirs(stack_dir, exist_ok=True)
        path = os.path.join(stack_dir, "config.json")
        with open(path, "w") as f:
            json.dump(config, f, indent=2)
        try:
            os.chmod(path, 0o666)
        except Exception:
            pass

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
            "image": config.get("image", "")
        }

    def _get_container_metrics(self, cname):
        cgroup = f"/sys/fs/cgroup/ank/{cname}"
        if not os.path.isdir(cgroup):
            return {"cpu_percent": 0, "mem_percent": 0, "mem_bytes": 0,
                    "mem_limit": 0, "pids": 0, "requests_per_sec": 0}
        mem = 0
        mem_limit = 0
        cpu_usage = 0
        pids = 0
        try:
            for fname in ("memory.current", "memory.usage_in_bytes"):
                p = os.path.join(cgroup, fname)
                if os.path.isfile(p):
                    with open(p) as fh:
                        mem = int(fh.read().strip())
                    break
            for fname in ("memory.max", "memory.limit_in_bytes"):
                p = os.path.join(cgroup, fname)
                if os.path.isfile(p):
                    with open(p) as fh:
                        v = fh.read().strip()
                    if v and v != "max":
                        mem_limit = int(v)
                    break
            p = os.path.join(cgroup, "cpu.stat")
            if os.path.isfile(p):
                with open(p) as fh:
                    for line in fh:
                        if line.startswith("usage_usec"):
                            cpu_usage = int(line.split()[1]) // 1000
                            break
            for fname in ("pids.current", "pids.max"):
                p = os.path.join(cgroup, fname)
                if os.path.isfile(p):
                    with open(p) as fh:
                        v = fh.read().strip()
                    if v and v != "max":
                        pids = int(v)
                    break
        except (ValueError, OSError):
            pass
        mem_percent = 0
        if mem_limit > 0:
            mem_percent = round((mem / mem_limit) * 100, 1)
        return {
            "cpu_percent": min(100, round(cpu_usage / 100, 1)) if cpu_usage > 0 else 0,
            "mem_percent": mem_percent,
            "mem_bytes": mem,
            "mem_limit": mem_limit,
            "pids": pids,
            "requests_per_sec": self._estimate_rps(cname)
        }

    def _estimate_rps(self, cname):
        config = load_container_config(cname)
        if not config or config.get("status") != "running":
            return 0
        return 0

    def _create_stack_container(self, stack_name, cname, template, root_password, ankfile=""):
        ssh_port = _get_free_ssh_port()
        image = f"ank-alpinebase-3.20"
        pkgs = ""
        custom_workdir = "/"
        custom_cmd = ""
        custom_ports = []

        if ankfile:
            parsed = self._parse_ankfile(ankfile)
            image = parsed.get("base_image", image)
            pkgs = parsed.get("pkgs", "")
            custom_workdir = parsed.get("workdir", "/")
            custom_cmd = parsed.get("cmd", "")
            custom_ports = parsed.get("ports", [])
            template = "ankfile"
            _log(f"Creating container '{cname}' (ankfile, image={image}, port={ssh_port})")
        else:
            if template == "nginx":
                pkgs = "nginx"
            elif template == "apache":
                pkgs = "apache2"
            elif template == "php":
                pkgs = "php82 php82-cgi"
            elif template == "node":
                pkgs = "nodejs npm"
            elif template == "python":
                pkgs = "python3"
            _log(f"Creating container '{cname}' (template={template}, port={ssh_port})")

        output, code = run_script(
            "container.sh", "create", cname, image, root_password, str(ssh_port), pkgs
        )
        if code != 0:
            _log(f"ERROR: Failed to create '{cname}': {output}")
            return False

        if ankfile:
            self._apply_ankfile_config(cname, parsed)

        stack_data_dir = os.path.join(STACKS_DIR, stack_name, "data")
        container_dir = os.path.join(CONTAINERS_DIR, cname)
        merged_dir = os.path.join(container_dir, "merged")
        data_mount = self._get_data_mount_path(template) if not ankfile else (parsed.get("volumes", ["/var/www/data"])[0] if parsed.get("volumes") else "/var/www/data")
        if data_mount and os.path.isdir(stack_data_dir) and os.path.isdir(merged_dir):
            target = os.path.join(merged_dir, data_mount.lstrip("/"))
            os.makedirs(target, exist_ok=True)
            output, code = run_script("container.sh", "start", cname)
            if code == 0:
                self._bind_mount(stack_data_dir, target)
        output, code = run_script("container.sh", "start", cname)
        if code != 0:
            _log(f"ERROR: Failed to start '{cname}': {output}")
            return False
        return True

    def _parse_ankfile(self, content):
        """Parse an Ankfile and return structured build info."""
        result = {
            "base_image": "ank-alpinebase-3.20",
            "pkgs": "",
            "workdir": "/",
            "cmd": "",
            "ports": [],
            "volumes": [],
            "root_password": "",
            "run_commands": []
        }
        pkgs = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("FROM "):
                base = line.split(" ", 1)[1].strip()
                # Map alpine-X.Y to ank-alpinebase-X.Y
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
                for pkg in cmd.replace("apk add", "").replace("--no-cache", "").replace("--allow-untrusted", "").split():
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
        result["pkgs"] = " ".join(pkgs) if pkgs else ""
        return result

    def _apply_ankfile_config(self, cname, parsed):
        """Apply ankfile WORKDIR/CMD/VOLUME to container config."""
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

    def _get_data_mount_path(self, template):
        paths = {
            "nginx": "/var/www/html",
            "apache": "/var/www/localhost/htdocs",
            "php": "/var/www/php",
            "node": "/var/www/app",
            "python": "/var/www/app"
        }
        return paths.get(template)

    def _bind_mount(self, host_path, container_path):
        output, code = run_script(
            "container.sh", "exec", "mount", "--bind", host_path, container_path
        )
        if code != 0:
            _log(f"WARN: bind mount failed: {host_path} -> {container_path}")

    def _destroy_container(self, cname):
        config = load_container_config(cname)
        if config and config.get("status") == "running":
            run_script("container.sh", "stop", cname)
        run_script("container.sh", "delete", cname)
        _log(f"Container '{cname}' destroyed")

    def _pick_least_loaded(self, container_name=None):
        if container_name is None:
            return None
        best = None
        best_load = float("inf")
        for cname in container_name:
            metrics = self._get_container_metrics(cname)
            load = metrics.get("cpu_percent", 0) + metrics.get("mem_percent", 0)
            if load < best_load:
                best_load = load
                best = cname
        return best

    def _setup_load_balancer(self, stack_name, stack_config):
        port = stack_config.get("port")
        containers = stack_config.get("containers", [])
        lb_algorithm = stack_config.get("load_balance", "least_conn")
        if not port or not containers:
            return
        _log(f"Setting up LB for '{stack_name}' on port {port} (algorithm={lb_algorithm})")
        self._remove_iptables_rules(port)
        running = []
        for cname in containers:
            info = self._get_container_info(cname)
            if info and info.get("status") == "running" and info.get("ip"):
                running.append(info)
        if not running:
            _log(f"WARN: No running containers for LB in '{stack_name}'")
            return
        if lb_algorithm == "round_robin" or len(running) <= 1:
            for info in running:
                self._add_iptables_rule(port, info["ip"], info.get("ssh_port", 22))
        elif lb_algorithm == "least_conn":
            self._add_iptables_rule(port, running[0]["ip"], running[0].get("ssh_port", 22))
        elif lb_algorithm == "ip_hash":
            for info in running:
                self._add_iptables_rule(port, info["ip"], info.get("ssh_port", 22))
        _log(f"LB configured: {len(running)} backends for port {port}")

    def _add_iptables_rule(self, host_port, container_ip, container_port=80):
        cmd = f"iptables -t nat -A PREROUTING -p tcp --dport {host_port} -j DNAT --to-destination {container_ip}:{container_port}"
        try:
            subprocess.run(["su", "-c", cmd], capture_output=True, text=True, timeout=10)
        except Exception as e:
            _log(f"WARN: iptables add failed: {e}")

    def _remove_iptables_rules(self, port):
        cmd = f"iptables -t nat -S PREROUTING | grep '\\-\\-dport {port} '"
        try:
            result = subprocess.run(["su", "-c", cmd], capture_output=True, text=True, timeout=10)
            for line in result.stdout.strip().split("\n"):
                if line.startswith("-A"):
                    del_cmd = line.replace("-A", "-D", 1)
                    subprocess.run(["su", "-c", f"iptables -t nat {del_cmd}"],
                                   capture_output=True, text=True, timeout=10)
        except Exception:
            pass

    def _remove_load_balancer(self, stack_name, stack_config):
        port = stack_config.get("port")
        if port:
            self._remove_iptables_rules(port)
            _log(f"LB removed for '{stack_name}' (port {port})")

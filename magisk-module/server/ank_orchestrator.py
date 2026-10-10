import os
import json
import time
import threading
import glob

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
STACKS_DIR = os.path.join(ANK_DIR, "stacks")
CONTAINERS_DIR = os.path.join(ANK_DIR, "containers")
LOGS_DIR = os.path.join(ANK_DIR, "logs")


def _log(msg):
    print(f"[ORCH] {msg}", flush=True)


class Orchestrator:
    """Supervisor loop: reconciles the load balancers and the userspace
    portproxy forwards every tick, then evaluates stack auto-scaling."""

    def __init__(self, stack_manager):
        self.stack_manager = stack_manager
        self._thread = None
        self._running = False
        self._interval = 10
        self._scale_state = {}
        self._ppm = None

    def start(self, interval=10):
        """Start the orchestrator background thread"""
        self._running = True
        self._interval = interval
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _get_ppm(self):
        if self._ppm is None:
            from ank_portproxy import PortProxyManager
            self._ppm = PortProxyManager(
                log=lambda m: _log(f"[PORTPROXY] {m}"))
        return self._ppm

    def _loop(self):
        """Main supervisor loop"""
        first = True
        while self._running:
            try:
                self._reconcile(first=first)
                stacks = self.stack_manager.list_stacks()
                for stack in stacks:
                    if stack.get("status") == "active":
                        self._check_stack(stack)
            except Exception as e:
                _log(f"tick error: {e}")
            first = False
            time.sleep(self._interval)

    def _reconcile(self, first=False):
        """Bring reality back to the desired state: every active stack with
        containers has a live LB, and every container's ports are forwarded
        through ank_portproxy (releases stale entries automatically)."""
        ppm = self._get_ppm()

        # -- restore missing LBs (boot, crash, rollback) --
        for stack in self.stack_manager.list_stacks():
            if stack.get("status") != "active":
                continue
            name = stack.get("name")
            if not stack.get("containers"):
                continue
            if name not in self.stack_manager._lb_instances:
                if first:
                    _log(f"[RECONCILE] restoring LB for stack '{name}'")
                self.stack_manager._start_lb(name, stack)

        # -- portproxy forwards for every root-mode container --
        desired = {}
        for cfg_file in glob.glob(os.path.join(CONTAINERS_DIR, "*/config.json")):
            cname = os.path.basename(os.path.dirname(cfg_file))
            try:
                with open(cfg_file) as f:
                    cfg = json.load(f)
            except Exception:
                continue
            if cfg.get("mode") == "lite":
                continue  # proot containers share the host network
            if cfg.get("status") in ("failed", "deleting"):
                continue
            ip = cfg.get("ip_address", "")
            try:
                ssh_port = int(cfg.get("ssh_port") or 0)
            except (TypeError, ValueError):
                ssh_port = 0
            # SSH: same host port into the container's netns
            if ip and ssh_port:
                desired[ssh_port] = (ip, ssh_port)
            for pm in cfg.get("port_mappings", []):
                try:
                    hp = int(pm.get("host_port"))
                    cp = int(pm.get("container_port"))
                except (TypeError, ValueError):
                    continue
                if ip:
                    # Isolated/bridge container: host port -> container ip
                    desired[hp] = (ip, cp)
                else:
                    # Legacy compat: service already on the host loopback.
                    # hp==cp needs no forward; hp!=cp maps to 127.0.0.1:cp.
                    if hp != cp:
                        desired[hp] = ("127.0.0.1", cp)
        ppm.reconcile(desired)

    def _check_stack(self, stack):
        """Check if a stack needs scaling"""
        name = stack["name"]
        trigger = stack.get("trigger", "requests")
        # Guard: a none/null trigger means "never auto-scale this stack"
        if trigger is None or str(trigger).strip().lower() in ("", "none"):
            return
        current_count = len(stack.get("containers", []))
        trigger = stack.get("trigger", "requests")
        threshold_up = stack.get("threshold_up", 100)
        threshold_down = stack.get("threshold_down", 20)
        scale_up_after = stack.get("scale_up_after", 30)
        scale_down_after = stack.get("scale_down_after", 120)
        min_count = stack.get("min", 1)
        max_count = stack.get("max", 10)

        metrics = self._get_stack_metrics(stack)

        if name not in self._scale_state:
            self._scale_state[name] = {
                "up_start": 0,
                "down_start": 0,
                "last_scale_up": 0,
                "last_scale_down": 0,
            }
        state = self._scale_state[name]
        now = time.time()

        value = self._get_trigger_value(metrics, trigger)

        # Scale UP logic
        if value > threshold_up and current_count < max_count:
            if state["up_start"] == 0:
                state["up_start"] = now
            elif now - state["up_start"] >= scale_up_after:
                if now - state["last_scale_up"] >= 60:
                    self._scale_up(name)
                    state["last_scale_up"] = now
                    state["up_start"] = 0
        else:
            state["up_start"] = 0

        # Scale DOWN logic
        if value < threshold_down and current_count > min_count:
            if state["down_start"] == 0:
                state["down_start"] = now
            elif now - state["down_start"] >= scale_down_after:
                if now - state["last_scale_down"] >= 120:
                    self._scale_down(name)
                    state["last_scale_down"] = now
                    state["down_start"] = 0
        else:
            state["down_start"] = 0

    def _get_stack_metrics(self, stack):
        """Aggregate metrics for all containers in a stack"""
        containers = stack.get("containers", [])
        if not containers:
            return {
                "total_requests_per_sec": 0,
                "avg_cpu": 0,
                "avg_mem": 0,
                "per_container": [],
            }

        per_container = []
        total_cpu = 0.0
        total_mem = 0.0
        total_rps = 0.0
        count = 0

        for container_name in containers:
            m = self._get_container_metrics(container_name)
            if m is not None:
                per_container.append({"name": container_name, **m})
                total_cpu += m.get("cpu_percent", 0)
                total_mem += m.get("mem_percent", 0)
                count += 1
            rps = self._read_request_rate(container_name)
            total_rps += rps

        avg_cpu = total_cpu / count if count > 0 else 0
        avg_mem = total_mem / count if count > 0 else 0

        return {
            "total_requests_per_sec": total_rps,
            "avg_cpu": avg_cpu,
            "avg_mem": avg_mem,
            "per_container": per_container,
        }

    def _get_trigger_value(self, metrics, trigger):
        """Get the value to compare against thresholds"""
        if trigger == "requests":
            return metrics.get("total_requests_per_sec", 0)
        elif trigger == "cpu":
            return metrics.get("avg_cpu", 0)
        elif trigger == "mem":
            return metrics.get("avg_mem", 0)
        elif trigger == "combined":
            return max(metrics.get("avg_cpu", 0), metrics.get("avg_mem", 0))
        return 0

    def _scale_up(self, stack_name):
        """Add a container to the stack"""
        self.stack_manager.scale_up(stack_name)

    def _scale_down(self, stack_name):
        """Remove the least loaded container"""
        self.stack_manager.scale_down(stack_name)

    @staticmethod
    def _find_cgroup_path(container_name, *suffixes):
        """Probe multiple cgroup path patterns to find one that exists on this kernel."""
        prefix = f"ank-{container_name}"
        search_bases = [
            os.path.join("/sys/fs/cgroup/memory", prefix),
            os.path.join("/sys/fs/cgroup", prefix),
            os.path.join("/sys/fs/cgroup/cpuacct", prefix),
            os.path.join("/sys/fs/cgroup/pids", prefix),
        ]
        for base in search_bases:
            for suffix in suffixes:
                candidate = os.path.join(base, suffix)
                if os.path.exists(candidate):
                    return candidate
        return None

    def _get_container_metrics(self, container_name):
        """Read CPU and memory metrics for a container.

        Tries cgroup v1, then v2, then /proc fallback.
        Detects the correct cgroup path format for the device kernel version.

        Returns: {cpu_percent, mem_percent, mem_bytes, mem_limit, pid_count}
        """
        mem_bytes = 0
        mem_limit = 0
        cpu_usage_ns = 0
        pid_count = 0

        # --- cgroup memory (auto-detect v1/v2 paths) ---
        cg_mem = self._find_cgroup_path(container_name, "memory.usage_in_bytes", "memory.current")
        cg_limit = self._find_cgroup_path(container_name, "memory.limit_in_bytes", "memory.max")
        if cg_mem:
            mem_bytes = self._read_int_file(cg_mem)
            if cg_limit:
                mem_limit = self._read_int_file(cg_limit)
            if mem_limit == 0 or mem_limit == 0x7FFFFFFFFFFFFFFF:
                mem_limit = mem_bytes

        # --- cgroup cpu (auto-detect v1/v2 paths) ---
        cg_cpu = self._find_cgroup_path(container_name, "cpuacct.usage", "cpu.stat")
        if cg_cpu:
            if cg_cpu.endswith("cpuacct.usage"):
                cpu_usage_ns = self._read_int_file(cg_cpu)
            elif cg_cpu.endswith("cpu.stat"):
                cpu_usage_ns = self._read_cgroup2_cpu(cg_cpu)

        # --- pid count via cgroup procs or pids ---
        cg_pids = self._find_cgroup_path(container_name, "pids.current")
        if cg_pids:
            pid_count = self._read_int_file(cg_pids)
        else:
            pid_count = self._count_procs(container_name)

        # --- cpu percent (approximate) ---
        cpu_percent = 0.0
        if cpu_usage_ns > 0 and pid_count > 0:
            # cpu_usage_ns is total accumulated; approximate as usage / (1e9 * elapsed)
            # Since we lack per-interval delta here, report normalized load
            cpu_percent = min(100.0, (cpu_usage_ns / 1_000_000_000) / max(pid_count, 1) * 100)
            cpu_percent = round(cpu_percent, 2)

        # --- mem percent ---
        mem_percent = 0.0
        if mem_limit > 0:
            mem_percent = round((mem_bytes / mem_limit) * 100, 2)
            mem_percent = min(100.0, mem_percent)

        return {
            "cpu_percent": cpu_percent,
            "mem_percent": mem_percent,
            "mem_bytes": mem_bytes,
            "mem_limit": mem_limit,
            "pid_count": pid_count,
        }

    def _read_request_rate(self, container_name):
        """Read requests-per-second from a container's metrics endpoint."""
        metrics_dir = os.path.join(CONTAINERS_DIR, container_name, "metrics")
        rps_file = os.path.join(metrics_dir, "rps")
        if os.path.exists(rps_file):
            return self._read_float_file(rps_file)

        # Fallback: sum request counts from log tail
        log_path = os.path.join(LOGS_DIR, f"{container_name}.log")
        if not os.path.exists(log_path):
            return 0.0
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            if not lines:
                return 0.0
            recent = lines[-200:]
            cutoff = time.time() - 1.0
            count = 0
            for line in recent:
                try:
                    entry = json.loads(line)
                    ts = entry.get("ts", 0)
                    if ts >= cutoff:
                        count += 1
                except json.JSONDecodeError:
                    continue
            return float(count)
        except OSError:
            return 0.0

    @staticmethod
    def _read_int_file(path):
        try:
            with open(path, "r") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return 0

    @staticmethod
    def _read_float_file(path):
        try:
            with open(path, "r") as f:
                return float(f.read().strip())
        except (OSError, ValueError):
            return 0.0

    @staticmethod
    def _read_cgroup2_cpu(path):
        """Parse cpu.stat for usage_usec from cgroup v2."""
        try:
            with open(path, "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) == 2 and parts[0] == "usage_usec":
                        return int(parts[1]) * 1000  # convert to ns
            return 0
        except (OSError, ValueError):
            return 0

    @staticmethod
    def _count_procs(container_name):
        """Count processes by scanning /proc for matching container cgroup."""
        cgroup_path = f"ank-{container_name}"
        count = 0
        try:
            for pid_dir in glob.glob("/proc/[0-9]*/cgroup"):
                try:
                    with open(pid_dir, "r") as f:
                        content = f.read()
                    if cgroup_path in content:
                        count += 1
                except OSError:
                    continue
        except OSError:
            pass
        return count

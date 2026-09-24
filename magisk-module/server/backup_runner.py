import os
import subprocess
import time
import json
import datetime
import glob
import shlex

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
CONTAINERS_DIR = os.path.join(ANK_DIR, "containers")
SCRIPTS_DIR = os.path.join(ANK_DIR, "core")

SOURCE_TYPES = (
    "container_full",
    "engine_config",
    "system_complete",
    "container_selective",
    "node_full",
    "container_file",
)


class BackupRunner:
    def __init__(self, routine_config, log_file):
        self.config = routine_config
        self.log_file = log_file
        self.remote = routine_config.get("remote", {})

    def log(self, msg):
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"[{ts}] {msg}\n"
        try:
            with open(self.log_file, "a") as f:
                f.write(line)
        except OSError:
            pass

    def run(self):
        battery = self._get_battery()
        if battery is not None and battery < 10:
            self.log(f"CRITICAL: Battery {battery}% — aborting backup")
            return {"status": "aborted", "reason": "battery_critical", "size": 0, "remote_path": None}
        if battery is not None and battery < 15:
            self.log(f"WARNING: Battery {battery}% — running final backup")

        self.log("Backup started")
        self.log(f"Source type: {self.config.get('source_type', 'container_full')}")

        tar_path = self._create_archive()
        try:
            size = os.path.getsize(tar_path)
        except OSError:
            size = 0
        self.log(f"Archive created: {tar_path} ({size} bytes)")

        if size == 0:
            self.log("Archive empty — skipping upload")
            self._cleanup(tar_path)
            return {"status": "success", "remote_path": None, "size": 0}

        remote_path = self._upload(tar_path)
        self.log(f"Uploaded to: {remote_path}")

        if self.config.get("immutable", False):
            self._apply_immutability(remote_path)

        self._apply_retention()
        self._cleanup(tar_path)
        self.log("Backup completed")
        return {"status": "success", "remote_path": remote_path, "size": size}

    def _create_archive(self):
        routine_id = self.config.get("id", "unknown")
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        tar_name = f"{routine_id}-{ts}.tar.gz"
        tar_path = os.path.join("/tmp", tar_name)
        source_type = self.config.get("source_type", "container_full")

        if source_type == "container_full":
            sources = self._sources_container_full()
        elif source_type == "engine_config":
            sources = self._sources_engine_config()
        elif source_type == "system_complete":
            sources = [ANK_DIR]
        elif source_type == "container_selective":
            sources = self._sources_container_selective()
        elif source_type == "node_full":
            sources = self._sources_node_full()
        elif source_type == "container_file":
            sources = self._sources_container_file()
        else:
            sources = [ANK_DIR]

        sources = [s for s in sources if os.path.exists(s)]
        if not sources:
            sources = [ANK_DIR]

        incremental = self.config.get("backup_mode", "full") == "incremental"
        if incremental:
            return self._create_incremental(tar_path, sources, routine_id)
        else:
            cmd = ["tar", "-czf", tar_path] + sources
            subprocess.run(cmd, check=True, capture_output=True)
            return tar_path

    def _sources_container_full(self):
        sources = []
        if os.path.isdir(CONTAINERS_DIR):
            sources.append(CONTAINERS_DIR)
        nodes_dir = os.path.join(ANK_DIR, "nodes")
        if os.path.isdir(nodes_dir):
            sources.append(nodes_dir)
        return sources

    def _sources_engine_config(self):
        sources = []
        for name in ("config.json", "nodes", "stacks", "state"):
            p = os.path.join(ANK_DIR, name)
            if os.path.exists(p):
                sources.append(p)
        for d in ("core", "plugins", "skills", "agents"):
            p = os.path.join(ANK_DIR, d)
            if os.path.isdir(p):
                sources.append(p)
        return sources

    def _sources_container_selective(self):
        containers = self.config.get("containers", [])
        sources = []
        for c in containers:
            cpath = os.path.join(CONTAINERS_DIR, c)
            if os.path.exists(cpath):
                sources.append(cpath)
        nodes = self.config.get("nodes", [])
        for node_id in nodes:
            node_dir = os.path.join(ANK_DIR, "nodes", node_id)
            if os.path.isdir(node_dir):
                sources.append(node_dir)
        return sources

    def _sources_node_full(self):
        sources = []
        nodes = self.config.get("nodes", [])
        if not nodes:
            nodes_dir = os.path.join(ANK_DIR, "nodes")
            if os.path.isdir(nodes_dir):
                for n in os.listdir(nodes_dir):
                    nd = os.path.join(nodes_dir, n)
                    if os.path.isdir(nd):
                        sources.append(nd)
        else:
            for node_id in nodes:
                node_dir = os.path.join(ANK_DIR, "nodes", node_id)
                if os.path.isdir(node_dir):
                    sources.append(node_dir)
        config_file = os.path.join(ANK_DIR, "config.json")
        if os.path.isfile(config_file):
            sources.append(config_file)
        return sources

    def _sources_container_file(self):
        custom_paths = self.config.get("custom_paths", {})
        sources = []
        for container_name, paths in custom_paths.items():
            for p in paths:
                full = os.path.join(CONTAINERS_DIR, container_name, "merged", p.lstrip("/"))
                if os.path.exists(full):
                    sources.append(full)
        return sources

    def _create_incremental(self, tar_path, sources, routine_id):
        snapshot_file = os.path.join(ANK_DIR, "state", ".last_backup_time")
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        try:
            last_time = 0
            if os.path.isfile(snapshot_file):
                with open(snapshot_file, "r") as f:
                    last_time = float(f.read().strip())
            changed = []
            for src in sources:
                for root, dirs, filenames in os.walk(src):
                    for fn in filenames:
                        fp = os.path.join(root, fn)
                        try:
                            if os.path.getmtime(fp) > last_time:
                                changed.append(fp)
                        except OSError:
                            pass
            if not changed:
                self.log("No changed files since last backup")
                return tar_path
            list_file = os.path.join("/tmp", f"backup-list-{ts}.txt")
            with open(list_file, "w") as f:
                for fp in changed:
                    f.write(fp + "\n")
            cmd = ["tar", "-czf", tar_path, "-T", list_file]
            subprocess.run(cmd, check=True, capture_output=True)
            try:
                os.remove(list_file)
            except OSError:
                pass
        except (OSError, ValueError):
            cmd = ["tar", "-czf", tar_path] + sources
            subprocess.run(cmd, check=True, capture_output=True)

        os.makedirs(os.path.dirname(snapshot_file), exist_ok=True)
        with open(snapshot_file, "w") as f:
            f.write(str(time.time()))
        return tar_path

    def _upload(self, tar_path):
        host = self.remote.get("host", "")
        port = self.remote.get("port", 22)
        user = self.remote.get("user", "root")
        password = self.remote.get("password", "")
        remote_path = self.remote.get("path", "/backups/ank").rstrip("/")
        filename = os.path.basename(tar_path)
        remote_dest = f"{remote_path}/{filename}"
        from backup_manager import run_ssh_argv
        cmd = [
            "scp", "-P", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            tar_path,
            f"{user}@{host}:{remote_dest}"
        ]
        result = run_ssh_argv(cmd, password, timeout=600)
        if result.returncode != 0:
            self.log(f"SCP upload failed: {result.stderr}")
            raise RuntimeError(f"SCP upload failed: {result.stderr}")
        return remote_dest

    def _apply_retention(self):
        retention_days = self.config.get("retention_days", 30)
        if retention_days <= 0:
            return
        host = self.remote.get("host", "")
        port = self.remote.get("port", 22)
        user = self.remote.get("user", "root")
        password = self.remote.get("password", "")
        remote_path = shlex.quote(self.remote.get("path", "/backups/ank").rstrip("/"))
        from backup_manager import run_ssh_argv
        cmd = [
            "ssh", "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            f"{user}@{host}",
            f"find {remote_path} -maxdepth 1 -name '*.tar.gz' -mtime +{retention_days} -delete"
        ]
        result = run_ssh_argv(cmd, password, timeout=30)
        if result.returncode != 0:
            self.log(f"Retention cleanup failed: {result.stderr}")
        else:
            self.log(f"Retention: deleted backups older than {retention_days} days")

    def _apply_immutability(self, remote_path):
        host = self.remote.get("host", "")
        port = self.remote.get("port", 22)
        user = self.remote.get("user", "root")
        password = self.remote.get("password", "")
        filename = os.path.basename(remote_path)
        from backup_manager import run_ssh_argv

        cmd_detect = [
            "ssh", "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            f"{user}@{host}",
            "uname -s"
        ]
        result = run_ssh_argv(cmd_detect, password, timeout=10)
        os_type = result.stdout.strip().lower()

        if "linux" in os_type:
            immut_cmd = f"chattr +i {shlex.quote(remote_path)} 2>/dev/null || true"
        elif "darwin" in os_type:
            immut_cmd = f"chflags uchg {shlex.quote(remote_path)}"
        elif "mingw" in os_type or "msys" in os_type or "cygwin" in os_type:
            immut_cmd = f"attrib +R {shlex.quote(remote_path)}"
        else:
            self.log(f"Immutability: unsupported OS '{os_type}', skipping")
            return

        cmd = [
            "ssh", "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            f"{user}@{host}",
            immut_cmd
        ]
        result = run_ssh_argv(cmd, password, timeout=10)
        if result.returncode == 0:
            self.log(f"Immutability applied to {filename}")
        else:
            self.log(f"Immutability failed: {result.stderr}")

    def _cleanup(self, tar_path):
        try:
            os.remove(tar_path)
        except OSError:
            pass

    @staticmethod
    def _get_battery():
        paths = [
            "/sys/class/power_supply/battery/capacity",
            "/sys/class/power_supply/BAT0/capacity",
            "/sys/class/power_supply/bms/capacity",
        ]
        for p in paths:
            try:
                with open(p) as f:
                    return int(f.read().strip())
            except (OSError, ValueError):
                continue
        return None


def get_battery_status():
    level = BackupRunner._get_battery()
    if level is None:
        return {"level": None, "status": "unknown", "can_backup": True}
    if level >= 30:
        status = "normal"
    elif level >= 15:
        status = "priority"
    elif level >= 10:
        status = "warning"
    else:
        status = "critical"
    return {
        "level": level,
        "status": status,
        "can_backup": level >= 10,
        "should_cancel": level < 15,
        "final_backup": level < 10,
    }

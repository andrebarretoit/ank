import os
import subprocess
import time
import json
import datetime

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
CONTAINERS_DIR = os.path.join(ANK_DIR, "containers")


class BackupRunner:
    def __init__(self, routine_config, log_file):
        self.config = routine_config
        self.log_file = log_file
        self.remote = routine_config["remote"]

    def log(self, msg):
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"[{timestamp}] {msg}\n"
        try:
            with open(self.log_file, "a") as f:
                f.write(line)
        except OSError:
            pass

    def run(self):
        self.log("Backup started")
        tar_path = self._create_archive()
        try:
            size = os.path.getsize(tar_path)
        except OSError:
            size = 0
        self.log(f"Archive created: {tar_path} ({size} bytes)")
        remote_path = self._upload(tar_path)
        self.log(f"Uploaded to: {remote_path}")
        self._apply_retention()
        self._cleanup(tar_path)
        self.log("Backup completed")
        return {"status": "success", "remote_path": remote_path, "size": size}

    def _create_archive(self):
        backup_type = self.config.get("type", "full")
        routine_id = self.config.get("id", "unknown")
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        tar_name = f"{routine_id}-{ts}.tar.gz"
        tar_path = os.path.join("/tmp", tar_name)
        include_core = self.config.get("include_core", True)
        scope = self.config.get("scope", "all")
        containers = self.config.get("containers", [])

        sources = []
        if backup_type == "snapshot":
            state_dir = os.path.join(ANK_DIR, "state")
            if os.path.isdir(state_dir):
                sources.append(state_dir)
            proc_file = os.path.join(ANK_DIR, "processes.json")
            if os.path.isfile(proc_file):
                sources.append(proc_file)

        if scope in ("all", "selected"):
            if containers:
                for c in containers:
                    cpath = os.path.join(CONTAINERS_DIR, c)
                    if os.path.exists(cpath):
                        sources.append(cpath)
            else:
                if os.path.isdir(CONTAINERS_DIR):
                    sources.append(CONTAINERS_DIR)

        if include_core:
            core_dirs = ["config", "plugins", "skills", "agents"]
            for d in core_dirs:
                dpath = os.path.join(ANK_DIR, d)
                if os.path.isdir(dpath):
                    sources.append(dpath)

        if not sources:
            sources.append(ANK_DIR)

        if backup_type == "incremental":
            snapshot_file = os.path.join(ANK_DIR, "state", ".last_backup_time")
            if os.path.isfile(snapshot_file):
                try:
                    with open(snapshot_file, "r") as f:
                        last_time = float(f.read().strip())
                    files = []
                    for src in sources:
                        for root, dirs, filenames in os.walk(src):
                            for fn in filenames:
                                fp = os.path.join(root, fn)
                                try:
                                    if os.path.getmtime(fp) > last_time:
                                        files.append(fp)
                                except OSError:
                                    pass
                    if not files:
                        self.log("No changed files since last backup")
                        with open(tar_path, "wb") as f:
                            pass
                        return tar_path
                    list_file = os.path.join("/tmp", f"backup-list-{ts}.txt")
                    with open(list_file, "w") as f:
                        for fp in files:
                            f.write(fp + "\n")
                    cmd = ["tar", "-czf", tar_path, "-T", list_file]
                    subprocess.run(cmd, check=True, capture_output=True)
                    try:
                        os.remove(list_file)
                    except OSError:
                        pass
                    os.makedirs(os.path.dirname(snapshot_file), exist_ok=True)
                    with open(snapshot_file, "w") as f:
                        f.write(str(time.time()))
                    return tar_path
                except (OSError, ValueError):
                    pass

        if not sources:
            sources = [ANK_DIR]

        cmd = ["tar", "-czf", tar_path] + sources
        subprocess.run(cmd, check=True, capture_output=True)

        if backup_type != "incremental":
            snapshot_file = os.path.join(ANK_DIR, "state", ".last_backup_time")
            try:
                os.makedirs(os.path.dirname(snapshot_file), exist_ok=True)
                with open(snapshot_file, "w") as f:
                    f.write(str(time.time()))
            except OSError:
                pass

        return tar_path

    def _upload(self, tar_path):
        host = self.remote["host"]
        port = self.remote.get("port", 22)
        user = self.remote["user"]
        password = self.remote["password"]
        remote_path = self.remote["path"].rstrip("/")
        filename = os.path.basename(tar_path)
        remote_dest = f"{remote_path}/{filename}"
        cmd = [
            "sshpass", "-p", password,
            "scp", "-P", str(port),
            "-o", "StrictHostKeyChecking=no",
            tar_path,
            f"{user}@{host}:{remote_dest}"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.log(f"SCP upload failed: {result.stderr}")
            raise RuntimeError(f"SCP upload failed: {result.stderr}")
        return remote_dest

    def _apply_retention(self):
        retention_days = self.config.get("retention_days", 30)
        if retention_days <= 0:
            return
        host = self.remote["host"]
        port = self.remote.get("port", 22)
        user = self.remote["user"]
        password = self.remote["password"]
        remote_path = self.remote["path"].rstrip("/")
        cmd = [
            "sshpass", "-p", password,
            "ssh", "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            f"{user}@{host}",
            f"find {remote_path} -name '*.tar.gz' -mtime +{retention_days} -delete"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.log(f"Retention cleanup failed: {result.stderr}")

    def _cleanup(self, tar_path):
        try:
            os.remove(tar_path)
        except OSError:
            pass

    def _test_connection(self):
        host = self.remote["host"]
        port = self.remote.get("port", 22)
        user = self.remote["user"]
        password = self.remote["password"]
        cmd = [
            "sshpass", "-p", password,
            "ssh", "-p", str(port),
            "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=no",
            f"{user}@{host}",
            "echo ok"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.returncode == 0 and "ok" in result.stdout

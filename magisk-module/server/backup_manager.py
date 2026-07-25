import os
import json
import time
import subprocess
import threading
import glob
import datetime

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
BACKUPS_DIR = os.path.join(ANK_DIR, "backups")
CONTAINERS_DIR = os.path.join(ANK_DIR, "containers")
LOGS_DIR = os.path.join(BACKUPS_DIR, "logs")


class BackupManager:
    def __init__(self):
        os.makedirs(BACKUPS_DIR, exist_ok=True)
        os.makedirs(LOGS_DIR, exist_ok=True)
        self.routines_dir = os.path.join(BACKUPS_DIR, "routines")
        self.history_dir = os.path.join(BACKUPS_DIR, "history")
        os.makedirs(self.routines_dir, exist_ok=True)
        os.makedirs(self.history_dir, exist_ok=True)

    def list_routines(self):
        routines = []
        for fp in glob.glob(os.path.join(self.routines_dir, "*.json")):
            try:
                with open(fp, "r") as f:
                    routines.append(json.load(f))
            except (OSError, json.JSONDecodeError):
                continue
        return routines

    def get_routine(self, routine_id):
        fp = os.path.join(self.routines_dir, f"{routine_id}.json")
        if not os.path.isfile(fp):
            return None
        try:
            with open(fp, "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def create_routine(self, config):
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
        routine_id = f"bkp-routine-{ts}"
        config["id"] = routine_id
        if "created_at" not in config:
            config["created_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if "enabled" not in config:
            config["enabled"] = True
        fp = os.path.join(self.routines_dir, f"{routine_id}.json")
        with open(fp, "w") as f:
            json.dump(config, f, indent=2)
        return config

    def update_routine(self, routine_id, config):
        fp = os.path.join(self.routines_dir, f"{routine_id}.json")
        if not os.path.isfile(fp):
            return None
        config["id"] = routine_id
        with open(fp, "w") as f:
            json.dump(config, f, indent=2)
        return config

    def delete_routine(self, routine_id):
        fp = os.path.join(self.routines_dir, f"{routine_id}.json")
        if os.path.isfile(fp):
            os.remove(fp)
            return True
        return False

    def run_backup(self, routine_id):
        routine = self.get_routine(routine_id)
        if not routine:
            raise ValueError(f"Routine {routine_id} not found")
        if not routine.get("enabled", True):
            raise ValueError(f"Routine {routine_id} is disabled")

        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        history_id = f"bkp-{ts}"
        log_file = os.path.join(LOGS_DIR, f"{history_id}.log")

        history_entry = {
            "id": history_id,
            "routine_id": routine_id,
            "type": routine.get("type", "full"),
            "status": "running",
            "started_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finished_at": None,
            "size_bytes": 0,
            "remote_path": None,
            "containers": routine.get("containers", [])
        }

        thread = threading.Thread(
            target=self._execute_backup,
            args=(routine, history_entry, log_file),
            daemon=True
        )
        thread.start()
        return history_entry

    def _execute_backup(self, routine, history_entry, log_file):
        from backup_runner import BackupRunner
        runner = BackupRunner(routine, log_file)
        try:
            result = runner.run()
            history_entry["status"] = result["status"]
            history_entry["remote_path"] = result["remote_path"]
            history_entry["size_bytes"] = result["size"]
        except Exception as e:
            history_entry["status"] = "failed"
            history_entry["error"] = str(e)
            with open(log_file, "a") as f:
                f.write(f"[ERROR] {e}\n")
        finally:
            history_entry["finished_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._save_history(history_entry)

    def _save_history(self, entry):
        routine_id = entry["routine_id"]
        routine_dir = os.path.join(self.history_dir, routine_id)
        os.makedirs(routine_dir, exist_ok=True)
        fp = os.path.join(routine_dir, f"{entry['id']}.json")
        with open(fp, "w") as f:
            json.dump(entry, f, indent=2)

    def get_history(self, routine_id=None, limit=50):
        entries = []
        if routine_id:
            routine_dir = os.path.join(self.history_dir, routine_id)
            if os.path.isdir(routine_dir):
                for fp in sorted(glob.glob(os.path.join(routine_dir, "*.json")), reverse=True)[:limit]:
                    try:
                        with open(fp, "r") as f:
                            entries.append(json.load(f))
                    except (OSError, json.JSONDecodeError):
                        continue
        else:
            for routine_dir in sorted(glob.glob(os.path.join(self.history_dir, "*")), reverse=True):
                if not os.path.isdir(routine_dir):
                    continue
                for fp in sorted(glob.glob(os.path.join(routine_dir, "*.json")), reverse=True):
                    try:
                        with open(fp, "r") as f:
                            entries.append(json.load(f))
                    except (OSError, json.JSONDecodeError):
                        continue
                    if len(entries) >= limit:
                        break
                if len(entries) >= limit:
                    break
        return entries[:limit]

    def get_logs(self, routine_id, limit=100):
        log_files = sorted(glob.glob(os.path.join(LOGS_DIR, f"bkp-*-{routine_id}*.log")), reverse=True)[:limit]
        logs = []
        for lf in log_files:
            try:
                with open(lf, "r") as f:
                    logs.append({"file": os.path.basename(lf), "content": f.read()})
            except OSError:
                continue
        return logs

    def test_connection(self, routine_id):
        routine = self.get_routine(routine_id)
        if not routine:
            raise ValueError(f"Routine {routine_id} not found")
        remote = routine["remote"]
        host = remote["host"]
        port = remote.get("port", 22)
        user = remote["user"]
        password = remote["password"]
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

    def list_remote_files(self, routine_id, path=""):
        routine = self.get_routine(routine_id)
        if not routine:
            raise ValueError(f"Routine {routine_id} not found")
        remote = routine["remote"]
        base = remote["path"].rstrip("/")
        full_path = f"{base}/{path}".rstrip("/") if path else base
        host = remote["host"]
        port = remote.get("port", 22)
        user = remote["user"]
        password = remote["password"]
        cmd = [
            "sshpass", "-p", password,
            "ssh", "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            f"{user}@{host}",
            f"ls -la --time-style=long-iso {full_path}"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return []
        files = []
        for line in result.stdout.strip().split("\n"):
            if line.startswith("total") or not line.strip():
                continue
            parts = line.split(None, 7)
            if len(parts) < 8:
                continue
            ftype = "dir" if parts[0].startswith("d") else "file"
            files.append({
                "permissions": parts[0],
                "size": parts[4],
                "modified": f"{parts[5]} {parts[6]}",
                "name": parts[7],
                "type": ftype
            })
        return files

    def delete_remote_file(self, routine_id, remote_path):
        routine = self.get_routine(routine_id)
        if not routine:
            raise ValueError(f"Routine {routine_id} not found")
        remote = routine["remote"]
        host = remote["host"]
        port = remote.get("port", 22)
        user = remote["user"]
        password = remote["password"]
        full_path = f"{remote['path'].rstrip('/')}/{remote_path}"
        cmd = [
            "sshpass", "-p", password,
            "ssh", "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            f"{user}@{host}",
            f"rm -f {full_path}"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0

    def restore_from_remote(self, routine_id, remote_path, target_dir=""):
        routine = self.get_routine(routine_id)
        if not routine:
            raise ValueError(f"Routine {routine_id} not found")
        remote = routine["remote"]
        host = remote["host"]
        port = remote.get("port", 22)
        user = remote["user"]
        password = remote["password"]
        base = remote["path"].rstrip("/")
        full_remote = f"{base}/{remote_path}"
        if not target_dir:
            target_dir = os.path.join(BACKUPS_DIR, "restores")
        os.makedirs(target_dir, exist_ok=True)
        local_dest = os.path.join(target_dir, os.path.basename(remote_path))
        cmd = [
            "sshpass", "-p", password,
            "scp", "-P", str(port),
            "-o", "StrictHostKeyChecking=no",
            f"{user}@{host}:{full_remote}",
            local_dest
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"SCP download failed: {result.stderr}")
        return local_dest

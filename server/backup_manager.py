import os
import json
import time
import subprocess
import threading
import glob
import datetime
import hashlib
import hmac
import shlex

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
BACKUPS_DIR = os.path.join(ANK_DIR, "backups")
CONTAINERS_DIR = os.path.join(ANK_DIR, "containers")
LOGS_DIR = os.path.join(BACKUPS_DIR, "logs")

SOURCE_TYPES = (
    "container_full",
    "engine_config",
    "system_complete",
    "container_selective",
    "node_full",
    "container_file",
)

SOURCE_TYPE_LABELS = {
    "container_full": "Container Full Backup",
    "engine_config": "Engine Configuration Backup",
    "system_complete": "System Complete Backup",
    "container_selective": "Container Selective Backup",
    "node_full": "Node Full Backup",
    "container_file": "Container File Backup",
}


class BackupManager:
    def __init__(self):
        os.makedirs(BACKUPS_DIR, exist_ok=True)
        os.makedirs(LOGS_DIR, exist_ok=True)
        self.routines_dir = os.path.join(BACKUPS_DIR, "routines")
        self.history_dir = os.path.join(BACKUPS_DIR, "history")
        os.makedirs(self.routines_dir, exist_ok=True)
        os.makedirs(self.history_dir, exist_ok=True)
        self._scheduler_thread = None
        self._scheduler_running = False

    def list_routines(self):
        routines = []
        for fp in glob.glob(os.path.join(self.routines_dir, "*.json")):
            try:
                with open(fp, "r") as f:
                    r = json.load(f)
                r["_source_type_label"] = SOURCE_TYPE_LABELS.get(r.get("source_type", ""), "Unknown")
                routines.append(r)
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
        config.setdefault("created_at", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        config.setdefault("enabled", True)
        config.setdefault("source_type", "container_full")
        config.setdefault("containers", [])
        config.setdefault("nodes", [])
        config.setdefault("custom_paths", {})
        config.setdefault("encryption", "none")
        config.setdefault("immutable", False)
        config.setdefault("backup_mode", "full")
        config.setdefault("retention_days", 30)
        config.setdefault("schedule", "")
        config.setdefault("last_run", None)
        config.setdefault("last_status", None)
        fp = os.path.join(self.routines_dir, f"{routine_id}.json")
        with open(fp, "w") as f:
            json.dump(config, f, indent=2)
        return config

    def update_routine(self, routine_id, updates):
        fp = os.path.join(self.routines_dir, f"{routine_id}.json")
        if not os.path.isfile(fp):
            return None
        with open(fp, "r") as f:
            config = json.load(f)
        for k, v in updates.items():
            if k != "id":
                config[k] = v
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

        from backup_runner import get_battery_status
        battery = get_battery_status()
        if not battery.get("can_backup", True):
            raise ValueError(f"Battery critical ({battery['level']}%) — backup aborted")

        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        history_id = f"bkp-{ts}"
        log_file = os.path.join(LOGS_DIR, f"{history_id}.log")

        history_entry = {
            "id": history_id,
            "routine_id": routine_id,
            "routine_name": routine.get("name", ""),
            "source_type": routine.get("source_type", "container_full"),
            "status": "running",
            "started_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finished_at": None,
            "size_bytes": 0,
            "remote_path": None,
            "containers": routine.get("containers", []),
            "nodes": routine.get("nodes", []),
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
            history_entry["remote_path"] = result.get("remote_path")
            history_entry["size_bytes"] = result.get("size", 0)
            if result.get("reason"):
                history_entry["reason"] = result["reason"]
        except Exception as e:
            history_entry["status"] = "failed"
            history_entry["error"] = str(e)
            with open(log_file, "a") as f:
                f.write(f"[ERROR] {e}\n")
        finally:
            history_entry["finished_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._save_history(history_entry)
            routine = self.get_routine(history_entry["routine_id"])
            if routine:
                routine["last_run"] = history_entry["finished_at"]
                routine["last_status"] = history_entry["status"]
                fp = os.path.join(self.routines_dir, f"{history_entry['routine_id']}.json")
                try:
                    with open(fp, "w") as f:
                        json.dump(routine, f, indent=2)
                except OSError:
                    pass

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
            for rd in sorted(glob.glob(os.path.join(self.history_dir, "*")), reverse=True):
                if not os.path.isdir(rd):
                    continue
                for fp in sorted(glob.glob(os.path.join(rd, "*.json")), reverse=True):
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

    def get_logs(self, history_id):
        log_file = os.path.join(LOGS_DIR, f"{history_id}.log")
        if not os.path.isfile(log_file):
            return ""
        try:
            with open(log_file, "r") as f:
                return f.read()
        except OSError:
            return ""

    def test_connection(self, remote_config):
        host = shlex.quote(str(remote_config.get("host", "")))
        port = shlex.quote(str(remote_config.get("port", 22)))
        user = shlex.quote(str(remote_config.get("user", "root")))
        password = shlex.quote(str(remote_config.get("password", "")))
        cmd = (
            f"sshpass -e ssh -p {port} "
            f"-o ConnectTimeout=5 -o StrictHostKeyChecking=no "
            f"{user}@{host} echo ok"
        )
        result = subprocess.run(
            ["/system/bin/sh", "-c", cmd],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "SSHPASS": remote_config.get("password", "")}
        )
        return result.returncode == 0 and "ok" in result.stdout

    def list_remote_files(self, remote_config, path=""):
        base = remote_config.get("path", "/backups/ank").rstrip("/")
        full_path = shlex.quote(f"{base}/{path}".rstrip("/") if path else base)
        host = shlex.quote(str(remote_config.get("host", "")))
        port = shlex.quote(str(remote_config.get("port", 22)))
        user = shlex.quote(str(remote_config.get("user", "root")))
        password = shlex.quote(str(remote_config.get("password", "")))
        cmd = (
            f"sshpass -e ssh -p {port} "
            f"-o StrictHostKeyChecking=no "
            f"{user}@{host} ls -la --time-style=long-iso {full_path} 2>/dev/null"
        )
        result = subprocess.run(
            ["/system/bin/sh", "-c", cmd],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "SSHPASS": remote_config.get("password", "")}
        )
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
            try:
                size = int(parts[4])
            except ValueError:
                size = 0
            files.append({
                "name": parts[7],
                "type": ftype,
                "size": size,
                "modified": f"{parts[5]} {parts[6]}",
                "permissions": parts[0],
            })
        return files

    def delete_remote_file(self, remote_config, remote_path):
        host = shlex.quote(str(remote_config.get("host", "")))
        port = shlex.quote(str(remote_config.get("port", 22)))
        user = shlex.quote(str(remote_config.get("user", "root")))
        base = remote_config.get("path", "/backups/ank").rstrip("/")
        full_path = shlex.quote(f"{base}/{remote_path}")
        cmd = (
            f"sshpass -e ssh -p {port} "
            f"-o StrictHostKeyChecking=no "
            f"{user}@{host} rm -f {full_path}"
        )
        result = subprocess.run(
            ["/system/bin/sh", "-c", cmd],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "SSHPASS": remote_config.get("password", "")}
        )
        return result.returncode == 0

    def rename_remote_file(self, remote_config, old_name, new_name):
        host = shlex.quote(str(remote_config.get("host", "")))
        port = shlex.quote(str(remote_config.get("port", 22)))
        user = shlex.quote(str(remote_config.get("user", "root")))
        base = remote_config.get("path", "/backups/ank").rstrip("/")
        cmd = (
            f"sshpass -e ssh -p {port} "
            f"-o StrictHostKeyChecking=no "
            f"{user}@{host} mv {shlex.quote(f'{base}/{old_name}')} {shlex.quote(f'{base}/{new_name}')}"
        )
        result = subprocess.run(
            ["/system/bin/sh", "-c", cmd],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "SSHPASS": remote_config.get("password", "")}
        )
        return result.returncode == 0

    def download_remote_file(self, remote_config, remote_name, local_path):
        host = shlex.quote(str(remote_config.get("host", "")))
        port = shlex.quote(str(remote_config.get("port", 22)))
        user = shlex.quote(str(remote_config.get("user", "root")))
        base = remote_config.get("path", "/backups/ank").rstrip("/")
        full_remote = shlex.quote(f"{base}/{remote_name}")
        local_path_safe = shlex.quote(local_path)
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        cmd = (
            f"sshpass -e scp -P {port} "
            f"-o StrictHostKeyChecking=no "
            f"{user}@{host}:{full_remote} {local_path_safe}"
        )
        result = subprocess.run(
            ["/system/bin/sh", "-c", cmd],
            capture_output=True, text=True, timeout=600,
            env={**os.environ, "SSHPASS": remote_config.get("password", "")}
        )
        if result.returncode != 0:
            raise RuntimeError(f"SCP download failed: {result.stderr}")
        return local_path

    def restore_from_remote(self, remote_config, remote_name, target_dir=""):
        if not target_dir:
            target_dir = os.path.join(BACKUPS_DIR, "restores")
        os.makedirs(target_dir, exist_ok=True)
        local_dest = os.path.join(target_dir, remote_name)
        return self.download_remote_file(remote_config, remote_name, local_dest)

    def preview_backup(self, remote_config, remote_name, preview_dir=""):
        local_path = self.restore_from_remote(remote_config, remote_name, preview_dir)
        if local_path.endswith(".tar.gz"):
            extract_dir = local_path[:-8]
            os.makedirs(extract_dir, exist_ok=True)
            subprocess.run(
                ["tar", "-xzf", local_path, "-C", extract_dir],
                capture_output=True, timeout=120
            )
            return {"tar_path": local_path, "extract_dir": extract_dir}
        return {"tar_path": local_path, "extract_dir": None}

    def get_containers_in_routine(self, routine_id):
        routine = self.get_routine(routine_id)
        if not routine:
            return []
        source_type = routine.get("source_type", "container_full")
        if source_type == "container_full":
            if os.path.isdir(CONTAINERS_DIR):
                return [d for d in os.listdir(CONTAINERS_DIR) if os.path.isdir(os.path.join(CONTAINERS_DIR, d))]
            return []
        elif source_type == "container_selective":
            return routine.get("containers", [])
        return []

    def get_routine_for_container(self, container_name):
        for routine in self.list_routines():
            if not routine.get("enabled", True):
                continue
            containers = self.get_containers_in_routine(routine["id"])
            if container_name in containers:
                return routine
        return None

    def start_scheduler(self, interval=60):
        if self._scheduler_running:
            return
        self._scheduler_running = True

        def _loop():
            while self._scheduler_running:
                try:
                    self._check_schedules()
                except Exception as e:
                    print(f"[BACKUP-SCHEDULER] Error: {e}", flush=True)
                time.sleep(interval)

        self._scheduler_thread = threading.Thread(target=_loop, daemon=True)
        self._scheduler_thread.start()

    def stop_scheduler(self):
        self._scheduler_running = False

    def _check_schedules(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        for routine in self.list_routines():
            if not routine.get("enabled", True):
                continue
            schedule = routine.get("schedule", "")
            if not schedule:
                continue
            last_run = routine.get("last_run")
            if self._should_run_now(schedule, last_run, now):
                self.log(f"Scheduler: running routine '{routine.get('name')}'")
                try:
                    self.run_backup(routine["id"])
                except Exception as e:
                    self.log(f"Scheduler: failed to run '{routine.get('name')}': {e}")

    def _should_run_now(self, schedule, last_run, now):
        if not last_run:
            return True
        try:
            last_dt = datetime.datetime.fromisoformat(last_run.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return True
        elapsed = (now - last_dt).total_seconds()
        if schedule.startswith("every "):
            try:
                hours = int(schedule.split()[1])
                return elapsed >= hours * 3600
            except (IndexError, ValueError):
                pass
        elif schedule.startswith("daily"):
            return elapsed >= 86400
        elif schedule.startswith("weekly"):
            return elapsed >= 604800
        elif " " in schedule:
            return self._check_cron(schedule, last_dt, now)
        return False

    def _check_cron(self, cron_str, last_dt, now):
        parts = cron_str.split()
        if len(parts) < 5:
            return False
        minute, hour, day, month, dow = parts
        if minute != "*" and now.minute != int(minute):
            return False
        if hour != "*" and now.hour != int(hour):
            return False
        if day != "*" and now.day != int(day):
            return False
        if month != "*" and now.month != int(month):
            return False
        if dow != "*" and now.weekday() != int(dow):
            return False
        elapsed = (now - last_dt).total_seconds()
        return elapsed > 300

    @staticmethod
    def log(msg):
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"[{ts}] [BACKUP] {msg}", flush=True)

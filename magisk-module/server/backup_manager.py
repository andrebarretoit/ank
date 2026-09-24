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
import shutil
import stat

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
BACKUPS_DIR = os.path.join(ANK_DIR, "backups")
CONTAINERS_DIR = os.path.join(ANK_DIR, "containers")
LOGS_DIR = os.path.join(BACKUPS_DIR, "logs")
TMP_DIR = os.path.join(ANK_DIR, "tmp")


def _write_askpass(password):
    """Write SSH_ASKPASS helper that echoes the password from env.

    Returns (host_path, path_visible_to_ssh).  host_path is where we write
    the file; path_visible_to_ssh is what to put in SSH_ASKPASS (differs when
    running inside the ankfs chroot).
    """
    os.makedirs(TMP_DIR, exist_ok=True)
    host_path = os.path.join(TMP_DIR, "ank_askpass.sh")
    with open(host_path, "w") as f:
        f.write("#!/bin/sh\n")
        f.write('echo "$ANK_ASKPASS_PASSWORD"\n')
    os.chmod(host_path, 0o700)
    return host_path, host_path


def _ssh_askpass_env(password, ssh_askpass_path):
    env = {k: v for k, v in os.environ.items() if k != "SSHPASS"}
    env["ANK_ASKPASS_PASSWORD"] = password
    env["SSH_ASKPASS"] = ssh_askpass_path
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env["DISPLAY"] = env.get("DISPLAY") or ":0"
    return env


def _find_chroot_bin():
    b = shutil.which("chroot")
    if b:
        return b
    for cand in ("/system/bin/chroot", "/system/xbin/chroot", "/sbin/chroot"):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def run_ssh_argv(ssh_argv, password, timeout=30, remote_cmd_note=""):
    """Run ssh/scp argv with password auth via SSH_ASKPASS (no PTY / no sshpass).

    ssh_argv[0] must be 'ssh' or 'scp'.  Paths and -p/-P flags are the caller's.
    Chooses host ssh if present, else chroots into ankfs.
    Returns CompletedProcess-like or raises.
    """
    rootfs = os.path.join(ANK_DIR, "ankfs")
    rootfs_ssh = os.path.join(rootfs, "usr", "bin", ssh_argv[0])
    host_ssh = shutil.which(ssh_argv[0])

    run_kwargs = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "stdin": subprocess.DEVNULL,
    }

    if host_ssh:
        _, ask_path = _write_askpass(password)
        env = _ssh_askpass_env(password, ask_path)
        run_kwargs["env"] = env
        argv = [host_ssh] + ssh_argv[1:]
        return subprocess.run(argv, **run_kwargs)

    if not os.path.isfile(rootfs_ssh):
        raise FileNotFoundError(f"{ssh_argv[0]} not found on host or in ankfs")

    # Chroot: askpass must live inside the rootfs at a path ssh can see.
    os.makedirs(os.path.join(rootfs, "tmp"), exist_ok=True)
    ask_host = os.path.join(rootfs, "tmp", "ank_askpass.sh")
    with open(ask_host, "w") as f:
        f.write("#!/bin/sh\n")
        f.write('echo "$ANK_ASKPASS_PASSWORD"\n')
    os.chmod(ask_host, 0o700)

    env = _ssh_askpass_env(password, "/tmp/ank_askpass.sh")
    env["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
    env["HOME"] = "/root"
    run_kwargs["env"] = env

    chroot_bin = _find_chroot_bin()
    inner = [f"/usr/bin/{ssh_argv[0]}"] + ssh_argv[1:]
    if chroot_bin:
        argv = [chroot_bin, rootfs] + inner
        return subprocess.run(argv, **run_kwargs)

    def _preexec(rootfs_path=rootfs):
        os.chroot(rootfs_path)
        os.chdir("/")

    argv = inner
    return subprocess.run(argv, preexec_fn=_preexec, **run_kwargs)

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

    def ensure_remote_path(self, remote_config):
        """mkdir -p the remote backup path after routine creation. Returns rich result or None."""
        host = str(remote_config.get("host", "")).strip()
        if not host:
            return None
        try:
            port = int(str(remote_config.get("port", 22)).strip() or "22")
        except (TypeError, ValueError):
            port = 22
        user = str(remote_config.get("user", "root")).strip() or "root"
        password = str(remote_config.get("password", ""))
        path = str(remote_config.get("path", "/backups/ank")).rstrip("/") or "/backups/ank"
        target = host if "@" in host else f"{user}@{host}"

        ssh_args = [
            "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            "-o", "BatchMode=no",
            target,
            "mkdir", "-p", path,
        ]
        try:
            result = run_ssh_argv(["ssh"] + ssh_args, password, timeout=30)
        except subprocess.TimeoutExpired:
            return {"ok": False, "reason": "timed out creating remote path", "exit_code": 124}
        except (OSError, ValueError, FileNotFoundError) as e:
            return {"ok": False, "reason": f"could not run ssh: {e}"}

        ok = result.returncode == 0
        stderr_tail = (result.stderr or result.stdout or "").strip()[-200:]
        if ok:
            return {"ok": True, "reason": f"remote path {path} ensured"}
        return {"ok": False, "reason": self._map_ssh_failure(result.returncode, stderr_tail), "exit_code": result.returncode, "stderr_tail": stderr_tail}

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
        """Test SSH connectivity to a remote backup target.

        Returns a rich result dict:
          {"ok": bool, "reason": str, "exit_code": int or None,
           "stderr_tail": str, "timed_out": bool}
        """
        def _result(ok, reason, exit_code=None, stderr_tail="", timed_out=False):
            return {
                "ok": ok,
                "reason": reason,
                "exit_code": exit_code,
                "stderr_tail": (stderr_tail or "")[-200:],
                "timed_out": timed_out,
            }

        host = str(remote_config.get("host", "")).strip()
        try:
            port = int(str(remote_config.get("port", 22)).strip() or "22")
        except (TypeError, ValueError):
            return _result(False, "invalid port number", None, str(remote_config.get("port", "")))
        if not host:
            return _result(False, "host is empty")
        user = str(remote_config.get("user", "root")).strip() or "root"
        password = str(remote_config.get("password", ""))
        target = host if "@" in host else f"{user}@{host}"

        ssh_args = [
            "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            "-o", "BatchMode=no",
            target,
            "echo", "__ANK_OK__",
        ]
        try:
            result = run_ssh_argv(["ssh"] + ssh_args, password, timeout=30)
        except subprocess.TimeoutExpired:
            return _result(False, "timed out — host unreachable or sshd not responding",
                           124, "", timed_out=True)
        except (OSError, ValueError, FileNotFoundError) as e:
            return _result(False, f"could not run ssh: {e}", None, str(e))

        exit_code = result.returncode
        stderr_tail = (result.stderr or result.stdout or "").strip()
        ok = exit_code == 0 and "__ANK_OK__" in (result.stdout or "")
        if ok:
            return _result(True, "connected", exit_code, stderr_tail)
        return _result(False, self._map_ssh_failure(exit_code, stderr_tail), exit_code, stderr_tail)

    @staticmethod
    def _ensure_chroot_pty(rootfs):
        """Make sure sshpass can allocate a PTY inside the ankfs chroot.

        sshpass needs /dev/ptmx + a mounted devpts to intercept ssh's
        password prompt (exit 3 otherwise).  Strategy:
          1. Bind-mount host /dev into chroot (best — host already has working ptmx)
          2. Fallback: mknod ptmx + mount devpts
        Logs every failure to stderr so [Backup] tests can diagnose.
        """
        import sys
        dev = os.path.join(rootfs, "dev")
        pts = os.path.join(dev, "pts")
        ptmx = os.path.join(dev, "ptmx")

        def _log(msg):
            print(f"[BACKUP] _ensure_chroot_pty: {msg}", file=sys.stderr, flush=True)

        try:
            os.makedirs(pts, exist_ok=True)
        except OSError as e:
            _log(f"makedirs pts failed: {e}")

        # 1) Is host /dev already bind-mounted here?
        already = False
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == dev and parts[2] == "devtmpfs":
                        already = True
                        break
                    # also accept a bind mount of /dev
                    if len(parts) >= 3 and parts[1] == dev and parts[0] == "/dev":
                        already = True
                        break
        except OSError as e:
            _log(f"read /proc/mounts failed: {e}")

        if not already:
            # Primary: bind-mount host /dev (gives ptmx, pts, null, urandom, tty…)
            try:
                r = subprocess.run(
                    ["mount", "--bind", "/dev", dev],
                    capture_output=True, text=True, timeout=5,
                )
                _log(f"bind /dev -> {dev}: rc={r.returncode} stderr={r.stderr.strip()!r}")
                if r.returncode != 0:
                    # Secondary: just bind-mount host /dev/pts + ensure ptmx
                    r2 = subprocess.run(
                        ["mount", "--bind", "/dev/pts", pts],
                        capture_output=True, text=True, timeout=5,
                    )
                    _log(f"bind /dev/pts -> {pts}: rc={r2.returncode} stderr={r2.stderr.strip()!r}")
            except (OSError, subprocess.SubprocessError) as e:
                _log(f"bind mount failed: {e}")

        # 2) Ensure /dev/ptmx exists regardless (mknod fallback if bind failed)
        if not os.path.exists(ptmx):
            try:
                os.mknod(ptmx, 0o666 | stat.S_IFCHR, os.makedev(5, 2))
                _log(f"mknod {ptmx} ok")
            except OSError as e:
                _log(f"mknod {ptmx} failed: {e}")
                # last resort: copy host's ptmx node via cat/cp -a won't work for devices;
                # try busybox mknod
                try:
                    r = subprocess.run(
                        ["mknod", ptmx, "c", "5", "2"],
                        capture_output=True, text=True, timeout=5,
                    )
                    _log(f"mknod cmd rc={r.returncode} stderr={r.stderr.strip()!r}")
                    if r.returncode == 0:
                        os.chmod(ptmx, 0o666)
                except (OSError, subprocess.SubprocessError) as e:
                    _log(f"mknod cmd failed: {e}")
        else:
            try:
                os.chmod(ptmx, 0o666)
            except OSError as e:
                _log(f"chmod ptmx failed: {e}")

        # 3) Ensure devpts is mounted (if bind of whole /dev worked, pts is already there)
        mounted = False
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] in (pts, dev):
                        # devpts on pts, or if parent /dev is bind-mounted with devpts under it
                        if parts[2] == "devpts" or (parts[1] == dev and parts[2] in ("devtmpfs", "dev")):
                            mounted = True
                            break
        except OSError:
            pass
        if not mounted:
            try:
                r = subprocess.run(
                    ["mount", "-t", "devpts", "devpts", pts],
                    capture_output=True, text=True, timeout=5,
                )
                _log(f"mount devpts -> {pts}: rc={r.returncode} stderr={r.stderr.strip()!r}")
            except (OSError, subprocess.SubprocessError) as e:
                _log(f"mount devpts failed: {e}")

        _log(f"final: ptmx_exists={os.path.exists(ptmx)} pts_isdir={os.path.isdir(pts)}")

    @staticmethod
    def _map_ssh_failure(exit_code, stderr):
        """Map ssh/sshpass exit codes and stderr text to a short human reason."""
        low = (stderr or "").lower()
        if "permission denied" in low or "incorrect password" in low or "authentication failed" in low:
            return "authentication failed — wrong user or password"
        if "connection refused" in low:
            return "connection refused — wrong port or sshd not running on target"
        if ("could not resolve hostname" in low or "name or service not known" in low
                or "temporary failure in name resolution" in low or "nodename nor servname" in low):
            return "host not resolved — check hostname/DNS"
        if "connection timed out" in low or "no route to host" in low or "connection reset" in low:
            return "host unreachable — connection timed out"
        if "host key verification failed" in low:
            return "host key verification failed"
        if "posix_openpt" in low or "/dev/ptmx" in low or "failed to create pty" in low \
                or "pseudo terminal" in low or "failed to get a pseudo terminal" in low:
            return "sshpass could not allocate a pty (/dev/ptmx or devpts missing in ankfs)"
        if "chroot" in low and ("operation not permitted" in low or "permission denied" in low):
            return "chroot failed — insufficient permissions"
        if "not found" in low and ("sshpass" in low or low.endswith("ssh: not found")):
            return "sshpass/ssh not found on device"
        code_map = {
            1: "ssh connection or authentication failed (exit 1)",
            2: "ssh usage/option error (exit 2)",
            5: "wrong password or connection refused (exit 5)",
            6: "no password or host not resolved (exit 6)",
            124: "connection timed out — host unreachable (exit 124)",
            125: "ssh failed to start (exit 125)",
            126: "sshpass/ssh not executable (exit 126)",
            127: "sshpass or ssh not found on device (exit 127)",
            255: "ssh could not connect or authenticate (exit 255)",
        }
        if exit_code in code_map:
            return code_map[exit_code]
        return f"ssh failed with exit code {exit_code}"

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

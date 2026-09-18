import os
import subprocess
import json
import shlex


class BackupBrowser:
    def __init__(self, remote_config):
        self.remote = remote_config

    def _ssh(self, command):
        host = self.remote["host"]
        port = self.remote.get("port", 22)
        user = self.remote["user"]
        password = self.remote["password"]
        cmd = [
            "sshpass", "-e",
            "ssh", "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            f"{user}@{host}",
            command
        ]
        env = {**os.environ, "SSHPASS": password}
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        return result.stdout, result.stderr, result.returncode

    def list_files(self, path=""):
        base = self.remote["path"].rstrip("/")
        full_path = shlex.quote(f"{base}/{path}".rstrip("/") if path else base)
        stdout, stderr, rc = self._ssh(f"ls -la --time-style=long-iso {full_path}")
        if rc != 0:
            return []
        files = []
        for line in stdout.strip().split("\n"):
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
                "permissions": parts[0]
            })
        return files

    def get_file_info(self, path):
        base = self.remote["path"].rstrip("/")
        full_path = shlex.quote(f"{base}/{path}")
        stdout, stderr, rc = self._ssh(f"stat --format='%s %Y %F' {full_path}")
        if rc != 0:
            return None
        parts = stdout.strip().split(None, 2)
        if len(parts) < 3:
            return None
        return {
            "path": path,
            "size": int(parts[0]) if parts[0].isdigit() else 0,
            "modified_ts": int(parts[1]) if parts[1].isdigit() else 0,
            "type": parts[2]
        }

    def delete_file(self, path):
        base = self.remote["path"].rstrip("/")
        full_path = shlex.quote(f"{base}/{path}")
        _, _, rc = self._ssh(f"rm -f {full_path}")
        return rc == 0

    def delete_dir(self, path):
        base = self.remote["path"].rstrip("/")
        full_path = shlex.quote(f"{base}/{path}")
        _, _, rc = self._ssh(f"rm -rf {full_path}")
        return rc == 0

    def rename(self, old_path, new_path):
        base = self.remote["path"].rstrip("/")
        full_old = shlex.quote(f"{base}/{old_path}")
        full_new = shlex.quote(f"{base}/{new_path}")
        _, _, rc = self._ssh(f"mv {full_old} {full_new}")
        return rc == 0

    def download_file(self, remote_path, local_path):
        host = self.remote["host"]
        port = self.remote.get("port", 22)
        user = self.remote["user"]
        password = self.remote["password"]
        base = self.remote["path"].rstrip("/")
        full_remote = f"{base}/{remote_path}"
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        cmd = [
            "sshpass", "-e",
            "scp", "-P", str(port),
            "-o", "StrictHostKeyChecking=no",
            f"{user}@{host}:{full_remote}",
            local_path
        ]
        env = {**os.environ, "SSHPASS": password}
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"SCP download failed: {result.stderr}")
        return local_path

    def get_disk_usage(self):
        base = shlex.quote(self.remote["path"].rstrip("/"))
        stdout, stderr, rc = self._ssh(f"du -sh {base}")
        if rc != 0:
            return None
        parts = stdout.strip().split(None, 1)
        if len(parts) < 2:
            return None
        return {"size_human": parts[0], "path": parts[1]}

    def get_total_backups(self):
        base = shlex.quote(self.remote["path"].rstrip("/"))
        stdout, stderr, rc = self._ssh(f"find {base} -name '*.tar.gz' -type f | wc -l")
        if rc != 0:
            return 0
        try:
            return int(stdout.strip())
        except ValueError:
            return 0

    def get_storage_used(self):
        base = shlex.quote(self.remote["path"].rstrip("/"))
        stdout, stderr, rc = self._ssh(f"find {base} -name '*.tar.gz' -type f -exec stat --format='%s' {{}} \\;")
        if rc != 0:
            return 0
        total = 0
        for line in stdout.strip().split("\n"):
            line = line.strip()
            if line.isdigit():
                total += int(line)
        return total

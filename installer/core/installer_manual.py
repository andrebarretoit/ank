"""
ANK Installer - Manual Mode Installer
For non-Magisk rooted devices (KernelSU, etc).
Extracts everything from ank-magisk.zip + sets up services.
"""

import os
import sys
import json
import zipfile
import tempfile
import shutil
from typing import Optional, Callable
from core.adb import ADB


class ManualInstaller:
    """Handles manual installation for non-Magisk rooted devices."""

    def __init__(self, adb: ADB, serial: str, callback: Optional[Callable] = None):
        self.adb = adb
        self.serial = serial
        self.callback = callback
        self._tmp_dir = None
        self._zip_dir = None

    def _notify(self, step: str, message: str, progress: float = 0):
        if self.callback:
            self.callback(step, message, progress)

    def _find_zip(self) -> Optional[str]:
        """Find ank-magisk.zip from PyInstaller bundle or disk."""
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            exe_dir = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            exe_dir = os.path.join(base_path, "..")

        candidates = [
            os.path.join(exe_dir, "ank-magisk.zip"),
            os.path.join(base_path, "ank-magisk.zip"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return None

    def _extract_zip(self) -> bool:
        """Extract ank-magisk.zip to temp dir. Keeps it for later use."""
        zip_path = self._find_zip()
        if not zip_path:
            self._notify("error", "ank-magisk.zip not found", 0)
            return False

        self._tmp_dir = tempfile.mkdtemp(prefix="ank_extract_")
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(self._tmp_dir)
            self._zip_dir = self._tmp_dir
            return True
        except Exception as e:
            self._notify("error", f"Failed to extract ZIP: {e}", 0)
            return False

    def _find_in_zip(self, name_pattern: str) -> Optional[str]:
        """Find a file in the extracted ZIP by name pattern."""
        if not self._zip_dir:
            return None
        for root, dirs, files in os.walk(self._zip_dir):
            for f in files:
                if name_pattern in f:
                    return os.path.join(root, f)
        return None

    def _find_dir_in_zip(self, name: str) -> Optional[str]:
        """Find a directory in the extracted ZIP by name."""
        if not self._zip_dir:
            return None
        for root, dirs, files in os.walk(self._zip_dir):
            for d in dirs:
                if d == name:
                    return os.path.join(root, d)
        return None

    def install(self) -> bool:
        """Run the full manual installation."""
        try:
            return self._install_inner()
        finally:
            self._cleanup()

    def _install_inner(self) -> bool:
        self._notify("setup", "Preparing manual installation...", 0.05)

        # 0. Extract ZIP
        self._notify("zip", "Extracting package...", 0.08)
        if not self._extract_zip():
            return False

        # 1. Create ANK directories
        self._notify("dirs", "Creating directories...", 0.1)
        for d in [
            "/data/local/ank", "/data/local/ank/ankfs",
            "/data/local/ank/core", "/data/local/ank/logs",
            "/data/local/ank/images", "/data/local/ank/containers",
            "/data/local/ank/cache",
        ]:
            self.adb.shell_su(self.serial, f"mkdir -p {d}")

        # 2. Find and extract tarball from ZIP
        self._notify("tarball", "Extracting rootfs...", 0.2)
        if not self._extract_tarball():
            return False

        # 3. Copy server files from ZIP
        self._notify("server", "Copying the ANK server...", 0.5)
        if not self._copy_server_files():
            return False

        # 4. Copy core scripts from ZIP
        self._notify("scripts", "Copying scripts...", 0.65)
        self._copy_scripts()

        # 5. Setup boot service
        self._notify("services", "Configuring services...", 0.75)
        self._setup_services()

        # 6. Create config
        self._notify("config", "Creating configuration...", 0.85)
        self._create_config()

        # 7. Write mode file
        self._notify("mode", "Saving operation mode...", 0.9)
        mode = {"mode": "manual", "tier": "shared_host"}
        mode_str = json.dumps(mode).replace("'", "'\\''")
        self.adb.shell_su(self.serial,
            f"echo '{mode_str}' > /data/local/ank/mode")

        self._notify("done", "Manual installation complete!", 1.0)
        return True

    def _extract_tarball(self) -> bool:
        """Find ank-prebuild tarball in extracted ZIP and push to device."""
        arch_output, _ = self.adb.shell(self.serial, "uname -m")
        arch = arch_output.strip().lower()

        # Find tarball in extracted ZIP
        tarball_path = self._find_in_zip(f"ank-prebuild-{arch}")
        if not tarball_path:
            # Fallback: any ank-prebuild tarball
            tarball_path = self._find_in_zip("ank-prebuild-")
        if not tarball_path:
            self._notify("error", f"ank-prebuild tarball not found for {arch}", 0)
            return False

        self._notify("tarball", f"Uploading rootfs ({os.path.basename(tarball_path)})...", 0.3)
        remote_tar = "/data/local/tmp/ank-prebuild.tar.gz"
        if not self.adb.push(self.serial, tarball_path, remote_tar):
            self._notify("error", "Failed to upload tarball", 0)
            return False

        self._notify("tarball", "Extracting rootfs on device...", 0.4)
        self.adb.shell_su(self.serial,
            f"cd /data/local/ank/ankfs && tar xzf {remote_tar} && rm -f {remote_tar}",
            timeout=120)

        # Verify
        output, _ = self.adb.shell(self.serial, "ls /data/local/ank/ankfs/bin/sh 2>/dev/null")
        if not output or "sh" not in output:
            self._notify("error", "Rootfs extraction failed", 0)
            return False

        self._notify("tarball", "Rootfs extracted successfully", 0.45)
        return True

    def _copy_server_files(self) -> bool:
        """Copy server.py, static/, and ank-lite.py from extracted ZIP to device."""
        ankfs = "/data/local/ank/ankfs"
        server_dir = self._find_dir_in_zip("server")
        if not server_dir:
            self._notify("error", "server/ directory not found in ZIP", 0)
            return False

        # server.py
        server_py = os.path.join(server_dir, "server.py")
        if not os.path.exists(server_py):
            self._notify("error", "server.py not found in ZIP", 0)
            return False

        self.adb.shell_su(self.serial, f"mkdir -p {ankfs}/opt/ank")
        self.adb.push(self.serial, server_py, f"{ankfs}/opt/ank/server.py")

        # ank-lite.py
        ank_lite_py = os.path.join(server_dir, "ank_lite.py")
        if os.path.exists(ank_lite_py):
            self.adb.push(self.serial, ank_lite_py, f"{ankfs}/opt/ank/ank_lite.py")

        # static/
        static_dir = os.path.join(server_dir, "static")
        if os.path.isdir(static_dir):
            self.adb.shell_su(self.serial, f"mkdir -p {ankfs}/opt/ank/static")
            for root, dirs, files in os.walk(static_dir):
                for f in files:
                    local = os.path.join(root, f)
                    rel = os.path.relpath(local, static_dir).replace("\\", "/")
                    remote = f"{ankfs}/opt/ank/static/{rel}"
                    remote_dir = os.path.dirname(remote)
                    self.adb.shell_su(self.serial, f"mkdir -p {remote_dir}")
                    self.adb.push(self.serial, local, remote)

        return True

    def _copy_scripts(self):
        """Copy core scripts from extracted ZIP to device."""
        ank_dir = "/data/local/ank"
        remote_scripts = f"{ank_dir}/core"

        # Find scripts/ in extracted ZIP
        scripts_dir = self._find_dir_in_zip("scripts")
        if not scripts_dir:
            return

        for f in os.listdir(scripts_dir):
            if f.endswith(".sh"):
                local = os.path.join(scripts_dir, f)
                self.adb.push(self.serial, local, f"{remote_scripts}/{f}")
        self.adb.shell_su(self.serial, f"chmod 755 {remote_scripts}/*.sh 2>/dev/null")

        # Images directories
        self.adb.shell_su(self.serial, f"mkdir -p {ank_dir}/images/alpine-3.20")
        self.adb.shell_su(self.serial, f"mkdir -p {ank_dir}/images/ank-alpinebase")

    def _setup_services(self):
        """Setup boot service for ANK server."""
        self.adb.shell_su(self.serial, "mkdir -p /adb/services.d")

        service_content = """#!/system/bin/sh
# ANK Server Service - starts on boot
ANK_DIR="/data/local/ank"
LOG_FILE="$ANK_DIR/logs/service.log"

# Wait for boot to complete
while [ "$(getprop sys.boot_completed)" != "1" ]; do
    sleep 5
done

# Check if ANK mode file exists
if [ ! -f "$ANK_DIR/mode" ]; then
    exit 0
fi

# Start ANK server
cd "$ANK_DIR/ankfs"
export PATH="$ANK_DIR/ankfs/bin:$ANK_DIR/ankfs/usr/bin:$PATH"
export LD_LIBRARY_PATH="$ANK_DIR/ankfs/lib:$ANK_DIR/ankfs/usr/lib"

nohup python3 /opt/ank/server.py >> "$LOG_FILE" 2>&1 &
"""
        self.adb.shell_su(self.serial,
            f"echo '{service_content}' > /adb/services.d/ank.sh")
        self.adb.shell_su(self.serial, "chmod 755 /adb/services.d/ank.sh")

    def _create_config(self):
        """Create default config.json."""
        config = {
            "username": "admin",
            "password": "admin123",
            "force_change": True,
            "server_port": 8001,
            "lang": "pt",
        }
        config_str = json.dumps(config).replace("'", "'\\''")
        self.adb.shell_su(self.serial,
            f"echo '{config_str}' > /data/local/ank/config.json")

        self.adb.shell_su(self.serial,
            f"echo 'ANK - Credenciais de Acesso' > /data/local/ank/CREDENCIAIS.txt")
        self.adb.shell_su(self.serial,
            f"echo 'Usuario: admin' >> /data/local/ank/CREDENCIAIS.txt")
        self.adb.shell_su(self.serial,
            f"echo 'Senha: admin123' >> /data/local/ank/CREDENCIAIS.txt")
        self.adb.shell_su(self.serial,
            f"echo 'IMPORTANTE: Troque a senha apos o primeiro login!' >> /data/local/ank/CREDENCIAIS.txt")

    def _cleanup(self):
        """Remove temp extraction dir."""
        if self._tmp_dir and os.path.exists(self._tmp_dir):
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None
            self._zip_dir = None

    def install_ank_ui(self, apk_path: str) -> bool:
        """Install the ANK Launcher APK on the device."""
        self._notify("ank_ui", "Installing ANK UI...", 0.95)
        result = self.adb._run_device(self.serial, ["install", "-r", apk_path], timeout=60)
        if result.returncode == 0:
            self._notify("ank_ui", "ANK UI installed successfully!", 1.0)
            return True
        else:
            self._notify("ank_ui", f"Failed to install ANK UI: {result.stderr}", 0)
            return False

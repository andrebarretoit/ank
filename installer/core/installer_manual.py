"""
ANK Installer - Manual Mode Installer
For non-Magisk rooted devices (KernelSU, etc).
Manually extracts tarball + sets up services.
"""

import os
import json
from typing import Optional, Callable
from core.adb import ADB


class ManualInstaller:
    """Handles manual installation for non-Magisk rooted devices."""

    def __init__(self, adb: ADB, serial: str, callback: Optional[Callable] = None):
        self.adb = adb
        self.serial = serial
        self.callback = callback

    def _notify(self, step: str, message: str, progress: float = 0):
        if self.callback:
            self.callback(step, message, progress)

    def install(self) -> bool:
        """Run the full manual installation."""
        self._notify("setup", "Preparando instalacao manual...", 0.05)

        # 1. Create ANK directory
        self._notify("dirs", "Criando diretorios...", 0.1)
        self.adb.shell_su(self.serial, "mkdir -p /data/local/ank")
        self.adb.shell_su(self.serial, "mkdir -p /data/local/ank/ankfs")
        self.adb.shell_su(self.serial, "mkdir -p /data/local/ank/core")
        self.adb.shell_su(self.serial, "mkdir -p /data/local/ank/logs")
        self.adb.shell_su(self.serial, "mkdir -p /data/local/ank/images")
        self.adb.shell_su(self.serial, "mkdir -p /data/local/ank/containers")

        # 2. Find and extract tarball
        self._notify("tarball", "Extraindo rootfs...", 0.2)
        if not self._extract_tarball():
            self._notify("error", "Falha ao extrair tarball", 0)
            return False

        # 3. Copy server files
        self._notify("server", "Copiando servidor ANK...", 0.5)
        self._copy_server_files()

        # 4. Copy core scripts
        self._notify("scripts", "Copiando scripts...", 0.65)
        self._copy_scripts()

        # 5. Setup services in /adb/services.d/
        self._notify("services", "Configurando servicos...", 0.75)
        self._setup_services()

        # 6. Create config
        self._notify("config", "Criando configuracao...", 0.85)
        self._create_config()

        # 7. Write mode file
        self._notify("mode", "Salvando modo de operacao...", 0.9)
        mode = {"mode": "manual", "tier": "shared_host"}
        mode_str = json.dumps(mode).replace("'", "'\\''")
        self.adb.shell_su(self.serial,
            f"echo '{mode_str}' > /data/local/ank/mode")

        self._notify("done", "Instalacao manual concluida!", 1.0)
        return True

    def _extract_tarball(self) -> bool:
        """Find and extract the ankcore tarball."""
        import sys

        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            exe_dir = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            exe_dir = os.path.join(base_path, "..")

        # Find zip (contains the tarball)
        zip_candidates = [
            os.path.join(exe_dir, "ank-magisk.zip"),
            os.path.join(base_path, "ank-magisk.zip"),
        ]

        zip_path = None
        for c in zip_candidates:
            if os.path.isfile(c):
                zip_path = c
                break

        if not zip_path:
            self._notify("error", "ank-magisk.zip nao encontrado", 0)
            return False

        # Extract zip to temp, then find the tarball inside
        import zipfile
        import tempfile
        import shutil

        tmp_dir = tempfile.mkdtemp(prefix="ank_extract_")
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(tmp_dir)

            # Find ankcore tarball inside extracted zip
            tarball_path = None
            for root, dirs, files in os.walk(tmp_dir):
                for f in files:
                    if f.endswith(".tar.gz") and "ankcore" in f:
                        tarball_path = os.path.join(root, f)
                        break
                if tarball_path:
                    break

            if not tarball_path:
                self._notify("error", "ankcore tarball nao encontrado no zip", 0)
                return False

            # Push tarball to device
            self._notify("tarball", "Enviando tarball para device...", 0.3)
            remote_tar = "/data/local/tmp/ankcore.tar.gz"
            if not self.adb.push(self.serial, tarball_path, remote_tar):
                self._notify("error", "Falha ao enviar tarball", 0)
                return False

            # Extract tarball on device
            self._notify("tarball", "Extraindo rootfs no device...", 0.4)
            self.adb.shell_su(self.serial,
                f"cd /data/local/ank/ankfs && tar xzf {remote_tar} && rm -f {remote_tar}",
                timeout=120)

            # Verify extraction
            output, _ = self.adb.shell(self.serial, "ls /data/local/ank/ankfs/bin/sh 2>/dev/null")
            if not output or "sh" not in output:
                self._notify("error", "Extracao do rootfs falhou", 0)
                return False

            self._notify("tarball", "Rootfs extraido com sucesso", 0.45)
            return True

        except Exception as e:
            self._notify("error", f"Erro na extracao: {e}", 0)
            return False
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _copy_server_files(self):
        """Copy server.py and static files to the device."""
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project_dir = os.path.dirname(script_dir)

        ank_dir = "/data/local/ank"
        ankfs = f"{ank_dir}/ankfs"

        # server.py - copy to ankfs/opt/ank/
        server_py = os.path.join(project_dir, "server", "server.py")
        if os.path.exists(server_py):
            self.adb.shell_su(self.serial, f"mkdir -p {ankfs}/opt/ank")
            self.adb.push(self.serial, server_py, f"{ankfs}/opt/ank/server.py")

        # static/
        static_dir = os.path.join(project_dir, "server", "static")
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

    def _copy_scripts(self):
        """Copy core scripts to the device."""
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        magisk_dir = os.path.join(script_dir, "..", "magisk-module")
        scripts_dir = os.path.join(magisk_dir, "scripts")

        ank_dir = "/data/local/ank"
        remote_scripts = f"{ank_dir}/core"

        if os.path.isdir(scripts_dir):
            for f in os.listdir(scripts_dir):
                if f.endswith(".sh"):
                    local = os.path.join(scripts_dir, f)
                    self.adb.push(self.serial, local, f"{remote_scripts}/{f}")
            self.adb.shell_su(self.serial, f"chmod 755 {remote_scripts}/*.sh 2>/dev/null")

        # Images directory (for Alpine base + container base)
        self.adb.shell_su(self.serial, f"mkdir -p {ank_dir}/images/alpine-3.20")
        self.adb.shell_su(self.serial, f"mkdir -p {ank_dir}/images/ank-alpinebase")

    def _setup_services(self):
        """Setup Android service scripts in /adb/services.d/."""
        # Create /adb/services.d/ if it doesn't exist
        self.adb.shell_su(self.serial, "mkdir -p /adb/services.d")

        # Create ANK service script
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

        # Write service script to device
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

        # Create credentials file
        self.adb.shell_su(self.serial,
            f"echo 'ANK - Credenciais de Acesso' > /data/local/ank/CREDENCIAIS.txt")
        self.adb.shell_su(self.serial,
            f"echo 'Usuario: admin' >> /data/local/ank/CREDENCIAIS.txt")
        self.adb.shell_su(self.serial,
            f"echo 'Senha: admin123' >> /data/local/ank/CREDENCIAIS.txt")
        self.adb.shell_su(self.serial,
            f"echo 'IMPORTANTE: Troque a senha apos o primeiro login!' >> /data/local/ank/CREDENCIAIS.txt")

    def install_ank_ui(self, apk_path: str) -> bool:
        """Install the ANK Launcher APK on the device."""
        self._notify("ank_ui", "Instalando ANK UI...", 0.95)
        result = self.adb._run_device(self.serial, ["install", "-r", apk_path], timeout=60)
        if result.returncode == 0:
            self._notify("ank_ui", "ANK UI instalado com sucesso!", 1.0)
            return True
        else:
            self._notify("ank_ui", f"Falha ao instalar ANK UI: {result.stderr}", 0)
            return False

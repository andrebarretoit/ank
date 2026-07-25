"""
ANK Installer - Native Mode Installer
No containerization - direct installation on the device.
"""

import os
import json
from typing import Optional, Callable
from core.adb import ADB


class NativeInstaller:
    """Handles native mode installation (no containerization)."""

    def __init__(self, adb: ADB, serial: str, callback: Optional[Callable] = None):
        self.adb = adb
        self.serial = serial
        self.callback = callback

    def _notify(self, step: str, message: str, progress: float = 0):
        if self.callback:
            self.callback(step, message, progress)

    def install(self) -> bool:
        """Run the full Native installation."""
        self._notify("setup", "Preparando instalacao nativa...", 0.05)

        # 1. Create ANK directory
        self._notify("dirs", "Criando diretorios...", 0.1)
        self.adb.shell(self.serial, "mkdir -p /data/local/ank")
        self.adb.shell(self.serial, "mkdir -p /data/local/ank/ankfs")
        self.adb.shell(self.serial, "mkdir -p /data/local/ank/core")

        # 2. Copy server files
        self._notify("server", "Copiando servidor ANK...", 0.3)
        self._copy_server_files()

        # 3. Install Python if needed
        self._notify("python", "Verificando Python3...", 0.5)
        self._check_python()

        # 4. Create config
        self._notify("config", "Criando configuracao...", 0.7)
        self._create_config()

        # 5. Write mode file
        self._notify("mode", "Salvando modo de operacao...", 0.9)
        self.adb.shell(self.serial,
            f'echo \'{{"mode":"native","tier":"native_host"}}\' > /data/local/ank/mode')

        self._notify("done", "Instalacao nativa concluida!", 1.0)
        return True

    def _copy_server_files(self):
        """Copy server.py and static files to the device."""
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project_dir = os.path.dirname(script_dir)

        ank_dir = "/data/local/ank"

        # server.py
        server_py = os.path.join(project_dir, "server", "server.py")
        if os.path.exists(server_py):
            self.adb.push(self.serial, server_py, f"{ank_dir}/server.py")

        # static/
        static_dir = os.path.join(project_dir, "server", "static")
        if os.path.isdir(static_dir):
            self.adb.shell(self.serial, f"mkdir -p {ank_dir}/static")
            for root, dirs, files in os.walk(static_dir):
                for f in files:
                    local = os.path.join(root, f)
                    rel = os.path.relpath(local, static_dir).replace("\\", "/")
                    remote = f"{ank_dir}/static/{rel}"
                    remote_dir = os.path.dirname(remote)
                    self.adb.shell(self.serial, f"mkdir -p {remote_dir}")
                    self.adb.push(self.serial, local, remote)

    def _check_python(self):
        """Check if Python3 is available on the device."""
        output, code = self.adb.shell(self.serial, "which python3 2>/dev/null || echo ''")
        if output and "python3" in output:
            self._notify("python", f"Python3 encontrado: {output.strip()}", 0.6)
        else:
            self._notify("python", "Python3 nao encontrado - sera necessario instalar manualmente", 0.6)

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
        self.adb.shell(self.serial,
            f"echo '{config_str}' > /data/local/ank/config.json")

        # Create credentials file
        self.adb.shell(self.serial,
            f"echo 'ANK - Credenciais de Acesso' > /data/local/ank/CREDENCIAIS.txt")
        self.adb.shell(self.serial,
            f"echo 'Usuario: admin' >> /data/local/ank/CREDENCIAIS.txt")
        self.adb.shell(self.serial,
            f"echo 'Senha: admin123' >> /data/local/ank/CREDENCIAIS.txt")
        self.adb.shell(self.serial,
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

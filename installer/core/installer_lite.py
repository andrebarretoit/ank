"""
ANK Installer - Lite Mode Installer
Non-root installation via ADB using PRoot.
"""

import os
import time
import hashlib
from typing import Optional, Callable
from core.adb import ADB


# PRoot static binaries (from proot-me/proot GitHub releases)
PROOT_URLS = {
    "aarch64": "https://github.com/proot-me/proot/releases/download/v5.4.0/proot-v5.4.0-aarch64-static",
    "armv7l": "https://github.com/proot-me/proot/releases/download/v5.4.0/proot-v5.4.0-arm-static",
    "x86_64": "https://github.com/proot-me/proot/releases/download/v5.4.0/proot-v5.4.0-x86_64-static",
}

# Alpine minirootfs
ALPINE_URL = "https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/{arch}/alpine-minirootfs-3.20.2-{arch}.tar.gz"
ALPINE_ARCH_MAP = {"aarch64": "aarch64", "armv7l": "armhf", "x86_64": "x86_64"}

# Remote paths (on device)
ANK_DIR = "/data/local/ank"
REMOTE_PROOT = f"{ANK_DIR}/proot"
REMOTE_ROOTFS = f"{ANK_DIR}/ankfs"
REMOTE_BOOTSTRAP = f"{ANK_DIR}/ank-lite-bootstrap.sh"
REMOTE_CACHE = f"{ANK_DIR}/cache"


class LiteInstaller:
    """Handles non-root installation via PRoot + ADB."""

    def __init__(self, adb: ADB, serial: str, callback: Optional[Callable] = None):
        """
        Args:
            adb: ADB instance
            serial: Device serial number
            callback: Optional callback(step, message, progress) for UI updates
        """
        self.adb = adb
        self.serial = serial
        self.callback = callback

    def _notify(self, step: str, message: str, progress: float = 0):
        if self.callback:
            self.callback(step, message, progress)

    def _get_arch(self) -> str:
        """Detect device architecture via ADB."""
        output, code = self.adb.shell(self.serial, "uname -m")
        arch = output.strip().lower()
        if arch in ("aarch64", "arm64"):
            return "aarch64"
        elif arch in ("armv7l", "armv6l"):
            return "armv7l"
        elif arch in ("x86_64", "amd64"):
            return "x86_64"
        else:
            return "aarch64"  # default

    def _download(self, url: str, dest: str) -> bool:
        """Download a file to local cache."""
        import urllib.request
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            urllib.request.urlretrieve(url, dest)
            return True
        except Exception as e:
            print(f"Download failed: {url} -> {e}")
            return False

    def _find_local_proot(self, arch: str) -> Optional[str]:
        """Find a local PRoot binary in the installer distribution."""
        # Check relative to installer dir
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = [
            os.path.join(script_dir, "bin", f"proot-{arch}"),
            os.path.join(script_dir, "bin", "proot"),
            os.path.join(script_dir, "..", "bin", f"proot-{arch}"),
            os.path.join(script_dir, "..", "bin", "proot"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    def _find_local_rootfs(self) -> Optional[str]:
        """Find a local Alpine minirootfs tarball."""
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = [
            os.path.join(script_dir, "cache", "alpine-minirootfs.tar.gz"),
            os.path.join(script_dir, "..", "cache", "alpine-minirootfs.tar.gz"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    def install(self) -> bool:
        """
        Run the full Lite installation.
        Returns True on success.
        """
        self._notify("arch", "Detectando arquitetura...", 0.05)
        arch = self._get_arch()
        proot_url = PROOT_URLS.get(arch)
        if not proot_url:
            self._notify("error", f"Arquitetura nao suportada: {arch}", 0)
            return False

        self._notify("arch", f"Arquitetura: {arch}", 0.1)

        # Step 1: Push PRoot binary
        self._notify("proot", "Preparando PRoot...", 0.15)
        local_proot = self._find_local_proot(arch)
        if local_proot:
            self._notify("proot", "Usando PRoot local...", 0.2)
        else:
            self._notify("proot", "Baixando PRoot...", 0.2)
            local_proot = os.path.join(REMOTE_CACHE, f"proot-{arch}")
            if not self._download(proot_url, local_proot):
                self._notify("error", "Falha ao baixar PRoot", 0)
                return False
            os.chmod(local_proot, 0o755)

        self._notify("proot", "Enviando PRoot para device...", 0.25)
        self.adb.shell(self.serial, f"mkdir -p {ANK_DIR}")
        if not self.adb.push(self.serial, local_proot, REMOTE_PROOT):
            self._notify("error", "Falha ao enviar PRoot", 0)
            return False
        self.adb.shell(self.serial, f"chmod 755 {REMOTE_PROOT}")

        # Step 2: Push rootfs (if not already present)
        self._notify("rootfs", "Verificando rootfs...", 0.35)
        output, _ = self.adb.shell(self.serial, f"ls {REMOTE_ROOTFS}/bin/sh 2>/dev/null")
        if output and "/bin/sh" in output:
            self._notify("rootfs", "Rootfs ja existe, pulando...", 0.5)
        else:
            local_rootfs = self._find_local_rootfs()
            if local_rootfs:
                self._notify("rootfs", "Usando rootfs local...", 0.4)
            else:
                self._notify("rootfs", "Baixando Alpine minirootfs...", 0.4)
                alpine_arch = ALPINE_ARCH_MAP.get(arch, arch)
                url = ALPINE_URL.format(arch=alpine_arch)
                local_rootfs = os.path.join(REMOTE_CACHE, "alpine-minirootfs.tar.gz")
                if not self._download(url, local_rootfs):
                    self._notify("error", "Falha ao baixar Alpine rootfs", 0)
                    return False

            self._notify("rootfs", "Extraindo rootfs no device...", 0.45)
            self.adb.shell(self.serial, f"mkdir -p {REMOTE_ROOTFS}")
            # Push tar and extract on device
            remote_tar = f"{REMOTE_CACHE}/alpine-minirootfs.tar.gz"
            self.adb.shell(self.serial, f"mkdir -p {REMOTE_CACHE}")
            if not self.adb.push(self.serial, local_rootfs, remote_tar):
                self._notify("error", "Falha ao enviar rootfs", 0)
                return False
            self.adb.shell(self.serial,
                f"cd {REMOTE_ROOTFS} && tar xzf {remote_tar} && rm -f {remote_tar}",
                timeout=60)
            self._notify("rootfs", "Rootfs extraido com sucesso", 0.5)

        # Step 3: Setup DNS in rootfs
        self._notify("dns", "Configurando DNS...", 0.55)
        self.adb.shell(self.serial,
            f"echo 'nameserver 8.8.8.8' > {REMOTE_ROOTFS}/etc/resolv.conf")
        self.adb.shell(self.serial,
            f"echo 'nameserver 8.8.4.4' >> {REMOTE_ROOTFS}/etc/resolv.conf")

        # Step 4: Install Python3 via PRoot (bootstrap)
        self._notify("python", "Instalando Python3 via PRoot...", 0.6)
        self._setup_apk_repos(arch)
        self._install_python()

        # Step 5: Copy server files
        self._notify("server", "Copiando servidor ANK...", 0.75)
        self._copy_server_files()

        # Step 6: Create config
        self._notify("config", "Criando configuracao...", 0.85)
        self._create_config()

        # Step 7: Write mode file
        self._notify("mode", "Salvando modo de operacao...", 0.9)
        self.adb.shell(self.serial,
            f'echo \'{{"mode":"lite","tier":"lite"}}\' > {ANK_DIR}/mode')

        self._notify("done", "Instalacao Lite concluida!", 1.0)
        return True

    def _setup_apk_repos(self, arch: str):
        """Setup Alpine repos inside rootfs via PRoot."""
        # Create repos file
        repo_line = f"https://dl-cdn.alpinelinux.org/alpine/v3.20/main"
        self.adb.shell(self.serial,
            f"echo '{repo_line}' > {REMOTE_ROOTFS}/etc/apk/repositories")
        # Also add community repo
        self.adb.shell(self.serial,
            f"echo 'https://dl-cdn.alpinelinux.org/alpine/v3.20/community' >> {REMOTE_ROOTFS}/etc/apk/repositories")

    def _install_python(self):
        """Install Python3 in rootfs using PRoot + apk."""
        # Use PRoot to run apk
        cmd = (
            f"LD_LIBRARY_PATH={REMOTE_ROOTFS}/lib:{REMOTE_ROOTFS}/usr/lib "
            f"{REMOTE_PROOT} -0 -r {REMOTE_ROOTFS} "
            f"/sbin/apk add --no-cache python3"
        )
        output, code = self.adb.shell(self.serial, cmd, timeout=120)
        if code != 0:
            # Try with --allow-untrusted if key issue
            cmd = (
                f"LD_LIBRARY_PATH={REMOTE_ROOTFS}/lib:{REMOTE_ROOTFS}/usr/lib "
                f"{REMOTE_PROOT} -0 -r {REMOTE_ROOTFS} "
                f"/sbin/apk add --no-cache --allow-untrusted python3"
            )
            self.adb.shell(self.serial, cmd, timeout=120)

    def _copy_server_files(self):
        """Copy server.py and static files to the device."""
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project_dir = os.path.dirname(script_dir)

        # server.py
        server_py = os.path.join(project_dir, "server", "server.py")
        if os.path.exists(server_py):
            self.adb.shell(self.serial, f"mkdir -p {REMOTE_ROOTFS}/opt/ank")
            self.adb.push(self.serial, server_py, f"{REMOTE_ROOTFS}/opt/ank/server.py")

        # static/
        static_dir = os.path.join(project_dir, "server", "static")
        if os.path.isdir(static_dir):
            self.adb.shell(self.serial, f"mkdir -p {REMOTE_ROOTFS}/opt/ank/static")
            for root, dirs, files in os.walk(static_dir):
                for f in files:
                    local = os.path.join(root, f)
                    rel = os.path.relpath(local, static_dir).replace("\\", "/")
                    remote = f"{REMOTE_ROOTFS}/opt/ank/static/{rel}"
                    # Ensure remote dir exists
                    remote_dir = os.path.dirname(remote)
                    self.adb.shell(self.serial, f"mkdir -p {remote_dir}")
                    self.adb.push(self.serial, local, remote)

        # Core scripts (for lite mode, simplified)
        self.adb.shell(self.serial, f"mkdir -p {ANK_DIR}/core")

    def _create_config(self):
        """Create default config.json."""
        import json
        config = {
            "username": "admin",
            "password": "admin123",
            "force_change": True,
            "server_port": 8001,
            "lang": "pt",
        }
        # Write via adb shell echo (avoid push for small file)
        config_str = json.dumps(config).replace("'", "'\\''")
        self.adb.shell(self.serial,
            f"echo '{config_str}' > {ANK_DIR}/config.json")

        # Create credentials file
        self.adb.shell(self.serial,
            f"echo 'ANK - Credenciais de Acesso' > {ANK_DIR}/CREDENCIAIS.txt")
        self.adb.shell(self.serial,
            f"echo 'Usuario: admin' >> {ANK_DIR}/CREDENCIAIS.txt")
        self.adb.shell(self.serial,
            f"echo 'Senha: admin123' >> {ANK_DIR}/CREDENCIAIS.txt")
        self.adb.shell(self.serial,
            f"echo 'IMPORTANTE: Troque a senha apos o primeiro login!' >> {ANK_DIR}/CREDENCIAIS.txt")

    def start_server(self) -> bool:
        """Start the ANK server in Lite mode (via PRoot)."""
        cmd = (
            f"cd {REMOTE_ROOTFS} && "
            f"LD_LIBRARY_PATH={REMOTE_ROOTFS}/lib:{REMOTE_ROOTFS}/usr/lib "
            f"{REMOTE_PROOT} -0 -r {REMOTE_ROOTFS} "
            f"/usr/bin/python3 /opt/ank/server.py &"
        )
        output, code = self.adb.shell(self.serial, cmd, timeout=5)
        return code == 0

"""
ANK Installer - Lite Mode Installer
Non-root installation via ADB using PRoot.
"""

import os
import sys
import time
import hashlib
import tempfile
from typing import Optional, Callable, List
from core.adb import ADB


# PRoot static binary (from proot-me/proot GitHub releases)
# Single universal URL — GitHub /latest redirect handles arch + version
PROOT_URL = "https://github.com/proot-me/proot/releases/latest/download/proot"

# Alpine minirootfs (multiple mirrors)
ALPINE_URLS = [
    "https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/{arch}/alpine-minirootfs-3.20.2-{arch}.tar.gz",
    "https://mirrors.tuna.tsinghua.edu.cn/alpine/v3.20/releases/{arch}/alpine-minirootfs-3.20.2-{arch}.tar.gz",
]
ALPINE_ARCH_MAP = {"aarch64": "aarch64", "armv7l": "armhf", "x86_64": "x86_64"}

# Remote paths (on device)
ANK_DIR = "/data/local/ank"
REMOTE_PROOT = f"{ANK_DIR}/proot"
REMOTE_ROOTFS = f"{ANK_DIR}/ankfs"
REMOTE_BOOTSTRAP = f"{ANK_DIR}/ank-lite-bootstrap.sh"
REMOTE_CACHE = f"{ANK_DIR}/cache"


class LiteInstaller:
    """Handles non-root installation via PRoot + ADB."""

    def __init__(self, adb: ADB, serial: str, callback: Optional[Callable] = None, retry_callback: Optional[Callable] = None):
        """
        Args:
            adb: ADB instance
            serial: Device serial number
            callback: Optional callback(step, message, progress) for UI updates
            retry_callback: Optional callback(url, error) -> bool. Return True to retry.
        """
        self.adb = adb
        self.serial = serial
        self.callback = callback
        self.retry_callback = retry_callback

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
        elif arch in ("i686", "i386", "x86"):
            return "i686"
        else:
            return "aarch64"  # default to most common mobile arch

    def _download_with_retry(self, urls: List[str], dest: str, max_retries: int = 2) -> bool:
        """Download a file with retry and mirror fallback."""
        import urllib.request
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        for url in urls:
            for attempt in range(max_retries + 1):
                try:
                    self._notify("download", f"Trying {url}...", 0)
                    urllib.request.urlretrieve(url, dest)
                    self._notify("download", f"Download complete: {os.path.basename(dest)}", 0)
                    return True
                except Exception as e:
                    if attempt < max_retries:
                        self._notify("download", f"Attempt {attempt + 1} failed, retrying...", 0)
                        time.sleep(2)
                    else:
                        self._notify("download", f"Mirror failed: {e}", 0)

        # All mirrors failed - ask user to retry
        if self.retry_callback:
            self._notify("download", "All mirrors failed", 0)
            if self.retry_callback(urls[0] if urls else "", "All mirrors unavailable"):
                return self._download_with_retry(urls, dest, max_retries)

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

    def _extract_prebuild_from_zip(self, arch: str) -> Optional[str]:
        """Extract ank-prebuild from the bundled ZIP and return the tarball path."""
        import zipfile
        zip_path = self._find_zip()
        if not zip_path:
            return None
        tmp_dir = tempfile.mkdtemp(prefix="ank_lite_prebuild_")
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(tmp_dir)
        except Exception:
            return None
        # Find the prebuild tarball for this arch
        for root, dirs, files in os.walk(tmp_dir):
            for f in files:
                if f"ank-prebuild-{arch}" in f:
                    return os.path.join(root, f)
        # Fallback: any prebuild
        for root, dirs, files in os.walk(tmp_dir):
            for f in files:
                if "ank-prebuild-" in f:
                    return os.path.join(root, f)
        return None

    def install(self) -> bool:
        """
        Run the full Lite installation.
        Returns True on success.
        """
        self._notify("arch", "Detecting architecture...", 0.05)
        arch = self._get_arch()

        self._notify("arch", f"Architecture: {arch}", 0.1)

        # Step 1: Push PRoot binary
        self._notify("proot", "Preparing PRoot...", 0.15)
        local_proot = self._find_local_proot(arch)
        if local_proot:
            self._notify("proot", "Using local PRoot...", 0.2)
        else:
            # First try: device downloads directly with curl/wget
            self._notify("proot", "Downloading PRoot on device...", 0.2)
            self.adb.shell(self.serial, f"mkdir -p {ANK_DIR}")
            dl_ok = False
            for cmd in [f"curl -sL -o {REMOTE_PROOT} {PROOT_URL}",
                        f"wget -q -O {REMOTE_PROOT} {PROOT_URL}"]:
                out, code = self.adb.shell(self.serial, cmd, timeout=60)
                if code == 0:
                    dl_ok = True
                    break
            if dl_ok:
                self.adb.shell(self.serial, f"chmod 755 {REMOTE_PROOT}")
                self._notify("proot", "PRoot downloaded on device", 0.25)
            else:
                # Fallback: download to PC temp, then push
                self._notify("proot", "Downloading PRoot to PC...", 0.2)
                import tempfile
                local_proot = os.path.join(tempfile.gettempdir(), f"proot-{arch}")
                if not self._download_with_retry([PROOT_URL], local_proot):
                    self._notify("error", "Failed to download PRoot", 0)
                    return False
                os.chmod(local_proot, 0o755)
                self._notify("proot", "Uploading PRoot to the device...", 0.25)
                self.adb.shell(self.serial, f"mkdir -p {ANK_DIR}")
                if not self.adb.push(self.serial, local_proot, REMOTE_PROOT):
                    self._notify("error", "Failed to upload PRoot", 0)
                    return False
                self.adb.shell(self.serial, f"chmod 755 {REMOTE_PROOT}")

        # Step 2: Extract prebuild rootfs (same logic as install.sh)
        self._notify("rootfs", "Checking rootfs...", 0.35)
        output, _ = self.adb.shell(self.serial, f"ls {REMOTE_ROOTFS}/bin/sh 2>/dev/null")
        if output and "/bin/sh" in output:
            self._notify("rootfs", "Rootfs already present, skipping...", 0.5)
        else:
            self.adb.shell(self.serial, f"mkdir -p {REMOTE_ROOTFS} {REMOTE_CACHE}")

            # PATH A: prebuild from bundled ZIP (same as install.sh)
            prebuild_path = self._extract_prebuild_from_zip(arch)
            if prebuild_path:
                self._notify("rootfs", f"Using prebuild: {os.path.basename(prebuild_path)}", 0.4)
                remote_tar = f"{REMOTE_CACHE}/ank-prebuild.tar.gz"
                if not self.adb.push(self.serial, prebuild_path, remote_tar):
                    self._notify("error", "Failed to upload prebuild", 0)
                    return False
                self.adb.shell(self.serial,
                    f"cd {REMOTE_ROOTFS} && tar xzf {remote_tar} && rm -f {remote_tar}",
                    timeout=120)
            else:
                # PATH B: no prebuild — download Alpine on device + install packages
                self._notify("rootfs", "Prebuild not found, downloading Alpine...", 0.4)
                alpine_arch = ALPINE_ARCH_MAP.get(arch, arch)
                alpine_urls = [url.format(arch=alpine_arch) for url in ALPINE_URLS]
                remote_tar = f"{REMOTE_CACHE}/alpine-minirootfs.tar.gz"
                dl_ok = False
                for url in alpine_urls:
                    for cmd in [f"curl -sL -o {remote_tar} {url}",
                                f"wget -q -O {remote_tar} {url}"]:
                        self.adb.shell(self.serial, cmd, timeout=120)
                        out, _ = self.adb.shell(self.serial, f"[ -s {remote_tar} ] && echo ok")
                        if "ok" in out:
                            dl_ok = True
                            break
                    if dl_ok:
                        break
                if not dl_ok:
                    self._notify("error", "Failed to download Alpine rootfs", 0)
                    return False
                self.adb.shell(self.serial,
                    f"cd {REMOTE_ROOTFS} && tar xzf {remote_tar} && rm -f {remote_tar}",
                    timeout=60)

            # Verify
            output, _ = self.adb.shell(self.serial, f"ls {REMOTE_ROOTFS}/bin/sh 2>/dev/null")
            if not output or "sh" not in output:
                self._notify("error", "Rootfs extraction failed", 0)
                return False
            self._notify("rootfs", "Rootfs extracted successfully", 0.5)

        # Step 3: Setup DNS in rootfs
        self._notify("dns", "Configuring DNS...", 0.55)
        self.adb.shell(self.serial,
            f"echo 'nameserver 8.8.8.8' > {REMOTE_ROOTFS}/etc/resolv.conf")
        self.adb.shell(self.serial,
            f"echo 'nameserver 8.8.4.4' >> {REMOTE_ROOTFS}/etc/resolv.conf")

        # Step 4: Install Python3 via PRoot (bootstrap)
        self._notify("python", "Installing Python3 via PRoot...", 0.6)
        self._setup_apk_repos(arch)
        self._install_python()

        # Step 5: Copy server files
        self._notify("server", "Copying the ANK server...", 0.75)
        self._copy_server_files()

        # Step 6: Create config
        self._notify("config", "Creating configuration...", 0.85)
        self._create_config()

        # Step 7: Write mode file
        self._notify("mode", "Saving operation mode...", 0.9)
        self.adb.shell(self.serial,
            f'echo \'{{"mode":"lite","tier":"lite"}}\' > {ANK_DIR}/mode')

        self._notify("done", "Lite installation complete!", 1.0)
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
        """Install ALL packages in rootfs using PRoot + apk (same as install.sh)."""
        # Same packages as install.sh PATH B
        cmd = (
            f"LD_LIBRARY_PATH={REMOTE_ROOTFS}/lib:{REMOTE_ROOTFS}/usr/lib "
            f"{REMOTE_PROOT} -0 -r {REMOTE_ROOTFS} "
            f"/sbin/apk add --no-cache python3 openssl openssh bash busybox shadow sshpass nginx"
        )
        output, code = self.adb.shell(self.serial, cmd, timeout=180)
        if code != 0:
            cmd = (
                f"LD_LIBRARY_PATH={REMOTE_ROOTFS}/lib:{REMOTE_ROOTFS}/usr/lib "
                f"{REMOTE_PROOT} -0 -r {REMOTE_ROOTFS} "
                f"/sbin/apk add --no-cache --allow-untrusted python3 openssl openssh bash busybox shadow sshpass nginx"
            )
            self.adb.shell(self.serial, cmd, timeout=180)

        # Setup busybox symlinks (same as install.sh)
        self.adb.shell(self.serial,
            f"{REMOTE_PROOT} -0 -r {REMOTE_ROOTFS} /bin/busybox --install -s /bin 2>/dev/null")

    def _copy_server_files(self):
        """Copy server.py, static files, and core scripts to the device."""
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
                    remote_dir = os.path.dirname(remote)
                    self.adb.shell(self.serial, f"mkdir -p {remote_dir}")
                    self.adb.push(self.serial, local, remote)

        # Core scripts
        scripts_dir = os.path.join(project_dir, "magisk-module", "scripts")
        remote_scripts = f"{ANK_DIR}/core"
        self.adb.shell(self.serial, f"mkdir -p {remote_scripts}")
        if os.path.isdir(scripts_dir):
            for f in os.listdir(scripts_dir):
                if f.endswith(".sh"):
                    local = os.path.join(scripts_dir, f)
                    self.adb.push(self.serial, local, f"{remote_scripts}/{f}")
            self.adb.shell(self.serial, f"chmod 755 {remote_scripts}/*.sh 2>/dev/null")

        # Images directory (for Alpine base + container base)
        self.adb.shell(self.serial, f"mkdir -p {ANK_DIR}/images/alpine-3.20")
        self.adb.shell(self.serial, f"mkdir -p {ANK_DIR}/images/ank-alpinebase")

        # Containers structure
        self.adb.shell(self.serial, f"mkdir -p {ANK_DIR}/containers")

        # Logs directory
        self.adb.shell(self.serial, f"mkdir -p {ANK_DIR}/logs")

        # Cache directory
        self.adb.shell(self.serial, f"mkdir -p {ANK_DIR}/cache")

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

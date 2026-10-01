"""
ANK Installer - ADB Wrapper
Uses adbutils for device detection and communication.

ADB resolution order (so the installer works even without a system-wide
"adb" on PATH, mirroring how ank-magisk.zip / ank-launcher.apk are looked
up next to the executable):
  1. platform-tools/adb(.exe) bundled next to the installer executable.
  2. A copy previously downloaded into the local cache dir (~/.ank-installer/platform-tools).
  3. "adb" on the system PATH.
  4. As a last resort, download Google's official platform-tools zip into
     the local cache dir and use that.
Resolution happens lazily on the first real ADB command (not at ADB()
construction time), and only once per process - all further ADB() objects
reuse the same resolved path.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from typing import Optional, List, Dict

# Windows: prevent console window flicker from subprocess calls
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_PLATFORM_TOOLS_URLS = {
    "win32": "https://dl.google.com/android/repo/platform-tools-latest-windows.zip",
    "darwin": "https://dl.google.com/android/repo/platform-tools-latest-darwin.zip",
    "linux": "https://dl.google.com/android/repo/platform-tools-latest-linux.zip",
}

_ADB_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".ank-installer", "platform-tools")

# Module-level memo: resolved once per process so repeated `ADB()` objects
# (the codebase creates a fresh one per call site) don't re-probe the disk
# or re-download on every single call.
_resolved_adb_path: Optional[str] = None


def _adb_exe_name() -> str:
    return "adb.exe" if sys.platform == "win32" else "adb"


def _app_base_dir() -> str:
    """Directory the running exe/script lives in - the same directory
    ank-magisk.zip and ank-launcher.apk are looked up in."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_bundled_adb() -> Optional[str]:
    """adb shipped by the packager next to the installer, e.g.
    ANK-Installer.exe + platform-tools/adb.exe + platform-tools/*.dll"""
    exe_name = _adb_exe_name()
    base = _app_base_dir()
    for candidate in (
        os.path.join(base, "platform-tools", exe_name),
        os.path.join(base, exe_name),
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def _find_cached_adb() -> Optional[str]:
    path = os.path.join(_ADB_CACHE_DIR, _adb_exe_name())
    return path if os.path.isfile(path) else None


def _find_system_adb() -> Optional[str]:
    return shutil.which("adb")


def _download_platform_tools(on_progress=None) -> Optional[str]:
    """Download Google's official platform-tools zip and extract adb (plus
    the Windows companion DLLs) into the local cache dir. Returns the
    resolved adb path on success, or None."""
    url = _PLATFORM_TOOLS_URLS.get(sys.platform, _PLATFORM_TOOLS_URLS["linux"])
    try:
        import urllib.request

        os.makedirs(_ADB_CACHE_DIR, exist_ok=True)
        tmp_zip = os.path.join(tempfile.gettempdir(), "ank-platform-tools.zip")

        if on_progress:
            on_progress("Downloading ADB (platform-tools)...")
        urllib.request.urlretrieve(url, tmp_zip)

        if on_progress:
            on_progress("Extracting ADB...")
        wanted = {"adb.exe", "adb", "adbwinapi.dll", "adbwinusbapi.dll"}
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            for member in zf.namelist():
                name = os.path.basename(member)
                if name.lower() in wanted:
                    with zf.open(member) as src:
                        with open(os.path.join(_ADB_CACHE_DIR, name), "wb") as dst:
                            shutil.copyfileobj(src, dst)

        try:
            os.remove(tmp_zip)
        except OSError:
            pass

        adb_path = os.path.join(_ADB_CACHE_DIR, _adb_exe_name())
        if os.path.isfile(adb_path):
            if sys.platform != "win32":
                os.chmod(adb_path, 0o755)
            return adb_path
    except Exception:
        pass
    return None


def resolve_adb_path(on_progress=None) -> str:
    """Find a usable adb binary, downloading it once (and caching it) if
    nothing else is available. Safe to call from a background thread - it
    only touches disk / network the first time it's needed."""
    global _resolved_adb_path
    if _resolved_adb_path and (os.path.isfile(_resolved_adb_path) or shutil.which(_resolved_adb_path)):
        return _resolved_adb_path

    for finder in (_find_bundled_adb, _find_cached_adb, _find_system_adb):
        found = finder()
        if found:
            _resolved_adb_path = found
            return found

    downloaded = _download_platform_tools(on_progress)
    if downloaded:
        _resolved_adb_path = downloaded
        return downloaded

    # Nothing worked (offline first run, etc.) - fall back to the bare
    # command name so the caller gets a clear "not found" error instead of
    # a crash, exactly like the original behaviour.
    _resolved_adb_path = _adb_exe_name()
    return _resolved_adb_path


class ADBDevice:
    """Represents a connected Android device."""

    def __init__(self, serial: str, state: str = "device"):
        self.serial = serial
        self.state = state
        self.model: Optional[str] = None
        self.android_version: Optional[str] = None
        self.kernel: Optional[str] = None
        self.is_rooted: Optional[bool] = None
        self.has_magisk: Optional[bool] = None

    def __str__(self):
        root_status = "Rooted" if self.is_rooted else ("No Root" if self.is_rooted is not None else "Unknown")
        model = self.model or self.serial
        return f"{model} | {root_status}"


class ADB:
    """ADB wrapper using subprocess (adbutils fallback)."""

    def __init__(self):
        # Resolved lazily on first real command - see resolve_adb_path().
        self._adb_path: Optional[str] = None

    def _ensure_adb_path(self) -> str:
        if self._adb_path is None:
            self._adb_path = resolve_adb_path()
        return self._adb_path

    def _run(self, args: List[str], timeout: int = 10) -> subprocess.CompletedProcess:
        """Run an adb command."""
        cmd = [self._ensure_adb_path()] + args
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW
        )

    def _run_device(self, serial: str, args: List[str], timeout: int = 10) -> subprocess.CompletedProcess:
        """Run an adb command on a specific device."""
        return self._run(["-s", serial] + args, timeout=timeout)

    def devices(self) -> List[ADBDevice]:
        """List connected devices."""
        result = self._run(["devices"])
        devices = []
        for line in result.stdout.strip().split("\n")[1:]:
            parts = line.strip().split("\t")
            if len(parts) == 2 and parts[1] == "device":
                devices.append(ADBDevice(parts[0], parts[1]))
        return devices

    def get_model(self, serial: str) -> str:
        """Get device model."""
        result = self._run_device(serial, ["shell", "getprop", "ro.product.model"])
        return result.stdout.strip() or serial

    def get_android_version(self, serial: str) -> str:
        """Get Android version."""
        result = self._run_device(serial, ["shell", "getprop", "ro.build.version.release"])
        return result.stdout.strip() or "Unknown"

    def get_kernel(self, serial: str) -> str:
        """Get kernel version."""
        result = self._run_device(serial, ["shell", "uname", "-r"])
        return result.stdout.strip() or "Unknown"

    def check_root(self, serial: str) -> bool:
        """Check if device has root access."""
        try:
            result = self._run_device(serial, ["shell", "su", "-c", "exit"], timeout=5)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def check_magisk(self, serial: str) -> bool:
        """Check if Magisk is installed."""
        try:
            result = self._run_device(serial, ["shell", "su", "-c", "magisk --version"], timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return True
            # Fallback: check if magisk binary exists
            result2 = self._run_device(serial, ["shell", "su", "-c", "which magisk"], timeout=5)
            return result2.returncode == 0 and result2.stdout.strip() != ""
        except subprocess.TimeoutExpired:
            return False

    def check_kernelsu(self, serial: str) -> bool:
        """Check if KernelSU is installed."""
        try:
            # Check for KernelSU binary
            result = self._run_device(serial, ["shell", "su", "-c", "ksud --version"], timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return True
            # Check for KernelSU manager
            result2 = self._run_device(serial, ["shell", "ls /data/adb/ksu 2>/dev/null"], timeout=5)
            if result2.returncode == 0 and result2.stdout.strip():
                return True
            # Check kernel module
            result3 = self._run_device(serial, ["shell", "lsmod 2>/dev/null | grep ksu"], timeout=5)
            if result3.returncode == 0 and result3.stdout.strip():
                return True
        except subprocess.TimeoutExpired:
            pass
        return False

    def get_kernel_su_version(self, serial: str) -> str:
        """Get KernelSU version."""
        try:
            result = self._run_device(serial, ["shell", "su", "-c", "ksud --version"], timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except subprocess.TimeoutExpired:
            pass
        return "Unknown"

    def get_magisk_version(self, serial: str) -> str:
        """Get Magisk version."""
        try:
            result = self._run_device(serial, ["shell", "su", "-c", "magisk --version"], timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split("(")[0].strip()
            # Fallback: get version from manager
            result2 = self._run_device(serial, ["shell", "su", "-c", "magisk -v"], timeout=5)
            if result2.returncode == 0:
                return result2.stdout.strip()
        except subprocess.TimeoutExpired:
            pass
        return "Unknown"

    def check_proot(self, serial: str) -> bool:
        """Check if PRoot is available on the device."""
        # Check if PRoot binary exists in ANK dir
        output, _ = self.shell(serial, "ls /data/local/ank/proot 2>/dev/null")
        if output and "proot" in output:
            return True
        # Check system-wide
        output, _ = self.shell(serial, "which proot 2>/dev/null || echo ''")
        if output:
            return True
        # Check Termux
        output, _ = self.shell(serial, "ls /data/data/com.termux/files/usr/bin/proot 2>/dev/null")
        if output and "proot" in output:
            return True
        return False

    def check_termux(self, serial: str) -> bool:
        """Check if Termux is installed."""
        output, _ = self.shell(serial, "ls /data/data/com.termux 2>/dev/null")
        return bool(output and "com.termux" in output)

    def forward(self, serial: str, local_port: int, remote_port: int) -> bool:
        result = self._run_device(serial, ["forward", f"tcp:{local_port}", f"tcp:{remote_port}"])
        return result.returncode == 0

    def forward_remove(self, serial: str, local_port: int) -> bool:
        result = self._run_device(serial, ["forward", "--remove", f"tcp:{local_port}"])
        return result.returncode == 0

    def push(self, serial: str, local_path: str, remote_path: str) -> bool:
        """Push a file to the device."""
        result = self._run_device(serial, ["push", local_path, remote_path], timeout=120)
        return result.returncode == 0

    def pull(self, serial: str, remote_path: str, local_path: str, timeout: int = 180) -> bool:
        """Pull a file from the device."""
        result = self._run_device(serial, ["pull", remote_path, local_path], timeout=timeout)
        return result.returncode == 0

    def shell(self, serial: str, command: str, timeout: int = 30) -> tuple:
        """Run a shell command on the device."""
        result = self._run_device(serial, ["shell", command], timeout=timeout)
        return result.stdout.strip(), result.returncode

    def shell_su(self, serial: str, command: str, timeout: int = 30) -> tuple:
        """Run a shell command as root on the device."""
        return self.shell(serial, f"su -c '{command}'", timeout=timeout)

    def shell_su_streaming(self, serial: str, command: str, on_line, timeout: int = 600):
        """Run a shell command as root, streaming each line to callback. Returns exit code."""
        import subprocess as sp
        cmd = [self._adb_path, "-s", serial, "shell", f"su -c '{command}'"]
        proc = sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.STDOUT,
                        text=True, bufsize=1, creationflags=CREATE_NO_WINDOW)
        try:
            for line in proc.stdout:
                on_line(line.rstrip("\n"))
            proc.wait(timeout=timeout)
            return proc.returncode
        except sp.TimeoutExpired:
            proc.kill()
            return -1
        except Exception:
            proc.kill()
            return -1

    def reboot(self, serial: str) -> bool:
        """Reboot the device."""
        result = self._run_device(serial, ["reboot"])
        return result.returncode == 0

    def wait_for_device(self, serial: str, timeout: int = 120) -> bool:
        """Wait for device to come online after reboot."""
        start = time.time()
        while time.time() - start < timeout:
            devices = self.devices()
            for d in devices:
                if d.serial == serial and d.state == "device":
                    return True
            time.sleep(3)
        return False

    def wait_for_boot_completed(self, serial: str, timeout: int = 120) -> bool:
        """Wait until sys.boot_completed == 1 after reboot."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                result = self._run_device(serial, ["shell", "getprop", "sys.boot_completed"], timeout=5)
                if result.stdout.strip() == "1":
                    return True
            except subprocess.TimeoutExpired:
                pass
            time.sleep(2)
        return False

    def get_device_ip(self, serial: str) -> Optional[str]:
        """Get device IP address (wlan0)."""
        cmds = [
            "ip -4 -o addr show wlan0 | cut -d' ' -f7 | cut -d/ -f1",
            "ifconfig wlan0 2>/dev/null | grep 'inet ' | cut -d: -f2 | cut -d' ' -f1",
            "ip addr show wlan0 2>/dev/null | grep 'inet ' | cut -d' ' -f6 | cut -d/ -f1",
            "dumpsys wifi 2>/dev/null | grep -o 'inet [0-9.]*' | head -1 | cut -d' ' -f2",
        ]
        for cmd in cmds:
            result = self.shell(serial, cmd)
            ip = (result[0] or "").strip()
            if ip and ip.count('.') == 3 and not ip.startswith("127."):
                return ip.split('\n')[0].strip()
        return None

    def check_ank_installed(self, serial: str) -> bool:
        """Check if ANK is installed on the device (rooted or lite)."""
        output, _ = self.shell(serial, "ls /data/local/ank/mode 2>/dev/null; ls /data/local/tmp/ank/mode 2>/dev/null")
        return bool(output and "mode" in output)

    def get_ank_mode(self, serial: str) -> Optional[str]:
        """Get ANK installation mode."""
        for path in ("/data/local/ank/mode", "/data/local/tmp/ank/mode"):
            output, _ = self.shell(serial, f"cat {path} 2>/dev/null")
            if output and output.strip().startswith("{"):
                try:
                    import json
                    data = json.loads(output.strip())
                    return data.get("mode")
                except Exception:
                    pass
        return None

    def get_ank_base_dir(self, serial: str) -> str:
        """Get the ANK base directory (/data/local/ank or /data/local/tmp/ank)."""
        output, _ = self.shell(serial, "ls /data/local/ank/mode 2>/dev/null")
        if output and "mode" in output:
            return "/data/local/ank"
        return "/data/local/tmp/ank"

    ANK_UI_PACKAGE = "com.ank.anklauncher"

    def check_ank_ui_installed(self, serial: str) -> bool:
        """Check if ANK UI (launcher) is installed — exact package only."""
        output, _ = self.shell(serial, f"pm path {self.ANK_UI_PACKAGE} 2>/dev/null")
        return bool(output and "package:" in output)

    def uninstall_ank_ui(self, serial: str, callback=None) -> bool:
        """Uninstall ANK UI (launcher) from the device — exact package only."""
        if callback:
            callback("Removing ANK UI...")
        pkg = self.ANK_UI_PACKAGE
        output, _ = self.shell(serial, f"pm path {pkg} 2>/dev/null")
        if output and "package:" in output:
            if callback:
                callback(f"Uninstalling {pkg}...")
            self.shell(serial, f"pm uninstall {pkg}")
        return True

    def uninstall_ank_full(self, serial: str, rooted: bool = True, callback=None) -> bool:
        """Full uninstall of ANK from the device."""
        _sh = lambda cmd: self.shell_su(serial, cmd) if rooted else self.shell(serial, cmd)

        steps = [
            ("Killing ANK processes...", lambda: _sh(
                "pkill -9 -f 'ld-musl.*python3.*server.py' 2>/dev/null; "
                "pkill -9 -f 'ld-musl.*server.py' 2>/dev/null; "
                "pkill -9 -f 'sshd.*PidFile' 2>/dev/null; "
                "pkill -9 -f 'sshd.*-p.*22[0-9][0-9]' 2>/dev/null; "
                "pkill -9 -f 'proot.*-r.*/ank' 2>/dev/null; "
                "pkill -9 -f 'python3.*server.py' 2>/dev/null"
            )),
            ("Unmounting bind mounts...", lambda: _sh(
                "for m in /data/local/ank/ankfs/dev/null /data/local/ank/ankfs/dev/urandom "
                "/data/local/ank/ankfs/dev/random /data/local/ank/ankfs/dev/tty "
                "/data/local/ank/ankfs/dev/ptmx /data/local/ank/ankfs/proc "
                "/data/local/ank/ankfs/dev/pts /data/local/ank/ankfs/dev/shm "
                "/data/local/ank/ankfs/sys /data/local/ank/ankfs/run /data/local/ank/ankfs/tmp; do "
                "umount \"$m\" 2>/dev/null; umount -l \"$m\" 2>/dev/null; done"
            )),
            ("Unmounting container mounts...", lambda: _sh(
                "for c in /data/local/ank/containers/*/merged; do "
                "[ -d \"$c\" ] || continue; "
                "for m in dev/pts dev/shm dev proc sys run tmp; do "
                "umount \"$c/$m\" 2>/dev/null; umount -l \"$c/$m\" 2>/dev/null; done; "
                "umount \"$c\" 2>/dev/null; umount -l \"$c\" 2>/dev/null; done"
            )),
            ("Cleaning iptables...", lambda: _sh(
                "iptables -t nat -S 2>/dev/null | grep -i ank | sed 's/-A/-D/g' | while read rule; do "
                "iptables -t nat $rule 2>/dev/null; done; "
                "iptables -S 2>/dev/null | grep -i ank | sed 's/-A/-D/g' | while read rule; do "
                "iptables $rule 2>/dev/null; done"
            )),
            ("Removing bridge...", lambda: _sh(
                "ip link set ank0 down 2>/dev/null; ip link delete ank0 2>/dev/null; "
                "ip netns list 2>/dev/null | grep -i 'netns_\\|ank' | cut -d' ' -f1 | while read ns; do "
                "ip netns delete \"$ns\" 2>/dev/null; done"
            )),
            ("Removing /data/local/ank...", lambda: _sh("rm -rf /data/local/ank")),
            ("Removing /data/local/tmp/ank...", lambda: _sh("rm -rf /data/local/tmp/ank")),
            ("Removing /sdcard/AndroidKonteiner...", lambda: _sh("rm -rf /sdcard/AndroidKonteiner")),
            ("Removing Magisk module...", lambda: _sh("rm -rf /data/adb/modules/ank /data/adb/service.d/ank.sh")),
            ("Removing ANK UI...", lambda: self.uninstall_ank_ui(serial, callback)),
            ("Cleaning caches...", lambda: _sh("rm -rf /data/local/tmp/ank* 2>/dev/null")),
        ]
        for msg, func in steps:
            if callback:
                callback(msg)
            func()
        return True

"""
ANK Installer - ADB Wrapper
Uses adbutils for device detection and communication.
"""

import subprocess
import time
import sys
from typing import Optional, List, Dict

# Windows: prevent console window flicker from subprocess calls
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


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
        self._adb_path = "adb"

    def _run(self, args: List[str], timeout: int = 10) -> subprocess.CompletedProcess:
        """Run an adb command."""
        cmd = [self._adb_path] + args
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

    def push(self, serial: str, local_path: str, remote_path: str) -> bool:
        """Push a file to the device."""
        result = self._run_device(serial, ["push", local_path, remote_path], timeout=120)
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
        """Check if ANK is installed on the device."""
        output, _ = self.shell(serial, "ls /data/local/ank/mode 2>/dev/null")
        return bool(output and "mode" in output)

    def get_ank_mode(self, serial: str) -> Optional[str]:
        """Get ANK installation mode."""
        output, _ = self.shell(serial, "cat /data/local/ank/mode 2>/dev/null")
        if output:
            try:
                import json
                data = json.loads(output.strip())
                return data.get("mode")
            except Exception:
                pass
        return None

    def check_ank_ui_installed(self, serial: str) -> bool:
        """Check if ANK UI (launcher) is installed."""
        output, _ = self.shell(serial, "pm list packages 2>/dev/null | grep ank")
        return bool(output and "ank" in output.lower())

    def uninstall_ank_ui(self, serial: str, callback=None) -> bool:
        """Uninstall ANK UI (launcher) from the device."""
        if callback:
            callback("Removendo ANK UI...")
        output, _ = self.shell(serial, "pm list packages 2>/dev/null | grep ank")
        if output:
            for line in output.strip().split("\n"):
                pkg = line.replace("package:", "").strip()
                if pkg:
                    if callback:
                        callback(f"Desinstalando {pkg}...")
                    self.shell(serial, f"pm uninstall {pkg}")
        return True

    def uninstall_ank_full(self, serial: str, rooted: bool = True, callback=None) -> bool:
        """Full uninstall of ANK from the device."""
        steps = [
            ("Removendo /data/local/ank...", lambda: self.shell_su(serial, "rm -rf /data/local/ank") if rooted else self.shell(serial, "rm -rf /data/local/ank")),
            ("Removendo /sdcard/AndroidKonteiner...", lambda: self.shell_su(serial, "rm -rf /sdcard/AndroidKonteiner") if rooted else self.shell(serial, "rm -rf /sdcard/AndroidKonteiner")),
            ("Removendo ANK UI...", lambda: self.uninstall_ank_ui(serial, callback)),
            ("Limpando caches...", lambda: self.shell(serial, "rm -rf /data/local/tmp/ank* 2>/dev/null")),
        ]
        for msg, func in steps:
            if callback:
                callback(msg)
            func()
        return True

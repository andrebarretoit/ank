"""
ANK Installer - Device Detector
Detects device capabilities and determines installation mode.
"""

import time
from typing import Dict, Optional, Callable
from core.adb import ADB, ADBDevice


# Tier definitions
TIERS = {
    "isolated": {
        "color": "#22c55e",
        "label": "Isolated",
        "label_pt": "Isolado",
        "desc": "NETNS + PIDNS + Overlay",
        "desc_pt": "Namespace de rede + PID + Overlay (recomendado para producao)",
    },
    "shared_network": {
        "color": "#3b82f6",
        "label": "Shared Network",
        "label_pt": "Rede Compartilhada",
        "desc": "PIDNS + Overlay (host network)",
        "desc_pt": "PID namespace + Overlay (rede do host)",
    },
    "shared_host": {
        "color": "#eab308",
        "label": "Shared Host",
        "label_pt": "Host Compartilhado",
        "desc": "Chroot only",
        "desc_pt": "Chroot puro (kernels antigos)",
    },
    "native_host": {
        "color": "#94a3b8",
        "label": "Native Host",
        "label_pt": "Host Nativo",
        "desc": "No containerization",
        "desc_pt": "Sem containerizacao",
    },
    "lite": {
        "color": "#a855f7",
        "label": "Lite",
        "label_pt": "Lite",
        "desc": "PRoot (non-root)",
        "desc_pt": "PRoot userspace (sem root)",
    },
}


class DetectionResult:
    """Result of device capability detection."""

    def __init__(self):
        self.device: Optional[ADBDevice] = None
        self.is_rooted = False
        self.has_magisk = False
        self.has_kernelsu = False
        self.magisk_version = ""
        self.kernelsu_version = ""
        self.root_manager = ""  # "magisk", "kernelsu", or ""
        self.has_chroot = False
        self.has_netns = False
        self.has_pidns = False
        self.has_overlay = False
        self.has_cgroups = False
        self.has_proot = False
        self.has_termux = False
        self.kernel_version = ""
        self.arch = ""
        self.recommended_tier = "lite"
        self.checks: list = []  # [(label, passed, detail)]

    def to_dict(self) -> Dict:
        return {
            "device": str(self.device) if self.device else "Unknown",
            "is_rooted": self.is_rooted,
            "has_magisk": self.has_magisk,
            "has_kernelsu": self.has_kernelsu,
            "magisk_version": self.magisk_version,
            "kernelsu_version": self.kernelsu_version,
            "root_manager": self.root_manager,
            "has_chroot": self.has_chroot,
            "has_netns": self.has_netns,
            "has_pidns": self.has_pidns,
            "has_overlay": self.has_overlay,
            "has_cgroups": self.has_cgroups,
            "has_proot": self.has_proot,
            "has_termux": self.has_termux,
            "kernel_version": self.kernel_version,
            "arch": self.arch,
            "recommended_tier": self.recommended_tier,
            "tier_info": TIERS.get(self.recommended_tier, {}),
        }


class DeviceDetector:
    """Detects device capabilities for ANK installation."""

    def __init__(self, adb: ADB):
        self.adb = adb

    def detect(self, serial: str, callback: Optional[Callable] = None) -> DetectionResult:
        """
        Run full detection on a device.
        callback(label, passed, detail) is called for each check.
        """
        result = DetectionResult()
        result.device = ADBDevice(serial)

        def _check(label: str, func, *args):
            try:
                passed, detail = func(*args)
                result.checks.append((label, passed, detail))
                if callback:
                    callback(label, passed, detail)
                return passed
            except Exception as e:
                result.checks.append((label, False, str(e)))
                if callback:
                    callback(label, False, str(e))
                return False

        # Device info
        _check("Device found", lambda: (True, self.adb.get_model(serial)))
        result.device.model = self.adb.get_model(serial)
        result.device.android_version = self.adb.get_android_version(serial)
        result.device.kernel = self.adb.get_kernel(serial)
        result.kernel_version = result.device.kernel

        # Architecture detection
        result.arch = self._detect_arch(serial)
        _check("Architecture detected", lambda: (True, result.arch))

        _check("ADB authorized", lambda: (True, "Communication OK"))

        # Root check
        result.is_rooted = _check(
            "Root found",
            lambda: (self.adb.check_root(serial), "Magisk" if self.adb.check_root(serial) else "No root")
        )
        result.device.is_rooted = result.is_rooted

        if result.is_rooted:
            # Root manager check (Magisk or KernelSU)
            result.has_magisk = _check(
                "Magisk installed",
                lambda: (self.adb.check_magisk(serial), self.adb.get_magisk_version(serial) if self.adb.check_magisk(serial) else "Not found")
            )
            if result.has_magisk:
                result.magisk_version = self.adb.get_magisk_version(serial)
                result.root_manager = "magisk"
            else:
                result.has_kernelsu = _check(
                    "KernelSU installed",
                    lambda: (self.adb.check_kernelsu(serial), self.adb.get_kernel_su_version(serial) if self.adb.check_kernelsu(serial) else "Not found")
                )
                if result.has_kernelsu:
                    result.kernelsu_version = self.adb.get_kernel_su_version(serial)
                    result.root_manager = "kernelsu"

            # Kernel capabilities
            result.has_chroot = _check(
                "Chroot available",
                lambda: self._check_chroot(serial)
            )

            result.has_netns = _check(
                "NET Namespace available",
                lambda: self._check_netns(serial)
            )

            result.has_pidns = _check(
                "PID Namespace available",
                lambda: self._check_pidns(serial)
            )

            result.has_overlay = _check(
                "OverlayFS available",
                lambda: self._check_overlay(serial)
            )

            result.has_cgroups = _check(
                "Cgroups available",
                lambda: self._check_cgroups(serial)
            )

            # Determine tier
            result.recommended_tier = self._determine_tier(result)
        else:
            # Non-root: check PRoot availability
            result.has_proot = _check(
                "PRoot available",
                lambda: (self.adb.check_proot(serial), "PRoot found" if self.adb.check_proot(serial) else "PRoot will be installed")
            )

            # Check Termux
            result.has_termux = _check(
                "Termux installed",
                lambda: (self.adb.check_termux(serial), "Termux found" if self.adb.check_termux(serial) else "Not found")
            )

            result.recommended_tier = "lite"

        return result

    def _check_chroot(self, serial: str) -> tuple:
        """Check if chroot is available."""
        output, code = self.adb.shell(serial, "which chroot 2>/dev/null || echo ''")
        if output:
            return True, f"Found: {output}"
        # Try to run chroot
        output, code = self.adb.shell_su(serial, "chroot / /bin/true 2>/dev/null && echo ok")
        return "ok" in output, "Chroot functional" if "ok" in output else "Chroot not functional"

    def _check_netns(self, serial: str) -> tuple:
        """Check if network namespaces are available."""
        output, code = self.adb.shell_su(serial, "ip netns add _ank_test 2>/dev/null && ip netns del _ank_test 2>/dev/null && echo ok")
        return "ok" in output, "NETNS available" if "ok" in output else "NETNS unavailable"

    def _check_pidns(self, serial: str) -> tuple:
        """Check if PID namespaces are available."""
        output, code = self.adb.shell_su(serial, "unshare --pid --fork /bin/true 2>/dev/null && echo ok")
        return "ok" in output, "PIDNS available" if "ok" in output else "PIDNS unavailable"

    def _check_overlay(self, serial: str) -> tuple:
        """Check if OverlayFS is available."""
        output, code = self.adb.shell(serial, "cat /proc/filesystems 2>/dev/null | grep overlay")
        return "overlay" in output, "OverlayFS available" if "overlay" in output else "OverlayFS unavailable"

    def _check_cgroups(self, serial: str) -> tuple:
        """Check if cgroups are available."""
        output, code = self.adb.shell(serial, "ls /sys/fs/cgroup/ 2>/dev/null | head -5")
        return bool(output), f"Cgroups: {output[:50]}..." if output else "Cgroups unavailable"

    def _detect_arch(self, serial: str) -> str:
        """Detect device architecture."""
        output, _ = self.adb.shell(serial, "uname -m")
        arch = output.strip().lower()
        if arch in ("aarch64", "arm64"):
            return "aarch64"
        elif arch in ("armv7l", "armv6l"):
            return "armv7l"
        elif arch in ("x86_64", "amd64"):
            return "x86_64"
        return arch or "unknown"

    def _check_proot(self, serial: str) -> tuple:
        """Check if PRoot is available on the device."""
        # Use adb wrapper method
        has_proot = self.adb.check_proot(serial)
        if has_proot:
            # Get details
            output, _ = self.adb.shell(serial, "which proot 2>/dev/null || echo ''")
            if output:
                return True, f"System-wide: {output}"
            output, _ = self.adb.shell(serial, "ls /data/local/ank/proot 2>/dev/null")
            if output and "proot" in output:
                return True, "PRoot found in the ANK dir"
            output, _ = self.adb.shell(serial, "ls /data/data/com.termux/files/usr/bin/proot 2>/dev/null")
            if output and "proot" in output:
                return True, "PRoot via Termux"
            return True, "PRoot found"
        return False, "PRoot will be installed during setup"

    def _determine_tier(self, result: DetectionResult) -> str:
        """Determine the best tier based on capabilities.
        
        Tier table:
        | Tier            | NETNS | PIDNS | Overlay | Root |
        |-----------------|-------|-------|---------|------|
        | Isolated        | Yes   | Yes   | Yes     | Yes  |
        | Shared Network  | No    | Yes   | Yes     | Yes  |
        | Shared Host     | No    | No    | Yes     | Yes  |
        | Native Host     | No    | No    | No      | Yes  |
        | Lite            | No    | No    | No      | No   |
        """
        if result.has_netns and result.has_pidns and result.has_overlay:
            return "isolated"
        elif result.has_pidns and result.has_overlay:
            return "shared_network"
        elif result.has_overlay:
            return "shared_host"
        else:
            return "native_host"

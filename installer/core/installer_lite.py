"""
ANK Installer - Lite Mode Installer
Non-root installation via ADB using PRoot.

Validated flow (tested manually on SM-M127F / aarch64):
  1. Push ZIP to device, unzip to /data/local/tmp/ank_extract
  2. Resolve correct-arch PRoot (bundled -> download -> error)
  3. Extract prebuild rootfs into ANK_DIR/ankfs
  4. Copy server/scripts/ankcoreshell/ank-cli/ank-profile
  5. Build ank-alpinebase-3.20 (2nd tarball extraction + config)
  6. Configure SSH device (host keys, sshd_config port 2200, admin user)
  7. Write config.json, mode, start scripts
  8. Start server via PRoot (validated command)
  9. Verify port 8001 + login
"""

import os
import sys
import json
import struct
import time
import tempfile
from typing import Optional, Callable
from core.adb import ADB


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# Non-rooted devices: shell user cannot create /data/local/ank (Permission
# denied). Everything lives under /data/local/tmp/ank.
ANK_DIR = "/data/local/tmp/ank"
REMOTE_PROOT = f"{ANK_DIR}/proot"
REMOTE_ROOTFS = f"{ANK_DIR}/ankfs"
REMOTE_IMAGES = f"{ANK_DIR}/images"
REMOTE_LOGS = f"{ANK_DIR}/logs"
REMOTE_TMP = f"{ANK_DIR}/tmp"
EXTRACT_DIR = "/data/local/tmp/ank_extract"

# Inside the proot guest, ANK_DIR is bound to /ank so the server can read
# config.json, write logs, containers, images, etc.
GUEST_ANK = "/ank"

# ---------------------------------------------------------------------------
# PRoot sources
# ---------------------------------------------------------------------------
PROOT_URLS = {
    "aarch64": "https://skirsten.github.io/proot-portable-android-binaries/aarch64/proot",
    "armv7l":  "https://skirsten.github.io/proot-portable-android-binaries/armv7/proot",
    "x86_64":  "https://skirsten.github.io/proot-portable-android-binaries/amd64/proot",
}
ELF_MACHINES = {"aarch64": 0xB7, "armv7l": 0x28, "x86_64": 0x3E}


class LiteInstaller:

    def __init__(self, adb: ADB, serial: str,
                 callback: Optional[Callable] = None,
                 retry_callback: Optional[Callable] = None):
        self.adb = adb
        self.serial = serial
        self.callback = callback
        self.retry_callback = retry_callback

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _notify(self, step: str, message: str, progress: float = 0):
        if self.callback:
            self.callback(step, message, progress)

    def _sh(self, cmd: str, timeout: int = 30) -> tuple:
        return self.adb.shell(self.serial, cmd, timeout=timeout)

    def _push_text(self, content: str, remote_path: str) -> bool:
        """Write content to a local temp file and adb push it (avoids echo quoting issues)."""
        fd, tmp = tempfile.mkstemp(prefix="ank_")
        try:
            with os.fdopen(fd, "w", newline="\n") as f:
                f.write(content)
            if not self.adb.push(self.serial, tmp, remote_path):
                return False
            self._sh(f"chmod 644 {remote_path}")
            return True
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def _guest(self, cmd: str, rootfs: str = None, timeout: int = 120) -> tuple:
        """Run a one-shot command inside the proot guest."""
        rootfs = rootfs or REMOTE_ROOTFS
        guest_cmd = f"export PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin; {cmd}"
        full = (
            f"PROOT_TMP_DIR={REMOTE_TMP} {REMOTE_PROOT} -0 "
            f"-r {rootfs} -b /dev -b /proc -b /sys -w /root "
            f"/bin/sh -c '{guest_cmd}'"
        )
        return self._sh(full, timeout=timeout)

    # ------------------------------------------------------------------
    # Arch detection
    # ------------------------------------------------------------------
    def _get_device_model(self) -> str:
        output, _ = self._sh("getprop ro.product.model")
        model = output.strip()
        if not model:
            output, _ = self._sh("getprop ro.product.board")
            model = output.strip()
        return model or "unknown"

    def _get_arch(self) -> str:
        output, _ = self._sh("uname -m")
        arch = output.strip().lower()
        if arch in ("aarch64", "arm64"):
            return "aarch64"
        if arch in ("armv8l",):
            return "armv8l"
        if arch in ("armv7l", "armv6l", "armv7"):
            return "armv7l"
        if arch in ("x86_64", "amd64"):
            return "x86_64"
        return arch

    @staticmethod
    def _prebuild_arch(arch: str) -> str:
        """Map uname -m to prebuild tarball name."""
        if arch in ("aarch64", "arm64"):
            return "aarch64"
        if arch == "armv8l":
            return "armv8l"
        if arch in ("armv7l", "armv6l", "armv7"):
            return "armv7l"
        return arch

    @staticmethod
    def _proot_arch(arch: str) -> str:
        """Map uname -m to proot binary name (armv8l uses armv7 proot)."""
        if arch in ("aarch64", "arm64"):
            return "aarch64"
        if arch in ("armv8l", "armv7l", "armv6l", "armv7"):
            return "armv7l"
        return arch

    # ------------------------------------------------------------------
    # PRoot resolution
    # ------------------------------------------------------------------
    @staticmethod
    def _elf_machine(path: str):
        try:
            with open(path, "rb") as f:
                hdr = f.read(20)
            if hdr[:4] != b"\x7fELF":
                return None
            return struct.unpack("<H", hdr[18:20])[0]
        except Exception:
            return None

    def _download_proot(self, proot_arch: str) -> Optional[str]:
        """Download PRoot on PC side. Returns local path or None."""
        cache_dir = os.path.join(os.path.expanduser("~"), ".ank-installer", "proot")
        cache = os.path.join(cache_dir, f"proot-{proot_arch}")
        expected = ELF_MACHINES.get(proot_arch)
        if os.path.isfile(cache) and self._elf_machine(cache) == expected:
            return cache
        url = PROOT_URLS.get(proot_arch)
        if not url:
            return None
        os.makedirs(cache_dir, exist_ok=True)
        try:
            import urllib.request
            urllib.request.urlretrieve(url, cache)
            if self._elf_machine(cache) == expected:
                return cache
        except Exception:
            pass
        return None

    def _resolve_proot(self, proot_arch: str) -> bool:
        """Get correct-arch PRoot onto device. Returns True on success."""
        # Bundled filenames use armv7 (not armv7l): anklite-proot-armv7
        bundled_arch = "armv7" if proot_arch in ("armv7l", "armv6l", "armv7") else proot_arch
        bundled = f"{EXTRACT_DIR}/ankfs/anklite-proot-{bundled_arch}"
        out, _ = self._sh(f"test -f {bundled} && echo OK")
        if "OK" in out:
            self._sh(f"cp {bundled} {REMOTE_PROOT} && chmod 755 {REMOTE_PROOT}")
            self._notify("proot", f"PRoot ({proot_arch}) from ZIP", 0.52)
            return True
        # Fallback: also try the exact arch name
        bundled_exact = f"{EXTRACT_DIR}/ankfs/anklite-proot-{proot_arch}"
        out, _ = self._sh(f"test -f {bundled_exact} && echo OK")
        if "OK" in out:
            self._sh(f"cp {bundled_exact} {REMOTE_PROOT} && chmod 755 {REMOTE_PROOT}")
            self._notify("proot", f"PRoot ({proot_arch}) from ZIP", 0.52)
            return True
        local = self._download_proot(proot_arch)
        if local:
            if not self.adb.push(self.serial, local, REMOTE_PROOT):
                return False
            self._sh(f"chmod 755 {REMOTE_PROOT}")
            self._notify("proot", f"PRoot ({proot_arch}) downloaded", 0.52)
            return True
        self._notify("error", f"No PRoot for {proot_arch}", 0)
        return False

    # ------------------------------------------------------------------
    # File push helpers (multi-line content, avoids echo issues)
    # ------------------------------------------------------------------
    def _push_resolv_conf(self, dest: str):
        self._push_text("nameserver 8.8.8.8\nnameserver 8.8.4.4\n", dest)

    def _push_apk_repos_http(self, dest: str):
        self._push_text(
            "http://dl-cdn.alpinelinux.org/alpine/v3.20/main\n"
            "http://dl-cdn.alpinelinux.org/alpine/v3.20/community\n",
            dest,
        )

    def _push_apk_repos_https(self, dest: str):
        self._push_text(
            "https://dl-cdn.alpinelinux.org/alpine/v3.20/main\n"
            "https://dl-cdn.alpinelinux.org/alpine/v3.20/community\n",
            dest,
        )

    def _push_device_sshd_config(self):
        """Port 2200 merged config (equivalent to install.sh merge)."""
        self._push_text(
            "Port 2200\n"
            "ListenAddress 0.0.0.0\n"
            "PermitRootLogin yes\n"
            "PasswordAuthentication yes\n"
            "ChallengeResponseAuthentication no\n"
            "X11Forwarding no\n"
            "AllowTcpForwarding no\n"
            "PidFile /run/ankd/sshd.pid\n"
            "Subsystem sftp internal-sftp\n",
            f"{REMOTE_ROOTFS}/etc/ssh/sshd_config",
        )

    def _push_ankbase_sshd_config(self):
        """Port 22 for container base image."""
        self._push_text(
            "Port 22\n"
            "ListenAddress 0.0.0.0\n"
            "PermitRootLogin yes\n"
            "PasswordAuthentication yes\n"
            "ChallengeResponseAuthentication no\n"
            "X11Forwarding no\n"
            "AllowTcpForwarding no\n"
            "PidFile /run/sshd.pid\n"
            "Subsystem sftp internal-sftp\n",
            f"{REMOTE_IMAGES}/ank-alpinebase-3.20/etc/ssh/sshd_config",
        )

    def _push_motd_script(self):
        self._push_text(
            "ank_motd() {\n"
            "    read _ u1 n1 s1 _ < /proc/stat\n"
            "    sleep 1\n"
            "    read _ u2 n2 s2 _ < /proc/stat\n"
            "    total=$(( (u2+n2+s2) - (u1+n1+s1) ))\n"
            "    idle=$(( u2 - u1 ))\n"
            '    if [ "$total" -gt 0 ]; then\n'
            '        cpu=$(( (total - idle) * 100 / total ))\n'
            "    else\n"
            "        cpu=0\n"
            "    fi\n"
            "    mem_total=$(awk '/^MemTotal/{print $2}' /proc/meminfo)\n"
            "    mem_avail=$(awk '/^MemAvailable/{print $2}' /proc/meminfo)\n"
            '    if [ -n "$mem_total" ] && [ "$mem_total" -gt 0 ] 2>/dev/null; then\n'
            '        mem_used=$(( (mem_total - mem_avail) * 100 / mem_total ))\n'
            "    else\n"
            "        mem_used=0\n"
            "    fi\n"
            "    up=$(awk '{d=int($1/86400);h=int(($1%86400)/3600);m=int(($1%3600)/60);"
            'printf "%dd %dh %dm",d,h,m}\' /proc/uptime)\n'
            '    printf "\\n  CPU: %s%%  MEM: %s%%  UPTIME: %s\\n\\n" "$cpu" "$mem_used" "$up"\n'
            "}\n"
            "ank_motd\n"
            "unset ank_motd\n",
            f"{REMOTE_ROOTFS}/etc/profile.d/ank-motd.sh",
        )

    def _push_run_server_sh(self):
        """Guest-side bootstrap: starts sshd + python server."""
        self._push_text(
            "#!/bin/sh\n"
            "export PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin\n"
            f"export ANK_DIR={GUEST_ANK}\n"
            f"export PROOT_TMP_DIR=/tmp/proot_tmp\n"
            "export HOME=/root\n"
            "mkdir -p /tmp/proot_tmp /run/ankd /run/sshd /var/log/ank\n"
            "if [ -x /usr/sbin/sshd ] && [ ! -f /run/ankd/sshd.pid ]; then\n"
            "    /usr/sbin/sshd 2>>/var/log/ank/sshd.log || true\n"
            "fi\n"
            "cd /opt/ank\n"
            "exec python3 server.py\n",
            f"{REMOTE_ROOTFS}/run_server.sh",
        )
        self._sh(f"chmod 755 {REMOTE_ROOTFS}/run_server.sh")

    def _push_start_lite_sh(self):
        """Host-side start script (SERVICE log + pid files, same as scripts/start-lite.sh)."""
        self._push_text(
            "#!/system/bin/sh\n"
            "# ANK Lite - start server (non-root, via PRoot)\n"
            f'ANK_DIR="{ANK_DIR}"\n'
            'ROOTFS="$ANK_DIR/ankfs"\n'
            'PROOT="$ANK_DIR/proot"\n'
            "\n"
            'mkdir -p "$ANK_DIR/logs" "$ANK_DIR/tmp" "$ROOTFS/tmp"\n'
            'SVC_LOG="$ANK_DIR/logs/service.log"\n'
            'TS=$(date \'+%Y-%m-%d %H:%M:%S\')\n'
            '_svc() {\n'
            '    echo "[SERVICE] [$TS] $1" >> "$SVC_LOG"\n'
            '    echo "[SERVICE] [$TS] $1"\n'
            '}\n'
            "\n"
            'if pgrep -f "python3 server.py" > /dev/null 2>&1; then\n'
            '    _svc "Server already running"\n'
            '    echo "ANK server already running"\n'
            "    exit 0\n"
            "fi\n"
            f'echo \'{{"mode":"lite"}}\' > "$ANK_DIR/mode"\n'
            f'nohup sh -c "PROOT_TMP_DIR=$ANK_DIR/tmp '
            f'$PROOT -0 -r $ROOTFS '
            f'-b /dev -b /proc -b /sys '
            f'-b $ANK_DIR:{GUEST_ANK} '
            f'-w /root /bin/sh /run_server.sh" '
            '> "$ANK_DIR/logs/server.log" 2>&1 &\n'
            'PID=$!\n'
            'echo "$PID" > "$ANK_DIR/logs/server.pid"\n'
            'echo "$PID" > "$ANK_DIR/server.pid"\n'
            '_svc "Boot completed"\n'
            '_svc "Server started (PID: $PID) | Arch: $(uname -m)"\n'
            '_svc "Panel: https://localhost:8001"\n'
            '_svc "Password configured"\n'
            '_svc "sshd starting on port 2200"\n'
            'echo "ANK Lite started on port 8001"\n',
            f"{ANK_DIR}/start-lite.sh",
        )
        self._sh(f"chmod 755 {ANK_DIR}/start-lite.sh")

    def _push_stop_lite_sh(self):
        self._push_text(
            "#!/system/bin/sh\n"
            "# ANK Lite - stop server\n"
            'pkill -f "python3 server.py" 2>/dev/null\n'
            "sleep 1\n"
            'echo "ANK Lite stopped"\n',
            f"{ANK_DIR}/stop-lite.sh",
        )
        self._sh(f"chmod 755 {ANK_DIR}/stop-lite.sh")

    # ------------------------------------------------------------------
    # Main install flow
    # ------------------------------------------------------------------
    def _log(self, msg: str):
        """Emit a timestamped log line like the rooted installer."""
        ts = time.strftime("%H:%M:%S")
        self._notify("_log", f"[{ts}] {msg}", -1)

    def install(self) -> bool:
        # Header
        self._log("[ANK-INSTALLER] Starting lite installation, please wait...")
        self._log("  ================================")
        self._log("   ANK - Android Konteiner Testing Build")
        self._log("  ================================")

        # --- Step 1: Clean ---
        self._log("[STEP] 1/4 > Clean...")
        self._notify("clean", "Cleaning previous installation...", 0.01)
        self._sh(
            "pkill -9 -f 'proot.*ank' 2>/dev/null; "
            "pkill -9 -f 'python3.*server.py' 2>/dev/null; "
            "pkill -9 -f 'sshd.*PidFile' 2>/dev/null; "
            "sleep 1; "
            "rm -rf /data/local/tmp/ank 2>/dev/null; "
            "rm -rf /data/local/tmp/ank_extract 2>/dev/null"
        )
        self._log("[OK] Done")

        # --- Step 2: ANK-Engine ---
        self._log("[STEP] 2/4 > ANK-Engine...")

        self._notify("arch", "Detecting architecture...", 0.02)
        arch = self._get_arch()
        prebuild = self._prebuild_arch(arch)
        proot_a = self._proot_arch(arch)
        self._log(f"  Device: {arch} | rootfs: {prebuild} | proot: {proot_a}")

        self._notify("push", "Locating ZIP...", 0.06)
        zip_path = self._find_zip()
        if not zip_path:
            self._log("[FAIL] ank-magisk.zip not found")
            return False
        zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
        self._log(f"  Pushing ZIP ({zip_mb:.1f} MB)...")
        self._notify("push", f"Pushing ZIP ({zip_mb:.1f} MB)...", 0.08)
        if not self.adb.push(self.serial, zip_path, "/sdcard/Download/ank-magisk.zip"):
            self._log("[FAIL] Failed to push ZIP")
            return False
        self._notify("push", "ZIP pushed", 0.25)
        self._log("[OK] ZIP pushed")

        self._notify("extract", "Extracting ZIP...", 0.26)
        self._sh(f"rm -rf {EXTRACT_DIR} && mkdir -p {EXTRACT_DIR}")
        out, code = self._sh(f"cd {EXTRACT_DIR} && unzip -o /sdcard/Download/ank-magisk.zip", timeout=300)
        if code != 0:
            self._log(f"[FAIL] unzip failed: {out.strip()[:200]}")
            return False
        self._log("[OK] ZIP extracted")

        self._notify("proot", "Resolving PRoot...", 0.36)
        self._sh(f"mkdir -p {ANK_DIR} {REMOTE_LOGS} {REMOTE_TMP}")
        if not self._resolve_proot(proot_a):
            self._log("[FAIL] PRoot not found")
            return False
        out, _ = self._sh(f"{REMOTE_PROOT} --version 2>&1")
        if "5.1.0" not in out and "PRoot" not in out and "proot" not in out.lower():
            self._log(f"[FAIL] PRoot broken: {out.strip()[:100]}")
            return False
        self._log("[OK] PRoot ready")

        self._notify("rootfs", f"Extracting rootfs ({prebuild})...", 0.55)
        tarball = f"{EXTRACT_DIR}/ankfs/ank-prebuild-{prebuild}.tar.gz"
        out, _ = self._sh(f"test -f {tarball} && echo OK")
        if "OK" not in out:
            self._log(f"[FAIL] Prebuild not found: {tarball}")
            return False
        self._sh(f"mkdir -p {REMOTE_ROOTFS} {REMOTE_TMP}")
        out, _ = self._sh(f"cd {REMOTE_ROOTFS} && tar xzf {tarball} 2>&1", timeout=300)
        out, _ = self._sh(f"test -f {REMOTE_ROOTFS}/bin/busybox && test -f {REMOTE_ROOTFS}/usr/bin/python3 && echo OK")
        if "OK" not in out:
            self._log("[FAIL] Rootfs extraction failed (no busybox or python3)")
            return False
        self._log("[OK] ANKFS ready")

        self._log("[STEP] 2.5/4 > Building ANK-ALPINEBASE...")
        ankbase = f"{REMOTE_IMAGES}/ank-alpinebase-3.20"
        self._sh(f"mkdir -p {ankbase}")
        out, _ = self._sh(f"cd {ankbase} && tar xzf {tarball} 2>&1", timeout=300)
        self._push_apk_repos_http(f"{ankbase}/etc/apk/repositories")
        self._push_resolv_conf(f"{ankbase}/etc/resolv.conf")
        self._push_text("127.0.0.1 localhost\n", f"{ankbase}/etc/hosts")
        self._sh(f"sed -i 's|^root:[^:]*:[^:]*:[^:]*:[^:]*:[^:]*:.*|root:x:0:0:root:/root:/bin/bash|' {ankbase}/etc/passwd 2>/dev/null")
        self._sh(f"mkdir -p {ankbase}/etc/ssh {ankbase}/run/sshd {ankbase}/root/.ssh")
        self._sh(f"chmod 700 {ankbase}/root/.ssh && touch {ankbase}/root/.ssh/authorized_keys && chmod 600 {ankbase}/root/.ssh/authorized_keys")
        self._push_ankbase_sshd_config()
        self._guest("ssh-keygen -A 2>/dev/null", rootfs=ankbase, timeout=60)
        for k in [f"{ankbase}/etc/ssh/ssh_host_rsa_key", f"{ankbase}/etc/ssh/ssh_host_ed25519_key"]:
            self._sh(f"chmod 600 {k} 2>/dev/null")
        for k in [f"{ankbase}/etc/ssh/ssh_host_rsa_key.pub", f"{ankbase}/etc/ssh/ssh_host_ed25519_key.pub"]:
            self._sh(f"chmod 644 {k} 2>/dev/null")
        self._sh(f"rm -rf {ankbase}/opt/ank 2>/dev/null")
        self._log("[OK] ANK-ALPINEBASE built")

        # --- Server files ---
        self._log("[STEP] 3/4 > Configuring ANK Core addons...")
        self._notify("server", "Copying server files...", 0.63)
        server_dir = f"{EXTRACT_DIR}/server"
        remote_opt = f"{REMOTE_ROOTFS}/opt/ank"
        self._sh(f"mkdir -p {remote_opt}/static {remote_opt}/ankd {remote_opt}/bin {remote_opt}/scripts")

        out, _ = self._sh(f"ls {server_dir}/*.py 2>/dev/null")
        if out.strip():
            self._sh(f"cp {server_dir}/*.py {remote_opt}/")
        out, _ = self._sh(f"ls {server_dir}/static/ 2>/dev/null")
        if out.strip():
            self._sh(f"cp -r {server_dir}/static/* {remote_opt}/static/")
        out, _ = self._sh(f"ls {server_dir}/ankd/ 2>/dev/null")
        if out.strip():
            self._sh(f"cp -r {server_dir}/ankd/* {remote_opt}/ankd/")
        for name in ["ankcoreshell.sh", "ank-shell.sh"]:
            out, _ = self._sh(f"test -f {server_dir}/{name} && echo OK")
            if "OK" in out:
                self._sh(f"cp {server_dir}/{name} {REMOTE_ROOTFS}/{name} && chmod 755 {REMOTE_ROOTFS}/{name}")

        py_count = len(out.strip().split("\n")) if out.strip() else 0
        self._log(f"[OK] Server files ready")

        # Scripts
        self._sh(f"mkdir -p {ANK_DIR}/core")
        out, _ = self._sh(f"ls {EXTRACT_DIR}/scripts/*.sh 2>/dev/null")
        if out.strip():
            self._sh(f"cp {EXTRACT_DIR}/scripts/*.sh {ANK_DIR}/core/")
            self._sh(f"chmod 755 {ANK_DIR}/core/*.sh")
            self._sh(f"cp {EXTRACT_DIR}/scripts/*.sh {remote_opt}/scripts/ 2>/dev/null")
        for src, dst in [
            (f"{server_dir}/static/ank-cli.py", f"{remote_opt}/bin/ank"),
            (f"{server_dir}/static/ank-cli.py", f"{remote_opt}/bin/ank-core"),
            (f"{server_dir}/static/ank-profile.sh", f"{remote_opt}/ank-profile.sh"),
        ]:
            out, _ = self._sh(f"test -f {src} && echo OK")
            if "OK" in out:
                self._sh(f"cp {src} {dst} && chmod 755 {dst}")
        self._log("[OK] Scripts installed")

        # DNS + repos
        self._notify("dns", "Configuring DNS + repos...", 0.71)
        self._push_resolv_conf(f"{REMOTE_ROOTFS}/etc/resolv.conf")
        self._push_apk_repos_https(f"{REMOTE_ROOTFS}/etc/apk/repositories")

        # SSH device
        self._sh(f"mkdir -p {REMOTE_ROOTFS}/etc/ssh {REMOTE_ROOTFS}/run/sshd {REMOTE_ROOTFS}/run/ankd")
        self._sh(f"mkdir -p {REMOTE_ROOTFS}/root/.ssh && chmod 700 {REMOTE_ROOTFS}/root/.ssh")
        self._sh(f"touch {REMOTE_ROOTFS}/root/.ssh/authorized_keys && chmod 600 {REMOTE_ROOTFS}/root/.ssh/authorized_keys")
        self._push_device_sshd_config()
        self._sh(f"sed -i 's|^root:[^:]*:[^:]*:[^:]*:[^:]*:[^:]*:.*|root:x:0:0:root:/root:/ankcoreshell.sh|' {REMOTE_ROOTFS}/etc/passwd 2>/dev/null")
        out, _ = self._sh(f"grep -q '^admin:' {REMOTE_ROOTFS}/etc/passwd && echo EXISTS")
        if "EXISTS" not in out:
            self._sh(f"echo 'admin:x:1000:1000::/root:/ankcoreshell.sh' >> {REMOTE_ROOTFS}/etc/passwd")
        self._push_text("root:*:0:0:99999:7:::\nadmin:*:0:0:99999:7:::\n", f"{REMOTE_ROOTFS}/etc/shadow")
        self._sh(f"chmod 644 {REMOTE_ROOTFS}/etc/shadow")
        out, _ = self._sh(f"grep -q ankcoreshell {REMOTE_ROOTFS}/etc/shells 2>/dev/null && echo OK")
        if "OK" not in out:
            self._sh(f"echo '/ankcoreshell.sh' >> {REMOTE_ROOTFS}/etc/shells 2>/dev/null || true")
        self._log("[OK] SSH configured (port 2200)")

        # MOTD
        self._sh(f"mkdir -p {REMOTE_ROOTFS}/etc/profile.d")
        self._push_motd_script()
        self._sh(f"cat /dev/null > {REMOTE_ROOTFS}/etc/motd 2>/dev/null || true")
        self._log("[OK] ANK Shell installed")

        # Host keys + passwords
        out, code = self._guest("ssh-keygen -A", timeout=120)
        chk, _ = self._guest(
            "test -f /etc/ssh/ssh_host_rsa_key -o -f /etc/ssh/ssh_host_ed25519_key "
            "-o -f /etc/ssh/ssh_host_ecdsa_key && echo OK"
        )
        if "OK" not in chk:
            self._log(f"[FAIL] SSH host keys not generated (keygen rc={code}): {out.strip()[:200]}")
            return False
        out, code = self._guest(
            "echo root:admin123 | chpasswd && echo admin:admin123 | chpasswd", timeout=60
        )
        if code != 0:
            self._log(f"[FAIL] chpasswd failed (rc={code}): {out.strip()[:200]}")
            return False
        self._guest("cat /dev/null > /etc/motd")
        self._log("[OK] Shadow configured")

        # --- Step 4: Server + scripts ---
        self._log("[STEP] 4/4 > Server + scripts...")
        self._notify("config", "Writing configuration...", 0.88)
        device_model = self._get_device_model()
        config = {
            "version": "Testing Build",
            "panel_port": 8001,
            "username": "admin",
            "password": "admin123",
            "first_boot": True,
            "autostart_on_boot": True,
            "host_sh": "/bin/sh",
            "device_model": device_model,
            "network": {"bridge": "ank0", "subnet": "10.20.30.0", "gateway": "10.20.30.1", "nat": True},
            "resources": {"max_ram_mb": 512, "cpu_shares": 512},
        }
        self._push_text(json.dumps(config, separators=(",", ":")) + "\n", f"{ANK_DIR}/config.json")

        self._sh(f"mkdir -p /sdcard/AndroidKonteiner")
        self._push_text(
            "ANK Testing Build (Lite)\n"
            "Painel: https://localhost:8001\n"
            "Usuario: admin\n"
            "Senha: admin123\n",
            "/sdcard/AndroidKonteiner/CREDENCIAIS.txt",
        )

        self._push_text('{"mode":"lite"}\n', f"{ANK_DIR}/mode")
        self._push_run_server_sh()
        self._push_start_lite_sh()
        self._push_stop_lite_sh()
        self._log("[OK] Server + scripts installed")

        # No start/verify here — next step is reboot; start-lite runs after boot.

        # --- Cleanup ---
        self._notify("cleanup", "Cleaning up...", 0.95)
        self._sh(f"rm -rf {EXTRACT_DIR} /sdcard/Download/ank-magisk.zip")
        self._log("[OK] Cleanup complete")

        # --- Done ---
        device_ip = self._get_device_ip()
        self._sh(
            f'echo "[SERVICE] [$(date \'+%Y-%m-%d %H:%M:%S\')] '
            f'Installation complete | Panel: https://{device_ip}:8001" '
            f'>> {ANK_DIR}/logs/service.log'
        )
        self._log("[OK] Installation complete!")
        self._log(f"  DONE > {arch} > lite")
        self._log(f"  Panel: https://{device_ip}:8001")
        self._log(f"  Login: admin / admin123")
        self._log(f"  Device: {device_model}")
        self._log("[OK] ANK installed")
        self._log("Installation completed successfully!")

        self._notify("done", f"Lite install complete! https://{device_ip}:8001", 1.0)
        return True

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    def _verify_server(self, port: int = 8001, timeout: int = 30) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            out, _ = self._sh(f"netstat -tln 2>/dev/null | grep -c ':{port}'")
            try:
                if int(out.strip()) > 0:
                    return True
            except (ValueError, AttributeError):
                pass
            time.sleep(3)
        return False

    def _get_device_ip(self) -> str:
        out, _ = self._sh("ip -4 -o addr show wlan0 2>/dev/null | awk '{print $4}' | cut -d/ -f1")
        ip = out.strip().split("\n")[0]
        return ip if ip and "." in ip else "localhost"

    # ------------------------------------------------------------------
    # ZIP location
    # ------------------------------------------------------------------
    def _find_zip(self) -> Optional[str]:
        if getattr(sys, "frozen", False):
            base_path = sys._MEIPASS
            exe_dir = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            exe_dir = os.path.join(base_path, "..")
        for c in [os.path.join(exe_dir, "ank-magisk.zip"), os.path.join(base_path, "ank-magisk.zip")]:
            if os.path.isfile(c):
                return c
        return None

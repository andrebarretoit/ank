"""
ANK Installer - Step: Installing (PySide6)
"""

import datetime
import os
import tempfile
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from ui.theme import COLORS


class InstallThread(QThread):
    """Background thread for installation."""
    progress = Signal(float, str)
    log = Signal(str)
    done = Signal(bool, str)
    retry_needed = Signal(str, str)  # url, error message

    def __init__(self, adb, serial, tier, app):
        super().__init__()
        self.adb = adb
        self.serial = serial
        self.tier = tier
        self.app = app

    def run(self):
        try:
            mode = getattr(self.app, 'mode', 'install')

            # Handle uninstall mode
            if mode == "uninstall":
                self._uninstall()
                return

            # Handle reinstall mode (uninstall first, then install)
            if mode == "reinstall":
                self.progress.emit(0.05, "Removing current installation...")
                self.log.emit("Removing current ANK installation...")
                rooted = getattr(self.app.device_data, 'is_rooted', False)
                self.adb.uninstall_ank_full(self.serial, rooted,
                    lambda msg: self.log.emit(msg))
                self.progress.emit(0.3, "Installing fresh...")
                self.log.emit("Installing fresh ANK...")
                self._do_install()
                return

            # Handle export mode
            if mode == "export":
                self._export_ankengine()
                return

            # Normal install or restore_engine
            self._do_install()
        except Exception as e:
            self.done.emit(False, str(e))

    def _do_install(self):
        """Core install logic shared by install/reinstall."""
        install_mode = getattr(self.app, 'install_mode', 'native')
        device = self.app.device_data
        has_magisk = self.app._detection_result.get("has_magisk", False) if isinstance(self.app._detection_result, dict) else getattr(self.app._detection_result, "has_magisk", False) if self.app._detection_result else False

        if install_mode == "ank_ui":
            self._install_ank_ui_mode()
        elif device and not getattr(device, 'is_rooted', False):
            self._install_lite()
        elif has_magisk:
            self._install_rooted()
        else:
            self._install_manual()
        self.done.emit(True, "Installation complete!")

    def _uninstall(self):
        """Full ANK uninstall — removes everything, reboots, cleans again."""
        self.progress.emit(0.05, "Removing ANK...")
        self.log.emit("Starting full ANK uninstall...")

        rooted = getattr(self.app.device_data, 'is_rooted', False)
        success = self.adb.uninstall_ank_full(self.serial, rooted,
            lambda msg: self.log.emit(msg))

        if not success:
            self.done.emit(False, "Uninstall failed")
            return

        # Reboot to clear all bind mounts and running processes
        self.progress.emit(0.5, "Rebooting device...")
        self.log.emit("Rebooting device to clear all ANK traces...")
        self.adb.shell(self.serial, "reboot")

        # Wait for device to come back
        self.log.emit("Waiting for device to restart...")
        import time
        time.sleep(15)

        for _ in range(30):
            try:
                devices = self.adb.devices()
                if devices:
                    self.serial = devices[0].serial
                    self.log.emit("Device is back online.")
                    break
            except Exception:
                pass
            time.sleep(3)
        else:
            self.done.emit(False, "Device did not come back after reboot")
            return

        # Second cleanup pass — remove anything left behind
        self.progress.emit(0.8, "Final cleanup pass...")
        self.log.emit("Running final cleanup to remove any leftovers...")
        self.adb.shell(self.serial, "rm -rf /data/local/ank")
        self.adb.shell(self.serial, "rm -rf /data/adb/modules/ank*")
        self.adb.shell(self.serial, "rm -rf /data/adb/service.d/ank*")

        self.progress.emit(1.0, "Uninstall complete!")
        self.log.emit("ANK has been completely removed from the device.")
        self.done.emit(True, "Uninstall complete!")

    def _export_ankengine(self):
        """Export ANK setup to .ankengine file."""
        self.progress.emit(0.1, "Preparing export...")
        self.log.emit("Exporting ANK configuration...")

        import zipfile
        import tempfile
        import os

        try:
            # Create temp .ankengine file
            tmp_file = os.path.join(tempfile.gettempdir(), "ank-export.ankengine")

            with zipfile.ZipFile(tmp_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                # Export config
                self.progress.emit(0.2, "Exporting configuration...")
                config_out, _ = self.adb.shell(self.serial,
                    "cat /data/local/ank/config.json 2>/dev/null")
                if config_out:
                    zf.writestr("config.json", config_out)
                    self.log.emit("Configuration exported")

                # Export mode
                mode_out, _ = self.adb.shell(self.serial,
                    "cat /data/local/ank/mode 2>/dev/null")
                if mode_out:
                    zf.writestr("mode", mode_out)

                # Export containers
                containers_out, _ = self.adb.shell(self.serial,
                    "ls /data/local/ank/containers/ 2>/dev/null")
                if containers_out:
                    for name in containers_out.strip().split("\n"):
                        name = name.strip()
                        if not name:
                            continue
                        self.log.emit(f"Exporting container: {name}")
                        # Pull container config
                        cfg_out, _ = self.adb.shell(self.serial,
                            f"cat /data/local/ank/containers/{name}/config.json 2>/dev/null")
                        if cfg_out:
                            zf.writestr(f"containers/{name}/config.json", cfg_out)

                # Export server files
                self.progress.emit(0.5, "Exporting server files...")
                for f in ["server.py", "ank_lite.py"]:
                    file_out, _ = self.adb.shell(self.serial,
                        f"cat /data/local/ank/ankfs/opt/ank/{f} 2>/dev/null")
                    if file_out:
                        zf.writestr(f"server/{f}", file_out)

                # Export static files
                static_out, _ = self.adb.shell(self.serial,
                    "ls /data/local/ank/ankfs/opt/ank/static/ 2>/dev/null")
                if static_out:
                    for f in static_out.strip().split("\n"):
                        f = f.strip()
                        if not f:
                            continue
                        content, _ = self.adb.shell(self.serial,
                            f"cat /data/local/ank/ankfs/opt/ank/{f} 2>/dev/null")
                        if content:
                            zf.writestr(f"static/{f}", content)

            # Pull the file to the user's Downloads
            user_downloads = os.path.expanduser("~/Downloads")
            os.makedirs(user_downloads, exist_ok=True)
            dest = os.path.join(user_downloads, "ank-export.ankengine")

            self.progress.emit(0.8, "Saving export file...")
            result = self.adb._run_device(self.serial,
                ["pull", tmp_file, dest], timeout=60)

            if result.returncode == 0:
                self.progress.emit(1.0, "Export complete!")
                self.log.emit(f"Exported to: {dest}")
                self.done.emit(True, f"Exported to {dest}")
            else:
                self.done.emit(False, f"Failed to save: {result.stderr}")

            # Cleanup
            try:
                os.remove(tmp_file)
            except Exception:
                pass

        except Exception as e:
            self.done.emit(False, f"Export failed: {e}")

    def _install_ank_ui_mode(self):
        """Install ANK UI launcher + ANK engine."""
        import sys
        import os

        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            exe_dir = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            exe_dir = os.path.join(base_path, "..")

        # 1. Install ANK UI APK first (before engine, no reboot needed yet)
        self.progress.emit(0.05, "Installing ANK UI...")

        apk_candidates = [
            os.path.join(exe_dir, "ank-launcher.apk"),
            os.path.join(base_path, "ank-launcher.apk"),
        ]
        apk_path = None
        for c in apk_candidates:
            if os.path.isfile(c):
                apk_path = c
                break

        if apk_path:
            self.progress.emit(0.1, "Installing ANK Launcher...")
            result = self.adb._run_device(self.serial, ["install", "-r", apk_path], timeout=60)
            if result.returncode != 0:
                self.log.emit(f"WARN: Failed to install ANK UI: {result.stderr}")
        else:
            self.log.emit("WARN: skipping ANK UI")

        # 2. Install ANK engine
        tier = self.app.recommended_tier
        device = self.app.device_data
        has_magisk = self.app._detection_result.get("has_magisk", False) if isinstance(self.app._detection_result, dict) else getattr(self.app._detection_result, "has_magisk", False) if self.app._detection_result else False

        def callback(step, message, progress_val):
            self.progress.emit(0.1 + progress_val * 0.6, message)
            self.log.emit(message)

        if device and not getattr(device, 'is_rooted', False):
            from core.installer_lite import LiteInstaller
            installer = LiteInstaller(self.adb, self.serial, callback=callback)
            if not installer.install():
                raise Exception("Lite installation failed")
        elif has_magisk:
            self._install_rooted()
            return
        else:
            from core.installer_manual import ManualInstaller
            installer = ManualInstaller(self.adb, self.serial, callback=callback)
            if not installer.install():
                raise Exception("Manual installation failed")

        # 3. Set ANK UI as default launcher (after engine is ready)
        if apk_path:
            self.progress.emit(0.8, "Setting ANK UI as default launcher...")

            output, _ = self.adb.shell(self.serial, "pm list packages 2>/dev/null | grep ank")
            if output:
                for line in output.strip().split("\n"):
                    pkg = line.replace("package:", "").strip()
                    if pkg and ("launcher" in pkg.lower() or "ank" in pkg.lower()):
                        self.adb.shell(self.serial,
                            f"cmd role add-role-holder android.app.role.HOME {pkg}/.MainActivity 2>/dev/null")
                        self.adb.shell(self.serial,
                            f"cmd package set-home-activity {pkg}/.MainActivity 2>/dev/null")
                        self.adb.shell(self.serial,
                            f"pm set-home-activity {pkg}/.MainActivity 2>/dev/null")
                        self.adb.shell(self.serial,
                            f"am start -a android.intent.action.MAIN -c android.intent.category.HOME 2>/dev/null")
                        self.log.emit(f"OK: {pkg} set as default launcher")
                        break

        self.progress.emit(1.0, "ANK UI installation complete!")

    def _install_rooted(self):
        # 1. Find zip and ankcore from PyInstaller bundle or disk
        self.progress.emit(0.05, "Extracting files...")
        import sys
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            exe_dir = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            exe_dir = os.path.join(base_path, "..")

        # Find ank-magisk.zip
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
            raise Exception("ank-magisk.zip not found. Place it next to the exe.")
        with open(zip_path, "rb") as f:
            zip_data = f.read()

        tmp_zip = os.path.join(tempfile.gettempdir(), "ank-magisk.zip")
        with open(tmp_zip, "wb") as f:
            f.write(zip_data)

        # 2. Push zip to device (ankcore tar.gz is bundled inside the zip)
        self.progress.emit(0.25, "[ANK-INSTALLER] Checking for updates, please wait...")
        self.adb.push(self.serial, tmp_zip, "/sdcard/Download/ank-magisk.zip")
        self.log.emit("[ANK-INSTALLER] Checking for updates, please wait...")

        # 3. Install Magisk module (streaming output)
        self.progress.emit(0.5, "[ANK-INSTALLER] Installation started, this may take a few minutes.")
        self.log.emit("[ANK-INSTALLER] Starting installation, please wait...")

        def on_install_line(line):
            if line.strip():
                self.log.emit(line)

        code = self.adb.shell_su_streaming(
            self.serial,
            "magisk --install-module /sdcard/Download/ank-magisk.zip",
            on_install_line,
            timeout=600
        )

        # Check for failure
        if code != 0:
            # Fetch install log from device
            self.log.emit("\n--- Device install log ---")
            log_out, _ = self.adb.shell(self.serial, "cat /data/local/ank/logs/install.log 2>/dev/null || cat /sdcard/AndroidKonteiner/logs/install.log 2>/dev/null")
            if log_out:
                self.log.emit(log_out)
            self.log.emit("--- End of log ---\n")
            raise Exception("ANK installation failed")

        self.log.emit("OK: ANK installed")

        # 4. Verify installation
        self.progress.emit(0.8, "Verifying installation...")
        check, _ = self.adb.shell(self.serial, "ls /data/local/ank/ankfs/usr/bin/python3 2>/dev/null")
        if not check or "python3" not in check:
            self.log.emit("\n--- Device install log ---")
            log_out, _ = self.adb.shell(self.serial, "cat /data/local/ank/logs/install.log 2>/dev/null || cat /sdcard/AndroidKonteiner/logs/install.log 2>/dev/null")
            if log_out:
                self.log.emit(log_out)
            self.log.emit("--- End of log ---\n")
            raise Exception("Error. Check the log above.")

        self.log.emit("OK: Services configured")

        self.progress.emit(0.95, "Cleaning up temporary files...")
        self.log.emit("Cleaning up temporary files on the device...")
        self.adb.shell(self.serial, "rm -f /sdcard/Download/ank-magisk.zip 2>/dev/null")
        self.log.emit("OK: Cleanup complete")

        self.progress.emit(1.0, "Done!")
        self.log.emit("Installation completed successfully!")

    def _install_lite(self):
        import threading
        from core.installer_lite import LiteInstaller

        self._retry_event = None
        self._retry_result = False

        def callback(step, message, progress_val):
            if progress_val < 0:
                self.log.emit(message)
            else:
                self.progress.emit(progress_val, message)
                self.log.emit(message)

        def retry_callback(url, error):
            self._retry_event = threading.Event()
            self._retry_result = False
            self.retry_needed.emit(url, error)
            self._retry_event.wait()
            return self._retry_result

        installer = LiteInstaller(self.adb, self.serial, callback=callback, retry_callback=retry_callback)
        success = installer.install()
        if not success:
            raise Exception("Lite installation failed")

    def _install_manual(self):
        from core.installer_manual import ManualInstaller

        def callback(step, message, progress_val):
            self.progress.emit(progress_val, message)
            self.log.emit(message)

        installer = ManualInstaller(self.adb, self.serial, callback=callback)
        success = installer.install()
        if not success:
            raise Exception("Manual installation failed")


class StepInstall(QWidget):
    """Step: Installing."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._thread = None
        self._countdown = 0
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._countdown_tick)
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Installing")
        title.setObjectName("title")
        layout.addWidget(title)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(10)
        layout.addWidget(self.progress)

        self.progress_label = QLabel("0%")
        self.progress_label.setObjectName("text-muted")
        layout.addWidget(self.progress_label)

        self.status = QLabel("Running...")
        self.status.setObjectName("subtitle")
        layout.addWidget(self.status)

        log_label = QLabel("Logs")
        log_label.setObjectName("text-muted")
        layout.addWidget(log_label)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        self.countdown_label = QLabel("")
        self.countdown_label.setObjectName("subtitle")
        self.countdown_label.setStyleSheet(f"color: {COLORS['accent']}; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.countdown_label)

    def _add_log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")

    def on_show(self):
        self.progress.setValue(0)
        self.progress_label.setText("0%")
        self.log.clear()
        self.app.install_complete = False
        self.app.install_failed = False

        device = self.app.device_data
        if not device:
            self._add_log("Error: no device selected")
            return

        mode = self.app.mode or "install"

        try:
            from core.adb import ADB
            adb = self.app._adb
            tier = self.app.recommended_tier

            if self._thread is not None and self._thread.isRunning():
                self._thread.wait(3000)

            self._thread = InstallThread(adb, device.serial, tier, self.app)
            self._thread.progress.connect(self._on_progress)
            self._thread.log.connect(self._add_log)
            self._thread.done.connect(self._on_done)
            self._thread.retry_needed.connect(self._on_retry_needed)
            self._thread.start()
        except Exception as e:
            self._add_log(f"Error: {e}")

    def _on_progress(self, value, msg):
        self.progress.setValue(int(value * 100))
        self.progress_label.setText(f"{int(value * 100)}%")
        self.status.setText(msg)

    def _on_done(self, success, msg):
        mode = self.app.mode or "install"
        if success:
            self.progress.setValue(100)
            self.progress_label.setText("100%")
            titles = {
                "install": "Installation complete!",
                "uninstall": "Uninstall complete!",
                "reinstall": "Reinstall complete!",
                "export": "Export complete!",
            }
            self.status.setText(titles.get(mode, "Complete!"))
            self.status.setStyleSheet(f"color: {COLORS['success']}; font-size: 13px; font-weight: bold;")
            self.app.install_complete = True
            self._countdown = 5
            self.countdown_label.setText(f"Continuing in {self._countdown}s...")
            self._countdown_timer.start(1000)
        else:
            self.progress.setValue(0)
            self.status.setText(f"Failed: {msg}")
            self.status.setStyleSheet(f"color: {COLORS['danger']}; font-size: 13px; font-weight: bold;")
            self.app.install_failed = True
        # Refresh bottom bar buttons (Exit on failure, etc.)
        self.app._update_buttons()

    def _countdown_tick(self):
        self._countdown -= 1
        if self._countdown <= 0:
            self._countdown_timer.stop()
            self.countdown_label.setText("")
            self.app.show_step(self.app.current_step + 1)
        else:
            self.countdown_label.setText(f"Continuing in {self._countdown}s...")

    def _on_retry_needed(self, url, error):
        """Show retry dialog when all mirrors fail."""
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Download Failed",
            f"Failed to download from all mirrors:\n\n{error}\n\nTry again?",
            QMessageBox.Retry | QMessageBox.Cancel,
            QMessageBox.Retry
        )
        if self._thread and hasattr(self._thread, '_retry_event'):
            self._thread._retry_result = (reply == QMessageBox.Retry)
            self._thread._retry_event.set()

"""
ANK Installer - Clone Mode (PySide6)
Also reused by Migrate mode (ui/step_migrate.py adds an options step in
between StepCloneConnect and the shared Confirm step; StepCloneProgress
applies the migrate options when self.app.mode == "migrate").

Contains:
  - StepCloneConnect:  connect a source and a target device at the same time
  - StepCloneProgress: export the source's ANK data and import it on target
"""

import datetime
import json
import os
import tempfile

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QComboBox, QTextEdit, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal
from ui.theme import COLORS

ANK_DIR = "/data/local/ank"
REMOTE_TMP = "/data/local/tmp/ank_clone.tar.gz"


def _shell_for(adb, device):
    rooted = bool(getattr(device, "is_rooted", False))
    return adb.shell_su if rooted else adb.shell


# ----------------------------------------------------------------------
# Step: connect source + target devices
# ----------------------------------------------------------------------
class DeviceScanThread(QThread):
    """Lists connected ADB devices with model + root info."""
    result = Signal(list)  # list of ADBDevice, populated

    def __init__(self, adb):
        super().__init__()
        self.adb = adb

    def run(self):
        try:
            devices = self.adb.devices()
            for d in devices:
                try:
                    d.model = self.adb.get_model(d.serial)
                    d.is_rooted = self.adb.check_root(d.serial)
                except Exception:
                    d.model = d.model or d.serial
                    d.is_rooted = False
            self.result.emit(devices)
        except Exception:
            self.result.emit([])


class StepCloneConnect(QWidget):
    """Step: Connect Devices (source + target)."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._thread = None
        self._devices = []
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.title = QLabel("Connect Devices")
        self.title.setObjectName("title")
        layout.addWidget(self.title)

        self.subtitle = QLabel(
            "Connect both devices via USB at the same time (or use Wi-Fi ADB "
            "for one of them), then pick which is the source and which is "
            "the target below."
        )
        self.subtitle.setObjectName("subtitle")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)

        refresh_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Devices")
        self.refresh_btn.setObjectName("btn-secondary")
        self.refresh_btn.setFixedWidth(160)
        self.refresh_btn.clicked.connect(self._refresh)
        refresh_row.addWidget(self.refresh_btn)
        refresh_row.addStretch()
        layout.addLayout(refresh_row)

        self.source_card = self._build_role_card("Source Device (A)", is_source=True)
        layout.addWidget(self.source_card["frame"])

        self.target_card = self._build_role_card("Target Device (B)", is_source=False)
        layout.addWidget(self.target_card["frame"])

        self.warning_label = QLabel("")
        self.warning_label.setObjectName("text-error")
        self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)

        layout.addStretch()

    def _build_role_card(self, label_text, is_source):
        frame = QFrame()
        frame.setObjectName("card")
        card_layout = QVBoxLayout(frame)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(8)

        label = QLabel(label_text)
        label.setObjectName("field-label")
        card_layout.addWidget(label)

        combo = QComboBox()
        combo.addItem("-- No devices detected --", None)
        combo.currentIndexChanged.connect(
            lambda _idx, src=is_source: self._on_selection_changed(src)
        )
        card_layout.addWidget(combo)

        status = QLabel("")
        status.setObjectName("text-muted")
        card_layout.addWidget(status)

        return {"frame": frame, "combo": combo, "status": status}

    def _refresh(self):
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Scanning...")
        try:
            from core.adb import ADB
            adb = ADB()
        except ImportError:
            self.warning_label.setText("ADB not found")
            self.refresh_btn.setEnabled(True)
            self.refresh_btn.setText("Refresh Devices")
            return

        # Avoid dropping the last reference to a still-running QThread (Qt
        # treats destroying a running QThread as fatal).
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(5000)

        self._thread = DeviceScanThread(adb)
        self._thread.result.connect(self._on_devices)
        self._thread.start()

    def _on_devices(self, devices):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("Refresh Devices")
        self._devices = devices

        for card in (self.source_card, self.target_card):
            combo = card["combo"]
            combo.blockSignals(True)
            combo.clear()
            if not devices:
                combo.addItem("-- No devices detected --", None)
            else:
                combo.addItem("-- Select a device --", None)
                for d in devices:
                    root_status = "Rooted" if getattr(d, "is_rooted", False) else "No Root"
                    combo.addItem(f"{d.model} ({d.serial}) | {root_status}", d.serial)
            combo.blockSignals(False)

        if not devices:
            self.warning_label.setText("No devices found. Check USB debugging on both devices.")
        else:
            self.warning_label.setText("")

    def _device_by_serial(self, serial):
        for d in self._devices:
            if d.serial == serial:
                return d
        return None

    def _on_selection_changed(self, is_source):
        card = self.source_card if is_source else self.target_card
        serial = card["combo"].currentData()
        device = self._device_by_serial(serial) if serial else None

        if is_source:
            self.app.source_device = device
        else:
            self.app.target_device = device

        for c, dev in ((self.source_card, self.app.source_device),
                       (self.target_card, self.app.target_device)):
            if dev:
                root_status = "Rooted" if getattr(dev, "is_rooted", False) else "No Root"
                c["status"].setText(f"{dev.model} \u2022 {root_status}")
                c["status"].setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")
            else:
                c["status"].setText("")

        if (self.app.source_device and self.app.target_device
                and self.app.source_device.serial == self.app.target_device.serial):
            self.warning_label.setText("Source and target must be different devices.")
        else:
            self.warning_label.setText("")

        self.app._update_buttons()

    def on_show(self):
        is_migrate = self.app.mode == "migrate"
        self.title.setText("Connect Devices")
        self.subtitle.setText(
            "Connect both the old and the new device via USB at the same "
            "time (or use Wi-Fi ADB for one of them), then choose which is "
            "the old device (source) and which is the new one (target)."
            if is_migrate else
            "Connect both devices via USB at the same time (or use Wi-Fi "
            "ADB for one of them), then pick which is the source and which "
            "is the target below."
        )
        self._refresh()


# ----------------------------------------------------------------------
# Step: run the clone / migration
# ----------------------------------------------------------------------
class CloneThread(QThread):
    """Background thread that exports from source and imports onto target."""
    progress = Signal(float, str)
    log = Signal(str)
    done = Signal(bool, str)

    def __init__(self, adb, app):
        super().__init__()
        self.adb = adb
        self.app = app

    def run(self):
        local_tmp = None
        try:
            source = self.app.source_device
            target = self.app.target_device
            if not source or not target:
                raise Exception("Source and target devices are not both set")

            src_shell = _shell_for(self.adb, source)
            tgt_shell = _shell_for(self.adb, target)
            is_migrate = self.app.mode == "migrate"

            # 1. Export from source
            self.progress.emit(0.05, "Preparing export on the source device...")
            out, code = src_shell(
                source.serial, f"cd {ANK_DIR} && tar -czf /data/local/tmp/ank_clone.tar.gz . 2>&1"
            )
            if code != 0:
                if out:
                    self.log.emit(out)
                raise Exception("Failed to package the source device's ANK data")
            self.log.emit("OK: source data packaged")

            self.progress.emit(0.25, "Downloading configuration from the source device...")
            local_tmp = os.path.join(tempfile.gettempdir(), "ank_clone_transfer.tar.gz")
            if not self.adb.pull(source.serial, "/data/local/tmp/ank_clone.tar.gz", local_tmp):
                raise Exception("Failed to pull the exported data from the source device")
            src_shell(source.serial, "rm -f /data/local/tmp/ank_clone.tar.gz")
            self.log.emit("OK: configuration downloaded")

            # 2. Import to target
            self.progress.emit(0.4, "Uploading configuration to the target device...")
            if not self.adb.push(target.serial, local_tmp, REMOTE_TMP):
                raise Exception("Failed to push the configuration to the target device")
            self.log.emit("OK: configuration uploaded")

            self.progress.emit(0.5, "Removing existing ANK data on the target...")
            tgt_shell(target.serial, f"rm -rf {ANK_DIR}")
            tgt_shell(target.serial, f"mkdir -p {ANK_DIR}")

            self.progress.emit(0.6, "Extracting configuration on the target...")
            out, code = tgt_shell(target.serial, f"tar -xzf {REMOTE_TMP} -C {ANK_DIR} 2>&1")
            if code != 0:
                if out:
                    self.log.emit(out)
                raise Exception("Failed to extract the configuration on the target device")
            self.log.emit("OK: configuration extracted")

            # 3. Migrate-only options
            if is_migrate:
                self._apply_migrate_options(tgt_shell, target)

            self.progress.emit(0.95, "Cleaning up temporary files...")
            tgt_shell(target.serial, f"rm -f {REMOTE_TMP}")
            try:
                if local_tmp and os.path.exists(local_tmp):
                    os.remove(local_tmp)
            except OSError:
                pass
            self.log.emit("OK: cleanup complete")

            self.progress.emit(1.0, "Done!")
            self.done.emit(True, "Clone complete!" if not is_migrate else "Migration complete!")
        except Exception as e:
            self.done.emit(False, str(e))

    def _apply_migrate_options(self, tgt_shell, target):
        """Best-effort application of the options chosen in StepMigrateOptions."""
        self.progress.emit(0.72, "Applying migration options...")

        # Network configuration (server_port lives in config.json)
        cfg_out, cfg_code = tgt_shell(target.serial, f"cat {ANK_DIR}/config.json 2>/dev/null")
        config = None
        if cfg_code == 0 and cfg_out:
            try:
                config = json.loads(cfg_out.strip())
            except Exception:
                config = None

        if config is not None:
            changed = False
            if not self.app.migrate_keep_network:
                config["server_port"] = 8001
                changed = True
                self.log.emit("Reset network configuration to defaults")
            if self.app.migrate_remap_ports:
                config["server_port"] = self.app.migrate_server_port
                changed = True
                self.log.emit(f"Remapped server port to {self.app.migrate_server_port}")
            if changed:
                config_str = json.dumps(config).replace("'", "'\\''")
                tgt_shell(target.serial, f"echo '{config_str}' > {ANK_DIR}/config.json")
        else:
            self.log.emit("WARN: could not read config.json, skipping network options")

        # Container selection
        selection = self.app.migrate_container_selection
        if selection is not None:
            self.progress.emit(0.8, "Applying container selection...")
            out, code = tgt_shell(target.serial, f"ls {ANK_DIR}/containers 2>/dev/null")
            existing = [line.strip() for line in (out or "").splitlines() if line.strip()]
            for name in existing:
                if name not in selection:
                    tgt_shell(target.serial, f"rm -rf {ANK_DIR}/containers/{name}")
                    self.log.emit(f"Removed container not selected for migration: {name}")


class StepCloneProgress(QWidget):
    """Step: Cloning / Migrating."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._thread = None
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.title = QLabel("Cloning")
        self.title.setObjectName("title")
        layout.addWidget(self.title)

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

        from PySide6.QtCore import QTimer
        self._countdown = 0
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._countdown_tick)

    def _add_log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")

    def on_show(self):
        self.title.setText("Migrating" if self.app.mode == "migrate" else "Cloning")
        self.progress.setValue(0)
        self.progress_label.setText("0%")
        self.log.clear()
        self.app.clone_complete = False
        self.app.clone_failed = False

        source = self.app.source_device
        target = self.app.target_device
        if not source or not target:
            self._add_log("Error: source and target devices are not both set")
            return

        try:
            from core.adb import ADB
            adb = ADB()
            if self._thread is not None and self._thread.isRunning():
                self._thread.wait(3000)
            self._thread = CloneThread(adb, self.app)
            self._thread.progress.connect(self._on_progress)
            self._thread.log.connect(self._add_log)
            self._thread.done.connect(self._on_done)
            self._thread.start()
        except Exception as e:
            self._add_log(f"Error: {e}")

    def _on_progress(self, value, msg):
        self.progress.setValue(int(value * 100))
        self.progress_label.setText(f"{int(value * 100)}%")
        self.status.setText(msg)

    def _on_done(self, success, msg):
        if success:
            self.progress.setValue(100)
            self.progress_label.setText("100%")
            self.status.setText(msg)
            self.status.setStyleSheet(f"color: {COLORS['success']}; font-size: 13px; font-weight: bold;")
            self.app.clone_complete = True
            # From here on, the "device" being tracked is the target device
            # (used by the Reboot and Finished steps).
            self.app.device_data = self.app.target_device
            self._countdown = 5
            self.countdown_label.setText(f"Continuing in {self._countdown}s...")
            self._countdown_timer.start(1000)
        else:
            self.progress.setValue(0)
            self.status.setText(f"Failed: {msg}")
            self.status.setStyleSheet(f"color: {COLORS['danger']}; font-size: 13px; font-weight: bold;")
            self.app.clone_failed = True
        self.app._update_buttons()

    def _countdown_tick(self):
        self._countdown -= 1
        if self._countdown <= 0:
            self._countdown_timer.stop()
            self.countdown_label.setText("")
            self.app.show_step(self.app.current_step + 1)
        else:
            self.countdown_label.setText(f"Continuing in {self._countdown}s...")

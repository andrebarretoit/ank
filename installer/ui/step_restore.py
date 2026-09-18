"""
ANK Installer - Restore Mode (PySide6)
Restores a device from a previously exported .ankengine backup file.

A .ankengine file is simply a renamed .tar.gz of the device's entire
/data/local/ank directory (see step_clone.py for how one is produced).

Contains two step widgets used by the "restore" flow in ui/app.py:
  - StepRestoreSelect:   pick the .ankengine file on disk
  - StepRestoreProgress: push it to the device and extract it
"""

import datetime
import os
import tempfile

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTextEdit, QProgressBar, QFileDialog
)
from PySide6.QtCore import Qt, QThread, Signal
from ui.theme import COLORS

ANK_DIR = "/data/local/ank"
REMOTE_TMP = "/data/local/tmp/ank_restore.ankengine"


def _shell_for(adb, device):
    """Pick the root or non-root shell helper depending on the device."""
    rooted = bool(getattr(device, "is_rooted", False))
    return adb.shell_su if rooted else adb.shell


# ----------------------------------------------------------------------
# Step: pick the backup file
# ----------------------------------------------------------------------
class StepRestoreSelect(QWidget):
    """Step: Select Backup."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Select Backup")
        title.setObjectName("title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Choose the .ankengine backup file you want to restore onto "
            f"{self._device_label()}."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        self.file_label = QLabel("No file selected")
        self.file_label.setObjectName("subtitle")
        self.file_label.setWordWrap(True)
        card_layout.addWidget(self.file_label)

        self.size_label = QLabel("")
        self.size_label.setObjectName("text-muted")
        card_layout.addWidget(self.size_label)

        btn_row = QHBoxLayout()
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setObjectName("btn-secondary")
        self.browse_btn.setFixedWidth(140)
        self.browse_btn.clicked.connect(self._browse)
        btn_row.addWidget(self.browse_btn)
        btn_row.addStretch()
        card_layout.addLayout(btn_row)

        layout.addWidget(card)
        layout.addStretch()

    def _device_label(self):
        device = getattr(self.app, "device_data", None)
        if device:
            model = getattr(device, "model", None) or device.serial
            return model
        return "the connected device"

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select .ankengine backup",
            "",
            "ANK Backup (*.ankengine);;All Files (*)"
        )
        if not path:
            return
        self.app.restore_file_path = path
        self.file_label.setText(os.path.basename(path))
        self.file_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 13px;")
        try:
            size = os.path.getsize(path)
            self.size_label.setText(f"{path}  \u2022  {self._format_size(size)}")
        except OSError:
            self.size_label.setText(path)
        self.app._update_buttons()

    @staticmethod
    def _format_size(num_bytes):
        size = float(num_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def on_show(self):
        self.file_label.setText(
            os.path.basename(self.app.restore_file_path)
            if self.app.restore_file_path else "No file selected"
        )
        if not self.app.restore_file_path:
            self.file_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
            self.size_label.setText("")


# ----------------------------------------------------------------------
# Step: run the restore
# ----------------------------------------------------------------------
class RestoreThread(QThread):
    """Background thread that pushes and extracts the backup."""
    progress = Signal(float, str)
    log = Signal(str)
    done = Signal(bool, str)

    def __init__(self, adb, device, backup_path):
        super().__init__()
        self.adb = adb
        self.device = device
        self.backup_path = backup_path

    def run(self):
        try:
            serial = self.device.serial
            shell = _shell_for(self.adb, self.device)

            self.progress.emit(0.05, "Reading backup file...")
            if not os.path.isfile(self.backup_path):
                raise Exception(f"Backup file not found: {self.backup_path}")
            self.log.emit(f"Backup: {self.backup_path}")

            self.progress.emit(0.2, "Uploading backup to the device...")
            if not self.adb.push(serial, self.backup_path, REMOTE_TMP):
                raise Exception("Failed to push the backup file to the device")
            self.log.emit("OK: backup uploaded")

            self.progress.emit(0.4, "Removing existing ANK data...")
            shell(serial, f"rm -rf {ANK_DIR}")
            shell(serial, f"mkdir -p {ANK_DIR}")
            self.log.emit("OK: previous data removed")

            self.progress.emit(0.55, "Extracting backup...")
            out, code = shell(serial, f"tar -xzf {REMOTE_TMP} -C {ANK_DIR} 2>&1")
            if code != 0:
                if out:
                    self.log.emit(out)
                raise Exception("Failed to extract the backup on the device")
            self.log.emit("OK: backup extracted")

            self.progress.emit(0.85, "Verifying restored data...")
            check, _ = shell(serial, f"ls {ANK_DIR} 2>/dev/null")
            if not check:
                raise Exception("The restored directory looks empty")
            self.log.emit(f"OK: {ANK_DIR} restored")

            self.progress.emit(0.95, "Cleaning up temporary files...")
            shell(serial, f"rm -f {REMOTE_TMP}")
            self.log.emit("OK: cleanup complete")

            self.progress.emit(1.0, "Done!")
            self.done.emit(True, "Restore complete!")
        except Exception as e:
            self.done.emit(False, str(e))


class StepRestoreProgress(QWidget):
    """Step: Restoring."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._thread = None
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Restoring")
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

        from PySide6.QtCore import QTimer
        self._countdown = 0
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._countdown_tick)

    def _add_log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")

    def on_show(self):
        self.progress.setValue(0)
        self.progress_label.setText("0%")
        self.log.clear()
        self.app.restore_complete = False
        self.app.restore_failed = False

        device = self.app.device_data
        backup_path = self.app.restore_file_path
        if not device or not backup_path:
            self._add_log("Error: no device or backup file selected")
            return

        try:
            from core.adb import ADB
            adb = ADB()
            if self._thread is not None and self._thread.isRunning():
                self._thread.wait(3000)
            self._thread = RestoreThread(adb, device, backup_path)
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
            self.status.setText("Restore complete!")
            self.status.setStyleSheet(f"color: {COLORS['success']}; font-size: 13px; font-weight: bold;")
            self.app.restore_complete = True
            self._countdown = 5
            self.countdown_label.setText(f"Continuing in {self._countdown}s...")
            self._countdown_timer.start(1000)
        else:
            self.progress.setValue(0)
            self.status.setText(f"Failed: {msg}")
            self.status.setStyleSheet(f"color: {COLORS['danger']}; font-size: 13px; font-weight: bold;")
            self.app.restore_failed = True
        self.app._update_buttons()

    def _countdown_tick(self):
        self._countdown -= 1
        if self._countdown <= 0:
            self._countdown_timer.stop()
            self.countdown_label.setText("")
            self.app.show_step(self.app.current_step + 1)
        else:
            self.countdown_label.setText(f"Continuing in {self._countdown}s...")

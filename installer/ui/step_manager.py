"""
ANK Installer - Step: ANK Manager (PySide6)
Start/Stop/Restart ANK server + real-time logs.
Shown in sidebar when ANK is detected as installed.
"""

import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextEdit, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QTextCursor
from ui.theme import COLORS


class StatusPollThread(QThread):
    """Background thread polling ANK server status via ADB."""
    status_update = Signal(str, str)  # status, detail
    log_line = Signal(str)

    def __init__(self, adb, serial, rooted):
        super().__init__()
        self.adb = adb
        self.serial = serial
        self.rooted = rooted
        self._running = True

    def run(self):
        import subprocess
        while self._running:
            try:
                # Check if server process is running
                if self.rooted:
                    out, _ = self.adb.shell_su(self.serial,
                        "pgrep -f 'python3.*server.py' 2>/dev/null")
                else:
                    out, _ = self.adb.shell(self.serial,
                        "pgrep -f 'python3.*server.py' 2>/dev/null")

                pid = out.strip().split("\n")[0] if out.strip() else ""
                if pid and pid.isdigit():
                    self.status_update.emit("running", f"PID: {pid}")
                else:
                    self.status_update.emit("stopped", "Server not running")

                # Fetch last log lines
                log_cmd = "tail -5 /data/local/ank/logs/service.log 2>/dev/null"
                if not self.rooted:
                    log_cmd = "cat /data/local/ank/logs/service.log 2>/dev/null | tail -5"
                log_out, _ = self.adb.shell(self.serial, log_cmd)
                if log_out.strip():
                    for line in log_out.strip().split("\n")[-3:]:
                        if line.strip():
                            self.log_line.emit(line.strip())

            except Exception:
                self.status_update.emit("error", "Cannot reach device")

            for _ in range(30):
                if not self._running:
                    return
                time.sleep(0.1)

    def stop(self):
        self._running = False


class StepManager(QWidget):
    """ANK Manager panel: start/stop/restart + live logs."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._thread = None
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title = QLabel("ANK Manager")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Status card
        self.status_frame = QFrame()
        self.status_frame.setObjectName("card")
        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(20, 16, 20, 16)

        self.status_dot = QLabel("\u25cf")
        self.status_dot.setFixedWidth(20)
        self.status_dot.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 16px;")
        status_layout.addWidget(self.status_dot)

        status_col = QVBoxLayout()
        self.status_label = QLabel("Checking...")
        self.status_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 14px; font-weight: bold;")
        status_col.addWidget(self.status_label)
        self.status_detail = QLabel("")
        self.status_detail.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        status_col.addWidget(self.status_detail)
        status_layout.addLayout(status_col)
        status_layout.addStretch()

        layout.addWidget(self.status_frame)

        # Control buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_start = QPushButton("\u25b6  Start")
        self.btn_start.setObjectName("btn-start")
        self.btn_start.setFixedHeight(40)
        self.btn_start.clicked.connect(self._on_start)
        btn_row.addWidget(self.btn_start)

        self.btn_stop = QPushButton("\u25a0  Stop")
        self.btn_stop.setObjectName("btn-stop")
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.clicked.connect(self._on_stop)
        btn_row.addWidget(self.btn_stop)

        self.btn_restart = QPushButton("\u21bb  Restart")
        self.btn_restart.setObjectName("btn-restart")
        self.btn_restart.setFixedHeight(40)
        self.btn_restart.clicked.connect(self._on_restart)
        btn_row.addWidget(self.btn_restart)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Log area
        log_label = QLabel("Live Logs")
        log_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; font-weight: 600;")
        layout.addWidget(log_label)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet(f"""
            QTextEdit {{
                background: {COLORS['bg_primary']};
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 12px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }}
        """)
        self.log_area.setMinimumHeight(200)
        layout.addWidget(self.log_area, 1)

        # Back button
        back_row = QHBoxLayout()
        back_row.addStretch()
        self.btn_back = QPushButton("\u2190 Back to Installer")
        self.btn_back.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 8px 20px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                color: {COLORS['text']};
                border-color: {COLORS['accent']};
            }}
        """)
        self.btn_back.clicked.connect(self._on_back)
        back_row.addWidget(self.btn_back)
        layout.addLayout(back_row)

    def on_show(self):
        """Called when this step becomes visible."""
        self.log_area.clear()
        self._poll_status()

    def _poll_status(self):
        """Start polling device status."""
        if self._thread and self._thread.isRunning():
            self._thread.stop()
            self._thread.wait(1000)

        device = self.app.device_data
        if not device:
            self.status_label.setText("No device connected")
            self.status_dot.setStyleSheet(f"color: {COLORS['danger']}; font-size: 16px;")
            return

        self._thread = StatusPollThread(
            self.app._adb, device.serial, getattr(device, 'is_rooted', False))
        self._thread.status_update.connect(self._on_status)
        self._thread.log_line.connect(self._on_log)
        self._thread.start()

    def _on_status(self, status, detail):
        self.status_detail.setText(detail)
        if status == "running":
            self.status_label.setText("Running")
            self.status_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 14px; font-weight: bold;")
            self.status_dot.setStyleSheet(f"color: {COLORS['success']}; font-size: 16px;")
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_restart.setEnabled(True)
        elif status == "stopped":
            self.status_label.setText("Stopped")
            self.status_label.setStyleSheet(f"color: {COLORS['warning']}; font-size: 14px; font-weight: bold;")
            self.status_dot.setStyleSheet(f"color: {COLORS['warning']}; font-size: 16px;")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_restart.setEnabled(False)
        else:
            self.status_label.setText("Error")
            self.status_label.setStyleSheet(f"color: {COLORS['danger']}; font-size: 14px; font-weight: bold;")
            self.status_dot.setStyleSheet(f"color: {COLORS['danger']}; font-size: 16px;")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(True)
            self.btn_restart.setEnabled(True)

    def _on_log(self, line):
        self.log_area.append(line)
        cursor = self.log_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_area.setTextCursor(cursor)

    def _on_start(self):
        device = self.app.device_data
        if not device:
            return
        self.btn_start.setEnabled(False)
        self.status_label.setText("Starting...")
        self.status_label.setStyleSheet(f"color: {COLORS['accent']}; font-size: 14px; font-weight: bold;")
        self._exec_cmd("start")

    def _on_stop(self):
        device = self.app.device_data
        if not device:
            return
        self.btn_stop.setEnabled(False)
        self.status_label.setText("Stopping...")
        self.status_label.setStyleSheet(f"color: {COLORS['accent']}; font-size: 14px; font-weight: bold;")
        self._exec_cmd("stop")

    def _on_restart(self):
        device = self.app.device_data
        if not device:
            return
        self.btn_restart.setEnabled(False)
        self.status_label.setText("Restarting...")
        self.status_label.setStyleSheet(f"color: {COLORS['accent']}; font-size: 14px; font-weight: bold;")
        self._exec_cmd("restart")

    def _exec_cmd(self, cmd):
        """Execute start/stop/restart via ADB signals."""
        device = self.app.device_data
        if not device:
            return
        rooted = getattr(device, 'is_rooted', False)
        serial = device.serial

        class CmdThread(QThread):
            done = Signal()
            def __init__(self):
                super().__init__()
            def run(self):
                try:
                    # Find server PID
                    if rooted:
                        out, _ = adb.shell_su(serial,
                            "pgrep -f 'python3.*server.py' 2>/dev/null")
                    else:
                        out, _ = adb.shell(serial,
                            "pgrep -f 'python3.*server.py' 2>/dev/null")
                    pid = out.strip().split("\n")[0] if out.strip() else ""

                    if cmd == "start":
                        if pid and pid.isdigit():
                            return  # already running
                        # Launch server
                        if rooted:
                            adb.shell_su(serial,
                                "cd /data/local/ank/ankfs && "
                                "LD_LIBRARY_PATH=/data/local/ank/ankfs/lib:/data/local/ank/ankfs/usr/lib "
                                "nohup /data/local/ank/ankfs/lib/ld-musl-*.so* "
                                "/data/local/ank/ankfs/usr/bin/python3 /opt/ank/server.py "
                                ">> /data/local/ank/logs/service.log 2>&1 &")
                        else:
                            adb.shell(serial,
                                "cd /data/local/ank/ankfs && "
                                "nohup /data/local/ank/proot -0 -r /data/local/ank/ankfs "
                                "-b /dev -b /proc -w /root "
                                "/usr/bin/python3 /opt/ank/server.py "
                                ">> /data/local/ank/logs/service.log 2>&1 &")
                    elif cmd == "stop":
                        if pid and pid.isdigit():
                            if rooted:
                                adb.shell_su(serial, f"kill {pid}")
                            else:
                                adb.shell(serial, f"kill {pid}")
                    elif cmd == "restart":
                        if pid and pid.isdigit():
                            if rooted:
                                adb.shell_su(serial, f"kill -HUP {pid}")
                            else:
                                adb.shell(serial, f"kill -HUP {pid}")
                        else:
                            # Not running — just start
                            if rooted:
                                adb.shell_su(serial,
                                    "cd /data/local/ank/ankfs && "
                                    "LD_LIBRARY_PATH=/data/local/ank/ankfs/lib:/data/local/ank/ankfs/usr/lib "
                                    "nohup /data/local/ank/ankfs/lib/ld-musl-*.so* "
                                    "/data/local/ank/ankfs/usr/bin/python3 /opt/ank/server.py "
                                    ">> /data/local/ank/logs/service.log 2>&1 &")
                            else:
                                adb.shell(serial,
                                    "cd /data/local/ank/ankfs && "
                                    "nohup /data/local/ank/proot -0 -r /data/local/ank/ankfs "
                                    "-b /dev -b /proc -w /root "
                                    "/usr/bin/python3 /opt/ank/server.py "
                                    ">> /data/local/ank/logs/service.log 2>&1 &")
                except Exception:
                    pass
                self.done.emit()

        adb = self.app._adb
        t = CmdThread()
        t.done.connect(lambda: self._poll_status())
        t.start()
        # Keep reference to prevent GC
        self._cmd_thread = t

    def _on_back(self):
        """Return to mode selector."""
        if self._thread and self._thread.isRunning():
            self._thread.stop()
            self._thread.wait(1000)
        self.app.show_mode_select()

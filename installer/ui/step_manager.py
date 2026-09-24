"""
ANK Installer - Step: ANK Manager (PySide6)
Start/Stop/Restart ANK server + real-time logs.
Shown in sidebar when ANK is detected as installed.
Handles both rooted (chroot/musl) and lite (proot) installations.
"""

import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextEdit, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QTextCursor
from ui.theme import COLORS


def _detect_ank_paths(adb, serial):
    """Detect ANK installation paths and mode. Returns dict with paths or None."""
    # Check rooted first
    out, _ = adb.shell(serial, "ls /data/local/ank/mode 2>/dev/null")
    if out and "mode" in out:
        try:
            import json as _j
            mode_out, _ = adb.shell(serial, "cat /data/local/ank/mode 2>/dev/null")
            mode_data = _j.loads(mode_out.strip()) if mode_out.strip().startswith("{") else {}
            mode = mode_data.get("mode", "shared_host")
        except Exception:
            mode = "shared_host"

        if mode == "lite":
            return {
                "mode": "lite",
                "base_dir": "/data/local/tmp/ank",
                "start_script": "/data/local/tmp/ank/start-lite.sh",
                "stop_script": "/data/local/tmp/ank/stop-lite.sh",
                "log_file": "/data/local/tmp/ank/logs/server.log",
                "rooted": False,
            }
        return {
            "mode": mode,
            "base_dir": "/data/local/ank",
            "start_script": None,
            "stop_script": None,
            "log_file": "/data/local/ank/logs/service.log",
            "rooted": True,
        }

    # Check lite
    out, _ = adb.shell(serial, "ls /data/local/tmp/ank/mode 2>/dev/null")
    if out and "mode" in out:
        return {
            "mode": "lite",
            "base_dir": "/data/local/tmp/ank",
            "start_script": "/data/local/tmp/ank/start-lite.sh",
            "stop_script": "/data/local/tmp/ank/stop-lite.sh",
            "log_file": "/data/local/tmp/ank/logs/server.log",
            "rooted": False,
        }

    return None


class StatusPollThread(QThread):
    """Background thread polling ANK server status via ADB."""
    status_update = Signal(str, str)  # status, detail
    log_line = Signal(str)

    _NOISE = (
        "Orchestrator started",
        "Orchestrator not started",
        "[STACK] Auto-scaling monitor",
        "Stack auto-scale monitor started",
        "Stack monitor not started",
        "Auto-scaling monitor started",
    )

    def __init__(self, adb, serial, ank_paths):
        super().__init__()
        self.adb = adb
        self.serial = serial
        self.ank_paths = ank_paths
        self._running = True
        self._log_offset = None

    def _shell(self, rooted, cmd):
        if rooted:
            return self.adb.shell_su(self.serial, cmd)
        return self.adb.shell(self.serial, cmd)

    def _is_noise(self, line):
        return any(n in line for n in self._NOISE)

    def _file_size(self, rooted, log_file):
        out, _ = self._shell(rooted, f"wc -c < {log_file} 2>/dev/null")
        try:
            return int((out or "").strip())
        except (ValueError, AttributeError):
            return 0

    def _emit_log_lines(self, text):
        for line in (text or "").splitlines():
            line = line.strip()
            if line and not self._is_noise(line):
                self.log_line.emit(line)

    def _stream_logs(self, rooted, log_file):
        size = self._file_size(rooted, log_file)
        if size <= 0:
            self._log_offset = None
            return
        if self._log_offset is None:
            out, _ = self._shell(rooted, f"tail -50 {log_file} 2>/dev/null")
            self._emit_log_lines(out)
            self._log_offset = size
            return
        if size < self._log_offset:
            self._log_offset = 0
        if size > self._log_offset:
            out, _ = self._shell(
                rooted, f"tail -c +{self._log_offset + 1} {log_file} 2>/dev/null"
            )
            self._emit_log_lines(out)
            self._log_offset = self._file_size(rooted, log_file)

    def run(self):
        rooted = self.ank_paths.get("rooted", True) if self.ank_paths else True
        log_file = self.ank_paths.get("log_file", "/data/local/ank/logs/service.log") if self.ank_paths else "/data/local/ank/logs/service.log"

        while self._running:
            try:
                out, _ = self._shell(rooted,
                    "pgrep -f 'python3.*server.py' 2>/dev/null")

                pid = out.strip().split("\n")[0] if out.strip() else ""
                if pid and pid.isdigit():
                    port_check, _ = self._shell(rooted,
                        "netstat -tln 2>/dev/null | grep -c ':8001 '")
                    try:
                        listening = int(port_check.strip()) > 0
                    except (ValueError, AttributeError):
                        listening = False
                    if listening:
                        self.status_update.emit("running", f"PID: {pid} | Port 8001 OK")
                    else:
                        self.status_update.emit("stopped", f"PID: {pid} but port 8001 not listening")
                else:
                    self.status_update.emit("stopped", "Server not running")

                self._stream_logs(rooted, log_file)

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
        self._ank_paths = None
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("ANK Manager")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

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
        self.log_area.clear()
        self._poll_status()

    def _poll_status(self):
        if self._thread and self._thread.isRunning():
            self._thread.stop()
            self._thread.wait(1000)

        device = self.app.device_data
        if not device:
            self.status_label.setText("No device connected")
            self.status_dot.setStyleSheet(f"color: {COLORS['danger']}; font-size: 16px;")
            return

        adb = self.app._adb
        self._ank_paths = _detect_ank_paths(adb, device.serial)

        if not self._ank_paths:
            self.status_label.setText("ANK not installed")
            self.status_detail.setText("Run the installer first")
            self.status_dot.setStyleSheet(f"color: {COLORS['danger']}; font-size: 16px;")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_restart.setEnabled(False)
            return

        mode_label = f"{self._ank_paths['mode']} mode"
        self.status_detail.setText(mode_label)

        self._thread = StatusPollThread(adb, device.serial, self._ank_paths)
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
        """Execute start/stop/restart. Uses scripts for lite, server.py CLI for rooted."""
        device = self.app.device_data
        if not device or not self._ank_paths:
            return

        serial = device.serial
        adb = self.app._adb
        ank = self._ank_paths

        if ank["mode"] == "lite":
            if cmd == "start":
                run_cmd = f"sh {ank['start_script']}"
            elif cmd == "stop":
                run_cmd = f"sh {ank['stop_script']}"
            else:
                run_cmd = f"sh {ank['stop_script']}; sleep 2; sh {ank['start_script']}"

            class CmdThread(QThread):
                done = Signal()
                def run(self):
                    try:
                        adb.shell(serial, run_cmd)
                    except Exception:
                        pass
                    self.done.emit()

        else:
            PYTHON_BASE = "/data/local/ank/ankfs/usr/bin/python3"
            SERVER_SCRIPT = "/opt/ank/server.py"
            WORK_DIR = "/data/local/ank/ankfs"
            LIB_PATH = "/data/local/ank/ankfs/lib:/data/local/ank/ankfs/usr/lib"
            MUSL = "/data/local/ank/ankfs/lib/ld-musl-*.so*"
            LOG = "/data/local/ank/logs/service.log"

            if cmd == "start":
                out, _ = adb.shell_su(serial, "pgrep -f 'python3.*server.py' 2>/dev/null")
                pid = out.strip().split("\n")[0] if out.strip() else ""
                if pid and pid.isdigit():
                    return

                subcmd = "ankengine.startserver"
                run_cmd = (
                    f"cd {WORK_DIR} && "
                    f"LD_LIBRARY_PATH={LIB_PATH} "
                    f"nohup {MUSL} {PYTHON_BASE} {SERVER_SCRIPT} {subcmd} "
                    f">> {LOG} 2>&1 &"
                )
            else:
                subcmd = f"ankengine.{cmd}server"
                run_cmd = (
                    f"cd {WORK_DIR} && "
                    f"{MUSL} {PYTHON_BASE} {SERVER_SCRIPT} {subcmd}"
                )

            class CmdThread(QThread):
                done = Signal()
                def run(self):
                    try:
                        adb.shell_su(serial, run_cmd)
                    except Exception:
                        pass
                    self.done.emit()

        t = CmdThread()
        t.done.connect(lambda: self._poll_status())
        t.start()
        self._cmd_thread = t

    def _on_back(self):
        if self._thread and self._thread.isRunning():
            self._thread.stop()
            self._thread.wait(1000)
        self.app.show_mode_select()

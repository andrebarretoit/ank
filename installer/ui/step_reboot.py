"""
ANK Installer - Step: Rebooting (PySide6)
Shared by all modes: whichever device should come back online is expected
in self.app.device_data (for Clone/Migrate this is set to the target).
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from ui.theme import COLORS


class RebootThread(QThread):
    status = Signal(str)
    done = Signal(bool)

    def __init__(self, adb, serial, device_ip):
        super().__init__()
        self.adb = adb
        self.serial = serial
        self.device_ip = device_ip

    def run(self):
        import time
        import urllib.request
        import urllib.error

        self.status.emit("Rebooting device...")
        self.adb.reboot(self.serial)

        time.sleep(10)

        self.status.emit("Waiting for ADB to come back...")
        if not self.adb.wait_for_device(self.serial, timeout=120):
            self.status.emit("Timeout waiting for ADB")
            self.done.emit(False)
            return

        self.status.emit("Waiting for Android to finish booting...")
        if not self.adb.wait_for_boot_completed(self.serial, timeout=120):
            self.status.emit("Timeout waiting for boot to complete")
            self.done.emit(False)
            return

        try:
            ip = self.adb.get_device_ip(self.serial)
            if ip:
                self.device_ip = ip
        except Exception:
            pass

        if not self.device_ip:
            self.status.emit("Error: could not get the device's IP")
            self.done.emit(False)
            return

        # Lite: start the server with retries, only mark started on success
        try:
            out, _ = self.adb.shell(self.serial, "ls /data/local/tmp/ank/mode 2>/dev/null")
            if out and "mode" in out:
                started = False
                for attempt in range(1, 6):
                    self.status.emit(f"Starting ANK server (lite)... attempt {attempt}/5")
                    _, code = self.adb.shell(
                        self.serial, "sh /data/local/tmp/ank/start-lite.sh", timeout=60
                    )
                    if code == 0:
                        started = True
                        break
                    time.sleep(3)
                if not started:
                    self.status.emit("WARN: start-lite.sh failed, waiting for panel anyway...")
                else:
                    time.sleep(5)
        except Exception:
            pass

        self.status.emit("Waiting for the ANK server...")

        # Prefer panel_port from device config; fall back to common ports
        ports = [8001]
        try:
            _c = self.adb.shell(self.serial, "cat /data/local/ank/config.json 2>/dev/null")[0]
            import re as _re
            m = _re.search(r'"panel_port"\s*:\s*(\d+)', _c or '')
            if m:
                p = int(m.group(1))
                if p not in ports:
                    ports.insert(0, p)
        except Exception:
            pass
        for i in range(60):
            time.sleep(2)
            for scheme in ("http", "https"):
                for port in ports:
                    try:
                        url = f"{scheme}://{self.device_ip}:{port}/"
                        req = urllib.request.Request(url, method="GET")
                        resp = urllib.request.urlopen(req, timeout=5)
                        code = resp.getcode()
                        if code in (200, 301, 302, 401):
                            self.done.emit(True)
                            return
                    except urllib.error.HTTPError as e:
                        if e.code in (200, 301, 302, 401):
                            self.done.emit(True)
                            return
                    except Exception:
                        pass

        self.done.emit(False)


class StepReboot(QWidget):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._thread = None
        self._device_ip = None
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Rebooting")
        title.setObjectName("title")
        layout.addWidget(title)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)

        self.status_label = QLabel("Preparing to reboot...")
        self.status_label.setObjectName("subtitle")
        card_layout.addWidget(self.status_label)

        self.countdown_label = QLabel("3")
        self.countdown_label.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: 24px; font-weight: bold;"
        )
        card_layout.addWidget(self.countdown_label)

        layout.addWidget(card)

        desc = QLabel(
            "Do not unplug the USB cable.\n"
            "The device will reboot and ANK will start automatically."
        )
        desc.setObjectName("subtitle")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addStretch()

        self._countdown = 3
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._countdown_tick)

    def _countdown_tick(self):
        self._countdown -= 1
        if self._countdown <= 0:
            self._countdown_timer.stop()
            self.countdown_label.setText("")
            self._do_reboot()
        else:
            self.countdown_label.setText(str(self._countdown))

    def _do_reboot(self):
        device = self.app.device_data
        if not device:
            self.status_label.setText("Error: no device")
            return

        self.status_label.setText("Rebooting...")
        try:
            from core.adb import ADB
            adb = ADB()

            if not self._device_ip:
                self._device_ip = adb.get_device_ip(device.serial)

            if not self._device_ip:
                self.status_label.setText("Error: could not get the device's IP")
                return

            self.app.device_ip = self._device_ip

            self._thread = RebootThread(adb, device.serial, self._device_ip)
            self._thread.status.connect(self._on_status)
            self._thread.done.connect(self._on_done)
            self._thread.start()
        except Exception as e:
            self.status_label.setText(f"Error: {e}")

    def _on_status(self, msg):
        self.status_label.setText(msg)

    def on_show(self):
        self._device_ip = None
        self.app.reboot_complete = False
        device = self.app.device_data
        if device:
            try:
                from core.adb import ADB
                adb = ADB()
                self._device_ip = adb.get_device_ip(device.serial)
            except Exception:
                pass

        self._countdown = 3
        self.countdown_label.setText("3")
        self.countdown_label.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: 24px; font-weight: bold;"
        )
        self.status_label.setText("Rebooting in...")
        self._countdown_timer.start(1000)

    def _on_done(self, success):
        if success:
            if self._thread and getattr(self._thread, "device_ip", None):
                self._device_ip = self._thread.device_ip
                self.app.device_ip = self._device_ip
            self.status_label.setText("ANK is online!")
            self.countdown_label.setText("\u2713")
            self.countdown_label.setStyleSheet(
                f"color: {COLORS['success']}; font-size: 24px; font-weight: bold;"
            )
            self.app.reboot_complete = True
            self.app._update_buttons()
            QTimer.singleShot(1000, lambda: self.app.show_step(self.app.current_step + 1))
        else:
            self.status_label.setText("Failed waiting for the device")
            self.countdown_label.setText("\u2717")
            self.countdown_label.setStyleSheet(
                f"color: {COLORS['danger']}; font-size: 24px; font-weight: bold;"
            )
            # Offer retry instead of hanging forever
            if not hasattr(self, '_retry_btn'):
                from PySide6.QtWidgets import QPushButton
                self._retry_btn = QPushButton("Retry")
                self._retry_btn.setStyleSheet(
                    f"background:{COLORS['accent']};color:#fff;border:none;padding:8px 20px;border-radius:6px;font-weight:600;"
                )
                self.layout().insertWidget(2, self._retry_btn)
                self._retry_btn.clicked.connect(self._retry_reboot)
            self._retry_btn.show()

    def _retry_reboot(self):
        if hasattr(self, '_retry_btn'):
            self._retry_btn.hide()
        self.on_show()

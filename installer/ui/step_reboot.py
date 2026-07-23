"""
ANK Installer - Step 4: Rebooting (PySide6)
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

        self.status.emit("Reiniciando dispositivo...")
        self.adb.reboot(self.serial)

        time.sleep(15)

        self.status.emit("Aguardando ADB voltar...")
        if not self.adb.wait_for_device(self.serial, timeout=90):
            self.status.emit("Timeout aguardando ADB")
            self.done.emit(False)
            return

        self.status.emit("Aguardando servidor ANK...")

        for i in range(60):
            time.sleep(2)
            for scheme in ("http", "https"):
                try:
                    url = f"{scheme}://{self.device_ip}:8001/"
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

        title = QLabel("Reiniciando")
        title.setObjectName("title")
        layout.addWidget(title)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)

        self.status_label = QLabel("Preparando reinicializacao...")
        self.status_label.setObjectName("subtitle")
        card_layout.addWidget(self.status_label)

        self.countdown_label = QLabel("3")
        self.countdown_label.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: 24px; font-weight: bold;"
        )
        card_layout.addWidget(self.countdown_label)

        layout.addWidget(card)

        desc = QLabel(
            "Nao remova o cabo USB.\n"
            "O dispositivo vai reiniciar e o ANK vai iniciar automaticamente."
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
            self.status_label.setText("Erro: nenhum device")
            return

        self.status_label.setText("Reiniciando...")
        try:
            from core.adb import ADB
            adb = ADB()

            if not self._device_ip:
                self._device_ip = adb.get_device_ip(device.serial)

            if not self._device_ip:
                self.status_label.setText("Erro: nao foi possivel obter IP do device")
                return

            self.app.device_ip = self._device_ip

            self._thread = RebootThread(adb, device.serial, self._device_ip)
            self._thread.status.connect(self._on_status)
            self._thread.done.connect(self._on_done)
            self._thread.start()
        except Exception as e:
            self.status_label.setText(f"Erro: {e}")

    def _on_status(self, msg):
        self.status_label.setText(msg)

    def on_show(self):
        self._device_ip = None
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
        self.status_label.setText("Reiniciando em...")
        self._countdown_timer.start(1000)

    def _on_done(self, success):
        if success:
            self.status_label.setText("ANK online!")
            self.countdown_label.setText("\u2713")
            self.countdown_label.setStyleSheet(
                f"color: {COLORS['success']}; font-size: 24px; font-weight: bold;"
            )
            self.app.reboot_complete = True
            self.app._update_buttons()
            QTimer.singleShot(1000, lambda: self.app.show_step(5))
        else:
            self.status_label.setText("Falha ao aguardar device")
            self.countdown_label.setText("\u2717")
            self.countdown_label.setStyleSheet(
                f"color: {COLORS['error']}; font-size: 24px; font-weight: bold;"
            )

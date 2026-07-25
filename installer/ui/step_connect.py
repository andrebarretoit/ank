"""
ANK Installer - Step 1: Connect Device (PySide6)
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QComboBox,
    QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
from ui.theme import COLORS, FONTS


class DevicePollThread(QThread):
    """Background thread polling for ADB devices."""
    device_found = Signal(object, str, bool)  # device, model, is_rooted
    no_device = Signal()

    def __init__(self, adb):
        super().__init__()
        self.adb = adb
        self._running = True

    def run(self):
        import time
        while self._running:
            try:
                devices = self.adb.devices()
                if devices:
                    device = devices[0]
                    model = self.adb.get_model(device.serial)
                    is_rooted = self.adb.check_root(device.serial)
                    device.model = model
                    device.is_rooted = is_rooted
                    self.device_found.emit(device, model, is_rooted)
                    return
            except Exception:
                pass
            time.sleep(2)

    def stop(self):
        self._running = False


class StepConnect(QWidget):
    """Step 1: Connect Device."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.adb = None
        self._thread = None
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Title
        title = QLabel("Conectar Dispositivo")
        title.setObjectName("title")
        layout.addWidget(title)

        # Instructions
        instructions = QLabel(
            "Para que o dispositivo seja reconhecido:\n\n"
            "1. Ative o modo desenvolvedor\n"
            "   Configuracoes > Sobre o telefone\n"
            "   Toque 7x em \"Numero da versao\"\n\n"
            "2. Ative a Depuracao USB\n"
            "   Configuracoes > Sistema > Opcoes do Desenvolvedor\n"
            "   Habilite \"Depuracao USB\"\n\n"
            "3. Conecte o cabo USB\n\n"
            "4. No celular: marque \"Sempre permitir...\" e toque em Permitir"
        )
        instructions.setObjectName("subtitle")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        # Status card
        status_card = QFrame()
        status_card.setObjectName("card")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(16, 16, 16, 16)

        self.status_label = QLabel("Aguardando dispositivo...")
        self.status_label.setObjectName("text-muted")
        status_layout.addWidget(self.status_label)

        layout.addWidget(status_card)

        # Device selector (hidden)
        self.device_frame = QFrame()
        device_layout = QHBoxLayout(self.device_frame)
        device_layout.setContentsMargins(0, 0, 0, 0)

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(400)
        device_layout.addWidget(self.device_combo)
        device_layout.addStretch()
        self.device_frame.hide()
        layout.addWidget(self.device_frame)

        # ANK detection card (hidden)
        self.ank_frame = QFrame()
        self.ank_frame.setObjectName("card")
        ank_layout = QVBoxLayout(self.ank_frame)
        ank_layout.setContentsMargins(16, 16, 16, 16)

        self.ank_status = QLabel("")
        self.ank_status.setObjectName("subtitle")
        ank_layout.addWidget(self.ank_status)

        btn_layout = QHBoxLayout()
        self.btn_uninstall = QPushButton("Desinstalar ANK")
        self.btn_uninstall.setFixedWidth(160)
        self.btn_uninstall.clicked.connect(self._uninstall_ank)
        btn_layout.addWidget(self.btn_uninstall)

        btn_layout.addStretch()
        ank_layout.addLayout(btn_layout)

        self.ank_frame.hide()
        layout.addWidget(self.ank_frame)

        # Refresh button
        self.refresh_btn = QPushButton("Verificar novamente")
        self.refresh_btn.setFixedWidth(180)
        self.refresh_btn.clicked.connect(self._start_detection)
        layout.addWidget(self.refresh_btn, alignment=Qt.AlignLeft)

        layout.addStretch()

    def _start_detection(self):
        """Start device detection."""
        self.status_label.setText("Buscando dispositivos...")
        self.status_label.setStyleSheet(f"color: {COLORS['text_muted']};")
        self.refresh_btn.setEnabled(False)
        self.device_frame.hide()

        try:
            from core.adb import ADB
            self.adb = ADB()
        except ImportError:
            self.status_label.setText("ADB nao encontrado")
            self.status_label.setStyleSheet(f"color: {COLORS['error']};")
            self.refresh_btn.setEnabled(True)
            return

        self._thread = DevicePollThread(self.adb)
        self._thread.device_found.connect(self._on_device_found)
        self._thread.start()

    def _on_device_found(self, device, model, is_rooted):
        """Called when a device is found."""
        self.refresh_btn.setEnabled(True)
        root_status = "Rooted" if is_rooted else "No Root"
        display = f"{model} ({device.serial}) | {root_status}"

        self.status_label.setText(f"Device encontrado: {display}")
        self.status_label.setStyleSheet(f"color: {COLORS['success']};")

        self.device_combo.clear()
        self.device_combo.addItem(display)
        self.device_frame.show()

        self.app.device_data = device

        # Check if ANK is already installed
        self._check_ank_installed(device.serial, is_rooted)

        self.app._update_buttons()

    def _check_ank_installed(self, serial, is_rooted):
        """Check if ANK is installed and show uninstall option."""
        try:
            from core.adb import ADB
            adb = ADB()

            ank_installed = adb.check_ank_installed(serial)
            ank_ui_installed = adb.check_ank_ui_installed(serial)

            if ank_installed or ank_ui_installed:
                mode = adb.get_ank_mode(serial) if ank_installed else "N/A"
                status_parts = []
                if ank_installed:
                    status_parts.append(f"Servidor ANK: {mode}")
                if ank_ui_installed:
                    status_parts.append("ANK UI: Instalado")

                self.ank_status.setText(f"ANK ja instalado:\n" + "\n".join(status_parts))
                self.ank_status.setStyleSheet(f"color: {COLORS['warning']}; font-size: 12px;")
                self.ank_frame.show()
            else:
                self.ank_frame.hide()
        except Exception:
            self.ank_frame.hide()

    def _uninstall_ank(self):
        """Uninstall ANK from the device."""
        reply = QMessageBox.question(
            self,
            "Desinstalar ANK",
            "Tem certeza que deseja desinstalar o ANK deste dispositivo?\n\n"
            "Isso removera:\n"
            "- Servidor ANK\n"
            "- ANK UI (launcher)\n"
            "- Todos os dados do ANK",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                from core.adb import ADB
                adb = ADB()
                device = self.app.device_data
                if device:
                    adb.uninstall_ank_full(device.serial, device.is_rooted)
                    self.ank_frame.hide()
                    self.status_label.setText("ANK desinstalado com sucesso")
                    self.status_label.setStyleSheet(f"color: {COLORS['success']};")
            except Exception as e:
                self.status_label.setText(f"Erro ao desinstalar: {e}")
                self.status_label.setStyleSheet(f"color: {COLORS['error']};")

    def on_show(self):
        pass

    def on_hide(self):
        if self._thread:
            self._thread.stop()

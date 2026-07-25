"""
ANK Installer - Step 3: Confirm Installation (PySide6)
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt
from ui.theme import COLORS, TIER_COLORS


class StepConfirm(QWidget):
    """Step 3: Confirm Installation."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Confirmar Instalacao")
        title.setObjectName("title")
        layout.addWidget(title)

        # Info card
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(8)

        self.labels = {}
        fields = [
            ("device", "Device"),
            ("mode", "Modo"),
            ("root", "Root"),
            ("kernel", "Kernel"),
            ("storage", "Armazenamento"),
        ]
        for key, text in fields:
            row = QLabel(f"{text}: --")
            row.setObjectName("subtitle")
            card_layout.addWidget(row)
            self.labels[key] = row

        layout.addWidget(card)

        # Description
        self.desc_label = QLabel("")
        self.desc_label.setObjectName("subtitle")
        self.desc_label.setWordWrap(True)
        layout.addWidget(self.desc_label)

        layout.addStretch()

    def on_show(self):
        """Update display with current data."""
        device = self.app.device_data
        tier = self.app.recommended_tier
        install_mode = getattr(self.app, 'install_mode', 'native')

        if device:
            model = getattr(device, 'model', 'Unknown') or 'Unknown'
            serial = device.serial
            root = "Sim" if getattr(device, 'is_rooted', False) else "Nao"
            kernel = getattr(device, 'kernel', '--') or '--'

            self.labels["device"].setText(f"Device: {model} ({serial})")
            self.labels["root"].setText(f"Root: {root}")
            self.labels["kernel"].setText(f"Kernel: {kernel}")

        tier_names = {
            "isolated": "Isolated",
            "shared_network": "Shared Network",
            "shared_host": "Shared Host",
            "native_host": "Native Host",
            "lite": "Lite",
        }
        tier_name = tier_names.get(tier, tier)
        color = TIER_COLORS.get(tier, "#fff")
        self.labels["mode"].setText(f"Modo: {tier_name}")
        self.labels["mode"].setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")

        is_rooted = device and getattr(device, 'is_rooted', False)

        if install_mode == "ank_ui":
            method = "Magisk module" if is_rooted else "PRoot/Termux"
            self.labels["storage"].setText("Instalacao: ANK UI (launcher)")
            self.desc_label.setText(
                "O instalador ira:\n"
                f"  1. Instalar o stack ANK completo ({method})\n"
                "  2. Instalar o ANK Launcher\n"
                "  3. Configurar como launcher padrao\n"
                "  4. Reiniciar o dispositivo"
            )
        elif is_rooted:
            self.labels["storage"].setText("Armazenamento: ~200MB (rootfs + containeres)")
            self.desc_label.setText(
                "O instalador ira:\n"
                "  1. Instalar o stack ANK completo (server + core + containers)\n"
                "  2. Configurar servicos e rede\n"
                "  3. Criar container padrao\n"
                "  4. Reiniciar o dispositivo"
            )
        else:
            self.labels["storage"].setText("Armazenamento: ~150MB (rootfs + containeres)")
            self.desc_label.setText(
                "O instalador ira:\n"
                "  1. Instalar PRoot/Termux no device\n"
                "  2. Instalar o stack ANK completo (server + core + containers)\n"
                "  3. Configurar servicos e rede\n"
                "  4. Criar container padrao"
            )

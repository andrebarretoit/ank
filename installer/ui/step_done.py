"""
ANK Installer - Step 6: Done (PySide6)
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt, QTimer
from ui.theme import COLORS, TIER_COLORS


class StepDone(QWidget):
    """Step 6: Done."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._countdown = 0
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._countdown_tick)
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Success banner
        banner = QFrame()
        banner.setObjectName("card-success")
        banner_layout = QVBoxLayout(banner)
        banner_layout.setContentsMargins(16, 16, 16, 16)

        ok_label = QLabel("\u2713 Instalacao concluida")
        ok_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 18px; font-weight: bold;")
        banner_layout.addWidget(ok_label)

        layout.addWidget(banner)

        # Summary card
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(8)

        self.device_info = QLabel("Device: --")
        self.device_info.setObjectName("subtitle")
        card_layout.addWidget(self.device_info)

        self.mode_info = QLabel("Modo: --")
        self.mode_info.setObjectName("subtitle")
        card_layout.addWidget(self.mode_info)

        self.url_info = QLabel("URL: --")
        self.url_info.setObjectName("subtitle")
        card_layout.addWidget(self.url_info)

        self.creds_info = QLabel("Credenciais: admin / admin123")
        self.creds_info.setObjectName("subtitle")
        card_layout.addWidget(self.creds_info)

        layout.addWidget(card)

        # Instructions
        desc = QLabel(
            "Para acessar o painel:\n"
            "  1. Abra o navegador\n"
            "  2. Acesse a URL acima\n"
            "  3. Faca login com admin / admin123\n"
            "  4. Troque a senha imediatamente!"
        )
        desc.setObjectName("subtitle")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.countdown_label = QLabel("")
        self.countdown_label.setObjectName("subtitle")
        self.countdown_label.setStyleSheet(f"color: {COLORS['accent']}; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.countdown_label)

        layout.addStretch()

    def on_show(self):
        """Update display and auto-open browser."""
        device = self.app.device_data
        tier = self.app.recommended_tier

        if device:
            model = getattr(device, 'model', 'Unknown') or 'Unknown'
            serial = device.serial
            self.device_info.setText(f"Device: {model} ({serial})")

        tier_names = {
            "isolated": "Isolated",
            "shared_network": "Shared Network",
            "shared_host": "Shared Host",
            "native_host": "Native Host",
            "lite": "Lite",
        }
        tier_name = tier_names.get(tier, tier)
        color = TIER_COLORS.get(tier, "#fff")
        self.mode_info.setText(f"Modo: {tier_name}")
        self.mode_info.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")

        if device:
            ip = self.app.device_ip or getattr(device, 'ip_address', None) or "localhost"
            # Detect actual protocol by trying HTTP then HTTPS
            detected_protocol = self._detect_protocol(ip)
            self.url_info.setText(f"URL: {detected_protocol}://{ip}:8001")
            self.app.detected_protocol = detected_protocol

            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self._open_browser(ip, detected_protocol))

        self._countdown = 5
        self.countdown_label.setText(f"Fechando em {self._countdown}s...")
        self._countdown_timer.start(1000)

    def _countdown_tick(self):
        self._countdown -= 1
        if self._countdown <= 0:
            self._countdown_timer.stop()
            self.countdown_label.setText("")
            self.app.close()
        else:
            self.countdown_label.setText(f"Fechando em {self._countdown}s...")

    def _detect_protocol(self, ip):
        import urllib.request
        import urllib.error
        for scheme in ("http", "https"):
            try:
                url = f"{scheme}://{ip}:8001/"
                req = urllib.request.Request(url, method="GET")
                resp = urllib.request.urlopen(req, timeout=5)
                if resp.getcode() in (200, 301, 302, 401):
                    return scheme
            except urllib.error.HTTPError as e:
                if e.code in (200, 301, 302, 401):
                    return scheme
            except Exception:
                pass
        return "http"

    def _open_browser(self, ip, protocol="http"):
        import webbrowser
        webbrowser.open(f"{protocol}://{ip}:8001")

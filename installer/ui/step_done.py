"""
ANK Installer - Step: Finished (PySide6)
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt, QTimer
from ui.theme import COLORS, TIER_COLORS, TIER_NAMES


class StepDone(QWidget):
    """Step: Finished."""

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

        self.ok_label = QLabel("\u2713 Done")
        self.ok_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 18px; font-weight: bold;")
        banner_layout.addWidget(self.ok_label)

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

        self.mode_info = QLabel("Mode: --")
        self.mode_info.setObjectName("subtitle")
        card_layout.addWidget(self.mode_info)

        self.url_info = QLabel("URL: --")
        self.url_info.setObjectName("subtitle")
        card_layout.addWidget(self.url_info)

        self.creds_info = QLabel("Credentials: admin / admin123")
        self.creds_info.setObjectName("subtitle")
        card_layout.addWidget(self.creds_info)

        layout.addWidget(card)

        # Instructions
        self.desc = QLabel("")
        self.desc.setObjectName("subtitle")
        self.desc.setWordWrap(True)
        layout.addWidget(self.desc)

        self.countdown_label = QLabel("")
        self.countdown_label.setObjectName("subtitle")
        self.countdown_label.setStyleSheet(f"color: {COLORS['accent']}; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.countdown_label)

        layout.addStretch()

    def on_show(self):
        """Update display and auto-open browser."""
        mode = getattr(self.app, "mode", "install")

        headings = {
            "install": "✓ Installation complete",
            "restore": "✓ Restore complete",
            "clone": "✓ Clone complete",
            "migrate": "✓ Migration complete",
            "uninstall": "✓ Uninstall complete",
            "reinstall": "✓ Reinstall complete",
            "export": "✓ Export complete",
            "restore_engine": "✓ Restore complete",
        }
        self.ok_label.setText(headings.get(mode, "✓ Done"))

        self.url_info.show()
        self.creds_info.show()
        self.device_info.show()
        self.mode_info.show()
        self.countdown_label.show()
        self._countdown_timer.stop()

        if mode == "uninstall":
            self.desc.setText(
                "ANK has been completely removed from the device.\n\n"
                "To install again, reconnect the device and run the installer."
            )
            self.url_info.hide()
            self.creds_info.hide()
            self.mode_info.hide()
            self.countdown_label.hide()
            self._fill_info()
            return

        if mode == "export":
            self.desc.setText(
                "ANK configuration has been exported to a file.\n\n"
                "The .ankengine file can be used to restore this setup on any device."
            )
            self.countdown_label.hide()
            self._fill_info()
            return

        self.desc.setText(
            "To access the panel:\n"
            "  1. Open your browser\n"
            "  2. Go to the URL above\n"
            "  3. Log in with admin / admin123\n"
            "  4. Change the password immediately!"
        )

        filled = self._fill_info()
        if filled:
            ip, protocol = filled
            QTimer.singleShot(2000, lambda: self._open_browser(ip, protocol))

        self._countdown = 5
        self.countdown_label.setText(f"Closing in {self._countdown}s...")
        self._countdown_timer.start(1000)

    def _fill_info(self):
        device = self.app.device_data
        if self.app.mode in ("clone", "migrate") and self.app.target_device:
            device = self.app.target_device

        if device:
            model = getattr(device, 'model', 'Unknown') or 'Unknown'
            serial = device.serial
            self.device_info.setText(f"Device: {model} ({serial})")
        else:
            self.device_info.hide()

        tier = self.app.recommended_tier
        if tier:
            tier_name = TIER_NAMES.get(tier, tier)
            color = TIER_COLORS.get(tier, "#fff")
            self.mode_info.setText(f"Mode: {tier_name}")
            self.mode_info.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")
        else:
            self.mode_info.setText(f"Mode: {(self.app.mode or 'install').capitalize()}")
            self.mode_info.setStyleSheet(f"color: {COLORS['accent']}; font-size: 13px; font-weight: bold;")

        if device:
            ip = self.app.device_ip or getattr(device, 'ip_address', None) or "localhost"
            detected_protocol = self._detect_protocol(ip)
            self.url_info.setText(f"URL: {detected_protocol}://{ip}:8001")
            self.app.detected_protocol = detected_protocol
            return ip, detected_protocol

        self.url_info.hide()
        return None

    def _countdown_tick(self):
        self._countdown -= 1
        if self._countdown <= 0:
            self._countdown_timer.stop()
            self.countdown_label.setText("")
            self.app.close()
        else:
            self.countdown_label.setText(f"Closing in {self._countdown}s...")

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

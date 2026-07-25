"""
ANK Installer - Step 2: Detect Compatibility (PySide6)
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QTextEdit, QProgressBar, QPushButton
)
from PySide6.QtCore import Qt, QThread, Signal
from ui.theme import COLORS, FONTS, TIER_COLORS


class DetectThread(QThread):
    """Background thread for capability detection."""
    check_done = Signal(str, bool, str)  # label, passed, detail
    finished_ok = Signal(str, dict)  # recommended_tier, result_dict

    def __init__(self, adb, serial):
        super().__init__()
        self.adb = adb
        self.serial = serial

    def run(self):
        try:
            from core.detector import DeviceDetector, TIERS
            detector = DeviceDetector(self.adb)

            def callback(label, passed, detail):
                self.check_done.emit(label, passed, detail)

            result = detector.detect(self.serial, callback=callback)
            self.finished_ok.emit(result.recommended_tier, result.to_dict())
        except Exception as e:
            self.check_done.emit("Erro", False, str(e))


class StepDetect(QWidget):
    """Step 2: Detect Compatibility."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._thread = None
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Title
        title = QLabel("Detectar Compatibilidade")
        title.setObjectName("title")
        layout.addWidget(title)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(8)
        layout.addWidget(self.progress)

        # Log area
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(200)
        layout.addWidget(self.log)

        # Re-run button
        self.rerun_btn = QPushButton("Executar novamente")
        self.rerun_btn.setFixedWidth(180)
        self.rerun_btn.clicked.connect(self._start_detection)
        self.rerun_btn.hide()
        layout.addWidget(self.rerun_btn, alignment=Qt.AlignLeft)

        # Tier recommendation card (hidden initially)
        self.tier_frame = QFrame()
        self.tier_frame.setObjectName("card")
        tier_layout = QVBoxLayout(self.tier_frame)
        tier_layout.setContentsMargins(16, 16, 16, 16)

        self.tier_label = QLabel("Modo recomendado")
        self.tier_label.setObjectName("subtitle")
        tier_layout.addWidget(self.tier_label)

        self.tier_name = QLabel("")
        self.tier_name.setObjectName("title")
        tier_layout.addWidget(self.tier_name)

        self.tier_desc = QLabel("")
        self.tier_desc.setObjectName("subtitle")
        tier_layout.addWidget(self.tier_desc)

        self.tier_frame.hide()
        layout.addWidget(self.tier_frame)

        layout.addStretch()

    def _add_log(self, label, passed, detail):
        icon = "\u2713" if passed else "\u2717"
        color = COLORS["success"] if passed else COLORS["error"]
        self.log.append(f"<span style='color:{color}'>{icon}</span> {label}: {detail}")

    def _on_check(self, label, passed, detail):
        self._add_log(label, passed, detail)
        # Update progress
        lines = self.log.toPlainText().count("\n") + 1
        self.progress.setValue(min(lines * 15, 90))

    def _on_finished(self, tier, result_dict=None):
        from ui.theme import TIER_COLORS
        self.progress.setValue(100)
        self.app.recommended_tier = tier

        # Store result for later use
        if result_dict:
            self.app._detection_result = result_dict

        # Cache the result
        if result_dict and self.app.device_data:
            from core.cache import save_detection
            save_detection(self.app.device_data.serial, result_dict)

        tier_info = {
            "isolated": ("Isolated", "NETNS + PIDNS + Overlay"),
            "shared_network": ("Shared Network", "PIDNS + Overlay (host network)"),
            "shared_host": ("Shared Host", "Chroot apenas"),
            "native_host": ("Native Host", "Sem containerizacao"),
            "lite": ("Lite", "PRoot userspace (sem root)"),
        }
        name, desc = tier_info.get(tier, (tier, ""))

        # Add root manager info if available
        if hasattr(self.app, '_detection_result') and self.app._detection_result:
            result = self.app._detection_result
            if result.root_manager:
                desc += f" ({result.root_manager})"
            if result.has_termux:
                desc += " [Termux]"

        self.tier_name.setText(f"{name}")
        self.tier_name.setStyleSheet(f"color: {TIER_COLORS.get(tier, '#fff')}; font-size: 18px; font-weight: bold;")
        self.tier_desc.setText(desc)
        self.tier_frame.show()
        self.rerun_btn.show()
        self.app._update_buttons()

    def _start_detection(self):
        """Start compatibility detection."""
        self.log.clear()
        self.progress.setValue(0)
        self.tier_frame.hide()
        self.rerun_btn.hide()
        self.app.recommended_tier = None
        self.app._update_buttons()

        device = self.app.device_data
        if not device:
            self._add_log("Erro", False, "Nenhum dispositivo selecionado")
            return

        try:
            from core.adb import ADB
            adb = ADB()
            self._thread = DetectThread(adb, device.serial)
            self._thread.check_done.connect(self._on_check)
            self._thread.finished_ok.connect(self._on_finished)
            self._thread.start()
        except Exception as e:
            self._add_log("Erro", False, str(e))

    def on_show(self):
        """Check cache first, then run detection if needed."""
        self.log.clear()
        self.progress.setValue(100)
        self.tier_frame.hide()
        self.rerun_btn.hide()

        device = self.app.device_data
        if not device:
            self._add_log("Erro", False, "Nenhum dispositivo selecionado")
            return

        # Check cache
        from core.cache import load_detection
        cached = load_detection(device.serial)
        if cached:
            self._add_log("Cache", True, "Resultados anteriores encontrados")
            self.app.recommended_tier = cached.get("recommended_tier", "lite")
            self._on_finished(self.app.recommended_tier, cached)
            return

        # No cache, run detection
        self._start_detection()

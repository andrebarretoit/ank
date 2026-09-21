"""
ANK Installer - Mode Selector (PySide6)
Initial screen: choose what to do.
Auto-detects connected device via ADB and switches between
fresh-install modes and installed-device modes.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QThread
from ui.theme import COLORS, MODES, MODES_INSTALLED, apply_glass_shadow


class _DeviceDetectThread(QThread):
    """Quick ADB scan for a connected device — retries a few times."""
    found = Signal(bool)  # True = ANK installed

    def __init__(self, adb, parent=None, retries=5, delay=2):
        super().__init__(parent)
        self.adb = adb
        self.retries = retries
        self.delay = delay
        self._device = None

    def run(self):
        import time
        for attempt in range(self.retries):
            try:
                devices = self.adb.devices()
                if devices:
                    device = devices[0]
                    model = self.adb.get_model(device.serial)
                    is_rooted = self.adb.check_root(device.serial)
                    device.model = model
                    device.is_rooted = is_rooted
                    self._device = device

                    output, _ = self.adb.shell(device.serial,
                        "ls /data/local/ank/mode /data/local/tmp/ank/mode 2>/dev/null")
                    ank_installed = bool(output and "mode" in output)
                    self.found.emit(ank_installed)
                    return
            except Exception:
                pass
            time.sleep(self.delay)
        self.found.emit(False)


class ModeCard(QFrame):
    """A single clickable card describing one installer mode."""

    clicked = Signal(str)

    def __init__(self, mode: dict, parent=None):
        super().__init__(parent)
        self.mode_key = mode["key"]
        self.setObjectName("mode-card")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(6)

        icon = QLabel(mode["icon"])
        icon.setObjectName("mode-card-icon")
        if mode.get("danger"):
            icon.setStyleSheet(f"color: {COLORS['danger']};")
        layout.addWidget(icon)

        layout.addSpacing(6)

        title = QLabel(mode["title"])
        title.setObjectName("mode-card-title")
        if mode.get("danger"):
            title.setStyleSheet(f"color: {COLORS['danger']};")
        layout.addWidget(title)

        subtitle = QLabel(mode["subtitle"])
        subtitle.setObjectName("mode-card-subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addSpacing(4)

        desc = QLabel(mode["desc"])
        desc.setObjectName("mode-card-desc")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addStretch()

        apply_glass_shadow(self, blur=24, alpha=110, y_offset=4)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.clicked.emit(self.mode_key)


class StepModeSelect(QWidget):
    """Initial screen: pick what kind of operation to run.
    Auto-detects device on show and switches modes accordingly."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._cards = []
        self._detect_thread = None
        self._create_ui()

    def _create_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(14)

        self._title = QLabel("ANK Installer")
        self._title.setObjectName("title")
        self._layout.addWidget(self._title)

        self._subtitle = QLabel("What would you like to do?")
        self._subtitle.setObjectName("subtitle")
        self._layout.addWidget(self._subtitle)

        self._layout.addSpacing(4)

        # Card containers (two rows)
        self._grid_row1 = QHBoxLayout()
        self._grid_row1.setSpacing(16)
        self._grid_row2 = QHBoxLayout()
        self._grid_row2.setSpacing(16)

        self._layout.addLayout(self._grid_row1)
        self._layout.addLayout(self._grid_row2)
        self._layout.addStretch()

    def _build_cards(self, modes):
        """Clear and rebuild mode cards from a mode list."""
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        while self._grid_row1.count():
            item = self._grid_row1.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        while self._grid_row2.count():
            item = self._grid_row2.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, mode in enumerate(modes):
            card = ModeCard(mode)
            card.clicked.connect(self._on_card_clicked)
            self._cards.append(card)
            if len(modes) <= 4:
                (self._grid_row1 if i < 2 else self._grid_row2).addWidget(card)
            else:
                (self._grid_row1 if i < 3 else self._grid_row2).addWidget(card)

    def on_show(self):
        """Called when this step becomes visible.
        If a device is already known, use its state.
        Otherwise, kick off a quick ADB scan in the background."""
        # If device already detected (e.g. going back from connect step)
        if self.app.device_data:
            ank_installed = self.app.check_ank_installed()
            self._apply_mode(ank_installed)
            return

        # No device yet — show default cards immediately, detect in background
        self._apply_mode(False)
        self._start_detect()

    def _start_detect(self):
        """Start background ADB scan, retry a few times for device to appear."""
        try:
            from core.adb import ADB
            adb = ADB()
            self._detect_thread = _DeviceDetectThread(adb, self, retries=5, delay=2)
            self._detect_thread.found.connect(self._on_detect_done)
            self._detect_thread.start()
        except Exception:
            pass

    def _on_detect_done(self, ank_installed):
        """Called when background ADB scan finishes."""
        thread = self._detect_thread
        if thread and hasattr(thread, '_device'):
            device = thread._device
            self.app.device_data = device
            self.app.device_label.setText(f"Device: {device.model}")
            self.app.check_ank_installed()
        self._detect_thread = None
        self._apply_mode(ank_installed)

    def _apply_mode(self, ank_installed):
        """Switch between fresh-install and installed-device cards."""
        if ank_installed:
            self._subtitle.setText("ANK is installed on this device")
            self._build_cards(MODES_INSTALLED)
        else:
            self._subtitle.setText("What would you like to do?")
            self._build_cards(MODES)

    def _on_card_clicked(self, mode_key):
        self.app.select_mode(mode_key)

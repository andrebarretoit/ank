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
    """ADB scan for a connected device — keeps looking FOREVER until one
    shows up (no timeout): cold adb server start / first-run ADB download /
    authorization prompt can all delay the first listing arbitrarily. The
    scan is stopped when the user leaves this screen or the app closes."""
    found = Signal(bool)  # True = ANK installed

    def __init__(self, adb, parent=None, delay=2):
        super().__init__(parent)
        self.adb = adb
        self.delay = delay
        self._device = None
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        import time
        while not self._stop:
            try:
                devices = self.adb.devices()
            except Exception:
                devices = []
            if devices:
                device = devices[0]
                # Per-call guards: a slow get_model/check_root/shell must not
                # throw away an attempt where the device was already listed.
                try:
                    device.model = self.adb.get_model(device.serial)
                except Exception:
                    device.model = device.serial
                try:
                    device.is_rooted = self.adb.check_root(device.serial)
                except Exception:
                    device.is_rooted = None
                self._device = device
                ank_installed = False
                try:
                    output, _ = self.adb.shell(device.serial,
                        "ls /data/local/ank/mode /data/local/tmp/ank/mode 2>/dev/null")
                    ank_installed = bool(output and "mode" in output)
                except Exception:
                    pass
                self.found.emit(ank_installed)
                return
            time.sleep(self.delay)


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
        """Start background ADB scan. Any previous scan is stopped first so
        a stale result can't overwrite a newer one (on_show fires again on
        every Back navigation)."""
        prev = getattr(self, "_detect_thread", None)
        if prev is not None:
            try:
                prev.stop()
            except Exception:
                pass
            self._detect_thread = None
        try:
            from core.adb import ADB
            adb = ADB()
            thread = _DeviceDetectThread(adb, self)
            # lambda binds the thread so late/stale results can be discarded
            thread.found.connect(lambda ok, th=thread: self._on_detect_done(th, ok))
            self._detect_thread = thread
            thread.start()
        except Exception:
            pass

    def _on_detect_done(self, thread, ank_installed):
        """Called when a background ADB scan finishes."""
        if thread is not self._detect_thread:
            return  # superseded by a newer scan — ignore stale result
        self._detect_thread = None
        device = getattr(thread, "_device", None)
        if device is not None:
            self.app.device_data = device
            self.app.device_label.setText(f"Device: {device.model}")
            self.app.check_ank_installed()
        self._apply_mode(ank_installed if device is not None else False)

    def stop_detect(self):
        """Stop a running scan (leaving this screen / app closing)."""
        thread = getattr(self, "_detect_thread", None)
        if thread is not None:
            try:
                thread.stop()
            except Exception:
                pass
            self._detect_thread = None

    def _apply_mode(self, ank_installed):
        """Switch between fresh-install and installed-device cards."""
        if ank_installed:
            self._subtitle.setText("ANK is installed on this device")
            self._build_cards(MODES_INSTALLED)
        else:
            self._subtitle.setText("What would you like to do?")
            self._build_cards(MODES)

    def _on_card_clicked(self, mode_key):
        self.stop_detect()
        self.app.select_mode(mode_key)

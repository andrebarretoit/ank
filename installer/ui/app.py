"""
ANK Installer - Main Window (PySide6)

The window now starts on a mode-selector screen (Install / Restore / Clone /
Migrate). Once a mode is picked, a step flow specific to that mode runs in
the same sidebar + content + bottom-bar shell used by the original
installer. Step widgets are created once and reused across modes where it
makes sense (Confirm, Reboot, Done, ...).
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QStackedWidget
)
from PySide6.QtCore import Qt
from ui.theme import (
    COLORS, FONTS, WINDOW_WIDTH, WINDOW_HEIGHT, SIDEBAR_WIDTH,
    BOTTOM_BAR_HEIGHT, PADDING, STEPS_BY_MODE, STYLESHEET, TIER_COLORS
)
from ui.step_mode_select import StepModeSelect
from ui.step_connect import StepConnect
from ui.step_detect import StepDetect
from ui.step_confirm import StepConfirm
from ui.step_install import StepInstall
from ui.step_reboot import StepReboot
from ui.step_done import StepDone
from ui.step_restore import StepRestoreSelect, StepRestoreProgress
from ui.step_clone import StepCloneConnect, StepCloneProgress
from ui.step_migrate import StepMigrateOptions
from ui.step_manager import StepManager
from core.adb import ADB

# Ordered list of (key, StepClass) for every step widget that can appear in
# any flow. Widgets are instantiated once and reused by index.
WIDGET_SPECS = [
    ("connect", StepConnect),
    ("detect", StepDetect),
    ("confirm", StepConfirm),
    ("install", StepInstall),
    ("reboot", StepReboot),
    ("done", StepDone),
    ("restore_select", StepRestoreSelect),
    ("restore_progress", StepRestoreProgress),
    ("clone_connect", StepCloneConnect),
    ("clone_progress", StepCloneProgress),
    ("migrate_options", StepMigrateOptions),
    ("manager", StepManager),
]

# Which widget keys make up each mode's flow, in order.
MODE_FLOWS = {
    "install": ["connect", "detect", "confirm", "install", "reboot", "done"],
    "restore": ["connect", "restore_select", "confirm", "restore_progress", "reboot", "done"],
    "clone": ["clone_connect", "confirm", "clone_progress", "reboot", "done"],
    "migrate": ["clone_connect", "migrate_options", "confirm", "clone_progress", "reboot", "done"],
    "uninstall": ["connect", "confirm", "install", "done"],
    "reinstall": ["connect", "confirm", "install", "reboot", "done"],
    "export": ["connect", "confirm", "install", "done"],
    "restore_engine": ["connect", "restore_select", "confirm", "restore_progress", "reboot", "done"],
}

# key -> (complete_attr, failed_attr, running_label)
PROGRESS_KEYS = {
    "install": ("install_complete", "install_failed", "Installing..."),
    "restore_progress": ("restore_complete", "restore_failed", "Restoring..."),
    "clone_progress": ("clone_complete", "clone_failed", None),  # label depends on mode
}

CONFIRM_NEXT_LABEL = {
    "install": "\u25b6 Install",
    "restore": "\u25b6 Restore",
    "clone": "\u25b6 Clone",
    "migrate": "\u25b6 Migrate",
    "uninstall": "\u2716 Uninstall",
    "reinstall": "\u25b6 Reinstall",
    "export": "\u25b6 Export",
    "restore_engine": "\u25b6 Restore",
}


class InstallerWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ANK Installer v2.0")
        self.setMinimumSize(980, 640)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setStyleSheet(STYLESHEET)

        # ---- Shared / mode-agnostic state ----
        self.mode = None
        self.current_step = 0  # index into MODE_FLOWS[self.mode]

        self.device_data = None
        self.detection_result = None
        self._detection_result = None
        self.recommended_tier = None
        self.install_mode = "native"  # "native" or "ank_ui"
        self.install_complete = False
        self.install_failed = False
        self.reboot_complete = False
        self.device_ip = None
        self._came_from_step3 = False

        # ---- Restore-specific state ----
        self.restore_file_path = None
        self.restore_complete = False
        self.restore_failed = False

        # ---- Clone / Migrate-specific state ----
        self.source_device = None
        self.target_device = None
        self.clone_complete = False
        self.clone_failed = False
        self.migrate_keep_network = True
        self.migrate_remap_ports = False
        self.migrate_server_port = 8001
        self.migrate_container_selection = None  # None = all containers

        self._adb = ADB()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # SIDEBAR
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(SIDEBAR_WIDTH)
        main_layout.addWidget(self.sidebar)

        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(20, 24, 20, 20)
        sidebar_layout.setSpacing(0)

        logo_row = QHBoxLayout()
        logo_row.setSpacing(8)
        logo_mark = QLabel("\u25c8")
        logo_mark.setObjectName("logo-mark")
        logo_row.addWidget(logo_mark)
        logo = QLabel("ANK")
        logo.setObjectName("logo-label")
        logo_row.addWidget(logo)
        logo_row.addStretch()
        sidebar_layout.addLayout(logo_row)

        sub = QLabel("Installer v2.0")
        sub.setObjectName("logo-sub")
        sidebar_layout.addWidget(sub)
        sidebar_layout.addSpacing(28)

        # Build the maximum number of step rows any flow needs; rows beyond
        # the active flow's length are hidden per-mode.
        max_steps = max(len(v) for v in STEPS_BY_MODE.values())
        self.step_widgets = []
        self.step_rows = []
        for i in range(max_steps):
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = QLabel("\u25cf")
            dot.setObjectName("step-dot")
            dot.setFixedWidth(16)
            row.addWidget(dot)
            lbl = QLabel("")
            lbl.setObjectName("step-label")
            row.addWidget(lbl)
            row.addStretch()
            w = QWidget()
            w.setLayout(row)
            sidebar_layout.addWidget(w)
            sidebar_layout.addSpacing(4)
            self.step_widgets.append({"dot": dot, "label": lbl})
            self.step_rows.append(w)

        sidebar_layout.addStretch()

        # ANK Manager button (hidden by default, shown when ANK is installed)
        self.ank_manager_btn = QPushButton("  ANK Manager")
        self.ank_manager_btn.setObjectName("ank-manager-btn")
        self.ank_manager_btn.setFixedHeight(40)
        self.ank_manager_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(34, 197, 94, 0.1);
                color: {COLORS['success']};
                border: 1px solid rgba(34, 197, 94, 0.3);
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 600;
                text-align: left;
            }}
            QPushButton:hover {{
                background: rgba(34, 197, 94, 0.2);
                border-color: {COLORS['success']};
            }}
        """)
        self.ank_manager_btn.clicked.connect(self._show_manager)
        self.ank_manager_btn.hide()
        sidebar_layout.addWidget(self.ank_manager_btn)

        self.device_label = QLabel("Device: --")
        self.device_label.setObjectName("device-info")
        sidebar_layout.addWidget(self.device_label)

        self.mode_label = QLabel("Mode: --")
        self.mode_label.setObjectName("device-info")
        sidebar_layout.addWidget(self.mode_label)

        # RIGHT SIDE
        right = QWidget()
        right.setObjectName("content-area")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        main_layout.addWidget(right, 1)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)

        # Page 0: mode selector (always first, not part of a numbered flow)
        mode_select_page = QWidget()
        mode_select_layout = QVBoxLayout(mode_select_page)
        mode_select_layout.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
        self.mode_select_widget = StepModeSelect(mode_select_page, self)
        mode_select_layout.addWidget(self.mode_select_widget)
        self.stack.addWidget(mode_select_page)
        self.MODE_SELECT_PAGE_INDEX = 0

        # Remaining pages: one per unique step widget key
        self.widgets = {}
        self._page_index = {}
        for key, StepClass in WIDGET_SPECS:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
            widget = StepClass(page, self)
            layout.addWidget(widget)
            self.stack.addWidget(page)
            self.widgets[key] = widget
            self._page_index[key] = self.stack.count() - 1

        # BOTTOM BAR
        self.bottom = QFrame()
        self.bottom.setObjectName("bottom-bar")
        self.bottom.setFixedHeight(BOTTOM_BAR_HEIGHT)
        bottom_layout = QHBoxLayout(self.bottom)
        bottom_layout.setContentsMargins(24, 0, 24, 0)

        self.btn_back = QPushButton("\u2190 Back")
        self.btn_back.setObjectName("btn-back")
        self.btn_back.setFixedWidth(150)
        self.btn_back.clicked.connect(self._on_back)
        bottom_layout.addWidget(self.btn_back)

        bottom_layout.addStretch()

        self.btn_next = QPushButton("Continue \u2192")
        self.btn_next.setObjectName("btn-next")
        self.btn_next.setFixedWidth(150)
        self.btn_next.clicked.connect(self._on_next)
        bottom_layout.addWidget(self.btn_next)

        right_layout.addWidget(self.bottom)

        self.show_mode_select()

    # ------------------------------------------------------------------
    # Mode selection
    # ------------------------------------------------------------------
    def show_mode_select(self):
        """Return to the initial mode-selector screen and reset run state."""
        self.mode = None
        self.current_step = 0

        self.device_data = None
        self.recommended_tier = None
        self._detection_result = None
        self.install_complete = False
        self.install_failed = False
        self.reboot_complete = False
        self.device_ip = None

        self.restore_file_path = None
        self.restore_complete = False
        self.restore_failed = False

        self.source_device = None
        self.target_device = None
        self.clone_complete = False
        self.clone_failed = False

        self.device_label.setText("Device: --")
        self.mode_label.setText("Mode: --")

        self.bottom.hide()
        self.ank_manager_btn.hide()
        for row in self.step_rows:
            row.hide()
        self.stack.setCurrentIndex(self.MODE_SELECT_PAGE_INDEX)
        self.mode_select_widget.on_show()

    def select_mode(self, mode_key):
        """Called by the mode-selector screen when a card is clicked."""
        if mode_key not in MODE_FLOWS:
            return
        self.mode = mode_key
        self.mode_label.setText(f"Mode: {mode_key.capitalize()}")
        self.bottom.show()

        labels = STEPS_BY_MODE[mode_key]
        for i, row in enumerate(self.step_rows):
            if i < len(labels):
                self.step_widgets[i]["label"].setText(labels[i])
                row.show()
            else:
                row.hide()

        # If device is already known (auto-detected on mode selector),
        # skip the connect/clone_connect step and jump to the next one.
        flow = MODE_FLOWS[mode_key]
        start = 0
        if self.device_data and flow[0] in ("connect", "clone_connect"):
            start = 1

        self.show_step(start)

    # ------------------------------------------------------------------
    # ANK Manager
    # ------------------------------------------------------------------
    def check_ank_installed(self):
        """Check if ANK is installed on the connected device and show manager button."""
        device = self.device_data
        if not device:
            self.ank_manager_btn.hide()
            return False

        try:
            output, _ = self._adb.shell(device.serial,
                "ls /data/local/ank/ankfs/usr/bin/python3 /data/local/ank/mode 2>/dev/null")
            if output and "python3" in output:
                self.ank_manager_btn.show()
                return True
        except Exception:
            pass
        self.ank_manager_btn.hide()
        return False

    def _show_manager(self):
        """Switch to ANK Manager view."""
        self.mode = "manager"
        self.bottom.hide()
        for row in self.step_rows:
            row.hide()
        self.device_label.setText(f"Device: {self.device_data.model if self.device_data else '--'}")
        self.mode_label.setText("Mode: Manager")
        self.stack.setCurrentIndex(self._page_index["manager"])
        widget = self.widgets.get("manager")
        if widget and hasattr(widget, "on_show"):
            widget.on_show()

    # ------------------------------------------------------------------
    # Step flow
    # ------------------------------------------------------------------
    def _flow(self):
        return MODE_FLOWS.get(self.mode, [])

    def _current_key(self):
        flow = self._flow()
        if 0 <= self.current_step < len(flow):
            return flow[self.current_step]
        return None

    def show_step(self, index):
        flow = self._flow()
        if index < 0 or index >= len(flow):
            return

        self.current_step = index
        key = flow[index]
        self.stack.setCurrentIndex(self._page_index[key])

        for i, sw in enumerate(self.step_widgets):
            if i >= len(flow):
                continue
            if i < index:
                sw["dot"].setStyleSheet(f"color: {COLORS['success']}; font-size: 10px;")
                sw["label"].setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
            elif i == index:
                sw["dot"].setStyleSheet(f"color: {COLORS['accent']}; font-size: 10px;")
                sw["label"].setStyleSheet(f"color: {COLORS['text']}; font-size: 12px; font-weight: bold;")
            else:
                sw["dot"].setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 10px;")
                sw["label"].setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")

        self._update_buttons()

        widget = self.widgets.get(key)
        if widget is not None and hasattr(widget, "on_show"):
            widget.on_show()

    def _update_buttons(self):
        key = self._current_key()
        if key is None:
            return
        idx = self.current_step
        flow = self._flow()

        # ---- Back button ----
        if key in PROGRESS_KEYS:
            complete_attr, failed_attr, _ = PROGRESS_KEYS[key]
            if getattr(self, failed_attr):
                self.btn_back.setText("\u2190 Exit")
                self.btn_back.setEnabled(True)
            else:
                self.btn_back.setText("\u2190 Back")
                self.btn_back.setEnabled(False)
        elif key in ("reboot", "done"):
            self.btn_back.setText("\u2190 Back")
            self.btn_back.setEnabled(False)
        elif idx == 0:
            self.btn_back.setText("\u2190 Mode Select")
            self.btn_back.setEnabled(True)
        else:
            self.btn_back.setText("\u2190 Back")
            self.btn_back.setEnabled(True)

        # ---- Next button ----
        if key == "connect":
            self.btn_next.setText("Continue \u2192")
            self.btn_next.setEnabled(self.device_data is not None)
        elif key == "clone_connect":
            self.btn_next.setText("Continue \u2192")
            ready = (
                self.source_device is not None and self.target_device is not None
                and self.source_device.serial != self.target_device.serial
            )
            self.btn_next.setEnabled(ready)
        elif key == "detect":
            self.btn_next.setText("Continue \u2192")
            self.btn_next.setEnabled(self.recommended_tier is not None)
        elif key == "restore_select":
            self.btn_next.setText("Continue \u2192")
            self.btn_next.setEnabled(self.restore_file_path is not None)
        elif key == "migrate_options":
            self.btn_next.setText("Continue \u2192")
            self.btn_next.setEnabled(True)
        elif key == "confirm":
            self.btn_next.setText(CONFIRM_NEXT_LABEL.get(self.mode, "\u25b6 Continue"))
            self.btn_next.setEnabled(True)
        elif key in PROGRESS_KEYS:
            complete_attr, failed_attr, running_label = PROGRESS_KEYS[key]
            if running_label is None:
                running_label = "Cloning..." if self.mode == "clone" else "Migrating..."
            if getattr(self, complete_attr):
                self.btn_next.setText("Continue \u2192")
                self.btn_next.setEnabled(True)
            elif getattr(self, failed_attr):
                self.btn_next.setText("\u2717 Failed")
                self.btn_next.setEnabled(False)
            else:
                self.btn_next.setText(running_label)
                self.btn_next.setEnabled(False)
        elif key == "reboot":
            self.btn_next.setText("Please wait...")
            self.btn_next.setEnabled(False)
        elif key == "done":
            self.btn_next.setText("\u2713 Finish")
            self.btn_next.setEnabled(True)

    def _on_back(self):
        key = self._current_key()

        if key in PROGRESS_KEYS:
            _, failed_attr, _ = PROGRESS_KEYS[key]
            if getattr(self, failed_attr):
                self.close()
            return

        if key in ("reboot", "done"):
            if key == "done" and self.mode in ("uninstall", "reinstall", "export"):
                self.show_mode_select()
            return

        if self.current_step == 0:
            self.show_mode_select()
            return

        if self.mode == "install" and self._current_key() == "confirm":
            self._came_from_step3 = True

        self.show_step(self.current_step - 1)

    def _on_next(self):
        key = self._current_key()

        if key == "done":
            self.close()
            return

        if key == "connect" and not self.device_data:
            return
        if key == "clone_connect":
            if not (self.source_device and self.target_device):
                return
            if self.source_device.serial == self.target_device.serial:
                return
        if key == "detect" and not self.recommended_tier:
            return
        if key == "restore_select" and not self.restore_file_path:
            return

        self.show_step(self.current_step + 1)

    def update_device_info(self, model, mode):
        self.device_label.setText(f"Device: {model}")
        self.mode_label.setText(f"Mode: {mode}")

    def closeEvent(self, event):
        """Stop any background QThreads before the app tears widgets down,
        otherwise Qt can abort on a QThread destroyed while still running
        (e.g. an endless device-poll loop that never found a device)."""
        for widget in self.widgets.values():
            thread = getattr(widget, "_thread", None)
            if thread is not None and thread.isRunning():
                try:
                    if hasattr(thread, "stop"):
                        thread.stop()
                    else:
                        thread.quit()
                    thread.wait(2000)
                except Exception:
                    pass
        super().closeEvent(event)

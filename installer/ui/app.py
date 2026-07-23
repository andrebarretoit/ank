"""
ANK Installer - Main Window (PySide6)
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QStackedWidget
)
from PySide6.QtCore import Qt
from ui.theme import COLORS, FONTS, WINDOW_WIDTH, WINDOW_HEIGHT, SIDEBAR_WIDTH, BOTTOM_BAR_HEIGHT, PADDING, STEPS, STYLESHEET, TIER_COLORS
from ui.step_connect import StepConnect
from ui.step_detect import StepDetect
from ui.step_confirm import StepConfirm
from ui.step_install import StepInstall
from ui.step_reboot import StepReboot
from ui.step_done import StepDone


class InstallerWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ANK Installer v2.0")
        self.setMinimumSize(900, 600)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setStyleSheet(STYLESHEET)

        self.current_step = 0
        self.device_data = None
        self.detection_result = None
        self.recommended_tier = None
        self.install_complete = False
        self.install_failed = False
        self.reboot_complete = False
        self.device_ip = None

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
        sidebar_layout.setContentsMargins(16, 20, 16, 16)
        sidebar_layout.setSpacing(0)

        logo = QLabel("ANK")
        logo.setObjectName("logo-label")
        sidebar_layout.addWidget(logo)

        sub = QLabel("Installer v2.0")
        sub.setObjectName("logo-sub")
        sidebar_layout.addWidget(sub)
        sidebar_layout.addSpacing(30)

        self.step_widgets = []
        for i, name in enumerate(STEPS):
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = QLabel("\u25cf")
            dot.setObjectName("step-dot")
            dot.setFixedWidth(16)
            row.addWidget(dot)
            lbl = QLabel(name)
            lbl.setObjectName("step-label")
            row.addWidget(lbl)
            row.addStretch()
            w = QWidget()
            w.setLayout(row)
            sidebar_layout.addWidget(w)
            sidebar_layout.addSpacing(4)
            self.step_widgets.append({"dot": dot, "label": lbl})

        sidebar_layout.addStretch()

        self.device_label = QLabel("Device: --")
        self.device_label.setObjectName("device-info")
        sidebar_layout.addWidget(self.device_label)

        self.mode_label = QLabel("Mode: --")
        self.mode_label.setObjectName("device-info")
        sidebar_layout.addWidget(self.mode_label)

        # RIGHT SIDE
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        main_layout.addWidget(right, 1)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)

        step_classes = [StepConnect, StepDetect, StepConfirm, StepInstall, StepReboot, StepDone]
        self.step_pages = []
        for StepClass in step_classes:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
            widget = StepClass(page, self)
            layout.addWidget(widget)
            self.stack.addWidget(page)
            self.step_pages.append(page)

        # BOTTOM BAR
        bottom = QFrame()
        bottom.setObjectName("bottom-bar")
        bottom.setFixedHeight(BOTTOM_BAR_HEIGHT)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(20, 0, 20, 0)

        self.btn_back = QPushButton("\u2190 Voltar")
        self.btn_back.setObjectName("btn-back")
        self.btn_back.setFixedWidth(140)
        self.btn_back.clicked.connect(self._on_back)
        bottom_layout.addWidget(self.btn_back)

        bottom_layout.addStretch()

        self.btn_next = QPushButton("Prosseguir \u2192")
        self.btn_next.setObjectName("btn-next")
        self.btn_next.setFixedWidth(140)
        self.btn_next.clicked.connect(self._on_next)
        bottom_layout.addWidget(self.btn_next)

        right_layout.addWidget(bottom)

        self.show_step(0)

    def show_step(self, index):
        if index < 0 or index >= len(STEPS):
            return

        self.current_step = index
        self.stack.setCurrentIndex(index)

        for i, sw in enumerate(self.step_widgets):
            if i < index:
                sw["dot"].setStyleSheet(f"color: {COLORS['success']}; font-size: 10px;")
                sw["label"].setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
            elif i == index:
                sw["dot"].setStyleSheet(f"color: {COLORS['accent']}; font-size: 10px;")
                sw["label"].setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px; font-weight: bold;")
            else:
                sw["dot"].setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 10px;")
                sw["label"].setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")

        self._update_buttons()

        page = self.step_pages[index]
        for child in page.findChildren(QWidget):
            if hasattr(child, 'on_show'):
                child.on_show()
                break

    def _update_buttons(self):
        idx = self.current_step

        # Back: blocked after step 2 (confirm). Only exit on install fail.
        if self.install_failed and idx == 3:
            self.btn_back.setText("\u2190 Sair")
            self.btn_back.setEnabled(True)
        elif self.install_complete or self.reboot_complete or idx >= 3:
            self.btn_back.setText("\u2190 Voltar")
            self.btn_back.setEnabled(False)
        elif idx == 0:
            self.btn_back.setText("\u2190 Voltar")
            self.btn_back.setEnabled(False)
        elif idx == 1:
            self.btn_back.setText("\u2190 Voltar")
            self.btn_back.setEnabled(True)
        elif idx == 2:
            self.btn_back.setText("\u2190 Voltar")
            self.btn_back.setEnabled(True)
        else:
            self.btn_back.setText("\u2190 Voltar")
            self.btn_back.setEnabled(True)

        # Next
        if idx == 0:
            self.btn_next.setText("Prosseguir \u2192")
            self.btn_next.setEnabled(self.device_data is not None)
        elif idx == 1:
            self.btn_next.setText("Prosseguir \u2192")
            self.btn_next.setEnabled(self.recommended_tier is not None)
        elif idx == 2:
            self.btn_next.setText("\u25b6 Instalar")
            self.btn_next.setEnabled(True)
        elif idx == 3:
            if self.install_complete:
                self.btn_next.setText("Prosseguir \u2192")
                self.btn_next.setEnabled(True)
            elif self.install_failed:
                self.btn_next.setText("\u2717 Falhou")
                self.btn_next.setEnabled(False)
            else:
                self.btn_next.setText("Instalando...")
                self.btn_next.setEnabled(False)
        elif idx == 4:
            self.btn_next.setText("Aguarde...")
            self.btn_next.setEnabled(False)
        elif idx == 5:
            self.btn_next.setText("\u2713 Concluir")
            self.btn_next.setEnabled(True)

    def _on_back(self):
        if self.install_failed and self.current_step == 3:
            self.close()
            return
        if self.install_complete and self.current_step == 3:
            return
        if self.reboot_complete and self.current_step == 4:
            return
        if self.current_step > 0 and self.current_step <= 2:
            self.show_step(self.current_step - 1)

    def _on_next(self):
        if self.current_step == 5:
            self.close()
            return

        if self.current_step == 0 and not self.device_data:
            return
        if self.current_step == 1 and not self.recommended_tier:
            return

        self.show_step(self.current_step + 1)

    def update_device_info(self, model, mode):
        self.device_label.setText(f"Device: {model}")
        self.mode_label.setText(f"Mode: {mode}")

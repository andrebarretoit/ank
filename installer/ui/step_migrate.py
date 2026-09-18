"""
ANK Installer - Migrate Mode options (PySide6)
Runs between StepCloneConnect and Confirm in the "migrate" flow. The
actual data transfer + option application happens in
ui/step_clone.py::StepCloneProgress (shared with Clone mode).
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QCheckBox,
    QSpinBox, QListWidget, QListWidgetItem, QPushButton
)
from PySide6.QtCore import Qt, QThread, Signal
from ui.theme import COLORS

ANK_DIR = "/data/local/ank"


class ContainerListThread(QThread):
    """Lists container directories on the source device."""
    result = Signal(list)

    def __init__(self, adb, device):
        super().__init__()
        self.adb = adb
        self.device = device

    def run(self):
        try:
            rooted = bool(getattr(self.device, "is_rooted", False))
            shell = self.adb.shell_su if rooted else self.adb.shell
            out, code = shell(self.device.serial, f"ls {ANK_DIR}/containers 2>/dev/null")
            names = [line.strip() for line in (out or "").splitlines() if line.strip()]
            self.result.emit(names)
        except Exception:
            self.result.emit([])


class StepMigrateOptions(QWidget):
    """Step: Migration Options."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._thread = None
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Migration Options")
        title.setObjectName("title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Choose what should carry over from the old device to the new one."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Network configuration card
        net_card = QFrame()
        net_card.setObjectName("card")
        net_layout = QVBoxLayout(net_card)
        net_layout.setContentsMargins(16, 16, 16, 16)
        net_layout.setSpacing(8)

        self.keep_network_cb = QCheckBox("Keep network configuration")
        self.keep_network_cb.setChecked(True)
        self.keep_network_cb.toggled.connect(self._on_keep_network_toggled)
        net_layout.addWidget(self.keep_network_cb)

        net_desc = QLabel(
            "Keeps the server port and other network settings exactly as "
            "they were on the old device. Turn this off to reset them to "
            "ANK defaults on the new device."
        )
        net_desc.setObjectName("text-muted")
        net_desc.setWordWrap(True)
        net_layout.addWidget(net_desc)

        remap_row = QHBoxLayout()
        self.remap_cb = QCheckBox("Remap server port to:")
        self.remap_cb.toggled.connect(self._on_remap_toggled)
        remap_row.addWidget(self.remap_cb)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8001)
        self.port_spin.setEnabled(False)
        self.port_spin.valueChanged.connect(self._on_port_changed)
        remap_row.addWidget(self.port_spin)
        remap_row.addStretch()
        net_layout.addLayout(remap_row)

        layout.addWidget(net_card)

        # Container selection card
        containers_card = QFrame()
        containers_card.setObjectName("card")
        containers_layout = QVBoxLayout(containers_card)
        containers_layout.setContentsMargins(16, 16, 16, 16)
        containers_layout.setSpacing(8)

        containers_header = QHBoxLayout()
        containers_label = QLabel("Containers to migrate")
        containers_label.setObjectName("field-label")
        containers_header.addWidget(containers_label)
        containers_header.addStretch()

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setObjectName("btn-secondary")
        self.select_all_btn.setFixedWidth(90)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        containers_header.addWidget(self.select_all_btn)

        self.select_none_btn = QPushButton("Select None")
        self.select_none_btn.setObjectName("btn-secondary")
        self.select_none_btn.setFixedWidth(100)
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        containers_header.addWidget(self.select_none_btn)

        containers_layout.addLayout(containers_header)

        self.container_list = QListWidget()
        self.container_list.setMaximumHeight(160)
        self.container_list.itemChanged.connect(self._on_container_changed)
        containers_layout.addWidget(self.container_list)

        self.container_status = QLabel("")
        self.container_status.setObjectName("text-muted")
        containers_layout.addWidget(self.container_status)

        layout.addWidget(containers_card)
        layout.addStretch()

    # ------------------------------------------------------------------
    def _on_keep_network_toggled(self, checked):
        self.app.migrate_keep_network = checked

    def _on_remap_toggled(self, checked):
        self.app.migrate_remap_ports = checked
        self.port_spin.setEnabled(checked)

    def _on_port_changed(self, value):
        self.app.migrate_server_port = value

    def _set_all_checked(self, checked):
        self.container_list.blockSignals(True)
        for i in range(self.container_list.count()):
            item = self.container_list.item(i)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.container_list.blockSignals(False)
        self._recompute_selection()

    def _on_container_changed(self, _item):
        self._recompute_selection()

    def _recompute_selection(self):
        total = self.container_list.count()
        checked = []
        for i in range(total):
            item = self.container_list.item(i)
            if item.checkState() == Qt.Checked:
                checked.append(item.text())

        if total == 0:
            self.app.migrate_container_selection = None
        elif len(checked) == total:
            self.app.migrate_container_selection = None  # all = no filtering needed
        else:
            self.app.migrate_container_selection = checked

        self.container_status.setText(f"{len(checked)} of {total} container(s) selected")

    # ------------------------------------------------------------------
    def on_show(self):
        self.keep_network_cb.setChecked(self.app.migrate_keep_network)
        self.remap_cb.setChecked(self.app.migrate_remap_ports)
        self.port_spin.setValue(self.app.migrate_server_port)
        self.port_spin.setEnabled(self.app.migrate_remap_ports)

        self.container_list.clear()
        self.container_status.setText("Loading containers from the source device...")

        source = self.app.source_device
        if not source:
            self.container_status.setText("Connect a source device first.")
            return

        try:
            from core.adb import ADB
            adb = ADB()
            if self._thread is not None and self._thread.isRunning():
                self._thread.wait(5000)
            self._thread = ContainerListThread(adb, source)
            self._thread.result.connect(self._on_containers_loaded)
            self._thread.start()
        except Exception:
            self.container_status.setText("Could not list containers on the source device.")

    def _on_containers_loaded(self, names):
        self.container_list.clear()
        if not names:
            self.container_status.setText("No containers found on the source device.")
            return
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.container_list.addItem(item)
        self._recompute_selection()

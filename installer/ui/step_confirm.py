"""
ANK Installer - Step: Confirm (PySide6)
Shared by all four modes (Install / Restore / Clone / Migrate); the content
of the card and the summary text adapt to self.app.mode.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt
from ui.theme import COLORS, TIER_COLORS, TIER_NAMES


class StepConfirm(QWidget):
    """Step: Confirm the operation before it runs."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.title = QLabel("Confirm")
        self.title.setObjectName("title")
        layout.addWidget(self.title)

        # Info card
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(8)

        self.labels = {}
        fields = [
            ("device", "Device"),
            ("mode", "Mode"),
            ("root", "Root"),
            ("kernel", "Kernel"),
            ("storage", "Details"),
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
        mode = getattr(self.app, "mode", "install")
        if mode == "install":
            self._show_install()
        elif mode == "restore":
            self._show_restore()
        elif mode in ("clone", "migrate"):
            self._show_clone_or_migrate()
        elif mode == "uninstall":
            self._show_uninstall()
        elif mode == "reinstall":
            self._show_reinstall()
        elif mode == "export":
            self._show_export()
        elif mode == "restore_engine":
            self._show_restore()

    # ------------------------------------------------------------------
    def _show_install(self):
        self.title.setText("Confirm Installation")
        device = self.app.device_data
        tier = self.app.recommended_tier
        install_mode = getattr(self.app, 'install_mode', 'native')

        if device:
            model = getattr(device, 'model', 'Unknown') or 'Unknown'
            serial = device.serial
            root = "Yes" if getattr(device, 'is_rooted', False) else "No"
            kernel = getattr(device, 'kernel', '--') or '--'

            self.labels["device"].setText(f"Device: {model} ({serial})")
            self.labels["root"].setText(f"Root: {root}")
            self.labels["kernel"].setText(f"Kernel: {kernel}")

        tier_name = TIER_NAMES.get(tier, tier)
        color = TIER_COLORS.get(tier, "#fff")
        self.labels["mode"].setText(f"Mode: {tier_name}")
        self.labels["mode"].setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")

        is_rooted = device and getattr(device, 'is_rooted', False)

        if install_mode == "ank_ui":
            method = "Magisk module" if is_rooted else "PRoot/Termux"
            self.labels["storage"].setText("Installation: ANK UI (launcher)")
            self.desc_label.setText(
                "The installer will:\n"
                f"  1. Install the full ANK stack ({method})\n"
                "  2. Install the ANK Launcher\n"
                "  3. Set it as the default launcher\n"
                "  4. Reboot the device"
            )
        elif is_rooted:
            self.labels["storage"].setText("Storage: ~200MB (rootfs + containers)")
            self.desc_label.setText(
                "The installer will:\n"
                "  1. Install the full ANK stack (server + core + containers)\n"
                "  2. Configure services and network\n"
                "  3. Create the default container\n"
                "  4. Reboot the device"
            )
        else:
            self.labels["storage"].setText("Storage: ~150MB (rootfs + containers)")
            self.desc_label.setText(
                "The installer will:\n"
                "  1. Install PRoot/Termux on the device\n"
                "  2. Install the full ANK stack (server + core + containers)\n"
                "  3. Configure services and network\n"
                "  4. Create the default container"
            )

    # ------------------------------------------------------------------
    def _show_restore(self):
        self.title.setText("Confirm Restore")
        device = self.app.device_data
        backup = self.app.restore_file_path or "--"

        if device:
            model = getattr(device, 'model', 'Unknown') or 'Unknown'
            serial = device.serial
            root = "Yes" if getattr(device, 'is_rooted', False) else "No"
            kernel = getattr(device, 'kernel', '--') or '--'

            self.labels["device"].setText(f"Device: {model} ({serial})")
            self.labels["root"].setText(f"Root: {root}")
            self.labels["kernel"].setText(f"Kernel: {kernel}")

        self.labels["mode"].setText("Mode: Restore")
        self.labels["mode"].setStyleSheet(f"color: {COLORS['accent']}; font-size: 13px; font-weight: bold;")

        import os
        backup_name = os.path.basename(backup) if backup != "--" else "--"
        self.labels["storage"].setText(f"Backup file: {backup_name}")

        self.desc_label.setText(
            "The installer will:\n"
            "  1. Erase the existing ANK data on the device (if any)\n"
            "  2. Push and extract the .ankengine backup to /data/local/ank\n"
            "  3. Reboot the device\n\n"
            "\u26a0 This overwrites any current ANK installation on the target device."
        )

    # ------------------------------------------------------------------
    def _show_clone_or_migrate(self):
        mode = self.app.mode
        is_migrate = mode == "migrate"
        self.title.setText("Confirm Migration" if is_migrate else "Confirm Clone")

        source = self.app.source_device
        target = self.app.target_device

        if source:
            self.labels["device"].setText(
                f"Source: {getattr(source, 'model', source.serial)} ({source.serial})"
            )
        if target:
            self.labels["root"].setText(
                f"Target: {getattr(target, 'model', target.serial)} ({target.serial})"
            )
        if source:
            self.labels["kernel"].setText(
                f"Source root: {'Yes' if getattr(source, 'is_rooted', False) else 'No'}"
            )

        self.labels["mode"].setText(f"Mode: {'Migrate' if is_migrate else 'Clone'}")
        self.labels["mode"].setStyleSheet(f"color: {COLORS['accent']}; font-size: 13px; font-weight: bold;")

        if is_migrate:
            parts = []
            parts.append("keep network config" if self.app.migrate_keep_network else "reset network config")
            if self.app.migrate_remap_ports:
                parts.append(f"remap port -> {self.app.migrate_server_port}")
            if self.app.migrate_container_selection is not None:
                parts.append(f"{len(self.app.migrate_container_selection)} container(s) selected")
            else:
                parts.append("all containers")
            self.labels["storage"].setText("Options: " + ", ".join(parts))
        else:
            self.labels["storage"].setText("Options: full copy, no changes")

        self.desc_label.setText(
            "The installer will:\n"
            "  1. Export the ANK configuration from the source device\n"
            "  2. Erase the existing ANK data on the target device (if any)\n"
            "  3. Import the configuration onto the target device"
            + ("\n  4. Apply the migration options above" if is_migrate else "")
            + "\n  5. Reboot the target device\n\n"
            "\u26a0 This overwrites any current ANK installation on the target device."
        )

    # ------------------------------------------------------------------
    def _show_uninstall(self):
        self.title.setText("Confirm Uninstall")
        device = self.app.device_data

        if device:
            model = getattr(device, 'model', 'Unknown') or 'Unknown'
            serial = device.serial
            root = "Yes" if getattr(device, 'is_rooted', False) else "No"
            kernel = getattr(device, 'kernel', '--') or '--'

            self.labels["device"].setText(f"Device: {model} ({serial})")
            self.labels["root"].setText(f"Root: {root}")
            self.labels["kernel"].setText(f"Kernel: {kernel}")

        self.labels["mode"].setText("Mode: Uninstall")
        self.labels["mode"].setStyleSheet(f"color: {COLORS['danger']}; font-size: 13px; font-weight: bold;")
        self.labels["storage"].setText("This will remove everything")

        self.desc_label.setText(
            "\u26a0 WARNING: This will permanently delete:\n\n"
            "  \u2022  All ANK containers and their data\n"
            "  \u2022  All images and configurations\n"
            "  \u2022  The ANK server and all services\n"
            "  \u2022  All backups stored on the device\n"
            "  \u2022  Network rules and iptables entries\n\n"
            "This action cannot be undone."
        )
        self.desc_label.setStyleSheet(f"color: {COLORS['danger']}; font-size: 12px;")

    # ------------------------------------------------------------------
    def _show_reinstall(self):
        self.title.setText("Confirm Reinstall")
        device = self.app.device_data

        if device:
            model = getattr(device, 'model', 'Unknown') or 'Unknown'
            serial = device.serial
            root = "Yes" if getattr(device, 'is_rooted', False) else "No"
            kernel = getattr(device, 'kernel', '--') or '--'

            self.labels["device"].setText(f"Device: {model} ({serial})")
            self.labels["root"].setText(f"Root: {root}")
            self.labels["kernel"].setText(f"Kernel: {kernel}")

        self.labels["mode"].setText("Mode: Reinstall")
        self.labels["mode"].setStyleSheet(f"color: {COLORS['warning']}; font-size: 13px; font-weight: bold;")
        self.labels["storage"].setText("Removes current, installs fresh")

        self.desc_label.setText(
            "The installer will:\n"
            "  1. Remove the current ANK installation\n"
            "  2. Install a fresh copy of ANK\n"
            "  3. Reboot the device\n\n"
            "\u26a0 Container data will be lost."
        )

    # ------------------------------------------------------------------
    def _show_export(self):
        self.title.setText("Confirm Export")
        device = self.app.device_data

        if device:
            model = getattr(device, 'model', 'Unknown') or 'Unknown'
            serial = device.serial
            root = "Yes" if getattr(device, 'is_rooted', False) else "No"
            kernel = getattr(device, 'kernel', '--') or '--'

            self.labels["device"].setText(f"Device: {model} ({serial})")
            self.labels["root"].setText(f"Root: {root}")
            self.labels["kernel"].setText(f"Kernel: {kernel}")

        self.labels["mode"].setText("Mode: Export .ankengine")
        self.labels["mode"].setStyleSheet(f"color: {COLORS['success']}; font-size: 13px; font-weight: bold;")
        self.labels["storage"].setText("Creates a portable backup file")

        self.desc_label.setText(
            "The installer will:\n"
            "  1. Connect to the device and read the ANK configuration\n"
            "  2. Export containers, images, and server files\n"
            "  3. Create a portable .ankengine file\n"
            "  4. Save it to your Downloads folder\n\n"
            "The .ankengine file can be used to restore this setup on any device."
        )

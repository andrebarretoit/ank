#!/usr/bin/env python3
"""
ANK Installer - Main Entry Point
GUI installer for ANK (Android Konteiner)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QFile, QFileInfo
from PySide6.QtGui import QIcon
from ui.app import InstallerWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ANK Installer")
    app.setStyle("Fusion")

    # Set window icon
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base, "ANK.ico")
    if not os.path.isfile(icon_path):
        icon_path = os.path.join(os.path.dirname(base), "ANK.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = InstallerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

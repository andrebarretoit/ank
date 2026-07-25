"""
ANK Installer - Step 4: Installing (PySide6)
"""

import datetime
import os
import tempfile
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal
from ui.theme import COLORS


class InstallThread(QThread):
    """Background thread for installation."""
    progress = Signal(float, str)
    log = Signal(str)
    done = Signal(bool, str)
    retry_needed = Signal(str, str)  # url, error message

    def __init__(self, adb, serial, tier, app):
        super().__init__()
        self.adb = adb
        self.serial = serial
        self.tier = tier
        self.app = app

    def run(self):
        try:
            tier = self.app.recommended_tier
            if tier == "native_host":
                self._install_native()
            elif self.app.device_data and getattr(self.app.device_data, 'is_rooted', False):
                self._install_rooted()
            else:
                self._install_lite()
            self.done.emit(True, "Instalacao concluida!")
        except Exception as e:
            self.done.emit(False, str(e))

    def _install_native(self):
        from core.installer_native import NativeInstaller

        def callback(step, message, progress_val):
            self.progress.emit(progress_val, message)
            self.log.emit(message)

        installer = NativeInstaller(self.adb, self.serial, callback=callback)
        success = installer.install()
        if not success:
            raise Exception("Instalacao nativa falhou")

        # Install ANK UI APK if available
        import sys
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            exe_dir = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            exe_dir = os.path.join(base_path, "..")

        apk_candidates = [
            os.path.join(exe_dir, "ank-launcher.apk"),
            os.path.join(base_path, "ank-launcher.apk"),
        ]
        apk_path = None
        for c in apk_candidates:
            if os.path.isfile(c):
                apk_path = c
                break

        if apk_path:
            self.log.emit("Instalando ANK UI...")
            installer.install_ank_ui(apk_path)
        else:
            self.log.emit("ank-launcher.apk nao encontrado - ANK UI nao instalado")

    def _install_rooted(self):
        # 1. Find zip and ankcore from PyInstaller bundle or disk
        self.progress.emit(0.05, "Extraindo arquivos...")
        self.log.emit("Executando: Extraindo ank-magisk.zip...")

        import sys
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            exe_dir = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            exe_dir = os.path.join(base_path, "..")

        # Find ank-magisk.zip
        zip_candidates = [
            os.path.join(exe_dir, "ank-magisk.zip"),
            os.path.join(base_path, "ank-magisk.zip"),
        ]
        zip_path = None
        for c in zip_candidates:
            if os.path.isfile(c):
                zip_path = c
                break
        if not zip_path:
            raise Exception(f"ank-magisk.zip nao encontrado. Coloque ao lado do exe.")
        with open(zip_path, "rb") as f:
            zip_data = f.read()

        tmp_zip = os.path.join(tempfile.gettempdir(), "ank-magisk.zip")
        with open(tmp_zip, "wb") as f:
            f.write(zip_data)
        self.log.emit(f"OK: Zip extraido ({len(zip_data) // 1024}KB)")

        # 2. Push zip to device (ankcore tar.gz is bundled inside the zip)
        self.progress.emit(0.25, "Enviando modulo Magisk...")
        self.log.emit("Executando: Enviando ank-magisk.zip...")
        self.adb.push(self.serial, tmp_zip, "/sdcard/Download/ank-magisk.zip")
        self.log.emit("OK: Zip enviado")

        # 3. Install Magisk module (streaming output)
        self.progress.emit(0.5, "Instalando modulo Magisk...")
        self.log.emit("Executando: Instalando modulo Magisk...")
        self.log.emit("(pode demorar - instalando rootfs + templates...)")

        def on_install_line(line):
            if line.strip():
                self.log.emit(line)

        code = self.adb.shell_su_streaming(
            self.serial,
            "magisk --install-module /sdcard/Download/ank-magisk.zip",
            on_install_line,
            timeout=600
        )

        # Check for failure
        if code != 0:
            # Fetch install log from device
            self.log.emit("\n--- Log de instalacao do device ---")
            log_out, _ = self.adb.shell(self.serial, "cat /data/local/ank/logs/install.log 2>/dev/null || cat /sdcard/AndroidKonteiner/logs/install.log 2>/dev/null")
            if log_out:
                self.log.emit(log_out)
            self.log.emit("--- Fim do log ---\n")
            raise Exception("Instalacao do modulo Magisk falhou")

        self.log.emit("OK: Modulo instalado")

        # 4. Verify installation
        self.progress.emit(0.8, "Verificando instalacao...")
        check, _ = self.adb.shell(self.serial, "ls /data/local/ank/ankfs/usr/bin/python3 2>/dev/null")
        if not check or "python3" not in check:
            self.log.emit("\n--- Log de instalacao do device ---")
            log_out, _ = self.adb.shell(self.serial, "cat /data/local/ank/logs/install.log 2>/dev/null || cat /sdcard/AndroidKonteiner/logs/install.log 2>/dev/null")
            if log_out:
                self.log.emit(log_out)
            self.log.emit("--- Fim do log ---\n")
            raise Exception("Python3 nao foi instalado. Verifique o log acima.")

        self.log.emit("OK: Servicos configurados")

        self.progress.emit(0.95, "Limpando arquivos temporarios...")
        self.log.emit("Limpando arquivos temporarios do device...")
        self.adb.shell(self.serial, "rm -f /sdcard/Download/ank-magisk.zip 2>/dev/null")
        self.log.emit("OK: Limpeza concluida")

        self.progress.emit(1.0, "Finalizado!")
        self.log.emit("Instalacao concluida com sucesso!")

    def _install_lite(self):
        import threading
        from core.installer_lite import LiteInstaller

        self._retry_event = None
        self._retry_result = False

        def callback(step, message, progress_val):
            self.progress.emit(progress_val, message)
            self.log.emit(message)

        def retry_callback(url, error):
            self._retry_event = threading.Event()
            self._retry_result = False
            self.retry_needed.emit(url, error)
            self._retry_event.wait()
            return self._retry_result

        installer = LiteInstaller(self.adb, self.serial, callback=callback, retry_callback=retry_callback)
        success = installer.install()
        if not success:
            raise Exception("Instalacao Lite falhou")


class StepInstall(QWidget):
    """Step 4: Installing."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._thread = None
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Instalacao")
        title.setObjectName("title")
        layout.addWidget(title)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(10)
        layout.addWidget(self.progress)

        self.progress_label = QLabel("0%")
        self.progress_label.setObjectName("text-muted")
        layout.addWidget(self.progress_label)

        self.status = QLabel("Executando...")
        self.status.setObjectName("subtitle")
        layout.addWidget(self.status)

        log_label = QLabel("Logs")
        log_label.setObjectName("text-muted")
        layout.addWidget(log_label)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

    def _add_log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")

    def on_show(self):
        self.progress.setValue(0)
        self.progress_label.setText("0%")
        self.log.clear()

        device = self.app.device_data
        if not device:
            self._add_log("Erro: nenhum dispositivo selecionado")
            return

        try:
            from core.adb import ADB
            adb = ADB()
            tier = self.app.recommended_tier

            self._thread = InstallThread(adb, device.serial, tier, self.app)
            self._thread.progress.connect(self._on_progress)
            self._thread.log.connect(self._add_log)
            self._thread.done.connect(self._on_done)
            self._thread.retry_needed.connect(self._on_retry_needed)
            self._thread.start()
        except Exception as e:
            self._add_log(f"Erro: {e}")

    def _on_progress(self, value, msg):
        self.progress.setValue(int(value * 100))
        self.progress_label.setText(f"{int(value * 100)}%")
        self.status.setText(msg)

    def _on_done(self, success, msg):
        if success:
            self.progress.setValue(100)
            self.progress_label.setText("100%")
            self.status.setText("Instalacao concluida!")
            self.status.setStyleSheet(f"color: {COLORS['success']}; font-size: 13px; font-weight: bold;")
            self.app.install_complete = True
        else:
            self.progress.setValue(0)
            self.status.setText(f"Falha: {msg}")
            self.status.setStyleSheet(f"color: {COLORS['error']}; font-size: 13px; font-weight: bold;")
            self.app.install_failed = True
        # Refresh bottom bar buttons (Sair on failure, etc.)
        self.app._update_buttons()

    def _on_retry_needed(self, url, error):
        """Show retry dialog when all mirrors fail."""
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Download Falhou",
            f"Falha ao baixar de todos os mirrors:\n\n{error}\n\nDeseja tentar novamente?",
            QMessageBox.Retry | QMessageBox.Cancel,
            QMessageBox.Retry
        )
        if self._thread and hasattr(self._thread, '_retry_event'):
            self._thread._retry_result = (reply == QMessageBox.Retry)
            self._thread._retry_event.set()

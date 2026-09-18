"""
ANK Installer - Step 4: Installing (PySide6)
"""

import datetime
import os
import tempfile
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
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
            install_mode = getattr(self.app, 'install_mode', 'native')
            device = self.app.device_data
            has_magisk = self.app._detection_result.get("has_magisk", False) if isinstance(self.app._detection_result, dict) else getattr(self.app._detection_result, "has_magisk", False) if self.app._detection_result else False

            if install_mode == "ank_ui":
                self._install_ank_ui_mode()
            elif device and not getattr(device, 'is_rooted', False):
                self._install_lite()
            elif has_magisk:
                self._install_rooted()
            else:
                self._install_manual()
            self.done.emit(True, "Instalacao concluida!")
        except Exception as e:
            self.done.emit(False, str(e))

    def _install_ank_ui_mode(self):
        """Install ANK engine + ANK UI launcher."""
        import sys
        import os

        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            exe_dir = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            exe_dir = os.path.join(base_path, "..")

        # 1. Install ANK engine
        tier = self.app.recommended_tier
        device = self.app.device_data
        has_magisk = self.app._detection_result.get("has_magisk", False) if isinstance(self.app._detection_result, dict) else getattr(self.app._detection_result, "has_magisk", False) if self.app._detection_result else False

        def callback(step, message, progress_val):
            self.progress.emit(progress_val * 0.7, message)
            self.log.emit(message)

        if device and not getattr(device, 'is_rooted', False):
            from core.installer_lite import LiteInstaller
            installer = LiteInstaller(self.adb, self.serial, callback=callback)
            if not installer.install():
                raise Exception("Instalacao Lite falhou")
        elif has_magisk:
            self._install_rooted()
            return
        else:
            from core.installer_manual import ManualInstaller
            installer = ManualInstaller(self.adb, self.serial, callback=callback)
            if not installer.install():
                raise Exception("Instalacao manual falhou")

        # 2. Install ANK UI APK
        self.progress.emit(0.75, "Instalando ANK UI...")
        self.log.emit("Buscando ank-launcher.apk...")

        apk_candidates = [
            os.path.join(exe_dir, "ank-launcher.apk"),
            os.path.join(base_path, "ank-launcher.apk"),
        ]
        apk_path = None
        for c in apk_candidates:
            if os.path.isfile(c):
                apk_path = c
                break

        if not apk_path:
            self.log.emit("WARN: ank-launcher.apk nao encontrado - ANK UI nao instalado")
            return

        self.progress.emit(0.8, "Instalando ANK Launcher...")
        self.log.emit(f"Instalando: {apk_path}")
        result = self.adb._run_device(self.serial, ["install", "-r", apk_path], timeout=60)
        if result.returncode != 0:
            self.log.emit(f"WARN: Falha ao instalar ANK UI: {result.stderr}")
            return

        self.log.emit("OK: ANK Launcher instalado")

        # 3. Set ANK UI as default launcher
        self.progress.emit(0.9, "Configurando ANK UI como launcher padrao...")
        self.log.emit("Definindo ANK UI como app de inicio padrao...")

        # Find ANK UI package name
        output, _ = self.adb.shell(self.serial, "pm list packages 2>/dev/null | grep ank")
        if output:
            for line in output.strip().split("\n"):
                pkg = line.replace("package:", "").strip()
                if pkg and "launcher" in pkg.lower() or "ank" in pkg.lower():
                    # Set as default home activity
                    self.adb.shell(self.serial,
                        f"cmd package set-home-activity {pkg}/.MainActivity 2>/dev/null")
                    self.adb.shell(self.serial,
                        f"input keyevent KEYCODE_HOME 2>/dev/null")
                    self.log.emit(f"OK: {pkg} definido como launcher padrao")
                    break

        self.progress.emit(1.0, "Instalacao ANK UI concluida!")
        self.log.emit("ANK UI instalado com sucesso!")

    def _install_rooted(self):
        # 1. Find zip and ankcore from PyInstaller bundle or disk
        self.progress.emit(0.05, "Extraindo arquivos...")
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

        # 2. Push zip to device (ankcore tar.gz is bundled inside the zip)
        self.progress.emit(0.25, "[ANK-INSTALLER] Verificando atualizações, aguarde...")
        self.adb.push(self.serial, tmp_zip, "/sdcard/Download/ank-magisk.zip")
        self.log.emit("[ANK-INSTALLER] Verificando atualizações, aguarde...")

        # 3. Install Magisk module (streaming output)
        self.progress.emit(0.5, "[ANK-INSTALLER] Instalação iniciada, isso pode levar alguns minutos.")
        self.log.emit("[ANK-INSTALLER] Iniciando instalação, aguarde...")

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
            raise Exception("Instalacao do ANK falhou")

        self.log.emit("OK: ANK instalado")

        # 4. Verify installation
        self.progress.emit(0.8, "Verificando instalacao...")
        check, _ = self.adb.shell(self.serial, "ls /data/local/ank/ankfs/usr/bin/python3 2>/dev/null")
        if not check or "python3" not in check:
            self.log.emit("\n--- Log de instalacao do device ---")
            log_out, _ = self.adb.shell(self.serial, "cat /data/local/ank/logs/install.log 2>/dev/null || cat /sdcard/AndroidKonteiner/logs/install.log 2>/dev/null")
            if log_out:
                self.log.emit(log_out)
            self.log.emit("--- Fim do log ---\n")
            raise Exception("Erro. Verifique o log acima.")

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
        self._countdown = 0
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._countdown_tick)
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

        self.countdown_label = QLabel("")
        self.countdown_label.setObjectName("subtitle")
        self.countdown_label.setStyleSheet(f"color: {COLORS['accent']}; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.countdown_label)

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
            self._countdown = 5
            self.countdown_label.setText(f"Prosseguindo em {self._countdown}s...")
            self._countdown_timer.start(1000)
        else:
            self.progress.setValue(0)
            self.status.setText(f"Falha: {msg}")
            self.status.setStyleSheet(f"color: {COLORS['error']}; font-size: 13px; font-weight: bold;")
            self.app.install_failed = True
        # Refresh bottom bar buttons (Sair on failure, etc.)
        self.app._update_buttons()

    def _countdown_tick(self):
        self._countdown -= 1
        if self._countdown <= 0:
            self._countdown_timer.stop()
            self.countdown_label.setText("")
            self.app.show_step(self.current_step + 1)
        else:
            self.countdown_label.setText(f"Prosseguindo em {self._countdown}s...")

    @property
    def current_step(self):
        return self.app.current_step

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

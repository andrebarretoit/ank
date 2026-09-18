@echo off
REM ANK Installer - Build Script
REM Builds the installer as a standalone .exe using PyInstaller

echo ======================================
echo  ANK Installer Build
echo ======================================

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.11+
    exit /b 1
)

REM Check if PyInstaller is installed
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Check if PySide6 is installed
pip show PySide6 >nul 2>&1
if errorlevel 1 (
    echo Installing PySide6...
    pip install PySide6
)

REM Check if adbutils is installed
pip show adbutils >nul 2>&1
if errorlevel 1 (
    echo Installing adbutils...
    pip install adbutils
)

REM Build
REM Note: ui/*.py (including step_mode_select, step_restore, step_clone,
REM step_migrate) are picked up automatically via ui/app.py's imports -
REM no extra --add-data entries are needed for them.
REM
REM ADB: the installer no longer requires "adb" on PATH. Resolution order:
REM   1) platform-tools\adb.exe (+ AdbWinApi.dll, AdbWinUsbApi.dll) placed
REM      next to ANK-Installer.exe, same convention as ank-magisk.zip /
REM      ank-launcher.apk (drop a real platform-tools folder here if you
REM      want it fully offline/embedded).
REM   2) a copy already cached in %USERPROFILE%\.ank-installer\platform-tools\
REM   3) "adb" on the system PATH
REM   4) as a last resort, it is auto-downloaded from Google's official
REM      platform-tools zip into %USERPROFILE%\.ank-installer\platform-tools\
REM      the first time it's needed, then reused from cache after that.
echo Building ANK Installer...
pyinstaller --onefile --windowed ^
    --add-data "assets/icon.ico;assets" ^
    --hidden-import=PySide6 ^
    --hidden-import=adbutils ^
    --hidden-import=adbutils.adb_server ^
    --name "ANK-Installer" ^
    main.py

echo.
echo Build complete: dist\ANK-Installer.exe
echo NOTE: place ank-magisk.zip (and, for ANK UI mode, ank-launcher.apk)
echo next to ANK-Installer.exe - they are looked up at runtime, not bundled.
pause

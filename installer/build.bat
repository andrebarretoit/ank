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

REM Check if customtkinter is installed
pip show customtkinter >nul 2>&1
if errorlevel 1 (
    echo Installing customtkinter...
    pip install customtkinter
)

REM Build
echo Building ANK Installer...
pyinstaller --onefile --windowed ^
    --add-data "assets/icon.ico;assets" ^
    --hidden-import=customtkinter ^
    --hidden-import=adbutils ^
    --hidden-import=adbutils.adb_server ^
    --name "ANK-Installer" ^
    main.py

echo.
echo Build complete: dist\ANK-Installer.exe
pause

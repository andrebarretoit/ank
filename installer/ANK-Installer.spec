# -*- mode: python ; coding: utf-8 -*-
# NOTE: ui/step_mode_select.py, ui/step_restore.py, ui/step_clone.py and
# ui/step_migrate.py do not need their own `datas` entries here - PyInstaller's
# static analysis follows the `from ui.step_xxx import ...` statements in
# ui/app.py and bundles them as regular Python modules automatically.
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('E:/Ank/dist/ank-magisk.zip', '.'),
        ('E:/Ank/ANK.ico', '.'),
        ('E:/Ank/ank-launcher.apk', '.'),
    ],
    hiddenimports=['adbutils', 'PySide6'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ANK-Installer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='E:/Ank/ANK.ico',
)

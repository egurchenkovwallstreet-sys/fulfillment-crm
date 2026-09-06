# -*- mode: python ; coding: utf-8 -*-
# Один файл — медленный первый запуск на старых ПК. Основная сборка: build.spec (папка).
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

block_cipher = None
root = Path(SPECPATH)

hiddenimports = [
    'win32timezone',
    'win32print',
    'win32ui',
    'win32con',
    'win32api',
    'win32event',
    'win32gui',
    'pystray._win32',
    'PIL._tkinter_finder',
    'PIL.ImageWin',
    'flask',
    'flask_cors',
    'werkzeug',
    'jinja2',
    'itsdangerous',
    'click',
    'blinker',
    'markupsafe',
    'charset_normalizer',
    'encodings.idna',
    'compat',
]

datas = [('config.example.json', '.')]
binaries = []

for pkg in ('flask', 'flask_cors', 'PIL'):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    ['agent_main.py'],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='FulfillmentCRM-PrintAgent-onefile',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(root / 'assets' / 'icon.ico') if (root / 'assets' / 'icon.ico').exists() else None,
)

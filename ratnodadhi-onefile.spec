# -*- mode: python ; coding: utf-8 -*-
"""
ratnodadhi-onefile.spec – PyInstaller specification to build a single standalone portable .exe.

Usage:
    pyinstaller ratnodadhi-onefile.spec
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
project_root = Path.cwd()

# ── Data files to bundle ──────────────────────────────────────────────────────
datas = [
    (str(project_root / 'booklib' / 'db' / '*.sql'), 'booklib/db'),
    (str(project_root / 'booklib' / 'resources' / '*'), 'booklib/resources'),
    (str(project_root / 'booklib_web' / 'templates' / '*'), 'booklib_web/templates'),
    (str(project_root / 'booklib_web' / 'static' / '*'), 'booklib_web/static'),
]

# ── Hidden imports ────────────────────────────────────────────────────────────
hiddenimports = [
    'sqlite3',
    'fitz',
    'pymupdf',
    'PIL',
    'PIL.Image',
    'PIL.ImageQt',
    'platformdirs',
    'watchdog',
    'watchdog.observers',
    'send2trash',
    'keyring',
    'keyring.backends',
    'flask',
    'waitress',
    'qrcode',
    'qrcode.image.pil',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
]
hiddenimports += collect_submodules('booklib')
hiddenimports += collect_submodules('booklib_web')

a = Analysis(
    ['main.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'numpy', 'IPython', 'notebook', 'pytest'],
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
    name='Ratnodadhi-Portable',
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
    icon=str(project_root / 'booklib' / 'resources' / 'ratnodadhi-logo.ico'),
)

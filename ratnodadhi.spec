# -*- mode: python ; coding: utf-8 -*-
"""
ratnodadhi.spec – PyInstaller specification file for Ratnodadhi (BookLib).
Builds a standalone, windowed Windows application bundle.

Usage:
    pyinstaller ratnodadhi.spec
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
project_root = Path.cwd()

# ── Data files to bundle ──────────────────────────────────────────────────────
datas = [
    # Database SQL schemas & migrations
    (str(project_root / 'booklib' / 'db' / '*.sql'), 'booklib/db'),
    # Logos and icons
    (str(project_root / 'booklib' / 'resources' / '*'), 'booklib/resources'),
    # Web UI Jinja2 templates and CSS/JS assets
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
    'requests',
    'google',
    'google.auth',
    'google.auth.transport.requests',
    'google.oauth2.credentials',
    'google_auth_oauthlib',
    'google_auth_oauthlib.flow',
    'googleapiclient',
    'googleapiclient.discovery',
    'googleapiclient.http',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
]
hiddenimports += collect_submodules('booklib')
hiddenimports += collect_submodules('booklib_web')
try:
    datas += collect_data_files('googleapiclient')
except Exception:
    pass

# ── Analysis ──────────────────────────────────────────────────────────────────
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

# ── Executable (Directory mode for fast startup and Inno Setup packaging) ─────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Ratnodadhi',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # False = Windowed GUI (no black cmd terminal window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / 'booklib' / 'resources' / 'ratnodadhi-logo.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Ratnodadhi',
)

"""
fileops.py – open a file in the default app and show it in the file manager.
"""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def open_file(path: str) -> bool:
    """Open *path* in the system default application.  Returns True on success."""
    if not Path(path).exists():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def show_in_folder(path: str) -> None:
    """Reveal *path* in the native file manager."""
    p = Path(path)
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(["explorer", "/select,", str(p)])
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", str(p)])
        else:
            # Linux: open the parent directory
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))
    except Exception:
        # Last resort: open the parent directory
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))

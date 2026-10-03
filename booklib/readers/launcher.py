"""
launcher.py – safely open a book with a specific reader or the system default.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from booklib.readers.models import Reader

logger = logging.getLogger(__name__)


def launch(reader: Reader, book_path: str) -> bool:
    """
    Start *reader* with *book_path*.  Returns True on success.
    Never uses shell=True; the path is always passed as a list element.
    """
    if reader.key == "builtin":
        try:
            from booklib.reader.manager import get_reader_manager
            return get_reader_manager().open_path(book_path)
        except Exception as exc:
            logger.error("Could not launch builtin reader: %s", exc)
            return False

    try:
        template_parts = shlex.split(reader.args_template, posix=(os.name != "nt"))
        args = [reader.exe] + [p.replace("{file}", book_path) for p in template_parts]
        kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                        "close_fds": True}
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(args, **kwargs)
        return True
    except OSError as exc:
        logger.error("Could not start %s: %s", reader.name, exc)
        return False


def open_system_default(book_path: str) -> bool:
    """Open with the OS default app."""
    if not Path(book_path).exists():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(book_path))


def open_with_os_chooser(book_path: str) -> None:
    """Open the OS 'Open with…' dialog."""
    if os.name == "nt":
        try:
            subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", book_path])
        except OSError:
            open_system_default(book_path)
    else:
        open_system_default(book_path)


# Alias used by main_window.py
open_with_os_dialog = open_with_os_chooser

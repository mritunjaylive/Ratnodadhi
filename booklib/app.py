"""
app.py – QApplication setup, logging, and app-data directory creation.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon

from booklib.config import DATA_DIR, LOG_FILE, COVERS_DIR, SAFETY_DIR

_RESOURCES_DIR = Path(__file__).parent / "resources"
_LOGO_ICO = _RESOURCES_DIR / "ratnodadhi-logo.ico"
_LOGO_PNG = _RESOURCES_DIR / "ratnodadhi-logo.png"
_LOGO_SVG = _RESOURCES_DIR / "ratnodadhi-logo.svg"
_LOGO_PATH = _LOGO_SVG


def get_app_icon() -> QIcon:
    """Return a multi-resolution QIcon for the window and taskbar."""
    icon = QIcon()
    if _LOGO_ICO.exists():
        icon.addFile(str(_LOGO_ICO))
    if _LOGO_PNG.exists():
        icon.addFile(str(_LOGO_PNG))
    if _LOGO_SVG.exists():
        icon.addFile(str(_LOGO_SVG))
    return icon


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    SAFETY_DIR.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addHandler(console)


def create_app() -> QApplication:
    if sys.platform == "win32":
        import ctypes
        try:
            # Tell Windows to treat this as an explicit app so its icon appears on the taskbar instead of python.exe
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ratnodadhi.booklib.v5")
        except Exception:
            pass

    # High-DPI is automatic in Qt 6
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Ratnodadhi")
    app.setOrganizationName("Ratnodadhi")

    # App icon – shown in taskbar, Alt+Tab, and every native dialog
    icon = get_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    # Global font and custom typefaces
    from booklib.ui.theme import get_application_font, load_jaini_font, apply_window_rounding
    app.setFont(get_application_font())
    load_jaini_font()

    # Window rounding event filter
    from PySide6.QtCore import QObject, QEvent
    from PySide6.QtWidgets import QDialog, QMainWindow

    class _WindowRoundingFilter(QObject):
        def eventFilter(self, watched, event):
            if event.type() in (QEvent.Type.Show, QEvent.Type.Polish) and isinstance(watched, (QDialog, QMainWindow)):
                apply_window_rounding(watched)
            return super().eventFilter(watched, event)

    rounding_filter = _WindowRoundingFilter(app)
    app.installEventFilter(rounding_filter)
    app._rounding_filter = rounding_filter

    return app


def run_startup_tasks(db) -> None:
    """
    Run maintenance tasks that should execute once at startup, after the DB is open.

    - Sweep leftover temporary files registered in temp_files table.
    - Recover any rename_log rows still 'pending' from a previous crash.
    - Purge old rename batches (>90 days).
    """
    import logging
    log = logging.getLogger(__name__)

    conn = db.conn
    if conn is None:
        return

    # 1. Temp-file sweep
    try:
        from booklib.storage.tempfiles import TempFileRegistry
        reg = TempFileRegistry(conn)
        swept = reg.sweep()
        if swept:
            log.info("Startup: swept %d leftover temp file(s)", swept)
    except Exception as exc:
        log.warning("Temp-file sweep failed: %s", exc)

    # 2. Rename crash recovery
    try:
        from booklib.organize.executor import recover_pending_renames
        recovered = recover_pending_renames(conn)
        if recovered:
            log.info("Startup: recovered %d pending rename row(s)", recovered)
    except Exception as exc:
        log.warning("Rename crash recovery failed: %s", exc)

    # 3. Purge old rename batches
    try:
        from booklib.organize.undo import purge_old_batches
        purged = purge_old_batches(conn)
        if purged:
            log.debug("Startup: purged %d old rename batch(es)", purged)
    except Exception as exc:
        log.warning("Rename batch purge failed: %s", exc)

    # 4. Scheduled automatic backup
    try:
        from booklib.backup.scheduler import run_scheduled_backup
        run_scheduled_backup(conn)
    except Exception as exc:
        log.warning("Scheduled backup failed: %s", exc)

    # 5. Sweep extractor worker temp folders
    try:
        from booklib.extract.pool import sweep_extractor_temp_dir
        swept_ext = sweep_extractor_temp_dir()
        if swept_ext:
            log.info("Startup: swept %d orphaned extractor temp folder(s)", swept_ext)
    except Exception as exc:
        log.warning("Extractor temp sweep failed: %s", exc)

    # 6. FTS indexing crash recovery: reset 'indexing' to 'queued'
    try:
        with conn:
            cur = conn.execute("UPDATE books SET fts_state = 'queued' WHERE fts_state = 'indexing'")
            if cur.rowcount > 0:
                log.info("Startup: recovered %d book(s) stuck in 'indexing' state", cur.rowcount)
    except Exception as exc:
        log.warning("FTS crash recovery failed: %s", exc)


def check_pending_restore() -> None:
    """Apply staged restore before connecting to the database if pending."""
    try:
        from booklib.backup.restore import check_and_apply_pending_restore
        check_and_apply_pending_restore()
    except Exception as exc:
        logging.getLogger(__name__).warning("Pending restore check failed: %s", exc)


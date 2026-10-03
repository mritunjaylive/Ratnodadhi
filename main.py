"""
main.py – Ratnodadhi entry point.

Usage:
    python main.py
"""
import sys

from booklib.app import create_app, setup_logging, run_startup_tasks, check_pending_restore
from booklib.db.database import Database
from booklib.ui.main_window import MainWindow


def main() -> int:
    # Explicit AppUserModelID ensures Windows taskbar displays Ratnodadhi's logo instead of python.exe
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ratnodadhi.booklib.v5")
        except Exception:
            pass

    setup_logging()
    app = create_app()

    # Apply any pending restore before opening database
    check_pending_restore()

    db = Database()
    db.connect()

    # V5 startup maintenance: temp-file sweep, crash recovery, batch purge
    run_startup_tasks(db)

    try:
        win = MainWindow(db)
        win.show()
        return app.exec()
    finally:
        db.close()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())

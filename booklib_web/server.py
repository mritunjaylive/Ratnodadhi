"""
booklib_web.server – Waitress server runner for embedded in-app and headless usage.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from waitress.server import create_server

from booklib_web.app import create_app
from booklib_web.config import WebConfig

logger = logging.getLogger("booklib_web.server")

# Conditional PySide6 import for QThread if available
try:
    from PySide6.QtCore import QThread, Signal
    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    class QThread:  # type: ignore
        def __init__(self, parent=None):
            self.parent = parent
            self._thread = None
        def start(self):
            self._thread = threading.Thread(target=self.run, daemon=True)
            self._thread.start()

    class _DummySignal:
        def __init__(self):
            self._subscribers = []
        def connect(self, fn):
            self._subscribers.append(fn)
        def emit(self, *args):
            for fn in self._subscribers:
                try:
                    fn(*args)
                except Exception:
                    pass

    def Signal(*args):  # type: ignore
        return _DummySignal()


class WebServerThread(QThread):
    """
    Runs the Waitress WSGI server in a background thread.
    Can be used from PySide6 UI (via ServiceManager) or standalone.
    """
    if _HAS_QT:
        started_signal = Signal()
        stopped_signal = Signal()
        error_signal = Signal(str)
    else:
        started_signal = _DummySignal()
        stopped_signal = _DummySignal()
        error_signal = _DummySignal()

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        db_path: str | None = None,
        password_hash: str | None = None,
        auto_off_minutes: int = 240,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self.port = port
        self.auto_off_minutes = auto_off_minutes
        self._server = None
        self._is_running = False
        self._auto_off_timer: threading.Timer | None = None

        cfg = WebConfig(host=host, port=port, auto_off_minutes=auto_off_minutes)
        if db_path:
            cfg.db_path = db_path
        self._app = create_app(cfg)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def run(self) -> None:
        try:
            self._server = create_server(self._app, host=self.host, port=self.port, threads=8)
            self._is_running = True
            self.started_signal.emit()
            logger.info("BookLib web server listening on http://%s:%d", self.host, self.port)

            # Auto-off timer
            if self.auto_off_minutes > 0:
                self._auto_off_timer = threading.Timer(
                    self.auto_off_minutes * 60,
                    self._on_auto_off_timeout,
                )
                self._auto_off_timer.daemon = True
                self._auto_off_timer.start()

            self._server.run()
        except Exception as exc:
            logger.error("Web server error: %s", exc)
            self._is_running = False
            self.error_signal.emit(str(exc))
        finally:
            self._is_running = False
            if self._auto_off_timer:
                self._auto_off_timer.cancel()
            self.stopped_signal.emit()

    def _on_auto_off_timeout(self) -> None:
        logger.info("Auto-off timer reached (%d minutes). Stopping web server.", self.auto_off_minutes)
        self.stop()

    def stop(self) -> None:
        """Close server socket and terminate thread."""
        self._is_running = False
        if self._auto_off_timer:
            self._auto_off_timer.cancel()
        if self._server is not None:
            try:
                self._server.close()
            except Exception as exc:
                logger.warning("Error closing web server: %s", exc)
            self._server = None

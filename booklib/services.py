"""
services.py – ServiceManager for coordinating long-running background services.

Manages:
- Web server (Waitress running booklib_web Flask app)
- Full-text index scheduler (running in the index lane)
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class ServiceManager(QObject):
    """
    Coordinates long-running app services that run alongside the desktop UI:
    - In-app Web Server (Waitress thread)
    - Full-text Index Scheduler
    """

    service_started = Signal(str)   # service_name
    service_stopped = Signal(str)   # service_name
    service_error   = Signal(str, str)  # service_name, error_message

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._web_server_thread: Any | None = None
        self._index_scheduler: Any | None = None

    # ── Web Server ────────────────────────────────────────────────────────────

    def is_web_server_running(self) -> bool:
        return self._web_server_thread is not None and getattr(self._web_server_thread, "is_running", False)

    def start_web_server(self, host: str, port: int, db_path: str, password_hash: str | None = None) -> bool:
        """Start the embedded waitress web server."""
        if self.is_web_server_running():
            logger.info("Web server already running")
            return True

        try:
            from booklib_web.server import WebServerThread
            self._web_server_thread = WebServerThread(
                host=host,
                port=port,
                db_path=db_path,
                password_hash=password_hash,
                parent=self,
            )
            self._web_server_thread.started_signal.connect(lambda: self.service_started.emit("web_server"))
            self._web_server_thread.stopped_signal.connect(lambda: self.service_stopped.emit("web_server"))
            self._web_server_thread.error_signal.connect(lambda err: self.service_error.emit("web_server", err))
            self._web_server_thread.start()
            return True
        except Exception as exc:
            logger.error("Failed to start web server: %s", exc)
            self.service_error.emit("web_server", str(exc))
            return False

    def stop_web_server(self) -> None:
        """Stop the embedded web server."""
        if self._web_server_thread is not None:
            try:
                self._web_server_thread.stop()
            except Exception as exc:
                logger.warning("Error stopping web server: %s", exc)
            self._web_server_thread = None

    # ── Full-text Index Scheduler ─────────────────────────────────────────────

    def is_index_scheduler_running(self) -> bool:
        return self._index_scheduler is not None and getattr(self._index_scheduler, "is_running", False)

    def start_index_scheduler(self, db) -> bool:
        """Start the background index scheduler in the index lane."""
        if self.is_index_scheduler_running():
            return True

        try:
            from booklib.fulltext.scheduler import IndexScheduler
            self._index_scheduler = IndexScheduler(db, parent=self)
            self._index_scheduler.started_signal.connect(lambda: self.service_started.emit("index_scheduler"))
            self._index_scheduler.stopped_signal.connect(lambda: self.service_stopped.emit("index_scheduler"))
            self._index_scheduler.start()
            return True
        except Exception as exc:
            logger.error("Failed to start index scheduler: %s", exc)
            self.service_error.emit("index_scheduler", str(exc))
            return False

    def stop_index_scheduler(self) -> None:
        if self._index_scheduler is not None:
            try:
                self._index_scheduler.stop()
            except Exception as exc:
                logger.warning("Error stopping index scheduler: %s", exc)
            self._index_scheduler = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def shutdown_all(self) -> None:
        """Stop all running services on app quit."""
        self.stop_web_server()
        self.stop_index_scheduler()
        from booklib.extract.pool import shutdown_extractor_pool
        shutdown_extractor_pool()


_service_manager: ServiceManager | None = None


def get_service_manager() -> ServiceManager:
    global _service_manager
    if _service_manager is None:
        _service_manager = ServiceManager()
    return _service_manager

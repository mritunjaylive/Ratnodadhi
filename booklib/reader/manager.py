"""
reader/manager.py – Coordinates opening books, cloud downloads, leases, and sessions.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer

from booklib.reader.backend import Locator
from booklib.reader.position import load_reading_position, save_reading_position
from booklib.reader.sessions import ReadingSessionTracker
from booklib.reader.ui.reader_window import ReaderWindow

logger = logging.getLogger(__name__)

_LEASE_DURATION_SECONDS = 300     # 5 minutes
_LEASE_RENEW_INTERVAL_MS = 60000  # Renew every 60 seconds


class ReaderManager(QObject):
    """Singleton manager controlling ReaderWindow, cloud leases, and position tracking."""

    def __init__(self, conn_supplier=None, parent=None) -> None:
        super().__init__(parent)
        self._conn_supplier = conn_supplier
        self._window: ReaderWindow | None = None
        self.session_tracker = ReadingSessionTracker(self._get_conn, parent=self)
        self._lease_timers: dict[int, QTimer] = {}

    def _get_conn(self) -> sqlite3.Connection | None:
        if self._conn_supplier:
            return self._conn_supplier()
        return None

    def get_window(self) -> ReaderWindow:
        """Get or create singleton ReaderWindow."""
        if self._window is None:
            self._window = ReaderWindow(conn_supplier=self._conn_supplier)
            self._window.reading_position_saved.connect(self._on_position_saved)
            self._window.book_progress_updated.connect(self._on_progress_updated)
            self._window.destroyed.connect(self._on_window_destroyed)
        return self._window

    def open_path(self, path: str, book_id: int | None = None) -> bool:
        """Open a local file in ReaderWindow."""
        win = self.get_window()
        return win.open_book(path, book_id=book_id)

    def open_book(
        self,
        book_id: int,
        locator: Locator | None = None,
        highlight_query: str | None = None,
    ) -> bool:
        """Open a book by book_id, downloading if cloud and acquiring lease."""
        conn = self._get_conn()
        if not conn:
            return False

        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row:
            logger.warning("Cannot open book %d: not found in database", book_id)
            return False

        source = row["source"] if "source" in row.keys() else "local"
        path = row["path"]

        # Cloud book: ensure local and acquire lease
        if source != "local":
            try:
                from booklib.storage.guard import ensure_local
                local_path = ensure_local(row, conn, prompt_parent=self.get_window())
                if not local_path or not Path(local_path).exists():
                    return False
                path = local_path
                self._acquire_cloud_lease(row["id"], conn)
            except Exception as exc:
                logger.error("Failed to ensure local copy of cloud book: %s", exc)
                return False

        # Load saved position if not specified
        if locator is None:
            saved_loc, _, _ = load_reading_position(conn, book_id)
            locator = saved_loc

        win = self.get_window()
        opened = win.open_book(
            path,
            book_id=book_id,
            locator=locator,
            highlight_query=highlight_query,
        )

        if opened:
            # Record open in database
            try:
                with conn:
                    conn.execute(
                        """
                        UPDATE books SET
                            last_opened_at = datetime('now'),
                            open_count = open_count + 1
                        WHERE id = ?
                        """,
                        (book_id,),
                    )
            except Exception:
                pass

            # Start reading session
            tab = win.current_tab()
            start_prog = (float(tab.page_view.current_page + 1) / max(tab.backend.page_count, 1)) if tab else 0.0
            self.session_tracker.start_session(book_id, start_prog)

        return opened

    # ── Cloud Leases ──────────────────────────────────────────────────────────

    def _acquire_cloud_lease(self, book_id: int, conn: sqlite3.Connection) -> None:
        """Set in_use_until lease on cached cloud file and start 60s renewal timer."""
        self._renew_lease(book_id)

        timer = QTimer(self)
        timer.setInterval(_LEASE_RENEW_INTERVAL_MS)
        timer.timeout.connect(lambda: self._renew_lease(book_id))
        timer.start()
        self._lease_timers[book_id] = timer

    def _renew_lease(self, book_id: int) -> None:
        conn = self._get_conn()
        if not conn:
            return
        until_iso = datetime.fromtimestamp(time.time() + _LEASE_DURATION_SECONDS, tz=timezone.utc).isoformat()
        try:
            with conn:
                conn.execute(
                    "UPDATE drive_cache SET in_use_until = ? WHERE book_id = ?",
                    (until_iso, book_id),
                )
        except Exception:
            pass

    def release_cloud_lease(self, book_id: int) -> None:
        """Release lease on cloud file when reader tab is closed."""
        timer = self._lease_timers.pop(book_id, None)
        if timer:
            timer.stop()

        conn = self._get_conn()
        if not conn:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            with conn:
                conn.execute(
                    "UPDATE drive_cache SET in_use_until = ? WHERE book_id = ?",
                    (now_iso, book_id),
                )
        except Exception:
            pass

    # ── Callbacks from ReaderWindow ───────────────────────────────────────────

    def _on_position_saved(self, book_id: int, locator: Locator) -> None:
        conn = self._get_conn()
        if not conn:
            return
        tab = self.get_window().current_tab()
        prog = float(tab.page_view.current_page + 1) / max(tab.backend.page_count, 1) if tab else 0.0
        lkey = tab.settings.layout_key(tab.page_view.width(), tab.page_view.height()) if tab else ""
        save_reading_position(conn, book_id, locator, prog, lkey)

    def _on_progress_updated(self, book_id: int, progress: float) -> None:
        conn = self._get_conn()
        if conn:
            pct = round(progress * 100.0, 1)
            try:
                with conn:
                    conn.execute("UPDATE books SET progress_percent = ? WHERE id = ?", (pct, book_id))
                    # Mark as read if near end (>= 98%)
                    if progress >= 0.98:
                        conn.execute(
                            "UPDATE books SET status = 'read', status_changed_at = datetime('now') WHERE id = ? AND (status IS NULL OR status = 'reading')",
                            (book_id,),
                        )
            except Exception:
                pass
        self.session_tracker.update_progress(book_id, progress)

    def _on_window_destroyed(self) -> None:
        # Flush all sessions and release all leases
        self.session_tracker.flush_all()
        for bid in list(self._lease_timers.keys()):
            self.release_cloud_lease(bid)
        self._window = None


_reader_manager: ReaderManager | None = None


def get_reader_manager(conn_supplier=None) -> ReaderManager:
    global _reader_manager
    if _reader_manager is None:
        _reader_manager = ReaderManager(conn_supplier=conn_supplier)
    elif conn_supplier and _reader_manager._conn_supplier is None:
        _reader_manager._conn_supplier = conn_supplier
    return _reader_manager

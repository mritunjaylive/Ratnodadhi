"""
reader/sessions.py – Reading session tracking, active time accumulation, and flush.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, QSettings, QTimer

logger = logging.getLogger(__name__)

_IDLE_TIMEOUT_SECONDS = 120       # 2 minutes without user interaction
_MIN_SESSION_SECONDS = 10        # Discard sessions shorter than 10 seconds
_FLUSH_INTERVAL_MS = 60 * 1000    # Flush every minute


class ReadingSessionTracker(QObject):
    """Tracks active reading time for open books."""

    def __init__(self, conn_supplier, parent=None) -> None:
        super().__init__(parent)
        self._conn_supplier = conn_supplier  # callable returning sqlite3.Connection
        self._active_sessions: dict[int, dict[str, Any]] = {}

        # 60s periodic flush timer
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(_FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self.flush_all)
        self._flush_timer.start()

    @staticmethod
    def is_tracking_enabled() -> bool:
        s = QSettings()
        return bool(s.value("reader/track_reading_time", True, type=bool))

    @staticmethod
    def set_tracking_enabled(enabled: bool) -> None:
        s = QSettings()
        s.setValue("reader/track_reading_time", enabled)

    def start_session(self, book_id: int, start_progress: float = 0.0) -> int | None:
        """Start a new reading session for book_id."""
        if not self.is_tracking_enabled():
            return None

        # End any existing session for this book first
        if book_id in self._active_sessions:
            self.end_session(book_id, start_progress)

        conn = self._conn_supplier()
        if not conn:
            return None

        now_iso = datetime.now().isoformat()
        try:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO reading_sessions (book_id, started_at, ended_at, active_seconds, start_progress, end_progress)
                    VALUES (?, ?, ?, 0, ?, ?)
                    """,
                    (book_id, now_iso, now_iso, start_progress, start_progress),
                )
                session_id = cur.lastrowid
                self._active_sessions[book_id] = {
                    "session_id": session_id,
                    "started_time": time.time(),
                    "last_active_time": time.time(),
                    "accumulated_seconds": 0,
                    "is_paused": False,
                    "start_progress": start_progress,
                    "end_progress": start_progress,
                }
                return session_id
        except Exception as exc:
            logger.warning("Failed to insert reading session: %s", exc)
            return None

    def record_activity(self, book_id: int) -> None:
        """User interaction (scroll, key, mouse) occurred."""
        s = self._active_sessions.get(book_id)
        if not s:
            return

        now = time.time()
        elapsed = now - s["last_active_time"]
        if elapsed <= _IDLE_TIMEOUT_SECONDS:
            if not s["is_paused"]:
                s["accumulated_seconds"] += elapsed
        else:
            # Resuming from idle
            s["is_paused"] = False

        s["last_active_time"] = now

    def update_progress(self, book_id: int, progress: float) -> None:
        s = self._active_sessions.get(book_id)
        if s:
            s["end_progress"] = progress
            self.record_activity(book_id)

    def flush_all(self) -> None:
        """Flush accumulated active seconds to database."""
        conn = self._conn_supplier()
        if not conn:
            return

        now_iso = datetime.now().isoformat()
        now = time.time()

        for book_id, s in list(self._active_sessions.items()):
            elapsed = now - s["last_active_time"]
            if elapsed <= _IDLE_TIMEOUT_SECONDS and not s["is_paused"]:
                s["accumulated_seconds"] += elapsed
                s["last_active_time"] = now

            sec = int(s["accumulated_seconds"])
            try:
                with conn:
                    conn.execute(
                        """
                        UPDATE reading_sessions
                        SET active_seconds = ?, ended_at = ?, end_progress = ?
                        WHERE id = ?
                        """,
                        (sec, now_iso, s["end_progress"], s["session_id"]),
                    )
            except Exception as exc:
                logger.warning("Failed to flush session %d: %s", s["session_id"], exc)

    def end_session(self, book_id: int, end_progress: float | None = None) -> None:
        """End session and discard if shorter than 10 seconds."""
        s = self._active_sessions.pop(book_id, None)
        if not s:
            return

        now_iso = datetime.now().isoformat()
        now = time.time()
        elapsed = now - s["last_active_time"]
        if elapsed <= _IDLE_TIMEOUT_SECONDS and not s["is_paused"]:
            s["accumulated_seconds"] += elapsed

        total_sec = int(s["accumulated_seconds"])
        prog = end_progress if end_progress is not None else s["end_progress"]

        conn = self._conn_supplier()
        if not conn:
            return

        try:
            with conn:
                if total_sec < _MIN_SESSION_SECONDS:
                    # Discard short sessions (<10s)
                    conn.execute("DELETE FROM reading_sessions WHERE id = ?", (s["session_id"],))
                else:
                    conn.execute(
                        """
                        UPDATE reading_sessions
                        SET active_seconds = ?, ended_at = ?, end_progress = ?
                        WHERE id = ?
                        """,
                        (total_sec, now_iso, prog, s["session_id"]),
                    )
        except Exception as exc:
            logger.warning("Failed to end session: %s", exc)


def delete_all_reading_sessions(conn: sqlite3.Connection) -> None:
    """Clear all recorded reading sessions."""
    with conn:
        conn.execute("DELETE FROM reading_sessions")

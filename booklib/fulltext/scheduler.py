"""
fulltext/scheduler.py – FullTextIndexScheduler and background IndexJob.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from booklib.config import FULLTEXT_DB_PATH
from booklib.extract.pool import run_in_extractor_sync
from booklib.fulltext.chunker import chunk_sections
from booklib.fulltext.extract import extract_document_sections
from booklib.fulltext.store import FullTextStore, get_fulltext_store
from booklib.jobs.manager import BaseJob, JobManager

logger = logging.getLogger(__name__)

DEFAULT_INDEX_LIMIT_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
MIN_DISK_FREE_BYTES = 2 * 1024 * 1024 * 1024        # 2 GB


def _extract_and_chunk_worker(file_path: str, format_str: str, book_id: int) -> dict[str, Any]:
    """Top-level function for execution in ExtractorPool."""
    res = extract_document_sections(file_path, format_str)
    chunks = chunk_sections(book_id, res["sections"])
    return {
        "chunks": chunks,
        "total_chars": res["total_chars"],
        "is_no_text": res["is_no_text"],
    }


class FullTextIndexJob(BaseJob):
    """Indexes a single book in the low-priority 'index' lane."""

    lane = "index"

    def __init__(self, book_id: int, file_path: str, format_str: str, store: FullTextStore, db_conn_supplier) -> None:
        super().__init__()
        self.book_id = book_id
        self.file_path = file_path
        self.format_str = format_str
        self.store = store
        self.db_conn_supplier = db_conn_supplier

    @property
    def name(self) -> str:
        return f"Index Book #{self.book_id}"

    def run(self) -> None:
        if self._cancelled:
            return

        conn = self.db_conn_supplier()
        if not conn:
            return

        with conn:
            conn.execute("UPDATE books SET fts_state = 'indexing' WHERE id = ?", (self.book_id,))

        try:
            # Run extraction and chunking in extractor process pool
            data = run_in_extractor_sync(
                _extract_and_chunk_worker,
                self.file_path,
                self.format_str,
                self.book_id,
                timeout=120,
            )

            chunks = data["chunks"]
            total_chars = data["total_chars"]
            is_no_text = data["is_no_text"]

            if not self._cancelled:
                self.store.store_book_chunks(self.book_id, chunks)

                state = "no_text" if is_no_text else "indexed"
                with conn:
                    conn.execute(
                        """
                        UPDATE books SET
                            fts_state = ?,
                            fts_version = 1,
                            fts_indexed_at = datetime('now'),
                            text_chars = ?
                        WHERE id = ?
                        """,
                        (state, total_chars, self.book_id),
                    )

        except Exception as exc:
            logger.warning("Indexing failed for book %d (%s): %s", self.book_id, self.file_path, exc)
            with conn:
                conn.execute(
                    "UPDATE books SET fts_state = 'failed', fts_indexed_at = datetime('now') WHERE id = ?",
                    (self.book_id,),
                )


class FullTextIndexScheduler(QObject):
    """
    Coordinates scheduling of book indexing jobs with pause rules and limits.
    """

    status_changed = Signal(str)  # pause reason or 'running' / 'idle'
    started_signal = Signal()
    stopped_signal = Signal()

    def __init__(
        self,
        db_conn_supplier=None,
        job_manager: JobManager | None = None,
        store: FullTextStore | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if callable(db_conn_supplier):
            self.db_conn_supplier = db_conn_supplier
        elif hasattr(db_conn_supplier, "conn"):
            self.db_conn_supplier = lambda: db_conn_supplier.conn
        elif hasattr(db_conn_supplier, "connect"):
            self.db_conn_supplier = lambda: db_conn_supplier.connect()
        else:
            self.db_conn_supplier = lambda: None

        if job_manager is None:
            from booklib.jobs.manager import JobManager
            self.job_manager = JobManager.instance() if hasattr(JobManager, "instance") else JobManager(parent=self)
        else:
            self.job_manager = job_manager

        self.store = store or get_fulltext_store()
        self.is_running = False

        self.limit_bytes = DEFAULT_INDEX_LIMIT_BYTES
        self.auto_trim_days = 0
        self.pause_on_battery = True
        self.is_rendering = False

        self._pause_reason: str | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(15000)  # Check queue every 15s
        self._timer.timeout.connect(self._on_tick)

    @property
    def pause_reason(self) -> str | None:
        return self._pause_reason

    def start(self) -> None:
        self.is_running = True
        self._timer.start()
        self.started_signal.emit()
        self._on_tick()

    def stop(self) -> None:
        self.is_running = False
        self._timer.stop()
        self.stopped_signal.emit()

    def set_rendering_active(self, active: bool) -> None:
        """Pause indexing while user actively interacts or renders in reader."""
        self.is_rendering = active

    def check_pause_conditions(self) -> str | None:
        """Evaluate system state and return pause reason or None."""
        # 1. Reader rendering
        if self.is_rendering:
            return "rendering"

        # 2. Battery status
        if self.pause_on_battery:
            try:
                import psutil
                batt = psutil.sensors_battery()
                if batt is not None and not batt.power_plugged:
                    return "battery"
            except Exception:
                pass

        # 3. Size limit check
        size = self.store.get_size_bytes()
        if size >= self.limit_bytes:
            return "size_limit"

        # 4. Low disk space check
        try:
            free = shutil.disk_usage(FULLTEXT_DB_PATH.parent).free
            if free < MIN_DISK_FREE_BYTES:
                return "low_space"
        except Exception:
            pass

        return None

    def _on_tick(self) -> None:
        # Check if already a job in the index lane
        if self.job_manager.has_pending_jobs(lane="index"):
            return

        reason = self.check_pause_conditions()
        if reason != self._pause_reason:
            self._pause_reason = reason
            self.status_changed.emit(reason or "running")

        if reason is not None:
            # Check if auto trim is enabled
            if reason == "size_limit" and self.auto_trim_days > 0:
                conn = self.db_conn_supplier()
                if conn:
                    trimmed = self.store.trim_old_index(conn, self.auto_trim_days)
                    if trimmed > 0:
                        logger.info("Auto-trimmed %d books from full-text index", trimmed)
            return

        # Fetch next book needing index
        conn = self.db_conn_supplier()
        if not conn:
            return

        row = conn.execute(
            """
            SELECT id, path, format FROM books
            WHERE (fts_state IS NULL OR fts_state = 'pending' OR fts_version < 1)
              AND (source = 'local' OR (source = 'gdrive' AND cached = 1))
            ORDER BY (last_opened_at IS NOT NULL) DESC, last_opened_at DESC, id ASC
            LIMIT 1
            """
        ).fetchone()

        if not row:
            return

        bid = row["id"]
        path = row["path"]
        fmt = row["format"]

        if Path(path).exists():
            job = FullTextIndexJob(
                book_id=bid,
                file_path=path,
                format_str=fmt,
                store=self.store,
                db_conn_supplier=self.db_conn_supplier,
            )
            self.job_manager.submit(job)


IndexScheduler = FullTextIndexScheduler

"""
scan_job.py – Scan job adapted for JobManager.
"""
from __future__ import annotations

import logging
from booklib.jobs.manager import BaseJob
from booklib.scanner.worker import ScanWorker

logger = logging.getLogger(__name__)


class ScanJob(BaseJob):
    """Encapsulates library scanning as a BaseJob."""

    def __init__(self, folders: list[dict], parent=None):
        super().__init__(name="Scanning Library", parent=parent)
        self.folders = folders
        self._worker: ScanWorker | None = None

    def cancel(self) -> None:
        super().cancel()
        if self._worker:
            self._worker.cancel()

    def run(self) -> None:
        self._worker = ScanWorker(self.folders)
        if self.is_cancelled():
            self._worker.cancel()

        def on_prog(done: int, total: int, cur_file: str) -> None:
            self.progress.emit(done, total, f"Scanning: {cur_file}")

        def on_err(path: str, msg: str) -> None:
            self.error.emit(path, msg)

        def on_book_processed(bid: int) -> None:
            self.data_changed.emit()

        self._worker.progress.connect(on_prog)
        self._worker.error.connect(on_err)
        self._worker.book_processed.connect(on_book_processed)

        # Run synchronously in this thread
        self._worker.run()
        summary = getattr(self._worker, "_summary", None)
        self.finished.emit(summary or {})

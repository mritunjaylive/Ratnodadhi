"""
backfill_job.py – Background job to compute quick_hash for existing books missing one.
"""
from __future__ import annotations

import logging
from pathlib import Path

from booklib.db.database import Database
from booklib.duplicates.hashing import compute_quick_hash
from booklib.jobs.manager import BaseJob

logger = logging.getLogger(__name__)


class QuickHashBackfillJob(BaseJob):
    """Computes quick_hash for books that lack it."""

    def __init__(self, parent=None):
        super().__init__(name="Preparing Library", parent=parent)

    def run(self) -> None:
        db = Database()
        conn = db.new_connection()
        try:
            rows = conn.execute(
                "SELECT id, path, size_bytes FROM books WHERE quick_hash IS NULL AND is_missing = 0"
            ).fetchall()

            total = len(rows)
            if total == 0:
                self.finished.emit({"total": 0, "completed": 0})
                return

            completed = 0
            for i, (bid, path, size) in enumerate(rows, 1):
                if self.is_cancelled():
                    break

                self.progress.emit(i, total, f"Preparing library, {i} of {total}")

                if Path(path).exists():
                    qhash = compute_quick_hash(path, size)
                    if qhash:
                        conn.execute("UPDATE books SET quick_hash = ? WHERE id = ?", (qhash, bid))
                        completed += 1

                if i % 25 == 0:
                    conn.commit()

            conn.commit()
            if completed > 0:
                self.data_changed.emit()
            self.finished.emit({"total": total, "completed": completed})
        finally:
            conn.close()

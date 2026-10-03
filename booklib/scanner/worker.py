"""
worker.py – background scan worker (QThread).

Emits Qt signals so the UI can display progress without freezing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from booklib.scanner.walker import walk_folder
from booklib.scanner.pipeline import process_file
from booklib.db.database import Database
from booklib.db.repository import Repository
from booklib.duplicates.hashing import compute_quick_hash

logger = logging.getLogger(__name__)


@dataclass
class ScanSummary:
    added: int = 0
    updated: int = 0
    relinked: int = 0
    unchanged: int = 0
    errors: int = 0
    missing_marked: int = 0


class ScanWorker(QThread):
    """
    Runs the scan in a background thread.

    Signals
    -------
    progress(done, total, current_file)
    book_processed(book_id)
    finished(summary)
    error(path, message)
    """

    progress = Signal(int, int, str)
    book_processed = Signal(int)
    finished = Signal(object)   # ScanSummary
    error = Signal(str, str)

    def __init__(self, folders: list[dict], parent=None) -> None:
        super().__init__(parent)
        self._folders = folders   # list of {id, path}
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        from booklib.config import SCAN_BATCH_SIZE

        summary = ScanSummary()
        self._summary = summary
        db = Database()
        conn = db.new_connection()
        repo = Repository(conn)

        try:
            for folder in self._folders:
                if self._cancel:
                    break
                folder_id = folder["id"]
                folder_path = folder["path"]

                if not Path(folder_path).is_dir():
                    logger.warning("Folder not found: %s", folder_path)
                    continue

                db_index = repo.get_folder_books_indexed(folder_id)
                walk = walk_folder(folder_path, db_index)

                # Mark missing
                if walk.missing:
                    repo.mark_missing(walk.missing)
                    conn.commit()
                    summary.missing_marked += len(walk.missing)

                summary.unchanged += len(walk.unchanged)

                # Relink moved / renamed files only if there are actually missing books in the database
                missing_count = repo.count_missing()
                remaining_new: list[tuple[str, int, float]] = []

                if missing_count > 0 and walk.new:
                    total_new = len(walk.new)
                    for idx, (path, size, mtime) in enumerate(walk.new):
                        if self._cancel:
                            break
                        if total_new > 50 and (idx % 50 == 0 or idx == 0):
                            self.progress.emit(idx + 1, total_new, f"Checking moved books: {Path(path).name}")
                        qhash = compute_quick_hash(path, size)
                        if qhash:
                            missing_ids = repo.find_missing_by_size_and_quick_hash(size, qhash)
                            if missing_ids:
                                target_id = missing_ids[0]
                                target_fn = Path(path).name
                                if len(missing_ids) > 1:
                                    for mid in missing_ids:
                                        r = repo.get_book_row(mid)
                                        if r and Path(r.path).name == target_fn:
                                            target_id = mid
                                            break
                                repo.relink_book(target_id, path, target_fn, folder_id, mtime, size)
                                summary.relinked += 1
                                self.book_processed.emit(target_id)
                                continue
                        remaining_new.append((path, size, mtime))
                else:
                    remaining_new = list(walk.new)

                files_to_process = remaining_new + walk.changed
                new_paths = {p for p, *_ in remaining_new}
                total = len(files_to_process)

                for i, (path, size, mtime) in enumerate(files_to_process):
                    if self._cancel:
                        break
                    self.progress.emit(i + 1, total, path)
                    try:
                        book_id = process_file(path, size, mtime, folder_id, repo, commit=False)
                        if book_id is not None:
                            if path in new_paths:
                                summary.added += 1
                            else:
                                summary.updated += 1
                            self.book_processed.emit(book_id)
                    except Exception as exc:
                        logger.error("Scan error for %s: %s", path, exc)
                        self.error.emit(path, str(exc))
                        summary.errors += 1

                    # Batch commit
                    if (i + 1) % SCAN_BATCH_SIZE == 0:
                        conn.commit()

                conn.commit()
                repo.update_folder_scanned(folder_id)

        except Exception as exc:
            logger.exception("ScanWorker encountered unexpected error: %s", exc)
            self.error.emit(str(folder.get("path", "")), str(exc))
        finally:
            conn.close()

        self._summary = summary
        self.finished.emit(summary)


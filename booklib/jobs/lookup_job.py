"""
lookup_job.py – Background job for single/bulk online metadata lookup.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Any
import uuid

import requests

from booklib.covers.custom import save_custom_cover
from booklib.db.database import Database
from booklib.jobs.manager import BaseJob
from booklib.metadata.isbn_scan import scan_pdf_isbn
from booklib.metadata.online.merge import apply_candidate
from booklib.metadata.online.models import Candidate
from booklib.metadata.online.service import OnlineLookupService

logger = logging.getLogger(__name__)


class OnlineLookupJob(BaseJob):
    """
    Looks up metadata online for a list of book IDs.
    Supports pause, cancel, automatic apply, review queue, and batch undo.
    """

    def __init__(
        self,
        book_ids: list[int],
        scan_pdf_isbns: bool = True,
        fill_mode: str = "fill_only",
        threshold: float = 0.90,
        margin: float = 0.10,
        google_api_key: str | None = None,
        batch_id: str | None = None,
        parent=None,
    ):
        super().__init__(name="Online Metadata Lookup", parent=parent)
        self.book_ids = book_ids
        self.scan_pdf_isbns = scan_pdf_isbns
        self.fill_mode = fill_mode
        self.threshold = threshold
        self.margin = margin
        self.google_api_key = google_api_key
        self.batch_id = batch_id or uuid.uuid4().hex

    def run(self) -> None:
        db = Database()
        conn = db.new_connection()
        service = OnlineLookupService(google_api_key=self.google_api_key, db_conn=conn)

        summary = {
            "batch_id": self.batch_id,
            "total": len(self.book_ids),
            "applied": 0,
            "review": 0,
            "not_found": 0,
            "errors": 0,
            "offline": False,
        }

        total = len(self.book_ids)
        try:
            for idx, book_id in enumerate(self.book_ids, 1):
                if self.is_cancelled():
                    break

                while self.is_paused():
                    if self.is_cancelled():
                        break
                    time.sleep(0.3)

                row = conn.execute(
                    """SELECT id, title, author, publisher, year, isbn, pages,
                              genre, language, format, path, cover_path, cover_source,
                              field_sources
                       FROM books WHERE id = ?""",
                    (book_id,),
                ).fetchone()

                if not row:
                    continue

                b_id, title, author, pub, year, isbn, pages, genre, lang, fmt, path, cpath, csource, fsources_raw = row
                self.progress.emit(idx, total, f"Looking up '{title or Path(path).name}' ({idx}/{total})")

                # Step 1: Scan PDF for ISBN if missing and requested
                if self.scan_pdf_isbns and fmt == "pdf" and not isbn and Path(path).exists():
                    try:
                        scanned = scan_pdf_isbn(path)
                        if scanned:
                            isbn = scanned
                            fsources = json.loads(fsources_raw) if fsources_raw else {}
                            fsources["isbn"] = "file:pdftext"
                            conn.execute(
                                "UPDATE books SET isbn = ?, field_sources = ? WHERE id = ?",
                                (isbn, json.dumps(fsources), book_id),
                            )
                            conn.commit()
                    except Exception as e:
                        logger.debug("PDF ISBN scan error on %s: %s", path, e)

                book_dict = {
                    "id": b_id,
                    "title": title,
                    "author": author,
                    "isbn": isbn,
                    "year": year,
                    "pages": pages,
                }

                # Step 2: Query service
                try:
                    decision, candidates = service.lookup(
                        book_dict, threshold=self.threshold, margin=self.margin
                    )
                except Exception as exc:
                    logger.warning("Lookup error for book %d: %s", book_id, exc)
                    summary["errors"] += 1
                    continue

                if decision == "offline":
                    summary["offline"] = True
                    self.error.emit("Network", "Internet appears offline. Halting lookup job.")
                    break

                # Step 3: Handle decision
                if decision == "apply" and candidates:
                    best = candidates[0]
                    apply_candidate(
                        conn,
                        book_id,
                        best,
                        batch_id=self.batch_id,
                        mode=self.fill_mode,
                    )
                    # If candidate has cover and book has placeholder, optionally download cover
                    if best.cover_url and (csource in ("placeholder", "file", None)):
                        try:
                            resp = requests.get(best.cover_url, timeout=10)
                            if resp.status_code == 200 and resp.content:
                                save_custom_cover(conn, book_id, resp.content, source="online")
                        except Exception as e:
                            logger.debug("Failed to download online cover for %d: %s", book_id, e)

                    summary["applied"] += 1
                    self.data_changed.emit()

                elif decision == "review" and candidates:
                    # Cache candidates
                    cand_dicts = [
                        {
                            "provider": c.provider,
                            "provider_id": c.provider_id,
                            "title": c.title,
                            "authors": c.authors,
                            "publisher": c.publisher,
                            "year": c.year,
                            "isbn": c.isbn,
                            "pages": c.pages,
                            "genres": c.genres,
                            "language": c.language,
                            "description": c.description,
                            "edition": c.edition,
                            "cover_url": c.cover_url,
                            "matched_by": c.matched_by,
                            "score": c.score,
                        }
                        for c in candidates
                    ]
                    cache_key = f"cand:{book_id}"
                    conn.execute(
                        "INSERT OR REPLACE INTO online_cache (cache_key, provider, response, fetched_at) VALUES (?, ?, ?, datetime('now'))",
                        (cache_key, "aggregated", json.dumps(cand_dicts)),
                    )
                    conn.execute(
                        "UPDATE books SET lookup_status = 'review', lookup_at = datetime('now') WHERE id = ?",
                        (book_id,),
                    )
                    summary["review"] += 1
                    self.data_changed.emit()

                else:  # not_found
                    conn.execute(
                        "UPDATE books SET lookup_status = 'not_found', lookup_at = datetime('now') WHERE id = ?",
                        (book_id,),
                    )
                    summary["not_found"] += 1

                if idx % 10 == 0:
                    conn.commit()

            conn.commit()
            self.finished.emit(summary)
        finally:
            conn.close()

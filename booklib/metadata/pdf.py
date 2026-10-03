"""
pdf.py – PDF metadata and cover extractor using PyMuPDF.
"""
from __future__ import annotations

import logging

from booklib.metadata.base import BookMeta
from booklib.metadata.filename import is_junk_title, validate_year

logger = logging.getLogger(__name__)


def extract(path: str) -> BookMeta:
    meta = BookMeta()
    try:
        import pymupdf  # type: ignore
    except ImportError:
        logger.error("pymupdf not installed; PDF metadata unavailable")
        return meta

    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        logger.warning("Cannot open PDF %s: %s", path, exc)
        return meta

    try:
        # ── Encrypted / unreadable ────────────────────────────────────────────
        if doc.is_encrypted:
            if not doc.authenticate(""):
                logger.info("Password-protected PDF, skipping metadata: %s", path)
                return meta

        # ── Page count ────────────────────────────────────────────────────────
        meta.pages = doc.page_count

        # ── Metadata dict ─────────────────────────────────────────────────────
        info = doc.metadata or {}
        raw_title = info.get("title", "").strip() or None
        if raw_title and not is_junk_title(raw_title):
            meta.title = raw_title

        raw_author = info.get("author", "").strip() or None
        meta.author = raw_author or None

        # Creation date as a weak year fallback
        creation_date = info.get("creationDate", "") or ""
        meta.year = validate_year(creation_date)

        # ── Cover: render page 0 ──────────────────────────────────────────────
        if doc.page_count > 0:
            page = doc[0]
            # Scale so that width ≈ 300 px
            scale = 300 / max(page.rect.width, 1)
            mat = pymupdf.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            meta.cover_bytes = pix.tobytes("jpeg")

    except Exception as exc:
        logger.warning("PDF extraction error for %s: %s", path, exc)
    finally:
        doc.close()

    return meta

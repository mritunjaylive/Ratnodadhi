"""
extract.py – dispatches metadata extraction by file format.

This is the single entry point for the scan pipeline.
It never raises; errors are logged and a partial BookMeta is returned.
"""
from __future__ import annotations

import logging
from pathlib import Path

from booklib.metadata.base import BookMeta
from booklib.metadata.filename import is_junk_title, parse_filename

logger = logging.getLogger(__name__)


def extract_metadata(path: str, fmt: str) -> BookMeta:
    """
    Return a BookMeta for *path*.

    *fmt* is a lowercase format string: 'pdf', 'epub', 'cbz', etc.
    Never raises.
    """
    meta = BookMeta()
    try:
        if fmt == "epub":
            from booklib.metadata import epub
            meta = epub.extract(path)
        elif fmt == "pdf":
            from booklib.metadata import pdf
            meta = pdf.extract(path)
        elif fmt == "cbz":
            meta = _extract_cbz(path)
        # mobi, azw3, djvu, txt – filename only
    except Exception as exc:
        logger.warning("Unhandled error extracting %s (%s): %s", path, fmt, exc)

    # ── Gap-filling with filename ────────────────────────────────────────────
    stem = Path(path).stem
    fn_author, fn_title = parse_filename(stem)

    if is_junk_title(meta.title):
        meta.title = fn_title
    if not meta.author:
        meta.author = fn_author

    # Final fallback: use stem as title
    if is_junk_title(meta.title):
        meta.title = stem.replace("_", " ").strip() or None

    return meta


def _extract_cbz(path: str) -> BookMeta:
    """Use the alphabetically first image in the archive as the cover."""
    import zipfile

    meta = BookMeta()
    _IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    try:
        with zipfile.ZipFile(path, "r") as zf:
            images = sorted(
                n for n in zf.namelist()
                if Path(n).suffix.lower() in _IMAGE_EXTS
            )
            if images:
                meta.cover_bytes = zf.read(images[0])
    except Exception as exc:
        logger.warning("CBZ extraction error for %s: %s", path, exc)
    return meta

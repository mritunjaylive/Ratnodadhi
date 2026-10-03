"""
fulltext/extract.py – Background text extraction for all supported book formats.
Designed to be executed within ExtractorPool worker processes.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from booklib.fulltext.normalize import normalize_text

logger = logging.getLogger(__name__)


def extract_document_sections(file_path: str, format_str: str) -> dict[str, Any]:
    """
    Extract structured page/chapter text from a document file.
    Top-level picklable function for execution in ExtractorPool.

    Returns dict:
    {
        "sections": [{"page": int, "chapter": int, "text": str}],
        "total_chars": int,
        "is_no_text": bool,
    }
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Book file does not exist: {file_path}")

    fmt = (format_str or p.suffix.lstrip(".")).lower()
    sections: list[dict[str, Any]] = []
    total_chars = 0

    if fmt == "txt":
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = p.read_text(encoding="latin-1", errors="replace")

        norm = normalize_text(content)
        total_chars = len(norm)
        # Split into pseudo-pages of ~3000 chars
        page_size = 3000
        for i in range(0, max(1, len(norm)), page_size):
            sec_text = norm[i : i + page_size]
            sections.append({
                "page": i // page_size,
                "chapter": 0,
                "text": sec_text,
            })

    elif fmt in ("pdf", "epub", "mobi", "azw3", "fb2"):
        doc = fitz.open(str(p))
        try:
            page_count = len(doc)
            for pno in range(page_count):
                page = doc[pno]
                raw_text = page.get_text("text") or ""
                norm = normalize_text(raw_text)
                if norm:
                    total_chars += len(norm)
                    sections.append({
                        "page": pno,
                        "chapter": 0,
                        "text": norm,
                    })
        finally:
            doc.close()

    elif fmt == "cbz":
        # Comic books: image archive, typically no text layer
        pass

    is_no_text = (total_chars < 100)
    return {
        "sections": sections,
        "total_chars": total_chars,
        "is_no_text": is_no_text,
    }

"""
isbn_scan.py – Extract ISBNs from PDF text layer (front copyright & back pages) using PyMuPDF.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Tolerant regex for ISBN mentions
_ISBN_PATTERN = re.compile(
    r'\bISBN(?:-1[03])?\s*[:#\-]?\s*([0-9Xx\s\-]{10,25})\b',
    re.IGNORECASE
)


def validate_isbn_10(isbn: str) -> bool:
    """Validate checksum for a 10-character string (digits, ending in 0-9 or X)."""
    if len(isbn) != 10:
        return False
    if not (isbn[:9].isdigit() and (isbn[9].isdigit() or isbn[9].upper() == 'X')):
        return False
    total = 0
    for i in range(9):
        total += (10 - i) * int(isbn[i])
    total += 10 if isbn[9].upper() == 'X' else int(isbn[9])
    return total % 11 == 0


def validate_isbn_13(isbn: str) -> bool:
    """Validate checksum for a 13-character string of digits."""
    if len(isbn) != 13 or not isbn.isdigit():
        return False
    total = 0
    for i, ch in enumerate(isbn):
        weight = 1 if i % 2 == 0 else 3
        total += weight * int(ch)
    return total % 10 == 0


def isbn_10_to_13(isbn10: str) -> str:
    """Convert valid ISBN-10 to ISBN-13 with 978 prefix."""
    core = "978" + isbn10[:9]
    total = sum((1 if i % 2 == 0 else 3) * int(d) for i, d in enumerate(core))
    check = (10 - (total % 10)) % 10
    return core + str(check)


def clean_isbn(raw: str) -> str | None:
    """
    Clean raw candidate string and return normalized 10 or 13 char ISBN if valid, else None.
    """
    if not raw:
        return None
    s = re.sub(r'^(?:ISBN(?:-1[03])?[\s:#\-]*)', '', raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r'[\s\-]+', '', s)
    if len(cleaned) == 10 and validate_isbn_10(cleaned):
        return cleaned.upper()
    if len(cleaned) == 13 and validate_isbn_13(cleaned):
        return cleaned
    return None


def scan_pdf_isbn(path: str | Path) -> str | None:
    """
    Extract text from first 12 and last 4 pages of a PDF to find a valid ISBN.
    Prefers ISBN-13, and prefers the one closest to 'ebook' or 'pdf'.
    Returns normalized ISBN (string) or None.
    """
    try:
        import pymupdf  # type: ignore
    except ImportError:
        logger.warning("pymupdf not installed; cannot scan PDF text for ISBN")
        return None

    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        logger.debug("Failed to open PDF for ISBN scan: %s: %s", path, exc)
        return None

    try:
        if doc.is_encrypted and not doc.authenticate(""):
            return None

        total_pages = doc.page_count
        if total_pages == 0:
            return None

        # Pages to scan: first 12 pages, then last 4 pages
        pages_to_check: list[int] = []
        for i in range(min(12, total_pages)):
            pages_to_check.append(i)
        for i in range(max(0, total_pages - 4), total_pages):
            if i not in pages_to_check:
                pages_to_check.append(i)

        for page_idx in pages_to_check:
            try:
                page = doc[page_idx]
                text = page.get_text()
            except Exception:
                continue

            if not text:
                continue

            # Look for ISBN matches in this page
            matches = list(_ISBN_PATTERN.finditer(text))
            if not matches:
                continue

            candidates: list[dict] = []
            lower_text = text.lower()
            keyword_positions = [m.start() for m in re.finditer(r'\b(?:ebook|e-book|pdf)\b', lower_text)]

            for m in matches:
                raw_val = m.group(1)
                valid = clean_isbn(raw_val)
                if not valid:
                    continue

                start_pos = m.start()
                # Calculate distance to nearest ebook/pdf keyword
                if keyword_positions:
                    min_dist = min(abs(start_pos - kp) for kp in keyword_positions)
                else:
                    min_dist = float('inf')

                is_13 = len(valid) == 13
                candidates.append({
                    "isbn": valid,
                    "is_13": is_13,
                    "dist": min_dist,
                    "pos": start_pos,
                })

            if candidates:
                # Prefer closest to ebook/pdf if keyword present, and prefer ISBN-13
                candidates.sort(key=lambda c: (c["dist"], not c["is_13"], c["pos"]))
                best_isbn = candidates[0]["isbn"]
                # Convert ISBN-10 to ISBN-13 for consistency if desired, or prefer ISBN-13
                if len(best_isbn) == 10:
                    best_isbn = isbn_10_to_13(best_isbn)
                return best_isbn

    except Exception as exc:
        logger.warning("Error scanning PDF text for ISBN in %s: %s", path, exc)
    finally:
        try:
            doc.close()
        except Exception:
            pass

    return None

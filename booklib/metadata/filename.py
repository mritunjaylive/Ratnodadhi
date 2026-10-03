"""
filename.py – filename-based metadata extraction and junk-title detection.
"""
from __future__ import annotations

import re
from datetime import datetime


# Noise tokens often appended by sites like Z-lib, Libgen, PDFDrive.
_NOISE_PATTERNS = [
    r"\(z-lib(?:rary)?\.org\)",
    r"\[?PDFDrive\]?",
    r"\bLibGen\b",
    r"\bpdf\b",
    r"\bz-lib\b",
    r"\bepub\b",
    r"www\.\S+",
]
_NOISE_RE = re.compile(
    "|".join(_NOISE_PATTERNS), re.IGNORECASE
)

_AUTHOR_TITLE_RE = re.compile(r"^(.{1,60}?)\s+-\s+(.+)$")

_CURRENT_YEAR = datetime.now().year


def is_junk_title(title: str | None) -> bool:
    """Return True if title is blank, generic, or auto-generated."""
    if not title:
        return True
    t = title.strip().lower()
    if not t:
        return True
    from booklib.config import JUNK_TITLE_PREFIXES, JUNK_TITLE_SUFFIXES
    for pfx in JUNK_TITLE_PREFIXES:
        if t.startswith(pfx):
            return True
    for sfx in JUNK_TITLE_SUFFIXES:
        if t.endswith(sfx):
            return True
    return False


def clean_name(name: str) -> str:
    """Strip extension noise, underscores, and site watermarks."""
    # Remove extension if present
    name = re.sub(r"\.[a-z0-9]{2,5}$", "", name, flags=re.IGNORECASE)
    # Replace underscores with spaces
    name = name.replace("_", " ")
    # Remove noise tokens
    name = _NOISE_RE.sub("", name)
    # Collapse multiple spaces
    name = re.sub(r" {2,}", " ", name).strip()
    return name


def parse_filename(filename: str) -> tuple[str | None, str | None]:
    """
    Return (author, title) from a bare filename (no extension).

    Heuristic: if the name matches ``Author - Title`` (author part < 60 chars,
    not purely numeric), split it; otherwise the whole name is the title.
    """
    cleaned = clean_name(filename)
    m = _AUTHOR_TITLE_RE.match(cleaned)
    if m:
        left, right = m.group(1).strip(), m.group(2).strip()
        if left and not left.isdigit():
            return left, right or None
    return None, cleaned or None


def validate_year(year_str: str | None) -> int | None:
    """Extract a 4-digit year within a plausible range.

    Handles plain year strings, PDF creation dates (D:20191105…), and
    arbitrary strings containing embedded years.
    """
    if not year_str:
        return None
    # Try every 4-digit run in the string (non-overlapping, left to right)
    for m in re.finditer(r"\d{4}", year_str):
        y = int(m.group())
        if 1000 <= y <= _CURRENT_YEAR:
            return y
    return None


def _luhn10(isbn: str) -> bool:
    total = sum((10 - i) * int(d) for i, d in enumerate(isbn[:9]))
    check = isbn[9]
    remainder = total % 11
    expected = "X" if remainder == 1 else str((11 - remainder) % 11)
    return check.upper() == expected


def _luhn13(isbn: str) -> bool:
    total = sum(
        int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(isbn[:12])
    )
    check = (10 - (total % 10)) % 10
    return check == int(isbn[12])


def validate_isbn(raw: str | None) -> str | None:
    """Strip formatting, validate checksum, return clean ISBN or None."""
    if not raw:
        return None
    # Remove the urn:isbn: prefix if present
    raw = re.sub(r"^urn:isbn:", "", raw, flags=re.IGNORECASE)
    # Keep only digits and X
    digits = re.sub(r"[^0-9Xx]", "", raw)
    if len(digits) == 10 and _luhn10(digits):
        return digits
    if len(digits) == 13 and _luhn13(digits):
        return digits
    return None

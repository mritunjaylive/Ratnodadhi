"""
fulltext/normalize.py – Text normalization for indexing, chunking and searching.
"""
from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str) -> str:
    """
    Normalize text for indexing and retrieval:
    1. Unicode NFKC normalization.
    2. Rejoin line-end hyphenated words across line breaks (e.g. 'archi-\\ntecture' -> 'architecture').
    3. Remove non-printable control characters while retaining standard whitespace.
    4. Normalize excessive whitespace and multiple blank lines.
    """
    if not text:
        return ""

    # 1. Unicode NFKC
    n = unicodedata.normalize("NFKC", text)

    # 2. Join hyphenated words split across newlines: word- \n word
    n = re.sub(r"(\b\w+)[-\u2010\u2013]\s*\r?\n\s*(\w+\b)", r"\1\2", n)

    # 3. Filter control characters except \n and \t
    chars = []
    for ch in n:
        if ch in ("\n", "\t", " "):
            chars.append(ch)
        elif not unicodedata.category(ch).startswith("C"):
            chars.append(ch)
    n = "".join(chars)

    # 4. Collapse inline whitespace
    n = re.sub(r"[ \t\f\v]+", " ", n)

    # 5. Limit consecutive newlines to at most 2 (paragraphs)
    n = re.sub(r"\n{3,}", "\n\n", n)

    return n.strip()

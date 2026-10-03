"""
models.py – Candidate dataclass for online book metadata.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidate:
    provider: str                  # 'openlibrary' | 'googlebooks'
    provider_id: str               # work/edition key or volume id
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    publisher: str | None = None
    year: int | None = None
    isbn: str | None = None        # ISBN-13 preferred
    pages: int | None = None
    genres: list[str] = field(default_factory=list)
    language: str | None = None
    description: str | None = None
    edition: str | None = None
    cover_url: str | None = None
    matched_by: str = "title_author"  # 'isbn' | 'title_author'
    score: float = 0.0             # filled by scoring.py

"""
base.py – BookMeta dataclass shared by all metadata extractors.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BookMeta:
    title: str | None = None
    author: str | None = None
    publisher: str | None = None
    year: int | None = None
    isbn: str | None = None
    pages: int | None = None
    genre: str | None = None
    language: str | None = None
    description: str | None = None
    series: str | None = None
    series_index: float | None = None
    cover_bytes: bytes | None = None   # raw image data if found

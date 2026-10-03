"""
query.py – LibraryQuery dataclass and FTS query builder.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


VALID_SORT_FIELDS = frozenset({
    "title", "author", "year", "size_bytes", "format",
    "pages", "date_added", "last_opened_at", "status", "rating",
    "series", "progress", "source",
})

VALID_STATUSES = frozenset({"want", "reading", "read", "none"})


@dataclass
class LibraryQuery:
    search: str = ""
    statuses: set[str] = field(default_factory=set)   # 'want','reading','read','none'
    formats: set[str] = field(default_factory=set)
    authors: set[str] = field(default_factory=set)
    genres: set[str] = field(default_factory=set)
    languages: set[str] = field(default_factory=set)
    min_rating: int | None = None
    shelf: str | None = None          # None | 'continue' | 'recent' | 'needs_review' | 'incomplete'
    sort_field: str = "title"
    sort_desc: bool = False
    include_missing: bool = False
    # v3 organization & enrichment filters
    tag_ids: set[int] = field(default_factory=set)
    tag_mode: str = "any"             # 'any' | 'all'
    collection_id: int | None = None
    series_id: int | None = None
    lookup_status: str | None = None  # None | 'applied' | 'review' | 'not_found' | 'skipped'
    incomplete: bool = False
    # v4 cloud & source filters
    sources: set[str] = field(default_factory=set)    # 'local', 'drive'
    offline_only: bool = False
    drive_folder_id: int | None = None
    # v6 in-book search and subset filtering
    book_ids: set[int] = field(default_factory=set)

    def is_empty(self) -> bool:
        """True when no filters/search are active (shows all books)."""
        return (
            not self.search
            and not self.statuses
            and not self.formats
            and not self.authors
            and not self.genres
            and not self.languages
            and self.min_rating is None
            and self.shelf is None
            and not self.tag_ids
            and self.collection_id is None
            and self.series_id is None
            and self.lookup_status is None
            and not self.incomplete
            and not self.sources
            and not self.offline_only
            and self.drive_folder_id is None
            and not self.book_ids
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-friendly dictionary with versioning for smart collections."""
        return {
            "v": 1,
            "search": self.search,
            "statuses": sorted(self.statuses),
            "formats": sorted(self.formats),
            "authors": sorted(self.authors),
            "genres": sorted(self.genres),
            "languages": sorted(self.languages),
            "min_rating": self.min_rating,
            "shelf": self.shelf,
            "sort_field": self.sort_field,
            "sort_desc": self.sort_desc,
            "include_missing": self.include_missing,
            "tag_ids": sorted(self.tag_ids),
            "tag_mode": self.tag_mode,
            "collection_id": self.collection_id,
            "series_id": self.series_id,
            "lookup_status": self.lookup_status,
            "incomplete": self.incomplete,
            "sources": sorted(self.sources),
            "offline_only": self.offline_only,
            "drive_folder_id": self.drive_folder_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LibraryQuery:
        """Deserialize from dictionary, gracefully ignoring unknown keys."""
        if not isinstance(data, dict):
            return cls()
        return cls(
            search=str(data.get("search", "")),
            statuses=set(data.get("statuses", [])),
            formats=set(data.get("formats", [])),
            authors=set(data.get("authors", [])),
            genres=set(data.get("genres", [])),
            languages=set(data.get("languages", [])),
            min_rating=data.get("min_rating"),
            shelf=data.get("shelf"),
            sort_field=str(data.get("sort_field", "title")),
            sort_desc=bool(data.get("sort_desc", False)),
            include_missing=bool(data.get("include_missing", False)),
            tag_ids={int(t) for t in data.get("tag_ids", [])},
            tag_mode=str(data.get("tag_mode", "any")),
            collection_id=data.get("collection_id"),
            series_id=data.get("series_id"),
            lookup_status=data.get("lookup_status"),
            incomplete=bool(data.get("incomplete", False)),
            sources=set(data.get("sources", [])),
            offline_only=bool(data.get("offline_only", False)),
            drive_folder_id=data.get("drive_folder_id"),
        )


def build_fts_query(text: str) -> str | None:
    """
    Convert user input to a safe FTS5 MATCH expression.

    Returns None if there are no usable tokens (= no search).
    All tokens are prefix-matched and required (AND logic).
    Supports all Unicode scripts and preserves combining marks.
    """
    tokens = re.findall(r'[^\s!"#$%&\'()*+,-./:;<=>?@\[\\\]^_`{|}~]+', text)
    tokens = [t.strip() for t in tokens if t.strip()]
    if not tokens:
        return None
    return " ".join(f'"{t}"*' for t in tokens)

"""
porting/mapping.py – Column mapping and presets for CSV import.

Presets:
  - booklib:    identity mapping for our own CSV columns
  - goodreads:  maps Goodreads export columns to BookLib fields
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnMapping:
    """Maps source CSV column names → BookLib field names."""
    title:       str = ""
    author:      str = ""
    isbn:        str = ""
    year:        str = ""
    publisher:   str = ""
    pages:       str = ""
    genre:       str = ""
    language:    str = ""
    status:      str = ""
    rating:      str = ""
    notes:       str = ""
    tags:        str = ""
    series:      str = ""
    series_index: str = ""
    date_added:  str = ""
    started_on:  str = ""
    finished_on: str = ""
    description: str = ""


# Built-in presets
GOODREADS_MAPPING = ColumnMapping(
    title="Title",
    author="Author",
    isbn="ISBN13",
    year="Year Published",
    publisher="Publisher",
    pages="Number of Pages",
    status="Exclusive Shelf",
    rating="My Rating",
    notes="My Review",
    tags="Bookshelves",
    finished_on="Date Read",
)

BOOKLIB_MAPPING = ColumnMapping(
    title="title",
    author="author",
    isbn="isbn",
    year="year",
    publisher="publisher",
    pages="pages",
    genre="genre",
    language="language",
    status="status",
    rating="rating",
    notes="notes",
    tags="tags",
    series="series",
    series_index="series_index",
    date_added="date_added",
    started_on="started_on",
    finished_on="finished_on",
    description="description",
)

PRESETS: dict[str, ColumnMapping] = {
    "booklib": BOOKLIB_MAPPING,
    "goodreads": GOODREADS_MAPPING,
}


def apply_mapping(raw_row: dict[str, str], mapping: ColumnMapping) -> dict[str, Any]:
    """
    Apply *mapping* to a raw CSV row dict.
    Returns a normalized BookLib field dict.
    Handles Goodreads-specific quirks (ISBN `="..."`, rating 0 = unrated,
    shelf name translation, Date Read extraction).
    """
    out: dict[str, Any] = {}

    def get(col: str) -> str:
        if not col:
            return ""
        return raw_row.get(col, "").strip()

    def set_if(key: str, val: Any) -> None:
        if val is not None and val != "":
            out[key] = val

    # Core metadata
    set_if("title", get(mapping.title) or None)
    set_if("author", get(mapping.author) or None)
    set_if("publisher", get(mapping.publisher) or None)
    set_if("genre", get(mapping.genre) or None)
    set_if("language", get(mapping.language) or None)
    set_if("description", get(mapping.description) or None)

    # Year
    year_raw = get(mapping.year)
    if year_raw and year_raw.isdigit():
        set_if("year", int(year_raw))

    # Pages
    pages_raw = get(mapping.pages)
    if pages_raw and pages_raw.isdigit():
        set_if("pages", int(pages_raw))

    # ISBN – strip Goodreads ="…" wrapper
    isbn_raw = get(mapping.isbn)
    isbn_raw = isbn_raw.strip('="').strip('"').strip("'")
    isbn_raw = isbn_raw.replace("-", "").replace(" ", "")
    if isbn_raw and isbn_raw.isdigit() and len(isbn_raw) in (10, 13):
        set_if("isbn", isbn_raw)

    # Status – translate Goodreads shelf names
    status_raw = get(mapping.status)
    status_map = {
        "to-read": "want",
        "currently-reading": "reading",
        "read": "read",
        "want": "want",
        "reading": "reading",
    }
    status = status_map.get(status_raw.lower(), "")
    set_if("status", status or None)

    # Rating – Goodreads 0 means unrated
    rating_raw = get(mapping.rating)
    try:
        rating = int(rating_raw)
        if rating > 0:
            set_if("rating", rating)
    except (ValueError, TypeError):
        pass

    # Notes – Goodreads: prefix with "Goodreads review: "
    notes_raw = get(mapping.notes)
    if notes_raw:
        if mapping == GOODREADS_MAPPING:
            set_if("notes", f"Goodreads review: {notes_raw}")
        else:
            set_if("notes", notes_raw)

    # Tags – Goodreads bookshelves (semicolon separated)
    tags_raw = get(mapping.tags)
    if tags_raw:
        tags = [t.strip() for t in tags_raw.replace(",", ";").split(";") if t.strip()]
        if tags:
            set_if("tags", tags)

    # Series
    set_if("series", get(mapping.series) or None)
    si_raw = get(mapping.series_index)
    try:
        set_if("series_index", float(si_raw) if si_raw else None)
    except ValueError:
        pass

    # Dates
    set_if("date_added", get(mapping.date_added) or None)
    set_if("started_on", get(mapping.started_on) or None)
    set_if("finished_on", get(mapping.finished_on) or None)

    return out

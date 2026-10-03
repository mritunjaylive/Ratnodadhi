"""
porting/import_reader.py – Detect, decode and parse import files.

Supported types:
  - BookLib JSON (format == "booklib-export")
  - BookLib CSV (header matches BASIC_FIELDS)
  - Goodreads CSV (header contains "Exclusive Shelf")
  - Generic CSV (anything else)

Returns a ParseResult with detected type, headers (for CSV), and rows.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_FILE_SIZE = 50 * 1024 * 1024   # 50 MB

GOODREADS_SIGNATURE = {"Exclusive Shelf", "My Rating", "Date Read"}
BOOKLIB_CSV_SIGNATURE = {"title", "author", "isbn", "format", "status"}


@dataclass
class ParseResult:
    kind: str               # 'booklib_json' | 'booklib_csv' | 'goodreads_csv' | 'csv'
    headers: list[str]      # column names (empty for JSON)
    rows: list[dict]        # one dict per data row
    raw_collections: list[dict] = field(default_factory=list)  # for booklib_json
    error: str = ""


def detect_and_parse(file_path: Path) -> ParseResult:
    """Detect the file type and parse it. Raises ValueError on fatal errors."""
    if file_path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(
            f"File is too large ({file_path.stat().st_size // (1024*1024)} MB). "
            "Maximum supported size is 50 MB."
        )

    raw = _read_bytes(file_path)
    text = _decode(raw)

    ext = file_path.suffix.lower()

    # Try JSON first
    if ext == ".json":
        return _parse_json(text)

    # CSV
    return _parse_csv(text, file_path)


def _read_bytes(path: Path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _decode(raw: bytes) -> str:
    """Try UTF-8 with BOM, UTF-8, UTF-16, then Windows-1252."""
    for enc in ("utf-8-sig", "utf-8", "utf-16", "windows-1252"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError("Could not decode the file (tried UTF-8, UTF-16, Windows-1252).")


def _parse_json(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return ParseResult("csv", [], [], error=f"JSON parse error: {exc}")

    if not isinstance(data, dict) or data.get("format") != "booklib-export":
        return ParseResult("csv", [], [], error="Not a BookLib JSON export file.")

    books = data.get("books", [])
    cols = data.get("collections", [])
    return ParseResult("booklib_json", [], books, raw_collections=cols)


def _parse_csv(text: str, path: Path) -> ParseResult:
    reader = csv.DictReader(io.StringIO(text))
    try:
        headers = reader.fieldnames or []
    except Exception as exc:
        return ParseResult("csv", [], [], error=str(exc))

    header_set = {h.strip() for h in headers}

    # Detect type from headers
    if GOODREADS_SIGNATURE <= header_set:
        kind = "goodreads_csv"
    elif BOOKLIB_CSV_SIGNATURE <= {h.lower() for h in header_set}:
        kind = "booklib_csv"
    else:
        kind = "csv"

    rows = []
    for i, row in enumerate(reader):
        try:
            rows.append({k.strip(): v for k, v in row.items()})
        except Exception as exc:
            return ParseResult(kind, list(headers), rows,
                               error=f"Parse error at row {i + 2}: {exc}")

    return ParseResult(kind, list(headers), rows)

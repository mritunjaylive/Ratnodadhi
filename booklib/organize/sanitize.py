"""
organize/sanitize.py – Make file-system-safe names from metadata values.

Rules (applied per path component, not to the full path):
- Replace Windows-illegal characters: < > : " / \\ | ? * and control chars (U+0000–U+001F)
- Replace / inside metadata with - so it never creates folders by accident
- Strip leading/trailing spaces and trailing dots
- Collapse repeated spaces
- Normalize Unicode to NFC
- Avoid Windows reserved names (CON, PRN, AUX, NUL, COM1-COM9, LPT1-LPT9)
  by appending an underscore
- Component length: at most MAX_COMPONENT chars
- Full path: at most MAX_PATH chars; shorten title first, then author
"""
from __future__ import annotations

import re
import unicodedata

# Configurable limits (characters, not bytes)
MAX_COMPONENT = 120
MAX_PATH = 240

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_SPACE = re.compile(r' {2,}')
_TRAILING = re.compile(r'[\s.]+$')

_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})


def sanitize_component(name: str, is_folder: bool = False) -> str:
    """
    Make a single path component (file name or folder name) safe.

    - Slashes inside the value are replaced with a hyphen (they'd create
      unwanted folders; the planner keeps folder-pattern slashes separate).
    - Returns empty string if nothing remains after sanitizing.
    """
    if not name:
        return ""

    # Normalize Unicode
    name = unicodedata.normalize("NFC", name)

    # Replace slashes in metadata with hyphens (unless processing a folder separator)
    if not is_folder:
        name = name.replace("/", "-").replace("\\", "-")

    # Replace illegal characters with a space
    name = _ILLEGAL.sub(" ", name)

    # Collapse spaces, strip leading/trailing spaces and trailing dots
    name = _MULTI_SPACE.sub(" ", name).strip()
    name = _TRAILING.sub("", name)

    # Avoid reserved names (case-insensitive, with or without extension)
    stem = name.split(".")[0].upper()
    if stem in _RESERVED:
        name = name + "_"

    # Truncate at word boundary
    if len(name) > MAX_COMPONENT:
        name = _shorten(name, MAX_COMPONENT)

    return name


def sanitize_filename(name: str, ext: str) -> str:
    """
    Sanitize a file name (stem only, extension handled separately).
    Returns stem + '.' + ext.lower() (ext without leading dot).
    """
    stem = sanitize_component(name)
    ext = ext.lstrip(".").lower()
    if not stem:
        return f"unnamed.{ext}"
    return f"{stem}.{ext}"


def _shorten(text: str, limit: int) -> str:
    """Shorten *text* to at most *limit* characters at the last word boundary."""
    if len(text) <= limit:
        return text
    truncated = text[:limit]
    last_space = truncated.rfind(" ")
    if last_space > limit // 2:
        return truncated[:last_space].rstrip(" .")
    return truncated.rstrip(" .")


def shorten_for_path(stem: str, ext: str, max_path: int = MAX_PATH, prefix: str = "") -> tuple[str, bool]:
    """
    Ensure prefix + stem + '.' + ext fits within max_path.
    Returns (new_stem, was_shortened).
    """
    full = f"{prefix}{stem}.{ext}"
    if len(full) <= max_path:
        return stem, False
    available = max_path - len(prefix) - len(ext) - 1  # -1 for dot
    if available <= 0:
        return stem[:10], True
    new_stem = _shorten(stem, available)
    return new_stem, True

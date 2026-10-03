"""
format.py – human-readable formatting helpers.
"""
from __future__ import annotations


def human_size(size_bytes: int | None) -> str:
    """Return a human-readable file size string, e.g. '4.2 MB'."""
    if size_bytes is None:
        return "—"
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    for unit in units[:-1]:
        if value < 1024:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} {units[-1]}"


def dash_if_none(value) -> str:
    """Return '—' for None/empty values, otherwise str(value)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "—"
    return str(value)

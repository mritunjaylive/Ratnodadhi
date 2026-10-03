"""
reader/search.py – In-book search state and hit navigation.
"""
from __future__ import annotations

from booklib.reader.backend import Hit


class SearchState:
    """Tracks active search query, results, and active hit pointer."""

    def __init__(self) -> None:
        self.query: str = ""
        self.hits: list[Hit] = []
        self.current_idx: int = -1

    def set_results(self, query: str, hits: list[Hit]) -> None:
        self.query = query
        self.hits = hits
        self.current_idx = 0 if hits else -1

    def clear(self) -> None:
        self.query = ""
        self.hits.clear()
        self.current_idx = -1

    @property
    def total_count(self) -> int:
        return len(self.hits)

    @property
    def display_index(self) -> int:
        """1-based index of current hit for UI display."""
        return self.current_idx + 1 if self.current_idx >= 0 else 0

    def current_hit(self) -> Hit | None:
        if 0 <= self.current_idx < len(self.hits):
            return self.hits[self.current_idx]
        return None

    def next_hit(self) -> Hit | None:
        if not self.hits:
            return None
        self.current_idx = (self.current_idx + 1) % len(self.hits)
        return self.hits[self.current_idx]

    def prev_hit(self) -> Hit | None:
        if not self.hits:
            return None
        self.current_idx = (self.current_idx - 1 + len(self.hits)) % len(self.hits)
        return self.hits[self.current_idx]

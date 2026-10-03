"""
reader/textlayer.py – Text layer, hit-testing, selection, and copy with hyphen-rejoining.
"""
from __future__ import annotations

import math
import re
from typing import Any

from PySide6.QtGui import QGuiApplication

from booklib.reader.backend import DocumentBackend, TextWord


class TextLayer:
    """Manages word geometry and text selection for a document."""

    def __init__(self, backend: DocumentBackend) -> None:
        self.backend = backend
        self._words_cache: dict[int, list[TextWord]] = {}

    def get_words(self, page: int) -> list[TextWord]:
        """Fetch and cache words for a page."""
        if page not in self._words_cache:
            self._words_cache[page] = self.backend.words(page)
        return self._words_cache[page]

    def clear_cache(self) -> None:
        self._words_cache.clear()

    def hit_test(self, page: int, x: float, y: float) -> int | None:
        """Find the word index nearest to (x, y) on the page."""
        words = self.get_words(page)
        if not words:
            return None

        # Check direct containment first
        for i, w in enumerate(words):
            x0, y0, x1, y1 = w.rect
            if x0 <= x <= x1 and y0 <= y <= y1:
                return i

        # Nearest word by center distance
        best_idx = 0
        best_dist = float("inf")
        for i, w in enumerate(words):
            x0, y0, x1, y1 = w.rect
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            d = (cx - x) ** 2 + (cy - y) ** 2
            if d < best_dist:
                best_dist = d
                best_idx = i

        return best_idx

    def select_word(self, page: int, word_idx: int) -> tuple[int, int]:
        """Double-click selection: single word."""
        return (word_idx, word_idx)

    def select_line(self, page: int, word_idx: int) -> tuple[int, int]:
        """Triple-click selection: all words on the same line."""
        words = self.get_words(page)
        if not words or word_idx < 0 or word_idx >= len(words):
            return (word_idx, word_idx)

        target_block = words[word_idx].block_num
        target_line = words[word_idx].line_num

        start_idx = word_idx
        while start_idx > 0 and words[start_idx - 1].block_num == target_block and words[start_idx - 1].line_num == target_line:
            start_idx -= 1

        end_idx = word_idx
        while end_idx < len(words) - 1 and words[end_idx + 1].block_num == target_block and words[end_idx + 1].line_num == target_line:
            end_idx += 1

        return (start_idx, end_idx)

    def get_selection_text(self, page: int, start_idx: int, end_idx: int) -> str:
        """Extract clean text for selected word range with hyphen rejoining."""
        words = self.get_words(page)
        if not words:
            return ""

        s = min(start_idx, end_idx)
        e = max(start_idx, end_idx)
        s = max(0, min(s, len(words) - 1))
        e = max(0, min(e, len(words) - 1))

        tokens: list[str] = []
        cur_line = words[s].line_num
        cur_block = words[s].block_num

        for i in range(s, e + 1):
            w = words[i]
            if w.block_num != cur_block:
                tokens.append("\n\n")
                cur_block = w.block_num
                cur_line = w.line_num
            elif w.line_num != cur_line:
                tokens.append("\n")
                cur_line = w.line_num
            elif tokens:
                tokens.append(" ")
            tokens.append(w.text)

        text = "".join(tokens)
        # Rejoin hyphenated line endings: e.g. "com-\nputer" -> "computer"
        text = re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", text)
        return text

    def get_selection_rects(self, page: int, start_idx: int, end_idx: int) -> list[tuple[float, float, float, float]]:
        """Return merged bounding boxes per line for rendering selection overlay."""
        words = self.get_words(page)
        if not words:
            return []

        s = min(start_idx, end_idx)
        e = max(start_idx, end_idx)
        s = max(0, min(s, len(words) - 1))
        e = max(0, min(e, len(words) - 1))

        # Group words by (block, line)
        lines: dict[tuple[int, int], list[tuple[float, float, float, float]]] = {}
        for i in range(s, e + 1):
            w = words[i]
            k = (w.block_num, w.line_num)
            lines.setdefault(k, []).append(w.rect)

        # Merge rects on each line
        result: list[tuple[float, float, float, float]] = []
        for line_rects in lines.values():
            x0 = min(r[0] for r in line_rects)
            y0 = min(r[1] for r in line_rects)
            x1 = max(r[2] for r in line_rects)
            y1 = max(r[3] for r in line_rects)
            result.append((x0, y0, x1, y1))

        return result

    def copy_selection(self, page: int, start_idx: int, end_idx: int) -> str:
        """Copy selected text to system clipboard and return it."""
        text = self.get_selection_text(page, start_idx, end_idx)
        if text:
            clip = QGuiApplication.clipboard()
            if clip is not None:
                clip.setText(text)
        return text

"""
registry.py – merges detected + known + custom readers, caches per extension.
"""
from __future__ import annotations

import sys
from functools import lru_cache

from booklib.readers.models import Reader


class ReaderRegistry:
    """Thread-safe reader registry with per-extension lazy detection."""

    def __init__(self, repo=None) -> None:
        self._repo = repo       # Repository | None
        self._cache: dict[str, list[Reader]] = {}

    def refresh(self) -> None:
        """Clear the cache so the next call re-detects."""
        self._cache.clear()

    def readers_for(self, ext: str) -> list[Reader]:
        """Return all readers that can open *ext*, in preference order."""
        ext = ext.lower().lstrip(".")
        if ext not in self._cache:
            self._cache[ext] = self._build(ext)
        return self._cache[ext]

    def _build(self, ext: str) -> list[Reader]:
        readers: dict[str, Reader] = {}

        # 0. Built-in reader (BookLib Reader)
        _BUILTIN_FORMATS = frozenset({"pdf", "epub", "mobi", "fb2", "cbz", "txt"})
        if ext in _BUILTIN_FORMATS:
            readers["builtin"] = Reader(
                key="builtin",
                name="BookLib Reader",
                exe="builtin",
                formats=_BUILTIN_FORMATS,
            )

        # 1. Well-known readers (always probed)
        from booklib.readers.known import detect_known
        for r in detect_known():
            if r.handles(ext):
                readers[r.key] = r

        # 2. Platform-detected readers
        if sys.platform == "win32":
            from booklib.readers.detect_windows import detect_for_extension
            for r in detect_for_extension(ext, frozenset({ext})):
                if r.key not in readers:
                    readers[r.key] = r

        # 3. Custom readers from DB
        if self._repo is not None:
            try:
                for row in self._repo.list_custom_readers():
                    fmts_raw = row["formats"]
                    fmts = frozenset({"*"} if fmts_raw == "*"
                                     else {f.strip() for f in fmts_raw.split(",")})
                    r = Reader(
                        key=f"custom:{row['id']}",
                        name=row["name"],
                        exe=row["exe_path"],
                        formats=fmts,
                        args_template=row["args_template"],
                    )
                    if r.handles(ext):
                        readers[r.key] = r
            except Exception:
                pass

        # Sort: builtin first, then custom, then alphabetically
        return sorted(
            readers.values(),
            key=lambda r: (
                0 if r.key == "builtin" else (1 if r.key.startswith("custom:") else 2),
                r.name.lower(),
            ),
        )


# Module-level singleton; set `_registry.repo` after DB is ready
_registry = ReaderRegistry()


def get_registry() -> ReaderRegistry:
    return _registry

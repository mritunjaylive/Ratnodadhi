"""
base.py – Provider protocol for online metadata services.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable
from booklib.metadata.online.models import Candidate


@runtime_checkable
class Provider(Protocol):
    name: str

    def lookup_isbn(self, isbn: str) -> list[Candidate]:
        """Lookup candidates by ISBN. Returns list of Candidate objects."""
        ...

    def search(self, title: str, author: str | None) -> list[Candidate]:
        """Search candidates by title and optional author. Returns list of Candidate objects."""
        ...

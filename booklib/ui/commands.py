"""
commands.py – QUndoCommand implementations for status, rating, and metadata edits.
"""
from __future__ import annotations

from typing import Any, Callable
from PySide6.QtGui import QUndoCommand

from booklib.db.repository import Repository


class SetStatusCommand(QUndoCommand):
    """Undoable command to change reading status of one or more books."""

    def __init__(
        self,
        repo: Repository,
        book_ids: list[int],
        new_status: str | None,
        old_statuses: dict[int, str | None],
        callback: Callable[[], None] | None = None,
    ) -> None:
        name = {"want": "Want to Read", "reading": "Reading", "read": "Read"}.get(
            new_status or "", "Clear Status"
        )
        super().__init__(f"Set status: {name}")
        self._repo = repo
        self._book_ids = list(book_ids)
        self._new_status = new_status
        self._old_statuses = dict(old_statuses)
        self._callback = callback

    def redo(self) -> None:
        self._repo.set_status(self._book_ids, self._new_status)
        if self._callback:
            self._callback()

    def undo(self) -> None:
        for bid, old_s in self._old_statuses.items():
            self._repo.set_status([bid], old_s)
        if self._callback:
            self._callback()


class SetRatingCommand(QUndoCommand):
    """Undoable command to change star rating of a book."""

    def __init__(
        self,
        repo: Repository,
        book_id: int,
        new_rating: int | None,
        old_rating: int | None,
        callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(f"Set rating: {new_rating} stars" if new_rating else "Clear rating")
        self._repo = repo
        self._book_id = book_id
        self._new_rating = new_rating
        self._old_rating = old_rating
        self._callback = callback

    def redo(self) -> None:
        self._repo.set_rating(self._book_id, self._new_rating)
        if self._callback:
            self._callback()

    def undo(self) -> None:
        self._repo.set_rating(self._book_id, self._old_rating)
        if self._callback:
            self._callback()


class EditMetadataCommand(QUndoCommand):
    """Undoable command for single-book or bulk metadata edits."""

    def __init__(
        self,
        repo: Repository,
        book_ids: list[int],
        new_fields: dict[str, Any],
        old_snapshots: dict[int, dict[str, Any]],
        callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__("Edit metadata")
        self._repo = repo
        self._book_ids = list(book_ids)
        self._new_fields = dict(new_fields)
        self._old_snapshots = {bid: dict(vals) for bid, vals in old_snapshots.items()}
        self._callback = callback

    def redo(self) -> None:
        for bid in self._book_ids:
            self._repo.edit_book(bid, self._new_fields)
        if self._callback:
            self._callback()

    def undo(self) -> None:
        for bid, old_vals in self._old_snapshots.items():
            self._repo.edit_book(bid, old_vals)
        if self._callback:
            self._callback()

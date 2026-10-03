"""
models.py – Data models, exceptions, and helpers for Google Drive integration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class DriveError(Exception):
    """Base exception for Google Drive operations."""


class AuthExpired(DriveError):
    """Authentication token expired or revoked (invalid_grant)."""


class NotFound(DriveError):
    """File or folder not found (HTTP 404)."""


class Forbidden(DriveError):
    """Permission denied or download quota exceeded (HTTP 403)."""


class OfflineError(DriveError):
    """Internet connection is unavailable or timed out."""


class TransientError(DriveError):
    """Temporary server error or rate limit (HTTP 429, 5xx)."""


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int = 0
    md5: str | None = None
    modified_time: str | None = None
    parents: list[str] = None  # type: ignore
    web_view_link: str | None = None
    has_thumbnail: bool = False
    thumbnail_link: str | None = None
    is_folder: bool = False
    is_shortcut: bool = False
    shortcut_target_id: str | None = None
    target_id: str | None = None

    def __post_init__(self):
        if self.parents is None:
            self.parents = []
        if self.target_id is None and self.shortcut_target_id is not None:
            self.target_id = self.shortcut_target_id
        elif self.shortcut_target_id is None and self.target_id is not None:
            self.shortcut_target_id = self.target_id

    @property
    def is_google_doc(self) -> bool:
        return (
            self.mime_type.startswith("application/vnd.google-apps.")
            and not self.is_folder
            and not self.is_shortcut
        )


def is_drive(book_or_path: Any) -> bool:
    """
    Return True if book_or_path represents a cloud storage item:
    - has attribute source in ('drive', 'gdrive', 'onedrive', 'dropbox', 'fake')
    - or path starts with a cloud URI scheme ('gdrive://', 'onedrive://', etc.)
    """
    source = getattr(book_or_path, "source", None)
    if source in ("drive", "gdrive", "onedrive", "dropbox", "fake"):
        return True
    path = getattr(book_or_path, "path", None)
    if path is None and isinstance(book_or_path, str):
        path = book_or_path
    if path:
        p_str = str(path)
        if any(p_str.startswith(f"{prefix}://") for prefix in ("gdrive", "onedrive", "dropbox", "fake")):
            return True
    return False


def make_virtual_drive_path(account_id: int | str, file_id: str, provider: str = "gdrive") -> str:
    """Return virtual path URI for a cloud book: <provider>://<account_id>/<file_id>."""
    return f"{provider}://{account_id}/{file_id}"


def parse_virtual_drive_path(virtual_path: str) -> tuple[int, str]:
    """Parse <provider>://<account_id>/<file_id> into (account_id, file_id)."""
    m = re.match(r"^[a-zA-Z0-9_\-]+://([^/]+)/(.+)$", virtual_path)
    if not m:
        raise ValueError(f"Invalid virtual Drive path: {virtual_path}")
    return int(m.group(1)), m.group(2)

"""
booklib.cloud.provider – CloudProvider protocol, data structures, and hash utilities.

Supports multiple cloud storage providers (Google Drive, OneDrive, Dropbox, etc.)
behind a unified, thread-safe interface.
"""
from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Protocol, Union, runtime_checkable


@dataclass
class Account:
    """Represents a connected cloud storage account."""
    id: int | None = None
    provider: str = "gdrive"
    email: str = ""
    display_name: str | None = None
    state: str = "ok"  # 'ok' | 'needs_signin'
    changes_token: str | None = None
    added_at: str | None = None
    last_sync_at: str | None = None


@dataclass
class RemoteItem:
    """Metadata for a remote file or folder."""
    id: str
    name: str
    parent_id: str | None = None
    is_folder: bool = False
    size: int | None = None
    modified: str | None = None
    hash_kind: str | None = None  # 'md5' | 'quickxor' | 'sha1' | 'dropbox'
    hash_value: str | None = None
    mime: str | None = None
    web_url: str | None = None


@dataclass
class RemoteChange:
    """Change event for an item."""
    file_id: str
    removed: bool = False
    item: RemoteItem | None = None


@dataclass
class Page:
    """Paged list of remote items."""
    items: list[RemoteItem] = field(default_factory=list)
    next_page: str | None = None


@dataclass
class ChangePage:
    """Paged list of change events."""
    changes: list[RemoteChange] = field(default_factory=list)
    next_cursor: str = ""
    has_more: bool = False


@runtime_checkable
class CloudProvider(Protocol):
    """
    Standard interface for cloud storage backends (Google Drive, OneDrive, Dropbox).
    """
    key: str  # e.g. 'gdrive', 'onedrive', 'dropbox', 'fake'
    name: str  # e.g. 'Google Drive', 'Microsoft OneDrive', 'Dropbox'

    def authorize(self, ui_callbacks: Any = None) -> Account:
        """Run interactive authorization or token exchange, returning the Account."""
        ...

    def list_children(self, acct: Account, folder_id: str, page: str | None = None) -> Page:
        """List files and folders directly inside folder_id."""
        ...

    def initial_cursor(self, acct: Account) -> str:
        """Obtain initial synchronization cursor / delta token."""
        ...

    def list_changes(self, acct: Account, cursor: str) -> ChangePage:
        """Fetch incremental changes starting from cursor."""
        ...

    def open_download(self, acct: Account, item: RemoteItem, offset: int = 0) -> Any:
        """Open a streaming download starting at byte offset."""
        ...

    def thumbnail(self, acct: Account, item: RemoteItem) -> bytes | None:
        """Download cover/thumbnail image bytes if supported."""
        ...


# ── Hash Utilities ────────────────────────────────────────────────────────────

def compute_quickxor_hash(data: bytes) -> str:
    """
    Compute Microsoft QuickXorHash (160 bits, base64 encoded).
    Guaranteed on Microsoft OneDrive and SharePoint personal and business accounts.
    """
    width_in_bits = 160
    shift = 11
    data_length = len(data)

    cell = bytearray(20)
    cell_index = 0
    cell_bit_offset = 0

    for byte in data:
        next_cell_index = (cell_index + 1) % 20
        shifted_byte = byte << cell_bit_offset
        cell[cell_index] ^= shifted_byte & 0xFF
        cell[next_cell_index] ^= (shifted_byte >> 8) & 0xFF

        cell_bit_offset += shift
        cell_index = (cell_index + cell_bit_offset // 8) % 20
        cell_bit_offset %= 8

    # Finalize with length: XOR the data length into the end
    length_bytes = data_length.to_bytes(8, byteorder="little")
    for i, b in enumerate(length_bytes):
        cell[(20 - 8 + i) % 20] ^= b

    return base64.b64encode(cell).decode("ascii")


def compute_dropbox_content_hash(stream_or_data: Union[BinaryIO, bytes]) -> str:
    """
    Compute Dropbox content_hash:
    File is split into 4MB chunks (4,194,304 bytes).
    Each chunk is SHA-256 hashed.
    The concatenated SHA-256 binary digests are SHA-256 hashed and hex-encoded.
    """
    chunk_size = 4 * 1024 * 1024
    block_hashes = bytearray()

    if isinstance(stream_or_data, (bytes, bytearray)):
        data = stream_or_data
        if not data:
            block_hashes.extend(hashlib.sha256(b"").digest())
        else:
            for i in range(0, len(data), chunk_size):
                chunk = data[i : i + chunk_size]
                block_hashes.extend(hashlib.sha256(chunk).digest())
    else:
        stream = stream_or_data
        has_read = False
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                if not has_read:
                    block_hashes.extend(hashlib.sha256(b"").digest())
                break
            has_read = True
            block_hashes.extend(hashlib.sha256(chunk).digest())

    return hashlib.sha256(block_hashes).hexdigest()


def compare_remote_hashes(
    kind1: str | None,
    hash1: str | None,
    kind2: str | None,
    hash2: str | None,
) -> bool | None:
    """
    Compare two hashes. If both kinds match and are non-empty, compares values
    case-insensitively. If kinds differ or either is missing, returns None
    (indicating they cannot be compared directly).
    """
    if not kind1 or not hash1 or not kind2 or not hash2:
        return None
    if kind1.lower() != kind2.lower():
        return None
    return hash1.strip().lower() == hash2.strip().lower()


# ── Virtual Path Utilities ────────────────────────────────────────────────────

_CLOUD_SCHEME_PATTERN = re.compile(r"^([a-zA-Z0-9_\-]+)://([^/]+)/(.+)$")


def make_virtual_cloud_path(provider: str, account_id: int | str, item_id: str) -> str:
    """Format virtual cloud path URI: <provider>://<account_id>/<item_id>."""
    return f"{provider}://{account_id}/{item_id}"


def parse_virtual_cloud_path(virtual_path: str) -> tuple[str, int, str]:
    """Parse <provider>://<account_id>/<item_id> into (provider, account_id, item_id)."""
    m = _CLOUD_SCHEME_PATTERN.match(virtual_path)
    if not m:
        raise ValueError(f"Invalid virtual cloud path: {virtual_path}")
    provider = m.group(1)
    account_id = int(m.group(2))
    item_id = m.group(3)
    return provider, account_id, item_id


def is_cloud_path(path: str | Any) -> bool:
    """Check if given path or object represents a cloud storage item."""
    if hasattr(path, "source") and getattr(path, "source") in ("drive", "gdrive", "onedrive", "dropbox", "fake"):
        return True
    path_str = getattr(path, "path", None)
    if path_str is None and isinstance(path, str):
        path_str = path
    if path_str and "://" in str(path_str):
        scheme = str(path_str).split("://", 1)[0]
        return scheme in ("gdrive", "onedrive", "dropbox", "fake", "cloud")
    return False


# ── Provider Registry ─────────────────────────────────────────────────────────

_PROVIDERS: dict[str, CloudProvider] = {}


def register_provider(provider: CloudProvider) -> None:
    """Register a CloudProvider instance by its unique key."""
    _PROVIDERS[provider.key] = provider


def get_provider(key: str) -> CloudProvider:
    """Retrieve registered CloudProvider or raise KeyError."""
    if key not in _PROVIDERS:
        raise KeyError(f"No cloud provider registered with key '{key}'. Available: {list(_PROVIDERS.keys())}")
    return _PROVIDERS[key]


def list_providers() -> list[CloudProvider]:
    """Return all registered CloudProvider instances."""
    return list(_PROVIDERS.values())


def has_provider(key: str) -> bool:
    """Check if provider is registered."""
    return key in _PROVIDERS

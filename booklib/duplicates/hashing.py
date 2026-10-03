"""
hashing.py – Quick hash and full file hash computation for duplicate detection and relinking.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CHUNK_64K = 64 * 1024


def compute_quick_hash(path: str | Path, size_bytes: int | None = None) -> str | None:
    """
    Computes a fast hash: SHA-256 of (file_size + first 64KB + last 64KB).
    If file <= 128KB, reads entire file.
    Returns hex string or None if unreadable.
    """
    p = Path(path)
    try:
        if size_bytes is None:
            size_bytes = p.stat().st_size

        hasher = hashlib.sha256()
        # Include size as big-endian 8 bytes to avoid prefix collisions
        hasher.update(size_bytes.to_bytes(8, byteorder="big"))

        with open(p, "rb") as f:
            if size_bytes <= CHUNK_64K * 2:
                hasher.update(f.read())
            else:
                first_chunk = f.read(CHUNK_64K)
                hasher.update(first_chunk)
                f.seek(max(0, size_bytes - CHUNK_64K))
                last_chunk = f.read(CHUNK_64K)
                hasher.update(last_chunk)

        return hasher.hexdigest()
    except Exception as exc:
        logger.debug("Failed to compute quick hash for %s: %s", path, exc)
        return None


def compute_full_hash(path: str | Path) -> str | None:
    """
    Computes full SHA-256 digest of the file.
    Uses hashlib.file_digest (Python 3.11+) with fallback to chunked reading.
    Returns hex string or None if unreadable.
    """
    p = Path(path)
    try:
        if hasattr(hashlib, "file_digest"):
            with open(p, "rb") as f:
                return hashlib.file_digest(f, "sha256").hexdigest()
        else:
            hasher = hashlib.sha256()
            with open(p, "rb") as f:
                while chunk := f.read(256 * 1024):
                    hasher.update(chunk)
            return hasher.hexdigest()
    except Exception as exc:
        logger.debug("Failed to compute full file hash for %s: %s", path, exc)
        return None

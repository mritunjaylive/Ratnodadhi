"""
policy.py – Storage retention policies and protection tiers for the Storage Manager.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any


class ProtectionTier:
    TIER_0_PROTECTED = 0
    TIER_1_RECENT = 1
    TIER_2_CANDIDATE = 2


@dataclass
class StoragePolicy:
    keep_recent_books: int = 10                  # 0 to 100
    keep_reading_books: bool = True
    cache_limit_bytes: int = 5 * 1024 * 1024 * 1024   # 5 GB
    max_age_days: int = 30                       # 0 to disable
    min_free_bytes: int = 2 * 1024 * 1024 * 1024      # 2 GB floor
    lease_minutes: int = 120                     # 2 hours default reader lease

    def __init__(
        self,
        keep_recent_books: int = 10,
        keep_reading_books: bool = True,
        cache_limit_bytes: int = 5 * 1024 * 1024 * 1024,
        max_age_days: int = 30,
        min_free_bytes: int = 2 * 1024 * 1024 * 1024,
        lease_minutes: int = 120,
        keep_recent_opened: int | None = None,
        size_cap_bytes: int | None = None,
    ):
        self.keep_recent_books = keep_recent_opened if keep_recent_opened is not None else keep_recent_books
        self.keep_reading_books = keep_reading_books
        self.cache_limit_bytes = size_cap_bytes if size_cap_bytes is not None else cache_limit_bytes
        self.max_age_days = max_age_days
        self.min_free_bytes = min_free_bytes
        self.lease_minutes = lease_minutes


def classify_book(
    book: Any,
    policy: StoragePolicy,
    recent_book_ids: set[int] | None = None,
    now_iso: str | None = None,
) -> int:
    """Classify a single book into a protection tier (0, 1, or 2)."""
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    is_pinned = getattr(book, "keep_offline", False)
    is_leased = getattr(book, "is_leased", False)
    if is_pinned or is_leased:
        return ProtectionTier.TIER_0_PROTECTED

    is_reading = (getattr(book, "status", None) == "reading")
    if policy.keep_reading_books and is_reading:
        return ProtectionTier.TIER_1_RECENT

    bid = getattr(book, "id", None)
    if recent_book_ids and bid in recent_book_ids:
        return ProtectionTier.TIER_1_RECENT

    return ProtectionTier.TIER_2_CANDIDATE


@dataclass
class CachedBookCandidate:
    book_id: int
    file_path: str
    size_bytes: int
    tier: int           # 0 (protected), 1 (soft-protected), 2 (evictable)
    recency: str        # ISO string for sorting (newest first)
    is_pinned: bool
    is_leased: bool
    is_reading: bool
    status: str | None


def load_storage_policy(conn: sqlite3.Connection) -> StoragePolicy:
    """Load policy settings from app_meta or return defaults."""
    policy = StoragePolicy()
    try:
        rows = conn.execute("SELECT key, value FROM app_meta WHERE key LIKE 'storage.%'").fetchall()
        meta = {r[0]: r[1] for r in rows}
        if "storage.keep_recent_books" in meta:
            policy.keep_recent_books = int(meta["storage.keep_recent_books"])
        if "storage.keep_reading_books" in meta:
            policy.keep_reading_books = (meta["storage.keep_reading_books"].lower() in ("1", "true"))
        if "storage.cache_limit_bytes" in meta:
            policy.cache_limit_bytes = int(meta["storage.cache_limit_bytes"])
        if "storage.max_age_days" in meta:
            policy.max_age_days = int(meta["storage.max_age_days"])
        if "storage.min_free_bytes" in meta:
            policy.min_free_bytes = int(meta["storage.min_free_bytes"])
    except Exception:
        pass
    return policy


def save_storage_policy(conn: sqlite3.Connection, policy: StoragePolicy) -> None:
    """Save policy settings to app_meta."""
    entries = [
        ("storage.keep_recent_books", str(policy.keep_recent_books)),
        ("storage.keep_reading_books", "1" if policy.keep_reading_books else "0"),
        ("storage.cache_limit_bytes", str(policy.cache_limit_bytes)),
        ("storage.max_age_days", str(policy.max_age_days)),
        ("storage.min_free_bytes", str(policy.min_free_bytes)),
    ]
    for k, v in entries:
        conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)", (k, v))
    conn.commit()


def classify_cached_books(
    conn: sqlite3.Connection,
    policy: StoragePolicy,
    now_iso: str | None = None,
) -> list[CachedBookCandidate]:
    """
    Classify all rows in drive_cache into protection tiers:
    - Tier 0: pinned (keep_offline=1) or active lease (in_use_until > now)
    - Tier 1: Reading status (if enabled) and top N most recently opened books
    - Tier 2: Remaining books
    """
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()

    sql = """
        SELECT c.book_id, c.file_path, c.size_bytes, c.downloaded_at, c.last_used_at, c.in_use_until,
               b.keep_offline, b.status, b.last_opened_at,
               COALESCE(c.last_opened_at, b.last_opened_at, c.last_used_at, c.downloaded_at) as recency
        FROM drive_cache c
        JOIN books b ON c.book_id = b.id
        ORDER BY recency DESC
    """
    rows = conn.execute(sql).fetchall()

    candidates: list[CachedBookCandidate] = []

    for r in rows:
        bid = r["book_id"]
        is_pinned = bool(r["keep_offline"])
        is_leased = bool(r["in_use_until"] and r["in_use_until"] > now_iso)
        is_reading = (r["status"] == "reading")
        recency = r["recency"] or ""

        if is_pinned or is_leased:
            tier = 0
        else:
            tier = 2  # default until soft-protected assignment

        c = CachedBookCandidate(
            book_id=bid,
            file_path=r["file_path"],
            size_bytes=r["size_bytes"],
            tier=tier,
            recency=recency,
            is_pinned=is_pinned,
            is_leased=is_leased,
            is_reading=is_reading,
            status=r["status"],
        )
        candidates.append(c)

    # Assign Tier 1 (soft-protected)
    recent_count = 0
    now_dt = datetime.fromisoformat(now_iso) if "T" in now_iso else datetime.now(timezone.utc)
    age_cutoff = (now_dt - timedelta(days=policy.max_age_days)).isoformat() if policy.max_age_days > 0 else None

    for c in candidates:
        if c.tier == 0:
            continue
        protect = False
        if policy.keep_reading_books and c.is_reading:
            protect = True
        elif policy.keep_recent_books > 0 and recent_count < policy.keep_recent_books:
            if not (age_cutoff and c.recency and c.recency < age_cutoff):
                protect = True
                recent_count += 1

        if protect:
            c.tier = 1

    return candidates

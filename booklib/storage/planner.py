"""
planner.py – Builds a CleanupPlan for storage areas without executing any deletions.

Crucial rule:
The exact same plan produced here is used for both preview ("Preview cleanup")
and execution ("Clean now" / automatic sweeps).
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

from booklib.config import COVERS_DIR, DRIVE_CACHE_DIR
from booklib.storage.areas import get_storage_areas
from booklib.storage.policy import (
    StoragePolicy,
    load_storage_policy,
    classify_cached_books,
    CachedBookCandidate,
)


@dataclass
class CleanupAction:
    area: str
    path: Path | None
    book_id: int | None
    size_bytes: int
    reason_text: str
    reason: str = "age"

    def __post_init__(self):
        if "cap" in self.reason_text.lower() or "size" in self.reason_text.lower():
            self.reason = "size"
        elif "age" in self.reason_text.lower():
            self.reason = "age"


@dataclass
class CleanupPlan:
    actions: list[CleanupAction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(a.size_bytes for a in self.actions)

    @property
    def file_count(self) -> int:
        return len(self.actions)


def plan_cleanup(
    conn_or_repo: Any,
    policy_or_dt: Any = None,
    now_dt: datetime | None = None,
    reason: str = "scheduled",
    exclude_book_ids: set[int] | None = None,
    policy: StoragePolicy | None = None,
) -> CleanupPlan:
    """
    Produce a deterministic CleanupPlan. Does NOT modify files or database.
    """
    conn: sqlite3.Connection = conn_or_repo._conn if hasattr(conn_or_repo, "_conn") else conn_or_repo
    if isinstance(policy_or_dt, StoragePolicy):
        policy = policy_or_dt
    elif isinstance(policy_or_dt, datetime):
        now_dt = policy_or_dt

    now_dt = now_dt or datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    policy = policy or load_storage_policy(conn)
    exclude_book_ids = exclude_book_ids or set()

    plan = CleanupPlan()
    areas = get_storage_areas()

    # ── 1. Sweeps: Temp indexing files older than 1 day ─────────────────────────
    tmp_area = areas.get("deep_index_tmp")
    if tmp_area and tmp_area.root.exists():
        cutoff_mtime = (now_dt - timedelta(days=1)).timestamp()
        try:
            for entry in os.scandir(tmp_area.root):
                if entry.is_file(follow_symlinks=False):
                    st = entry.stat()
                    if st.st_mtime < cutoff_mtime or reason == "emergency":
                        plan.actions.append(
                            CleanupAction(
                                area="deep_index_tmp",
                                path=Path(entry.path),
                                book_id=None,
                                size_bytes=st.st_size,
                                reason_text="Old temporary indexing file",
                            )
                        )
        except Exception:
            pass

    # ── 2. Sweeps: Stale .part files older than 7 days (or all if emergency) ───
    part_area = areas.get("partial_downloads")
    if part_area and part_area.root.exists():
        part_cutoff = (now_dt - timedelta(days=7)).timestamp()
        try:
            for root_dir, _, files in os.walk(part_area.root):
                for f in files:
                    if f.endswith(".part"):
                        fpath = Path(root_dir) / f
                        st = fpath.stat()
                        if st.st_mtime < part_cutoff or reason in ("emergency", "low_space"):
                            plan.actions.append(
                                CleanupAction(
                                    area="partial_downloads",
                                    path=fpath,
                                    book_id=None,
                                    size_bytes=st.st_size,
                                    reason_text="Stale partial download (.part)",
                                )
                            )
        except Exception:
            pass

    # ── 3. Sweeps: Orphan covers ───────────────────────────────────────────────
    # Files in covers/ (except custom/ and placeholders) not referenced in books table
    covers_area = areas.get("covers")
    if covers_area and covers_area.root.exists():
        try:
            rows = conn.execute("SELECT cover_path FROM books WHERE cover_path IS NOT NULL").fetchall()
            active_covers = {Path(r[0]).name for r in rows if r[0]}

            for entry in os.scandir(covers_area.root):
                if entry.is_file(follow_symlinks=False) and entry.name.endswith(".jpg"):
                    # Check if this filename is active
                    if entry.name not in active_covers and not entry.name.startswith("custom"):
                        st = entry.stat()
                        # Only sweep if older than 1 day to avoid race conditions with scanning
                        if (now_dt.timestamp() - st.st_mtime) > 86400 or reason == "emergency":
                            plan.actions.append(
                                CleanupAction(
                                    area="covers",
                                    path=Path(entry.path),
                                    book_id=None,
                                    size_bytes=st.st_size,
                                    reason_text="Superseded or orphan cover thumbnail",
                                )
                            )
        except Exception:
            pass

    # ── 4. Sweeps: Expired online cache entries ────────────────────────────────
    try:
        cur = conn.execute(
            "SELECT COUNT(*), SUM(LENGTH(response)) FROM online_cache WHERE fetched_at < datetime('now', '-30 days')"
        )
        exp_row = cur.fetchone()
        if exp_row and exp_row[0] and exp_row[0] > 0:
            plan.actions.append(
                CleanupAction(
                    area="online_cache",
                    path=None,
                    book_id=None,
                    size_bytes=exp_row[1] or 0,
                    reason_text=f"{exp_row[0]} expired online metadata cache entries (>30 days)",
                )
            )
    except Exception:
        pass

    # ── 5. Drive downloads: Keep-recent, size cap, and age rules ───────────────
    candidates = classify_cached_books(conn, policy, now_iso)
    # Filter out excluded books (e.g. current open or download)
    active_candidates = [c for c in candidates if c.book_id not in exclude_book_ids]

    evicted_ids: set[int] = set()

    # Rule 5a: Age rule on Tier 2
    if policy.max_age_days > 0 and reason != "emergency":
        age_cutoff = (now_dt - timedelta(days=policy.max_age_days)).isoformat()
        for c in active_candidates:
            if c.tier == 2 and c.recency and c.recency < age_cutoff:
                evicted_ids.add(c.book_id)
                c_p = Path(c.file_path) if Path(c.file_path).is_absolute() else (DRIVE_CACHE_DIR / c.file_path)
                plan.actions.append(
                    CleanupAction(
                        area="drive_downloads",
                        path=c_p,
                        book_id=c.book_id,
                        size_bytes=c.size_bytes,
                        reason_text=f"Not opened in {policy.max_age_days} days (age rule)",
                    )
                )

    # Calculate remaining total size
    remaining_total = sum(c.size_bytes for c in active_candidates if c.book_id not in evicted_ids)
    target_cap = int(policy.cache_limit_bytes * 0.90)  # Evict down to 90% of cap

    tier0_bytes = sum(c.size_bytes for c in active_candidates if c.tier == 0)
    if tier0_bytes > policy.cache_limit_bytes:
        gb_used = tier0_bytes / (1024**3)
        gb_lim = policy.cache_limit_bytes / (1024**3)
        plan.warnings.append(
            f"Kept-offline and currently open books use {gb_used:.1f} GB, which exceeds your cache limit of {gb_lim:.1f} GB."
        )

    if remaining_total > policy.cache_limit_bytes or reason in ("emergency", "low_space"):
        # Order Tier 2 candidates by recency ASC (oldest first)
        tier2_candidates = [c for c in active_candidates if c.tier == 2 and c.book_id not in evicted_ids]
        tier2_candidates.sort(key=lambda x: x.recency)

        for c in tier2_candidates:
            if remaining_total <= target_cap and reason not in ("emergency", "low_space"):
                break
            evicted_ids.add(c.book_id)
            remaining_total -= c.size_bytes
            c_p = Path(c.file_path) if Path(c.file_path).is_absolute() else (DRIVE_CACHE_DIR / c.file_path)
            plan.actions.append(
                CleanupAction(
                    area="drive_downloads",
                    path=c_p,
                    book_id=c.book_id,
                    size_bytes=c.size_bytes,
                    reason_text="Least recently used (cache size cap)",
                )
            )

        # If still over cap, evict Tier 1 candidates (oldest first)
        if remaining_total > target_cap or reason in ("emergency", "low_space"):
            tier1_candidates = [c for c in active_candidates if c.tier == 1 and c.book_id not in evicted_ids]
            tier1_candidates.sort(key=lambda x: x.recency)

            for c in tier1_candidates:
                if remaining_total <= target_cap and reason not in ("emergency", "low_space"):
                    break
                evicted_ids.add(c.book_id)
                remaining_total -= c.size_bytes
                c_p = Path(c.file_path) if Path(c.file_path).is_absolute() else (DRIVE_CACHE_DIR / c.file_path)
                plan.actions.append(
                    CleanupAction(
                        area="drive_downloads",
                        path=c_p,
                        book_id=c.book_id,
                        size_bytes=c.size_bytes,
                        reason_text="Recent book evicted due to hard cache cap",
                    )
                )

    return plan

"""
maintenance/health.py – Library health checks and fixes.

Each check:
  - Returns a HealthResult with count, severity, and optional fix.
  - Fixes are explicit user actions; nothing is deleted without confirmation.

Runs as a maintenance-lane job so it's exclusive with other heavy work.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from booklib.config import DB_PATH, COVERS_DIR, DATA_DIR

logger = logging.getLogger(__name__)


@dataclass
class HealthResult:
    check: str              # check name / label
    count: int              # number of issues found
    severity: str           # 'ok' | 'info' | 'warning' | 'error'
    detail: str = ""        # human-readable detail
    fix_label: str = ""     # label for the fix button (empty = no fix offered)
    fix_id: str = ""        # programmatic fix identifier for dispatch


@dataclass
class HealthReport:
    results: list[HealthResult] = field(default_factory=list)
    run_at: str = ""

    def any_issues(self) -> bool:
        return any(r.count > 0 for r in self.results)

    def to_text(self) -> str:
        lines = [f"Library Health Report – {self.run_at}", "=" * 60]
        for r in self.results:
            icon = {"ok": "[OK]", "info": "[INFO]", "warning": "[WARN]", "error": "[ERROR]"}.get(r.severity, "[?]")
            lines.append(f"{icon} {r.check}: {r.count} issue(s)")
            if r.detail:
                lines.append(f"   {r.detail}")
        return "\n".join(lines)


# ── Individual checks ──────────────────────────────────────────────────────────

def check_database_integrity(conn: sqlite3.Connection) -> HealthResult:
    """Run PRAGMA integrity_check and foreign_key_check."""
    try:
        ic = conn.execute("PRAGMA integrity_check").fetchall()
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        ok = (len(ic) == 1 and ic[0][0] == "ok") and len(fk) == 0
        if ok:
            return HealthResult("Database integrity", 0, "ok", "No issues found")
        issues = len(ic) + len(fk)
        return HealthResult(
            "Database integrity", issues, "error",
            f"Integrity check: {ic[0][0]}; {len(fk)} foreign key violation(s)",
            "Restore from backup…", "restore_backup",
        )
    except sqlite3.Error as exc:
        return HealthResult("Database integrity", 1, "error", str(exc),
                            "Restore from backup…", "restore_backup")


def check_fts_index(conn: sqlite3.Connection) -> HealthResult:
    """Check FTS5 index integrity and row count."""
    try:
        fts_tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_fts'"
            ).fetchall()
        ]
        if not fts_tables:
            return HealthResult("Search index", 0, "info", "No FTS index found (optional)")

        issues = 0
        for tbl in fts_tables:
            try:
                conn.execute(f"INSERT INTO {tbl}({tbl}) VALUES('integrity-check')")
                conn.rollback()
            except sqlite3.OperationalError:
                issues += 1

        if issues:
            return HealthResult("Search index", issues, "warning",
                                f"{issues} FTS table(s) have integrity errors",
                                "Rebuild index", "rebuild_fts")
        return HealthResult("Search index", 0, "ok", "FTS index is consistent")
    except Exception as exc:
        return HealthResult("Search index", 1, "warning", str(exc))


def check_missing_files(conn: sqlite3.Connection) -> HealthResult:
    """Count books marked is_missing=1."""
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM books WHERE is_missing = 1"
        ).fetchone()[0]
        if count == 0:
            return HealthResult("Missing local files", 0, "ok", "All files found")
        return HealthResult(
            "Missing local files", count, "warning",
            f"{count} book(s) have missing files",
            "Remove missing / Relocate folder", "remove_missing",
        )
    except sqlite3.Error as exc:
        return HealthResult("Missing local files", 1, "error", str(exc))


def check_missing_covers(conn: sqlite3.Connection) -> HealthResult:
    """Count books where cover_path is set but the file doesn't exist."""
    try:
        rows = conn.execute(
            "SELECT cover_path FROM books WHERE cover_path IS NOT NULL AND is_missing = 0"
        ).fetchall()
        missing = sum(1 for r in rows if not Path(r[0]).exists())
        if missing == 0:
            return HealthResult("Missing cover files", 0, "ok", "All covers present")
        return HealthResult(
            "Missing cover files", missing, "warning",
            f"{missing} book(s) have missing cover files",
            "Regenerate covers", "regen_covers",
        )
    except sqlite3.Error as exc:
        return HealthResult("Missing cover files", 1, "error", str(exc))


def check_orphan_covers(conn: sqlite3.Connection) -> HealthResult:
    """Find cover files not referenced by any book."""
    try:
        if not COVERS_DIR.exists():
            return HealthResult("Orphan cover files", 0, "ok", "Covers directory not found")

        known_paths = {
            r[0] for r in conn.execute(
                "SELECT cover_path FROM books WHERE cover_path IS NOT NULL"
            ).fetchall()
        }
        orphans = [
            p for p in COVERS_DIR.rglob("*")
            if p.is_file() and str(p) not in known_paths
        ]
        if not orphans:
            return HealthResult("Orphan cover files", 0, "ok", "No orphan covers found")
        size = sum(p.stat().st_size for p in orphans)
        return HealthResult(
            "Orphan cover files", len(orphans), "info",
            f"{len(orphans)} orphan file(s) ({size // 1024} KB)",
            "Delete orphans", "delete_orphan_covers",
        )
    except Exception as exc:
        return HealthResult("Orphan cover files", 1, "warning", str(exc))


def check_unused_tags(conn: sqlite3.Connection) -> HealthResult:
    """Count tags with zero associated books."""
    try:
        count = conn.execute(
            """SELECT COUNT(*) FROM tags t
               WHERE NOT EXISTS (SELECT 1 FROM book_tags bt WHERE bt.tag_id = t.id)"""
        ).fetchone()[0]
        if count == 0:
            return HealthResult("Unused tags", 0, "ok", "No unused tags")
        return HealthResult(
            "Unused tags", count, "info",
            f"{count} tag(s) with no books",
            "Review and delete", "delete_unused_tags",
        )
    except sqlite3.Error as exc:
        return HealthResult("Unused tags", 1, "warning", str(exc))


def check_empty_collections(conn: sqlite3.Connection) -> HealthResult:
    """Count manual collections with zero books."""
    try:
        count = conn.execute(
            """SELECT COUNT(*) FROM collections c
               WHERE c.kind = 'manual'
               AND NOT EXISTS (SELECT 1 FROM collection_books cb WHERE cb.collection_id = c.id)"""
        ).fetchone()[0]
        if count == 0:
            return HealthResult("Empty collections", 0, "ok", "No empty collections")
        return HealthResult(
            "Empty collections", count, "info",
            f"{count} empty manual collection(s)",
            "Review and delete", "delete_empty_collections",
        )
    except sqlite3.Error as exc:
        return HealthResult("Empty collections", 1, "warning", str(exc))


def check_old_history(conn: sqlite3.Connection, days: int = 30) -> HealthResult:
    """Count metadata_history rows older than N days."""
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        count = conn.execute(
            "SELECT COUNT(*) FROM metadata_history WHERE created_at < ?", (cutoff,)
        ).fetchone()[0]
        if count == 0:
            return HealthResult("Old history entries", 0, "ok", f"No entries older than {days} days")
        return HealthResult(
            "Old history entries", count, "info",
            f"{count} history row(s) older than {days} days",
            "Purge old history", "purge_old_history",
        )
    except sqlite3.Error as exc:
        return HealthResult("Old history entries", 1, "warning", str(exc))


def check_database_size(conn: sqlite3.Connection) -> HealthResult:
    """Check DB size and free pages; offer VACUUM."""
    try:
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        total_size = page_count * page_size
        free_size = freelist * page_size
        waste_pct = (freelist / page_count * 100) if page_count else 0

        detail = (
            f"Total: {total_size // (1024*1024)} MB, "
            f"Free pages: {free_size // 1024} KB ({waste_pct:.1f}%)"
        )
        if waste_pct > 10:
            return HealthResult(
                "Database size", 1, "info", detail,
                "Compact database (VACUUM)", "vacuum_db",
            )
        return HealthResult("Database size", 0, "ok", detail)
    except sqlite3.Error as exc:
        return HealthResult("Database size", 1, "warning", str(exc))


# ── Storage checks (v5 additions) ─────────────────────────────────────────────

def check_leftover_temp_files(conn: sqlite3.Connection) -> HealthResult:
    """Check for temp_files table entries (leftover from crashes)."""
    try:
        count = conn.execute("SELECT COUNT(*) FROM temp_files").fetchone()[0]
        if count == 0:
            return HealthResult("Leftover temp files", 0, "ok", "No leftover temp files")
        rows = conn.execute("SELECT path, purpose FROM temp_files").fetchall()
        detail = f"{count} registered temp file(s): " + ", ".join(r[1] for r in rows[:3])
        return HealthResult(
            "Leftover temp files", count, "warning", detail,
            "Clean up temp files", "sweep_temp_files",
        )
    except sqlite3.OperationalError:
        return HealthResult("Leftover temp files", 0, "ok", "Temp-file table not yet created")


def check_low_disk_space() -> HealthResult:
    """Check free space on the app-data drive."""
    try:
        usage = shutil.disk_usage(str(DATA_DIR))
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 2.0:
            return HealthResult(
                "Disk space", 1, "warning",
                f"Only {free_gb:.1f} GB free on app-data drive",
                "Open Storage settings", "storage.open_settings",
            )
        return HealthResult("Disk space", 0, "ok", f"{free_gb:.1f} GB free")
    except Exception as exc:
        return HealthResult("Disk space", 1, "info", str(exc))


# ── Full run ───────────────────────────────────────────────────────────────────

def run_all_checks(conn: sqlite3.Connection) -> HealthReport:
    """Run all health checks and return a HealthReport."""
    checks = [
        check_database_integrity,
        check_fts_index,
        check_missing_files,
        check_missing_covers,
        check_orphan_covers,
        check_unused_tags,
        check_empty_collections,
        check_old_history,
        check_database_size,
        check_leftover_temp_files,
        check_low_disk_space,
    ]
    results = []
    for check_fn in checks:
        try:
            if check_fn.__code__.co_argcount == 0:
                result = check_fn()
            else:
                result = check_fn(conn)
            results.append(result)
        except Exception as exc:
            logger.error("Health check %s failed: %s", check_fn.__name__, exc)
            results.append(HealthResult(check_fn.__name__, 1, "error", str(exc)))

    return HealthReport(
        results=results,
        run_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

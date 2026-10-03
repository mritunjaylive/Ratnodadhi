"""
test_v6_positions_sessions.py – Unit tests for Milestones 6 and 6b:
- Reading position persistence and V3 progress rules
- Reading session tracker (start, activity, flush, end, discard short sessions)
- Cloud lease management and storage policy Tier 0 protection
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from booklib.db.database import Database
from booklib.reader.backend import Locator
from booklib.reader.manager import ReaderManager
from booklib.reader.position import load_reading_position, save_reading_position
from booklib.reader.sessions import ReadingSessionTracker, delete_all_reading_sessions
from booklib.storage.policy import StoragePolicy, classify_cached_books


@pytest.fixture
def test_db(tmp_path: Path) -> sqlite3.Connection:
    db = Database(tmp_path / "test_positions.db")
    conn = db.connect()
    conn.execute("INSERT INTO folders (id, path) VALUES (1, '/books')")
    conn.execute(
        "INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime, title, status) "
        "VALUES (10, 1, '/books/b.pdf', 'b.pdf', 'pdf', 1000, 0, 'Clean Architecture', 'want')"
    )
    conn.commit()
    yield conn
    db.close()


def test_save_and_load_position(test_db: sqlite3.Connection) -> None:
    """Verify position save, load, and status transition from 'want' to 'reading'."""
    loc = Locator(t="pdf", page=5, y=0.42)
    save_reading_position(test_db, 10, loc, progress=0.25, layout_key="key1")

    # Verify load
    loaded_loc, prog, lkey = load_reading_position(test_db, 10)
    assert loaded_loc is not None
    assert loaded_loc.t == "pdf"
    assert loaded_loc.page == 5
    assert loaded_loc.y == 0.42
    assert prog == 0.25
    assert lkey == "key1"

    # Verify book row updated
    row = test_db.execute("SELECT progress_percent, status FROM books WHERE id = 10").fetchone()
    assert row["progress_percent"] == 25.0
    assert row["status"] == "reading"


def test_reading_sessions_lifecycle(test_db: sqlite3.Connection, qapp) -> None:
    """Verify session tracking, flush, and minimum duration discard."""
    tracker = ReadingSessionTracker(lambda: test_db)

    # 1. Short session (< 10s) -> should be discarded on end
    sid1 = tracker.start_session(10, start_progress=0.1)
    assert sid1 is not None
    tracker.end_session(10, end_progress=0.15)

    rows = test_db.execute("SELECT * FROM reading_sessions WHERE id = ?", (sid1,)).fetchall()
    assert len(rows) == 0  # Discarded because < 10s

    # 2. Long session with activity
    sid2 = tracker.start_session(10, start_progress=0.2)
    assert sid2 is not None
    # Simulate 12 seconds of active reading
    tracker._active_sessions[10]["accumulated_seconds"] = 15.0
    tracker.flush_all()

    row_flushed = test_db.execute("SELECT * FROM reading_sessions WHERE id = ?", (sid2,)).fetchone()
    assert row_flushed is not None
    assert row_flushed["active_seconds"] >= 15

    tracker.end_session(10, end_progress=0.3)
    row_ended = test_db.execute("SELECT * FROM reading_sessions WHERE id = ?", (sid2,)).fetchone()
    assert row_ended is not None
    assert row_ended["active_seconds"] >= 15

    # Test delete all reading sessions
    delete_all_reading_sessions(test_db)
    all_rows = test_db.execute("SELECT * FROM reading_sessions").fetchall()
    assert len(all_rows) == 0


def test_cloud_lease_protection(test_db: sqlite3.Connection, qapp) -> None:
    """Verify reader manager sets in_use_until and storage policy recognizes Tier 0 lease."""
    # Insert drive_cache row
    now_iso = datetime.now(timezone.utc).isoformat()
    future_iso = datetime.fromtimestamp(time.time() + 300, tz=timezone.utc).isoformat()

    test_db.execute(
        """
        INSERT INTO drive_cache (book_id, file_path, size_bytes, downloaded_at, last_used_at, in_use_until)
        VALUES (10, '/cache/b.pdf', 5000, ?, ?, ?)
        """,
        (now_iso, now_iso, future_iso),
    )
    test_db.commit()

    # Check policy categorization: item should be in tier 0 (protected active lease)
    policy = StoragePolicy(keep_recent_books=0, keep_reading_books=False)
    candidates = classify_cached_books(test_db, policy)
    assert any(c.book_id == 10 and c.tier == 0 for c in candidates)

    # Now release lease
    rm = ReaderManager(conn_supplier=lambda: test_db)
    rm.release_cloud_lease(10)

    # After release, in_use_until is <= now, so it is no longer tier 0
    candidates_after = classify_cached_books(test_db, policy)
    assert any(c.book_id == 10 and c.tier == 2 for c in candidates_after)

"""
tests/test_v5_storage.py – Tests for Milestone 10b: Storage management, temp-files registry, guard, and health checks.
"""
import sqlite3
import tempfile
from pathlib import Path

import pytest

from booklib.storage.areas import get_storage_areas, StorageArea
from booklib.storage.tempfiles import TempFileRegistry
from booklib.storage.guard import ensure_space, LowDiskSpace, guard_export
from booklib.maintenance.health import (
    run_all_checks,
    check_database_integrity,
    check_leftover_temp_files,
    check_low_disk_space,
)


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA user_version = 5")
    conn.execute(
        """CREATE TABLE temp_files (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            purpose TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.execute(
        """CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            title TEXT,
            author TEXT,
            cover_path TEXT,
            is_missing INTEGER DEFAULT 0
        )"""
    )
    conn.commit()
    yield conn, db_file
    conn.close()


def test_storage_areas():
    areas = get_storage_areas()
    assert "safety_snapshots" in areas
    assert "backups" in areas
    assert "covers" in areas


def test_temp_file_registry_lifecycle(test_db, tmp_path):
    conn, _ = test_db
    reg = TempFileRegistry(conn)

    # Valid UUID-format temp file
    fake_temp = tmp_path / "book.tmp-12345678-1234-1234-1234-123456789abc.epub"
    fake_temp.write_text("dummy")

    reg.register(fake_temp, "convert")
    entries = reg.all_entries()
    assert len(entries) == 1
    assert entries[0]["purpose"] == "convert"

    # Sweep should remove it
    removed = reg.sweep()
    assert removed == 1
    assert not fake_temp.exists()
    assert len(reg.all_entries()) == 0


def test_guard_export(tmp_path):
    dest = tmp_path / "export.csv"
    # Export of 100 books should require ~100KB, which easily succeeds
    guard_export(100, dest)


def test_health_checks(test_db):
    conn, _ = test_db
    res_db = check_database_integrity(conn)
    assert res_db.severity == "ok"

    res_temp = check_leftover_temp_files(conn)
    assert res_temp.severity == "ok"

    report = run_all_checks(conn)
    assert report.run_at != ""
    assert len(report.results) >= 8

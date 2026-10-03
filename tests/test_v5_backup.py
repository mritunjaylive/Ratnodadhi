"""
tests/test_v5_backup.py – Unit tests for Milestone 4 (Local backup & destinations) and Milestone 5 (Restore & scheduler).
"""
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from booklib.db.database import CURRENT_SCHEMA_VERSION
from booklib.backup.snapshot import take_db_snapshot, SnapshotError
from booklib.backup.package import (
    build_backup_zip,
    verify_backup_zip,
    BackupPackageError,
)
from booklib.backup.destinations import LocalFolderDestination
from booklib.backup.restore import (
    verify_and_prepare_restore,
    apply_staged_restore,
    RestoreError,
)
from booklib.backup.scheduler import (
    should_run_backup,
    mark_dirty,
    clear_dirty,
    is_dirty,
)


@pytest.fixture
def sample_db(tmp_path):
    """Create a temporary initialized SQLite database with v5 schema."""
    db_file = tmp_path / "test_library.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA user_version = 5")
    conn.execute(
        """CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            title TEXT,
            author TEXT,
            is_missing INTEGER DEFAULT 0
        )"""
    )
    conn.execute("INSERT INTO books (title, author) VALUES ('The Hobbit', 'J.R.R. Tolkien')")
    conn.execute("INSERT INTO books (title, author) VALUES ('Dune', 'Frank Herbert')")
    conn.commit()
    yield conn, db_file
    conn.close()


def test_snapshot_creation(sample_db, tmp_path):
    conn, _ = sample_db
    target = tmp_path / "snap.db"
    result = take_db_snapshot(conn, target)
    assert result.exists()

    # Check content in snapshot
    snap_conn = sqlite3.connect(str(result))
    cnt = snap_conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    snap_conn.close()
    assert cnt == 2


def test_package_and_verify(sample_db, tmp_path):
    conn, _ = sample_db
    zip_path = tmp_path / "backup.zip"
    build_backup_zip(conn, zip_path, computer_name="test-pc")
    assert zip_path.exists()

    manifest = verify_backup_zip(zip_path)
    assert manifest["app"] == "Ratnodadhi"
    assert manifest["book_count"] == 2
    assert manifest["computer_name"] == "test-pc"
    assert "library.db" in manifest["entries"]
    assert "manifest.json" in manifest["entries"] or "settings.json" in manifest["entries"]


def test_verify_rejects_corrupted_manifest(tmp_path):
    bad_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("something.txt", "not a backup")

    with pytest.raises(BackupPackageError, match="missing manifest.json"):
        verify_backup_zip(bad_zip)


def test_verify_rejects_future_schema(sample_db, tmp_path):
    conn, _ = sample_db
    zip_path = tmp_path / "future_backup.zip"
    build_backup_zip(conn, zip_path)

    # Modify manifest in zip to have a higher schema version
    with zipfile.ZipFile(zip_path, "r") as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        db_bytes = zf.read("library.db")
        settings_bytes = zf.read("settings.json")

    manifest["schema_version"] = 999
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("library.db", db_bytes)
        zf.writestr("settings.json", settings_bytes)

    with pytest.raises(BackupPackageError, match="newer schema"):
        verify_backup_zip(zip_path)


def test_local_folder_destination_lifecycle(sample_db, tmp_path):
    conn, _ = sample_db
    dest_dir = tmp_path / "dest"
    dest = LocalFolderDestination(dest_dir)

    # 1. Create a backup file
    source_zip = tmp_path / "src_backup.zip"
    build_backup_zip(conn, source_zip)

    # 2. Upload
    backup_id = dest.upload(source_zip)
    assert backup_id.endswith(".zip")
    assert (dest_dir / backup_id).exists()

    # 3. List
    items = dest.list()
    assert len(items) == 1
    assert items[0].id == backup_id
    assert items[0].book_count == 2
    assert items[0].source == "local"

    # 4. Download
    download_target = tmp_path / "downloaded.zip"
    dest.download(backup_id, download_target)
    assert download_target.exists()

    # 5. Pruning
    # Upload 3 more backups
    for _ in range(3):
        dest.upload(source_zip, keep_count=2)

    # After keeping 2, length should be at most 2
    items_after = dest.list()
    assert len(items_after) <= 2


def test_restore_lifecycle(sample_db, tmp_path):
    conn, active_db_path = sample_db

    # Create backup with current state (2 books)
    zip_path = tmp_path / "test_backup.zip"
    build_backup_zip(conn, zip_path)

    # Modify active db (add 3rd book)
    conn.execute("INSERT INTO books (title, author) VALUES ('Foundation', 'Isaac Asimov')")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 3
    conn.close()

    # Prepare restore
    staging_dir, safety_copy = verify_and_prepare_restore(
        zip_path,
        target_db_path=active_db_path,
    )
    assert staging_dir.exists()
    assert safety_copy.exists()

    # Apply restore
    ok = apply_staged_restore(staging_dir, target_db_path=active_db_path)
    assert ok is True

    # Verify active db has returned to 2 books
    reopened = sqlite3.connect(str(active_db_path))
    cnt = reopened.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    reopened.close()
    assert cnt == 2


def test_dirty_flag_and_scheduler():
    mark_dirty()
    assert is_dirty() is True
    clear_dirty()
    assert is_dirty() is False

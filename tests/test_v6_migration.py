"""
test_v6_migration.py – Unit tests for Milestone 1:
- Migration 5 to 6: new tables, columns, indices, FTS triggers
- Idempotent migration
- Extractor process pool & crash isolation
- JobManager index lane
- ServiceManager
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from booklib.db.database import Database, CURRENT_SCHEMA_VERSION, fts5_available
from booklib.extract.pool import (
    run_in_extractor,
    run_in_extractor_sync,
    sweep_extractor_temp_dir,
    shutdown_extractor_pool,
)
from booklib.jobs.manager import BaseJob, JobManager
from booklib.services import ServiceManager


# Top-level helper function for pool tests (must be picklable)
def _sample_extract_task(x: int, y: int) -> int:
    return x * y


def _sample_failing_task() -> None:
    raise ValueError("Simulated extractor parsing failure")


def _sample_temp_task() -> str:
    tmp = os.environ.get("BOOKLIB_EXTRACT_TMP")
    assert tmp is not None, "Worker temp not set"
    p = Path(tmp) / "sample_temp.txt"
    p.write_text("temporary data", encoding="utf-8")
    return str(p)


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_v6.db"


def test_migration_5_to_6(temp_db_path: Path) -> None:
    """Test full migration to v6 on a fresh database."""
    db = Database(temp_db_path)
    conn = db.connect()

    # Check schema version
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    assert ver == 6
    assert CURRENT_SCHEMA_VERSION == 6

    # Verify new tables exist
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "reading_positions" in tables
    assert "bookmarks" in tables
    assert "annotations" in tables
    assert "reading_sessions" in tables
    assert "recommendation_feedback" in tables
    assert "web_devices" in tables

    if fts5_available():
        assert "annotations_fts" in tables

    # Verify columns in books
    book_cols = {r[1] for r in conn.execute("PRAGMA table_info(books)").fetchall()}
    assert "fts_state" in book_cols
    assert "fts_version" in book_cols
    assert "fts_indexed_at" in book_cols
    assert "text_chars" in book_cols

    # Verify column in folders
    folder_cols = {r[1] for r in conn.execute("PRAGMA table_info(folders)").fetchall()}
    assert "index_contents" in folder_cols

    db.close()


def test_migration_running_twice_is_safe(temp_db_path: Path) -> None:
    """Opening database again must not fail or corrupt schema."""
    db = Database(temp_db_path)
    db.connect()
    db.close()

    db2 = Database(temp_db_path)
    conn2 = db2.connect()
    ver = conn2.execute("PRAGMA user_version").fetchone()[0]
    assert ver == 6
    db2.close()


def test_annotations_crud_and_fts(temp_db_path: Path) -> None:
    """Verify annotations table CRUD and FTS triggers."""
    db = Database(temp_db_path)
    conn = db.connect()

    # Insert folder and book
    conn.execute("INSERT INTO folders (id, path) VALUES (1, '/books')")
    conn.execute(
        "INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime, title) "
        "VALUES (1, 1, '/books/b.pdf', 'b.pdf', 'pdf', 100, 0, 'Clean Code')"
    )
    conn.commit()

    # Insert annotation
    conn.execute(
        "INSERT INTO annotations (id, book_id, kind, color, quote, prefix, suffix, locator, note) "
        "VALUES (1, 1, 'highlight', 'yellow', 'Clean code is readable', 'Notice: ', ' in reality', '{\"page\": 1}', 'Important note')"
    )
    conn.commit()

    row = conn.execute("SELECT * FROM annotations WHERE id = 1").fetchone()
    assert row["quote"] == "Clean code is readable"
    assert row["note"] == "Important note"

    if fts5_available():
        fts_row = conn.execute("SELECT * FROM annotations_fts WHERE annotations_fts MATCH 'readable'").fetchone()
        assert fts_row is not None

        # Update note
        conn.execute("UPDATE annotations SET note = 'Revised observation' WHERE id = 1")
        conn.commit()

        fts_row_revised = conn.execute("SELECT * FROM annotations_fts WHERE annotations_fts MATCH 'observation'").fetchone()
        assert fts_row_revised is not None

        # Delete
        conn.execute("DELETE FROM annotations WHERE id = 1")
        conn.commit()
        fts_del = conn.execute("SELECT * FROM annotations_fts WHERE annotations_fts MATCH 'readable'").fetchone()
        assert fts_del is None

    db.close()


def test_extractor_pool_execution() -> None:
    """Verify extractor pool runs functions in worker processes returning plain data."""
    res = run_in_extractor_sync(_sample_extract_task, 6, 7)
    assert res == 42


def test_extractor_pool_handles_failure() -> None:
    """Verify pool handles errors without crashing."""
    with pytest.raises(Exception):
        run_in_extractor_sync(_sample_failing_task)


def test_extractor_pool_worker_temp_cleanup() -> None:
    """Verify worker temp directory exists during task and is cleaned afterwards."""
    path_str = run_in_extractor_sync(_sample_temp_task)
    # File created inside worker temp should be cleaned up by wrapper
    assert not Path(path_str).exists()


def test_extractor_temp_sweep(tmp_path: Path, monkeypatch) -> None:
    """Verify sweeping orphaned directories older than 1 day or dead PID."""
    fake_extract_tmp = tmp_path / "extract_tmp"
    fake_extract_tmp.mkdir()
    monkeypatch.setattr("booklib.extract.pool.EXTRACT_TMP_DIR", fake_extract_tmp)

    # 1. Folder with dead PID (9999999)
    dead_folder = fake_extract_tmp / "9999999-uuid"
    dead_folder.mkdir()
    (dead_folder / "leftover.tmp").write_text("old")

    # 2. Folder with current PID (should not be swept if fresh)
    live_folder = fake_extract_tmp / f"{os.getpid()}-uuid"
    live_folder.mkdir()
    (live_folder / "active.tmp").write_text("active")

    swept = sweep_extractor_temp_dir()
    assert swept >= 1
    assert not dead_folder.exists()
    assert live_folder.exists()


def test_job_manager_index_lane(qapp) -> None:
    """Verify JobManager handles jobs in the index lane."""
    manager = JobManager()
    assert hasattr(manager, "_running_index_jobs")

    class SimpleIndexJob(BaseJob):
        def run(self) -> None:
            self.progress.emit(1, 1, "Indexing done")
            self.finished.emit({"indexed": 1})

    job = SimpleIndexJob("test_index", lane="index")
    manager.submit(job)

    # Wait for completion and process events
    job.wait(2000)
    qapp.processEvents()
    assert not manager._running_index_jobs


def test_service_manager_lifecycle(qapp) -> None:
    """Verify ServiceManager starts and stops services cleanly."""
    sm = ServiceManager()
    assert not sm.is_web_server_running()
    assert not sm.is_index_scheduler_running()

    sm.stop_web_server()
    sm.stop_index_scheduler()
    sm.shutdown_all()

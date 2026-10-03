"""
test_v4_storage.py – Storage manager, protection tiers, cleanup planner, executor, and guard tests.
"""
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from booklib.db.database import Database
from booklib.db.repository import Repository
from booklib.storage.areas import register_marker, has_marker, register_lease, release_lease, is_leased
from booklib.storage.policy import StoragePolicy, ProtectionTier, classify_book
from booklib.storage.planner import plan_cleanup
from booklib.storage.executor import execute_cleanup, safe_delete_file
from booklib.storage.guard import ensure_space, LowDiskSpace
from booklib.storage.usage import get_cache_usage_bytes, count_cached_books
from booklib.storage.scheduler import run_startup_consistency_check


@pytest.fixture
def repo(tmp_path: Path):
    db = Database(tmp_path / "test_storage.db")
    conn = db.connect()
    r = Repository(conn)
    yield r
    db.close()


def test_marker_file(tmp_path: Path):
    cache_dir = tmp_path / "cache_area"
    cache_dir.mkdir()
    assert not has_marker(cache_dir)
    register_marker(cache_dir)
    assert has_marker(cache_dir)


def test_leases(tmp_path: Path):
    target = tmp_path / "some_book.pdf"
    target.touch()
    assert not is_leased(target)

    lease_id = register_lease(target)
    assert is_leased(target)

    release_lease(lease_id)
    assert not is_leased(target)


def test_protection_tiers_classification(repo: Repository, tmp_path: Path):
    policy = StoragePolicy(keep_recent_opened=5, keep_reading_books=True)
    cache_dir = tmp_path / "drive_cache"
    cache_dir.mkdir()
    register_marker(cache_dir)

    fid = repo.add_folder("C:/DriveFolder")

    # 1. Pinned book -> Tier 0
    p1 = cache_dir / "pinned.pdf"
    p1.touch()
    b1 = repo.upsert_book(
        folder_id=fid, path="gdrive://1/pinned", filename="pinned.pdf", format="pdf",
        size_bytes=1000, file_mtime=1.0, title="Pinned", source="gdrive",
        drive_file_id="pinned", keep_offline=1,
    )
    repo.set_cached_file(b1, str(p1), 1000, "hash1")
    detail1 = repo.get_book_detail(b1)
    assert classify_book(detail1, policy, recent_book_ids={}) == ProtectionTier.TIER_0_PROTECTED

    # 2. Reading book -> Tier 1
    p2 = cache_dir / "reading.pdf"
    p2.touch()
    b2 = repo.upsert_book(
        folder_id=fid, path="gdrive://1/reading", filename="reading.pdf", format="pdf",
        size_bytes=1000, file_mtime=1.0, title="Reading", source="gdrive",
        drive_file_id="reading", status="reading",
    )
    repo.set_cached_file(b2, str(p2), 1000, "hash2")
    detail2 = repo.get_book_detail(b2)
    assert classify_book(detail2, policy, recent_book_ids={}) == ProtectionTier.TIER_1_RECENT

    # 3. Regular unpinned book -> Tier 2
    p3 = cache_dir / "other.pdf"
    p3.touch()
    b3 = repo.upsert_book(
        folder_id=fid, path="gdrive://1/other", filename="other.pdf", format="pdf",
        size_bytes=1000, file_mtime=1.0, title="Other", source="gdrive",
        drive_file_id="other",
    )
    repo.set_cached_file(b3, str(p3), 1000, "hash3")
    detail3 = repo.get_book_detail(b3)
    assert classify_book(detail3, policy, recent_book_ids={}) == ProtectionTier.TIER_2_CANDIDATE


def test_cleanup_planning_and_execution(repo: Repository, tmp_path: Path, monkeypatch):
    empty_covers = tmp_path / "covers"
    empty_covers.mkdir()
    monkeypatch.setattr("booklib.storage.planner.COVERS_DIR", empty_covers)
    monkeypatch.setattr("booklib.storage.planner.get_storage_areas", lambda: {})

    cache_dir = tmp_path / "drive_cache"
    cache_dir.mkdir()
    register_marker(cache_dir)

    fid = repo.add_folder("C:/DriveFolder")

    # Create old book (40 days old)
    old_file = cache_dir / "old_book.epub"
    old_file.write_bytes(b"x" * 2048)
    b_old = repo.upsert_book(
        folder_id=fid, path="gdrive://1/old", filename="old_book.epub", format="epub",
        size_bytes=2048, file_mtime=1.0, title="Old Book", source="gdrive", drive_file_id="old",
    )
    repo.set_cached_file(b_old, str(old_file), 2048, "hash_old")
    # Backdate last_opened_at in drive_cache
    old_time = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    repo._conn.execute("UPDATE drive_cache SET last_opened_at = ? WHERE book_id = ?", (old_time, b_old))
    repo._conn.commit()

    # Create recent pinned book
    pinned_file = cache_dir / "pinned_book.pdf"
    pinned_file.write_bytes(b"y" * 1024)
    b_pinned = repo.upsert_book(
        folder_id=fid, path="gdrive://1/pinned", filename="pinned_book.pdf", format="pdf",
        size_bytes=1024, file_mtime=1.0, title="Pinned Book", source="gdrive",
        drive_file_id="pinned", keep_offline=1,
    )
    repo.set_cached_file(b_pinned, str(pinned_file), 1024, "hash_pin")

    policy = StoragePolicy(max_age_days=30, size_cap_bytes=100000)

    # 1. Dry run plan
    plan = plan_cleanup(repo, policy, reason="routine")
    assert plan.file_count == 1
    assert plan.actions[0].path == old_file
    assert plan.actions[0].reason == "age"

    # Old file still exists before execution
    assert old_file.exists()

    # 2. Execute plan
    result = execute_cleanup(repo, plan)
    assert result.files_deleted == 1
    assert not old_file.exists()
    assert pinned_file.exists()

    # Check drive_cache row for b_old was cleared
    row = repo._conn.execute("SELECT * FROM drive_cache WHERE book_id = ?", (b_old,)).fetchone()
    assert row is None


def test_safe_delete_guards(tmp_path: Path):
    non_cache_dir = tmp_path / "documents"
    non_cache_dir.mkdir()
    doc_file = non_cache_dir / "important.docx"
    doc_file.touch()

    # safe_delete_file must refuse to delete a file in a folder without .booklib-cache marker
    assert not safe_delete_file(doc_file)
    assert doc_file.exists()


def test_startup_consistency_check(repo: Repository, tmp_path: Path):
    cache_dir = tmp_path / "drive_cache"
    cache_dir.mkdir()
    register_marker(cache_dir)

    fid = repo.add_folder("C:/DriveFolder")

    # Insert a drive_cache entry whose file does NOT exist on disk
    missing_file = cache_dir / "gone.pdf"
    b_gone = repo.upsert_book(
        folder_id=fid, path="gdrive://1/gone", filename="gone.pdf", format="pdf",
        size_bytes=1000, file_mtime=1.0, title="Gone", source="gdrive", drive_file_id="gone",
    )
    repo.set_cached_file(b_gone, str(missing_file), 1000, "hash_gone")

    # Run consistency check
    run_startup_consistency_check(repo)

    # Missing file's drive_cache record must be cleaned up
    row = repo._conn.execute("SELECT * FROM drive_cache WHERE book_id = ?", (b_gone,)).fetchone()
    assert row is None

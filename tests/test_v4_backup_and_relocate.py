"""
test_v4_backup_and_relocate.py – Library backup creation, security check, restore staging, and folder relocation tests.
"""
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from booklib.db.database import Database
from booklib.db.repository import Repository
from booklib.drive.backup import create_backup, verify_backup_zip, prepare_restore
from booklib.tools.relocate import relocate_folder, RelocationError


@pytest.fixture
def repo(tmp_path: Path):
    db = Database(tmp_path / "test_backup.db")
    conn = db.connect()
    r = Repository(conn)
    yield r
    db.close()


def test_backup_and_security(repo: Repository, tmp_path: Path):
    # Insert a book
    fid = repo.add_folder("C:/Books")
    repo.upsert_book(
        folder_id=fid, path="C:/Books/book1.pdf", filename="book1.pdf",
        format="pdf", size_bytes=1000, file_mtime=1.0, title="Test Book",
    )

    # Create backup zip
    zip_path = create_backup(repo)
    assert zip_path.exists()

    # Verify backup zip integrity
    manifest = verify_backup_zip(zip_path)
    assert manifest["book_count"] >= 1
    assert "db_sha256" in manifest

    # Security check: verify NO secrets exist in zip
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "library.db" in namelist
        assert "manifest.json" in namelist

        for name in namelist:
            assert "client_secret" not in name.lower()
            assert "token" not in name.lower()
            assert ".json" not in name or name == "manifest.json"


def test_prepare_restore(repo: Repository, tmp_path: Path):
    zip_path = create_backup(repo)

    # Prepare restore
    staging_dir, pre_restore_path = prepare_restore(zip_path)

    assert staging_dir.exists()
    assert (staging_dir / "library.db").exists()
    assert pre_restore_path.exists()
    assert ".pre-restore" in str(pre_restore_path)


def test_folder_relocation(repo: Repository, tmp_path: Path):
    old_dir = tmp_path / "old_library"
    old_dir.mkdir()
    book_file_old = old_dir / "novel.epub"
    book_file_old.touch()

    new_dir = tmp_path / "new_library"
    new_dir.mkdir()
    book_file_new = new_dir / "novel.epub"
    book_file_new.touch()

    fid = repo.add_folder(str(old_dir))
    bid = repo.upsert_book(
        folder_id=fid,
        path=str(book_file_old),
        filename="novel.epub",
        format="epub",
        size_bytes=1000,
        file_mtime=1.0,
        title="Novel",
    )

    # Relocate folder from old_dir to new_dir
    result = relocate_folder(repo, fid, str(new_dir))
    assert result.books_updated == 1

    # Check updated book path
    b = repo.get_book_row(bid)
    assert Path(b.path) == Path(book_file_new)
    assert b.is_missing is False

    # Check folder record updated
    folder = next(f for f in repo.list_folders() if f["id"] == fid)
    assert Path(folder["path"]) == Path(new_dir)

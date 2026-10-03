"""
test_v4_drive.py – Google Drive core, models, virtual paths, client mocking, ancestry, and download tests.
"""
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from booklib.db.database import Database
from booklib.db.repository import Repository
from booklib.drive.models import (
    DriveFile,
    make_virtual_drive_path,
    parse_virtual_drive_path,
    is_drive,
    OfflineError,
    TransientError,
    AuthExpired,
)
from booklib.drive.auth import InMemoryTokenStore, TokenStore
from booklib.drive.client import DriveClient
from booklib.drive.download import sanitize_filename, download_drive_file
from booklib.drive.sync import sync_drive_changes


@pytest.fixture
def repo(tmp_path: Path):
    db = Database(tmp_path / "test_drive.db")
    conn = db.connect()
    r = Repository(conn)
    yield r
    db.close()


def test_virtual_paths():
    vpath = make_virtual_drive_path(42, "file_abc_123")
    assert vpath == "gdrive://42/file_abc_123"
    assert is_drive(vpath)

    acc_id, file_id = parse_virtual_drive_path(vpath)
    assert acc_id == 42
    assert file_id == "file_abc_123"

    assert not is_drive("C:/Books/local.pdf")
    assert not is_drive("/home/user/book.epub")


def test_filename_sanitization():
    # Invalid characters in Windows: <>:"/\|?*
    dirty = 'Book: A <Great> "Story" / Chapter 1\\Part 2? *Yes*.pdf'
    clean = sanitize_filename(dirty)
    for ch in '<>:"/\\|?*':
        assert ch not in clean

    # Reserved names
    assert sanitize_filename("CON.pdf") == "_CON.pdf"
    assert sanitize_filename("nul.epub") == "_nul.epub"
    assert sanitize_filename("aux.mobi") == "_aux.mobi"


def test_in_memory_token_store():
    store = InMemoryTokenStore()
    assert store.get_refresh_token("user@example.com") is None
    store.save_refresh_token("user@example.com", "refresh_token_123")
    assert store.get_refresh_token("user@example.com") == "refresh_token_123"
    store.delete_refresh_token("user@example.com")
    assert store.get_refresh_token("user@example.com") is None


def test_client_listing_and_shortcuts():
    mock_session = MagicMock()

    # Response with a regular file, a shortcut, and a Google Doc
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "files": [
            {
                "id": "file1",
                "name": "Dune.pdf",
                "mimeType": "application/pdf",
                "size": "5000000",
                "md5Checksum": "abc123md5",
                "parents": ["root"],
            },
            {
                "id": "shortcut1",
                "name": "SciFi_Shortcut",
                "mimeType": "application/vnd.google-apps.shortcut",
                "shortcutDetails": {"targetId": "target_folder_1", "targetMimeType": "application/vnd.google-apps.folder"},
                "parents": ["root"],
            },
            {
                "id": "gdoc1",
                "name": "My Google Doc",
                "mimeType": "application/vnd.google-apps.document",
                "parents": ["root"],
            }
        ]
    }
    mock_session.get.return_value = fake_response

    client = DriveClient(credentials=None, session=mock_session)
    files = client.list_files(query="trashed = false")

    assert len(files) == 3
    # Check regular file
    assert files[0].id == "file1"
    assert files[0].is_shortcut is False
    assert files[0].is_google_doc is False

    # Check shortcut
    assert files[1].is_shortcut is True
    assert files[1].target_id == "target_folder_1"

    # Check google doc
    assert files[2].is_google_doc is True


def test_download_resumable_and_checksum(tmp_path: Path):
    content = b"This is the full book content for downloading test."
    content_md5 = hashlib.md5(content).hexdigest()

    mock_client = MagicMock()
    mock_client.download_file.return_value = iter([content[:20], content[20:]])

    dest_dir = tmp_path / "downloads"
    dest_dir.mkdir()

    # Download file
    saved_path = download_drive_file(
        client=mock_client,
        file_id="drive_file_1",
        dest_dir=dest_dir,
        expected_size=len(content),
        expected_md5=content_md5,
        filename="dune.pdf",
    )

    assert saved_path.exists()
    assert saved_path.read_bytes() == content
    # .part file must not remain
    part_files = list(dest_dir.glob("*.part"))
    assert len(part_files) == 0


def test_incremental_sync(repo: Repository):
    mock_client = MagicMock()

    # 1. Setup account and folder
    acc_id = repo.upsert_drive_account("sync_user@gmail.com", "Sync User")
    folder_id = repo.add_drive_folder(
        account_id=acc_id,
        drive_folder_id="drive_folder_root",
        folder_name="Drive Books",
    )
    repo.update_drive_folder_sync_token(folder_id, "token_100")

    # 2. Mock list_changes returning 1 updated book and 1 removed file
    mock_client.list_changes.return_value = (
        [
            {
                "fileId": "file_new",
                "removed": False,
                "file": {
                    "id": "file_new",
                    "name": "New Book.epub",
                    "mimeType": "application/epub+zip",
                    "size": "2048",
                    "md5Checksum": "md5_new",
                    "parents": ["drive_folder_root"],
                    "trashed": False,
                }
            },
            {
                "fileId": "file_removed",
                "removed": True,
            }
        ],
        "token_101",
    )

    # Pre-insert the file to be removed
    b_rem = repo.upsert_book(
        folder_id=folder_id, path="gdrive://1/file_removed", filename="old.pdf",
        format="pdf", size_bytes=1000, file_mtime=1.0, title="Old", source="gdrive",
        drive_file_id="file_removed",
    )

    # Run sync
    res = sync_drive_changes(repo, mock_client, acc_id)

    assert res.books_upserted >= 1
    assert res.books_marked_missing >= 1

    # Verify removed book is marked missing
    row_rem = repo.get_book_row(b_rem)
    assert row_rem.is_missing is True

    # Verify new sync token is recorded
    token = repo.get_drive_folder_sync_token(folder_id)
    assert token == "token_101"

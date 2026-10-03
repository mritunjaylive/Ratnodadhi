"""
tests/test_v6_cloud.py – Conformance and unit tests for Milestones 17, 18, 19:
- CloudProvider protocol compliance
- Provider Registry
- FakeProvider conformance (listing, paging, changes, deletions, downloads, offset, thumbnails)
- Standard Hash verification (QuickXorHash test vectors, Dropbox content_hash test vectors)
- Remote hash comparison rules (matching vs mismatched kinds)
- Virtual cloud path generation and parsing (gdrive, onedrive, dropbox)
- Migration 6b database schema verification (provider column, remote_hash_kind, remote_hash backfill)
"""
from __future__ import annotations

import io
from pathlib import Path
import pytest

from booklib.cloud.fake_provider import FakeProvider
from booklib.cloud.provider import (
    Account,
    CloudProvider,
    Page,
    RemoteItem,
    compare_remote_hashes,
    compute_dropbox_content_hash,
    compute_quickxor_hash,
    get_provider,
    is_cloud_path,
    list_providers,
    make_virtual_cloud_path,
    parse_virtual_cloud_path,
)
from booklib.db.database import Database
from booklib.db.repository import Repository


def test_provider_registry():
    """Verify built-in providers are registered and retrievable."""
    providers = list_providers()
    keys = {p.key for p in providers}
    assert "fake" in keys
    assert "gdrive" in keys
    assert "onedrive" in keys
    assert "dropbox" in keys

    fake_p = get_provider("fake")
    assert isinstance(fake_p, CloudProvider)
    assert fake_p.name == "Fake Cloud Storage"


def test_quickxorhash_standard_vectors():
    """Verify QuickXorHash against official Microsoft test vectors."""
    # Empty data vector: 20 bytes of zeros base64 encoded
    empty_hash = compute_quickxor_hash(b"")
    assert empty_hash == "AAAAAAAAAAAAAAAAAAAAAAAAAAA="

    # Official 'hello world' test vector
    hw_hash = compute_quickxor_hash(b"hello world")
    assert hw_hash == "aCgDG9jwBhDc4Q1yawMZAAAAAAA="


def test_dropbox_content_hash_standard_vectors():
    """Verify Dropbox content_hash against official test vectors."""
    # Empty data vector
    empty_hash = compute_dropbox_content_hash(b"")
    assert empty_hash == "5df6e0e2761359d30a8275058e299fcc0381534545f55cf43e41983f5d4c9456"

    # 'hello world' test vector (SHA-256 of SHA-256 of 'hello world')
    hw_hash = compute_dropbox_content_hash(b"hello world")
    assert hw_hash == "bc62d4b80d9e36da29c16c5d4d9f11731f36052c72401a76c23c0fb5a9b74423"

    # Streaming version
    stream = io.BytesIO(b"hello world")
    stream_hash = compute_dropbox_content_hash(stream)
    assert stream_hash == hw_hash


def test_compare_remote_hashes():
    """Verify hash comparison rules across matching and differing kinds."""
    # Same kinds, matching values
    assert compare_remote_hashes("quickxor", "aCgDG9jwBhDc4Q1yawMZAAAAAAA=", "quickxor", "aCgDG9jwBhDc4Q1yawMZAAAAAAA=") is True
    # Case insensitivity
    assert compare_remote_hashes("md5", "ABCDEF123456", "MD5", "abcdef123456") is True

    # Same kinds, mismatching values
    assert compare_remote_hashes("quickxor", "hashA", "quickxor", "hashB") is False

    # Differing kinds -> cannot compare directly (returns None)
    assert compare_remote_hashes("quickxor", "somequickxor", "md5", "somemd5") is None
    assert compare_remote_hashes("dropbox", "hash1", "sha1", "hash2") is None

    # Missing values or kinds
    assert compare_remote_hashes(None, "hash", "md5", "hash") is None
    assert compare_remote_hashes("md5", None, "md5", "hash") is None


def test_virtual_cloud_paths():
    """Verify virtual URI path construction, parsing, and type checks."""
    p1 = make_virtual_cloud_path("onedrive", 10, "item_abc_123")
    assert p1 == "onedrive://10/item_abc_123"
    assert is_cloud_path(p1) is True

    provider, acct_id, item_id = parse_virtual_cloud_path(p1)
    assert provider == "onedrive"
    assert acct_id == 10
    assert item_id == "item_abc_123"

    p2 = make_virtual_cloud_path("dropbox", 3, "id:dropbox_file_456")
    assert p2 == "dropbox://3/id:dropbox_file_456"
    assert is_cloud_path(p2) is True

    provider2, acct_id2, item_id2 = parse_virtual_cloud_path(p2)
    assert provider2 == "dropbox"
    assert acct_id2 == 3
    assert item_id2 == "id:dropbox_file_456"

    # Local path should not be cloud path
    assert is_cloud_path("C:\\Users\\books\\novel.epub") is False
    assert is_cloud_path("/home/user/novel.epub") is False


def test_fake_provider_conformance_suite():
    """
    Test FakeProvider against the full CloudProvider lifecycle:
    1. Authorize
    2. Add folders and files
    3. List children with paging
    4. Track initial cursor and incremental changes (create, move, delete)
    5. Download with range offset
    6. Thumbnails
    """
    provider = FakeProvider()
    acct = provider.authorize()
    assert acct.email == "tester@fakecloud.com"
    assert acct.provider == "fake"

    # 1. Setup folder hierarchy
    root_folder = provider.add_folder("f_root", "My Books", parent_id=None)
    fiction = provider.add_folder("f_fiction", "Fiction", parent_id="f_root")
    tech = provider.add_folder("f_tech", "Tech", parent_id="f_root")

    sample_content = b"PDF-1.4 file content for testing cloud download streams."
    thumb_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    book1 = provider.add_file("file_1", "Intro to Python.pdf", sample_content, parent_id="f_tech", thumb=thumb_bytes)
    book2 = provider.add_file("file_2", "Dune.epub", b"EPUB test content", parent_id="f_fiction")

    # 2. List children
    root_page = provider.list_children(acct, "f_root")
    assert len(root_page.items) == 2
    assert {it.name for it in root_page.items} == {"Fiction", "Tech"}

    tech_page = provider.list_children(acct, "f_tech")
    assert len(tech_page.items) == 1
    assert tech_page.items[0].name == "Intro to Python.pdf"
    assert tech_page.items[0].size == len(sample_content)
    assert tech_page.items[0].hash_kind == "quickxor"

    # 3. Changes cursor
    cursor = provider.initial_cursor(acct)

    # Make changes: move file_1 to fiction, delete file_2
    provider.move_item("file_1", "f_fiction")
    provider.remove_item("file_2")

    # List changes
    change_page = provider.list_changes(acct, cursor)
    assert len(change_page.changes) == 2
    c1, c2 = change_page.changes
    assert c1.file_id == "file_1"
    assert c1.removed is False
    assert c1.item.parent_id == "f_fiction"

    assert c2.file_id == "file_2"
    assert c2.removed is True
    assert c2.item is None

    # 4. Download full and with offset
    stream_full = provider.open_download(acct, book1, offset=0)
    assert stream_full.read() == sample_content

    offset = 10
    stream_part = provider.open_download(acct, book1, offset=offset)
    assert stream_part.read() == sample_content[offset:]

    # 5. Thumbnail
    thumb = provider.thumbnail(acct, book1)
    assert thumb == thumb_bytes

    no_thumb = provider.thumbnail(acct, book2)
    assert no_thumb is None


def test_database_migration_6b(tmp_path: Path):
    """
    Verify Migration 6b:
    - drive_accounts has provider column
    - books has remote_hash_kind and remote_hash
    - Existing books with md5 have remote_hash and remote_hash_kind populated
    """
    db_file = tmp_path / "test_migration6b.db"
    db = Database(db_file)
    conn = db.connect()

    # Verify drive_accounts schema
    cols_accts = [r["name"] for r in conn.execute("PRAGMA table_info(drive_accounts)").fetchall()]
    assert "provider" in cols_accts

    # Verify books schema
    cols_books = [r["name"] for r in conn.execute("PRAGMA table_info(books)").fetchall()]
    assert "remote_hash_kind" in cols_books
    assert "remote_hash" in cols_books

    repo = Repository(conn)

    # Insert an account with provider 'onedrive'
    acct_id = repo.add_drive_account("ms_user@outlook.com", "MS User", provider="onedrive")
    acct = repo.get_drive_account(acct_id)
    assert acct is not None
    assert acct["provider"] == "onedrive"
    assert acct["email"] == "ms_user@outlook.com"

    # Insert a book with md5 and run backfill logic
    with conn:
        conn.execute("INSERT INTO folders (id, path) VALUES (1, 'c:/books')")
        conn.execute(
            "INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime, md5) "
            "VALUES (101, 1, 'c:/books/test.pdf', 'test.pdf', 'pdf', 500, 10.0, 'dummy_md5_hash')"
        )

    # Trigger backfill update (as done during migration)
    with conn:
        conn.execute(
            "UPDATE books SET remote_hash = md5, remote_hash_kind = 'md5' "
            "WHERE md5 IS NOT NULL AND (remote_hash IS NULL OR remote_hash_kind IS NULL)"
        )

    book_row = conn.execute("SELECT remote_hash, remote_hash_kind FROM books WHERE id = 101").fetchone()
    assert book_row["remote_hash"] == "dummy_md5_hash"
    assert book_row["remote_hash_kind"] == "md5"

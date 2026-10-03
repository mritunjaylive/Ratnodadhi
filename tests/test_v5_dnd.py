"""
tests/test_v5_dnd.py – Unit tests for Milestone 3 (Drag and drop and Add Files).
"""
import shutil
import sqlite3
from pathlib import Path

import pytest

from booklib.duplicates.hashing import compute_quick_hash
from booklib.storage.guard import guard_add_files
from booklib.watcher.folder_watcher import FolderWatcher, is_supported_file


@pytest.fixture
def mock_library(tmp_path):
    library_folder = tmp_path / "MyLibrary"
    library_folder.mkdir()

    outside_folder = tmp_path / "Downloads"
    outside_folder.mkdir()

    # Create dummy ebook files
    file1 = outside_folder / "novel.epub"
    file1.write_bytes(b"PK\x03\x04" + b"A" * 1024)

    file2 = outside_folder / "notes.pdf"
    file2.write_bytes(b"%PDF-1.4" + b"B" * 2048)

    db_path = tmp_path / "library.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version = 5")
    conn.execute(
        """CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            folder_id INTEGER,
            path TEXT NOT NULL,
            title TEXT,
            size_bytes INTEGER,
            quick_hash TEXT,
            is_missing INTEGER DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE TABLE temp_files (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            purpose TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.commit()

    yield conn, library_folder, outside_folder, [file1, file2]
    conn.close()


def test_is_supported_file():
    assert is_supported_file("book.epub") is True
    assert is_supported_file("doc.pdf") is True
    assert is_supported_file("notes.txt") is True
    assert is_supported_file("temp.part") is False
    assert is_supported_file(".hidden.epub") is False


def test_quick_hash_calculation(mock_library):
    _, _, _, files = mock_library
    f = files[0]
    size = f.stat().st_size
    qh = compute_quick_hash(f, size)
    assert qh is not None
    assert len(qh) == 64


def test_duplicate_check_and_copy(mock_library):
    conn, lib_folder, _, files = mock_library
    f = files[0]
    size = f.stat().st_size
    qh = compute_quick_hash(f, size)

    # 1. First copy: file doesn't exist in lib_folder
    dest_file = lib_folder / f.name
    shutil.copy2(str(f), str(dest_file))
    conn.execute(
        "INSERT INTO books (folder_id, path, title, size_bytes, quick_hash) VALUES (?, ?, ?, ?, ?)",
        (1, str(dest_file), "Novel", size, qh),
    )
    conn.commit()

    # 2. Second file with same size and quick_hash is detected as duplicate
    dup_row = conn.execute(
        "SELECT id FROM books WHERE size_bytes = ? AND quick_hash = ? AND is_missing = 0",
        (size, qh),
    ).fetchone()
    assert dup_row is not None


def test_watcher_own_changes(tmp_path):
    watcher = FolderWatcher()
    test_path = tmp_path / "book.epub"
    watcher.add_own_change(test_path)
    assert str(test_path.resolve()) in watcher._own_changes

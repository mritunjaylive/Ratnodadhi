"""
test_walker.py – unit tests for the filesystem walker.
"""
import os
import time
from pathlib import Path

import pytest

from booklib.scanner.walker import walk_folder


@pytest.fixture()
def tmp_lib(tmp_path: Path):
    """A small temporary folder with a few book files."""
    (tmp_path / "book1.pdf").write_bytes(b"%PDF test")
    (tmp_path / "book2.epub").write_bytes(b"PK test")
    (tmp_path / "readme.txt").write_bytes(b"hello")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "book3.mobi").write_bytes(b"MOBI test")
    (tmp_path / ".hidden.pdf").write_bytes(b"ignored")
    return tmp_path


def test_walk_finds_new_files(tmp_lib):
    result = walk_folder(str(tmp_lib), db_index={})
    paths = [p for p, *_ in result.new]
    assert any("book1.pdf" in p for p in paths)
    assert any("book2.epub" in p for p in paths)
    assert any("book3.mobi" in p for p in paths)
    assert any("readme.txt" in p for p in paths)
    # Hidden files excluded
    assert not any(".hidden" in p for p in paths)


def test_walk_unchanged(tmp_lib):
    # Build a db_index that exactly matches the files the walker would find.
    # Hidden files (.hidden.pdf) are skipped by the walker, so they must NOT
    # be in the db_index (otherwise they'd appear as "missing").
    db_index = {}
    for dirpath, dirnames, filenames in os.walk(str(tmp_lib)):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            full = str(Path(dirpath) / name)
            stat = os.stat(full)
            db_index[full] = {"size_bytes": stat.st_size, "file_mtime": stat.st_mtime}

    result = walk_folder(str(tmp_lib), db_index=db_index)
    # All files match → unchanged
    assert result.new == []
    assert result.changed == []
    assert result.missing == []
    assert len(result.unchanged) > 0


def test_walk_changed_file(tmp_lib):
    book_path = str(tmp_lib / "book1.pdf")
    stat = os.stat(book_path)
    # Report a different size in the index
    db_index = {book_path: {"size_bytes": stat.st_size + 100, "file_mtime": stat.st_mtime}}
    result = walk_folder(str(tmp_lib), db_index=db_index)
    changed_paths = [p for p, *_ in result.changed]
    assert book_path in changed_paths


def test_walk_missing(tmp_lib):
    ghost_path = str(tmp_lib / "ghost.pdf")
    db_index = {ghost_path: {"size_bytes": 100, "file_mtime": 0.0}}
    result = walk_folder(str(tmp_lib), db_index=db_index)
    assert ghost_path in result.missing

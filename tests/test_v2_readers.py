"""
test_v2_readers.py – Tests for reader detection parsing, custom readers and defaults.
"""
from pathlib import Path

import pytest

from booklib.db.database import Database
from booklib.db.repository import Repository
from booklib.readers.detect_windows import _exe_from_command, _SKIP_EXES
from booklib.readers.models import Reader
from booklib.readers.registry import ReaderRegistry


def test_extract_exe_from_command():
    # Quoted path
    cmd1 = r'"C:\Program Files\SumatraPDF\SumatraPDF.exe" "%1"'
    exe1 = _exe_from_command(cmd1)
    assert exe1 == r"C:\Program Files\SumatraPDF\SumatraPDF.exe"

    # Unquoted path with arguments
    cmd2 = r'C:\Tools\Reader.exe /opt "%1"'
    exe2 = _exe_from_command(cmd2)
    assert exe2 == r"C:\Tools\Reader.exe"

    # System launchers should be in _SKIP_EXES
    assert "rundll32.exe" in _SKIP_EXES
    assert "explorer.exe" in _SKIP_EXES
    assert "cmd.exe" in _SKIP_EXES
    assert "powershell.exe" in _SKIP_EXES


def test_reader_model():
    r = Reader(
        key="custom:1",
        name="SumatraPDF",
        exe=r"C:\Sumatra\SumatraPDF.exe",
        formats=frozenset({"pdf", "epub"}),
    )
    assert r.handles("pdf") is True
    assert r.handles(".PDF") is True
    assert r.handles("epub") is True
    assert r.handles("mobi") is False

    # Wildcard formats
    r_all = Reader(
        key="custom:2",
        name="Universal",
        exe=r"C:\App.exe",
        formats=frozenset({"*"}),
    )
    assert r_all.handles("pdf") is True
    assert r_all.handles("cbz") is True


def test_custom_readers_and_defaults(tmp_path: Path):
    db = Database(tmp_path / "readers_test.db")
    conn = db.connect()
    repo = Repository(conn)

    # Add custom reader
    rid = repo.add_custom_reader(
        name="My PDF Reader",
        exe_path=r"C:\Custom\reader.exe",
        args_template="{file} --fullscreen",
        formats="pdf,djvu",
    )
    assert rid > 0

    customs = repo.list_custom_readers()
    assert len(customs) == 1
    assert customs[0]["name"] == "My PDF Reader"
    assert customs[0]["formats"] == "pdf,djvu"

    # Set default reader for pdf
    repo.set_format_default("pdf", f"custom:{rid}")
    assert repo.get_format_default("pdf") == f"custom:{rid}"
    assert repo.get_format_default("epub") is None

    # Test ReaderRegistry integrates with repo
    reg = ReaderRegistry(repo=repo)
    readers = reg.readers_for("pdf")
    # Custom reader should be present and prioritized
    keys = [r.key for r in readers]
    assert f"custom:{rid}" in keys

    # Remove custom reader
    repo.remove_custom_reader(rid)
    customs_after = repo.list_custom_readers()
    assert len(customs_after) == 0

    db.close()

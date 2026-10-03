"""
tests/test_v5_actions.py – Unit tests for Milestone 2: Central action registry and shortcuts.
"""
import pytest
from booklib.actions import (
    get_all_defs,
    get_def,
    save_shortcut,
    reset_shortcut,
    detect_conflicts,
    ActionDef,
)


def test_action_registry_contains_expected_actions():
    defs = get_all_defs()
    ids = {d.id for d in defs}

    expected = {
        "file.add_files",
        "file.add_folder",
        "edit.edit_metadata",
        "library.rename",
        "library.convert",
        "library.export",
        "library.import_",
        "library.health",
        "view.statistics",
        "tools.backup",
        "tools.restore",
        "tools.compact_db",
        "tools.fix_dates",
        "storage.clean_now",
        "storage.open_settings",
        "help.palette",
        "help.cheat_sheet",
    }
    missing = expected - ids
    assert not missing, f"Missing actions in registry: {missing}"


def test_get_def():
    d = get_def("help.palette")
    assert d is not None
    assert d.default_shortcut == "Ctrl+K"
    assert d.menu == "Help"


def test_save_and_reset_shortcut():
    save_shortcut("help.palette", "Ctrl+Shift+P")
    from PySide6.QtCore import QSettings
    settings = QSettings("Ratnodadhi", "Ratnodadhi")
    assert settings.value("shortcuts/help.palette") == "Ctrl+Shift+P"

    reset_shortcut("help.palette")
    assert settings.value("shortcuts/help.palette") is None

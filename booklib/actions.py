"""
actions.py – Central action registry for Ratnodadhi.

Every user command is an ActionDef with:
  - id:               unique dot-namespaced string ('library.rescan')
  - text:             display name in menus and palette
  - default_shortcut: key sequence string (empty = no shortcut)
  - menu:             which menu it lives in ('File', 'Library', …)
  - context:          'window' | 'library_view' | 'details'
  - icon:             optional icon name/path
  - enabled_when:     optional callable(main_window) → bool

QActions are built from the registry once; menus, toolbar, context menus
and the command palette all use those same QAction objects, so changing
a shortcut applies everywhere.

Usage:
    from booklib.actions import build_actions, get_action
    build_actions(main_window)
    get_action('library.rescan').trigger()
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

# ── ActionDef ──────────────────────────────────────────────────────────────────

@dataclass
class ActionDef:
    id: str
    text: str
    default_shortcut: str = ""
    menu: str = ""                          # menu group name
    context: str = "window"                 # 'window' | 'library_view' | 'details'
    icon: str = ""                          # optional icon name
    enabled_when: Callable | None = None    # callable(window) → bool; None = always


# ── Registry ───────────────────────────────────────────────────────────────────

_REGISTRY: list[ActionDef] = [

    # ── File ──────────────────────────────────────────────────────────────────
    ActionDef("file.add_files",       "Add files…",         "Ctrl+O",       "File"),
    ActionDef("file.add_folder",      "Add folder…",        "Ctrl+Shift+O", "File"),
    ActionDef("file.open_book",       "Open book",          "Return",       "File", "library_view"),
    ActionDef("file.open_with",       "Open with…",         "Shift+Return", "File", "library_view"),
    ActionDef("file.settings",        "Settings…",          "Ctrl+,",       "File"),

    # ── Edit ──────────────────────────────────────────────────────────────────
    ActionDef("edit.undo",            "Undo",               "Ctrl+Z",       "Edit"),
    ActionDef("edit.redo",            "Redo",               "Ctrl+Y",       "Edit"),
    ActionDef("edit.select_all",      "Select all",         "Ctrl+A",       "Edit"),
    ActionDef("edit.edit_metadata",   "Edit metadata",      "Ctrl+E",       "Edit", "library_view"),
    ActionDef("edit.fetch_metadata",  "Fetch online metadata", "Ctrl+I",    "Edit", "library_view"),
    ActionDef("edit.rename_file",     "Rename file",        "F2",           "Edit", "library_view"),
    ActionDef("edit.add_tag",         "Add tag",            "Ctrl+T",       "Edit", "library_view"),

    # ── View ──────────────────────────────────────────────────────────────────
    ActionDef("view.grid",            "Grid view",          "Ctrl+G",       "View"),
    ActionDef("view.list",            "List view",          "",             "View"),
    ActionDef("view.toggle_sidebar",  "Toggle sidebar",     "Ctrl+B",       "View"),
    ActionDef("view.toggle_details",  "Toggle details pane","F4",           "View"),
    ActionDef("view.statistics",      "Statistics",         "F6",           "View"),
    ActionDef("view.focus_search",    "Focus search bar",   "Ctrl+F",       "View"),
    ActionDef("view.clear_search",    "Clear search",       "Escape",       "View"),

    # ── Status ────────────────────────────────────────────────────────────────
    ActionDef("status.want",          "Mark as Want to Read","Ctrl+1",       "Library", "library_view"),
    ActionDef("status.reading",       "Mark as Reading",    "Ctrl+2",       "Library", "library_view"),
    ActionDef("status.read",          "Mark as Read",       "Ctrl+3",       "Library", "library_view"),
    ActionDef("status.clear",         "Clear status",       "Ctrl+0",       "Library", "library_view"),
    ActionDef("rating.1",             "Rate 1 star",        "Alt+1",        "Library", "library_view"),
    ActionDef("rating.2",             "Rate 2 stars",       "Alt+2",        "Library", "library_view"),
    ActionDef("rating.3",             "Rate 3 stars",       "Alt+3",        "Library", "library_view"),
    ActionDef("rating.4",             "Rate 4 stars",       "Alt+4",        "Library", "library_view"),
    ActionDef("rating.5",             "Rate 5 stars",       "Alt+5",        "Library", "library_view"),
    ActionDef("rating.clear",         "Clear rating",       "Alt+0",        "Library", "library_view"),

    # ── Library ───────────────────────────────────────────────────────────────
    ActionDef("library.rescan",       "Rescan folders",     "F5",           "Library"),
    ActionDef("library.sync_drive",   "Sync Google Drive",  "Ctrl+F5",      "Library"),
    ActionDef("library.rename",       "Rename files…",      "",             "Library"),
    ActionDef("library.convert",      "Convert format…",    "",             "Library", "library_view"),
    ActionDef("library.export",       "Export library…",    "",             "Library"),
    ActionDef("library.import_",      "Import…",            "",             "Library"),
    ActionDef("library.health",       "Library health…",    "",             "Library"),
    ActionDef("library.search_inside", "Search inside books…", "Ctrl+Shift+F", "Library"),
    ActionDef("reader.open",          "Open in built-in reader", "Ctrl+R",      "File", "library_view"),
    ActionDef("view.annotations",     "Highlights & notes",  "Ctrl+H",       "View"),

    # ── Tools ─────────────────────────────────────────────────────────────────
    ActionDef("tools.backup",         "Backup library…",    "",             "Tools"),
    ActionDef("tools.restore",        "Restore backup…",    "",             "Tools"),
    ActionDef("tools.compact_db",     "Compact database…",  "",             "Tools"),
    ActionDef("tools.fix_dates",      "Fix reading dates…", "",             "Tools"),
    ActionDef("tools.surprise_me",    "Surprise me (Random book)", "Ctrl+Alt+R", "Tools"),
    ActionDef("tools.recommendations","Recommendations…",   "",             "Tools"),
    ActionDef("tools.web_access",     "Web access & pairing…", "",          "Tools"),

    # ── Storage ───────────────────────────────────────────────────────────────
    ActionDef("storage.clean_now",    "Clean up storage now", "",           "Tools"),
    ActionDef("storage.open_settings","Open Storage settings", "",          "Tools"),

    # ── Help ──────────────────────────────────────────────────────────────────
    ActionDef("help.palette",         "Command palette",    "Ctrl+K",       "Help"),
    ActionDef("help.cheat_sheet",     "Keyboard shortcuts", "Ctrl+/",       "Help"),
    ActionDef("help.about",           "About Ratnodadhi…",  "",             "Help"),
]

# Map id → ActionDef for quick lookup
_REGISTRY_MAP: dict[str, ActionDef] = {a.id: a for a in _REGISTRY}

# Instantiated QActions (built once per window)
_ACTIONS: dict[str, QAction] = {}


def get_all_defs() -> list[ActionDef]:
    """Return all registered ActionDef objects."""
    return list(_REGISTRY)


def get_def(action_id: str) -> ActionDef | None:
    return _REGISTRY_MAP.get(action_id)


def build_actions(window: QWidget, handlers: dict[str, Callable]) -> dict[str, QAction]:
    """
    Create QAction objects from the registry, wiring each to *handlers[action_id]*.

    Missing handler → action is created but disabled.
    Returns the {id: QAction} map; also stored globally for get_action().
    """
    from PySide6.QtCore import QSettings
    settings = QSettings("Ratnodadhi", "Ratnodadhi")

    actions: dict[str, QAction] = {}
    for defn in _REGISTRY:
        act = QAction(defn.text, window)

        # Load custom shortcut or fall back to default
        custom = settings.value(f"shortcuts/{defn.id}", "")
        shortcut_str = custom or defn.default_shortcut
        if shortcut_str:
            act.setShortcut(QKeySequence(shortcut_str))
            act.setShortcutContext(
                # Window-level shortcuts for global actions
                __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.WindowShortcut
            )

        handler = handlers.get(defn.id)
        if handler:
            act.triggered.connect(handler)
        else:
            act.setEnabled(False)
            logger.debug("No handler for action: %s", defn.id)

        act.setProperty("action_id", defn.id)
        actions[defn.id] = act

    _ACTIONS.clear()
    _ACTIONS.update(actions)
    return actions


def get_action(action_id: str) -> QAction | None:
    """Return the built QAction by id, or None if not built yet."""
    return _ACTIONS.get(action_id)


def save_shortcut(action_id: str, key_sequence: str) -> None:
    """Persist a custom shortcut for an action."""
    from PySide6.QtCore import QSettings
    settings = QSettings("Ratnodadhi", "Ratnodadhi")
    settings.setValue(f"shortcuts/{action_id}", key_sequence)
    act = _ACTIONS.get(action_id)
    if act:
        act.setShortcut(QKeySequence(key_sequence))


def reset_shortcut(action_id: str) -> None:
    """Reset a shortcut to its default."""
    from PySide6.QtCore import QSettings
    settings = QSettings("Ratnodadhi", "Ratnodadhi")
    settings.remove(f"shortcuts/{action_id}")
    defn = _REGISTRY_MAP.get(action_id)
    act = _ACTIONS.get(action_id)
    if defn and act:
        act.setShortcut(QKeySequence(defn.default_shortcut))


def detect_conflicts() -> list[tuple[str, str, str]]:
    """
    Return (action_id1, action_id2, shortcut) tuples for all shortcut conflicts.
    """
    from collections import defaultdict
    seen: dict[str, list[str]] = defaultdict(list)
    for action_id, act in _ACTIONS.items():
        ks = act.shortcut().toString()
        if ks:
            seen[ks].append(action_id)
    return [
        (ids[0], ids[1], ks)
        for ks, ids in seen.items()
        if len(ids) > 1
    ]

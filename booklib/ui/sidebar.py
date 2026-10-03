"""
sidebar.py – Collapsible sidebar with shelves, collections, series, tags, tools, and filters.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QMenu, QMessageBox, QPushButton, QRadioButton, QScrollArea, QSizePolicy,
    QSpinBox, QStyle, QVBoxLayout, QWidget,
)

from booklib.db.query import LibraryQuery

logger = logging.getLogger(__name__)


class CollapsibleSection(QWidget):
    """A titled section that can be expanded/collapsed."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        self._toggle = QPushButton(f"▾  {title}")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(True)
        self._toggle.setFlat(True)
        self._toggle.setStyleSheet(
            "QPushButton { font-weight: 700; font-size: 11px; letter-spacing: 0.6px; text-align: left; "
            "padding: 6px 8px; color: palette(window-text); border: none; border-radius: 4px; background: transparent; }"
            "QPushButton:checked { background: transparent; color: palette(window-text); border: none; }"
            "QPushButton:hover { background: rgba(128, 128, 128, 0.12); }"
        )
        self._toggle.clicked.connect(self._on_toggle)
        header_layout.addWidget(self._toggle, stretch=1)

        self._action_btn: QPushButton | None = None
        layout.addLayout(header_layout)

        self._body = QWidget()
        layout.addWidget(self._body)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(8, 0, 0, 4)
        self._body_layout.setSpacing(2)

    def add_action_button(self, text: str, callback: Any) -> None:
        btn = QPushButton(text)
        btn.setFixedSize(22, 22)
        btn.setStyleSheet(
            "QPushButton { padding: 0px; font-size: 14px; font-weight: bold; "
            "color: palette(window-text); border-radius: 4px; border: 1px solid palette(mid); "
            "background: palette(button); text-align: center; line-height: 20px; }"
            "QPushButton:hover { background: rgba(128, 128, 128, 0.25); border-color: palette(window-text); }"
            "QPushButton:pressed { background: palette(mid); }"
        )
        btn.clicked.connect(callback)
        self.layout().itemAt(0).layout().addWidget(btn)

    def _on_toggle(self, checked: bool) -> None:
        self._body.setVisible(checked)
        self._toggle.setText(("▾  " if checked else "▸  ") + self._toggle.text()[3:])

    def add_widget(self, widget: QWidget) -> None:
        self._body_layout.addWidget(widget)

    def body_layout(self):
        return self._body_layout


_SIDEBAR_BTN_STYLE = """
QPushButton {
    font-size: 12px;
    font-weight: 500;
    text-align: left;
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    color: palette(window-text);
    background-color: transparent;
}
QPushButton:hover:!checked {
    background-color: rgba(128, 128, 128, 0.12);
}
QPushButton:checked {
    background-color: palette(alternate-base);
    border: 1px solid palette(mid);
    border-left: 3px solid palette(window-text);
    color: palette(window-text);
    font-weight: 600;
}
"""


class CollectionDropButton(QPushButton):
    """QPushButton that accepts dragged book IDs and forwards drops."""
    books_dropped = Signal(int, list)  # collection_id, list of book_ids

    def __init__(self, collection_id: int, label: str, parent=None):
        super().__init__(label, parent)
        self.collection_id = collection_id
        self.setAcceptDrops(True)
        self.setCheckable(True)
        self.setFlat(True)
        self.setStyleSheet(_SIDEBAR_BTN_STYLE)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat("application/x-booklib-ids"):
            event.acceptProposedAction()
            self.setStyleSheet(
                _SIDEBAR_BTN_STYLE + "\nQPushButton { border: 1px dashed palette(highlight); }"
            )
        else:
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self.setStyleSheet(_SIDEBAR_BTN_STYLE)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setStyleSheet(_SIDEBAR_BTN_STYLE)
        data = event.mimeData().data("application/x-booklib-ids")
        try:
            ids = json.loads(bytes(data).decode("utf-8"))
            if isinstance(ids, list):
                self.books_dropped.emit(self.collection_id, ids)
                event.acceptProposedAction()
                return
        except Exception:
            pass
        super().dropEvent(event)


class Sidebar(QWidget):
    """
    Left sidebar with Library shelves, Status shelves, Collections,
    Series, Tags, Tools, and Format/Rating Filters.
    """

    query_changed = Signal(object)  # LibraryQuery
    create_collection_requested = Signal()
    books_dropped_on_collection = Signal(int, list)  # collection_id, book_ids
    find_duplicates_requested = Signal()
    manage_collection_requested = Signal(str, int)  # action ('rename'/'delete'), collection_id
    highlights_notes_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(180)
        self.setMaximumWidth(260)
        self._query = LibraryQuery()
        self._counts: dict[str, int] = {}
        self._shelf_btns: dict[str, QPushButton] = {}
        self._collection_btns: dict[int, CollectionDropButton] = {}
        self._series_btns: dict[int, QPushButton] = {}
        self._tag_checks: dict[int, QCheckBox] = {}
        self._format_checks: dict[str, QCheckBox] = {}
        self._active_key = "all"
        self._setup_ui()

    def _setup_ui(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(0)

        # 1. Library Shelves
        lib_sec = CollapsibleSection("LIBRARY")
        for key, label in [
            ("all", "All Books"),
            ("continue", "Continue Reading"),
            ("recent", "Recently Added"),
            ("recommended", "Recommended"),
        ]:
            btn = self._make_btn(label, lambda checked, k=key: self._select_shelf(k))
            lib_sec.add_widget(btn)
            self._shelf_btns[key] = btn
        layout.addWidget(lib_sec)

        layout.addWidget(self._make_separator())

        # Sources
        sources_sec = CollapsibleSection("SOURCES")
        for key, label in [
            ("source_all", "All"),
            ("source_local", "Local"),
            ("source_gdrive", "Google Drive"),
            ("source_offline", "Available Offline"),
        ]:
            btn = self._make_btn(label, lambda checked, k=key: self._select_shelf(k))
            sources_sec.add_widget(btn)
            self._shelf_btns[key] = btn
        layout.addWidget(sources_sec)

        layout.addWidget(self._make_separator())

        # 2. Status Shelves
        status_sec = CollapsibleSection("STATUS")
        for key, label in [("want", "Want to Read"), ("reading", "Reading"), ("read", "Read"), ("none", "Unset")]:
            btn = self._make_btn(label, lambda checked, k=key: self._select_shelf(k))
            status_sec.add_widget(btn)
            self._shelf_btns[key] = btn
        layout.addWidget(status_sec)

        layout.addWidget(self._make_separator())

        # 3. Collections
        self._col_sec = CollapsibleSection("COLLECTIONS")
        self._col_sec.add_action_button("+", self.create_collection_requested.emit)
        layout.addWidget(self._col_sec)

        layout.addWidget(self._make_separator())

        # 4. Series
        self._series_sec = CollapsibleSection("SERIES")
        layout.addWidget(self._series_sec)

        layout.addWidget(self._make_separator())

        # 5. Tags
        self._tags_sec = CollapsibleSection("TAGS")
        mode_row = QHBoxLayout()
        self._tag_mode_any = QRadioButton("Any")
        self._tag_mode_all = QRadioButton("All")
        self._tag_mode_any.setChecked(True)
        self._tag_mode_any.toggled.connect(self._on_tag_mode_changed)
        mode_row.addWidget(self._tag_mode_any)
        mode_row.addWidget(self._tag_mode_all)
        mode_row.addStretch()
        self._tags_sec.add_widget(QWidget())  # spacer
        self._tags_sec.body_layout().addLayout(mode_row)
        layout.addWidget(self._tags_sec)

        layout.addWidget(self._make_separator())

        # 6. Tools
        tools_sec = CollapsibleSection("TOOLS")
        btn_review = self._make_btn("Needs Review", lambda checked: self._select_shelf("tool_review"))
        self._shelf_btns["tool_review"] = btn_review
        tools_sec.add_widget(btn_review)

        btn_incomplete = self._make_btn("Incomplete Metadata", lambda checked: self._select_shelf("tool_incomplete"))
        self._shelf_btns["tool_incomplete"] = btn_incomplete
        tools_sec.add_widget(btn_incomplete)

        btn_duplicates = self._make_btn("Find Duplicates…", lambda checked: self.find_duplicates_requested.emit())
        tools_sec.add_widget(btn_duplicates)

        btn_notes = self._make_btn("Highlights & Notes", lambda checked: self.highlights_notes_requested.emit())
        tools_sec.add_widget(btn_notes)
        layout.addWidget(tools_sec)

        layout.addWidget(self._make_separator())

        # 7. Filters (Format & Min. Rating)
        self._filter_sec = CollapsibleSection("FILTERS")
        layout.addWidget(self._filter_sec)

        self._format_sec = CollapsibleSection("Format")
        self._filter_sec.add_widget(self._format_sec)

        self._rating_sec = CollapsibleSection("Min. Rating")
        self._rating_spin = QSpinBox()
        self._rating_spin.setRange(0, 5)
        self._rating_spin.setSpecialValueText("Any")
        self._rating_spin.valueChanged.connect(self._on_rating_changed)
        self._rating_sec.add_widget(self._rating_spin)
        self._filter_sec.add_widget(self._rating_sec)

        layout.addStretch()
        self._select_shelf("all")

    def _make_btn(self, label: str, callback: Any) -> QPushButton:
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setFlat(True)
        btn.setStyleSheet(_SIDEBAR_BTN_STYLE)
        btn.clicked.connect(callback)
        return btn

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        return sep

    def _select_shelf(self, key: str) -> None:
        self._active_key = key
        for k, btn in self._shelf_btns.items():
            btn.setChecked(k == key)
        for btn in self._collection_btns.values():
            btn.setChecked(False)
        for btn in self._series_btns.values():
            btn.setChecked(False)

        q = LibraryQuery()
        # Preserve search and active filters
        q.search = self._query.search
        q.formats = set(self._query.formats)
        q.min_rating = self._query.min_rating
        q.tag_ids = set(self._query.tag_ids)
        q.tag_mode = self._query.tag_mode
        q.sort_field = self._query.sort_field
        q.sort_desc = self._query.sort_desc

        if key in ("continue", "recent", "recommended"):
            q.shelf = key
        elif key in ("want", "reading", "read", "none"):
            q.statuses = {key}
        elif key == "tool_review":
            q.lookup_status = "review"
        elif key == "tool_incomplete":
            q.incomplete = True
        elif key == "source_all":
            q.sources = []
            q.offline_only = False
        elif key == "source_local":
            q.sources = ["local"]
            q.offline_only = False
        elif key == "source_gdrive":
            q.sources = ["gdrive"]
            q.offline_only = False
        elif key == "source_offline":
            q.sources = []
            q.offline_only = True

        self._query = q
        self._emit()

    def _on_collection_clicked(self, cid: int) -> None:
        self._active_key = f"col_{cid}"
        for btn in self._shelf_btns.values():
            btn.setChecked(False)
        for c, btn in self._collection_btns.items():
            btn.setChecked(c == cid)
        for btn in self._series_btns.values():
            btn.setChecked(False)

        q = LibraryQuery()
        q.search = self._query.search
        q.formats = set(self._query.formats)
        q.min_rating = self._query.min_rating
        q.tag_ids = set(self._query.tag_ids)
        q.tag_mode = self._query.tag_mode
        q.collection_id = cid
        self._query = q
        self._emit()

    def _on_series_clicked(self, sid: int) -> None:
        self._active_key = f"series_{sid}"
        for btn in self._shelf_btns.values():
            btn.setChecked(False)
        for btn in self._collection_btns.values():
            btn.setChecked(False)
        for s, btn in self._series_btns.items():
            btn.setChecked(s == sid)

        q = LibraryQuery()
        q.search = self._query.search
        q.formats = set(self._query.formats)
        q.min_rating = self._query.min_rating
        q.tag_ids = set(self._query.tag_ids)
        q.tag_mode = self._query.tag_mode
        q.series_id = sid
        q.sort_field = "series"
        q.sort_desc = False
        self._query = q
        self._emit()

    def _on_tag_toggled(self) -> None:
        self._query.tag_ids = {tid for tid, cb in self._tag_checks.items() if cb.isChecked()}
        self._emit()

    def _on_tag_mode_changed(self) -> None:
        self._query.tag_mode = "all" if self._tag_mode_all.isChecked() else "any"
        self._emit()

    def _on_format_toggled(self) -> None:
        self._query.formats = {f for f, cb in self._format_checks.items() if cb.isChecked()}
        self._emit()

    def _on_rating_changed(self, val: int) -> None:
        self._query.min_rating = val if val > 0 else None
        self._emit()

    def _emit(self) -> None:
        self.query_changed.emit(LibraryQuery(
            search=self._query.search,
            statuses=set(self._query.statuses),
            formats=set(self._query.formats),
            min_rating=self._query.min_rating,
            shelf=self._query.shelf,
            sort_field=self._query.sort_field,
            sort_desc=self._query.sort_desc,
            tag_ids=set(self._query.tag_ids),
            tag_mode=self._query.tag_mode,
            collection_id=self._query.collection_id,
            series_id=self._query.series_id,
            lookup_status=self._query.lookup_status,
            incomplete=self._query.incomplete,
            sources=list(self._query.sources),
            offline_only=self._query.offline_only,
            drive_folder_id=self._query.drive_folder_id,
        ))

    # ── Public Updates ────────────────────────────────────────────────────────

    def update_counts(self, counts: dict[str, int]) -> None:
        self._counts = counts
        labels = {
            "all":             f"All Books  {counts.get('all', 0):,}",
            "continue":        f"Continue Reading  {counts.get('reading', 0):,}",
            "recent":          f"Recently Added  {counts.get('recent', 0):,}",
            "source_all":      f"All  {counts.get('all', 0):,}",
            "source_local":    f"Local  {counts.get('local', 0):,}",
            "source_gdrive":   f"Google Drive  {counts.get('gdrive', 0):,}",
            "source_offline":  f"Available Offline  {counts.get('cached', 0):,}",
            "want":            f"Want to Read  {counts.get('want', 0):,}",
            "reading":         f"Reading  {counts.get('reading', 0):,}",
            "read":            f"Read  {counts.get('read', 0):,}",
            "none":            f"Unset  {counts.get('none', 0):,}",
            "tool_review":     f"Needs Review  {counts.get('review', 0):,}",
            "tool_incomplete": f"Incomplete  {counts.get('incomplete', 0):,}",
        }
        for key, btn in self._shelf_btns.items():
            btn.setText(labels.get(key, key))

    def update_collections(self, collections: list[dict[str, Any]]) -> None:
        # Clear old
        for btn in self._collection_btns.values():
            btn.deleteLater()
        self._collection_btns.clear()

        for c in collections:
            cid = c["id"]
            name = c["name"]
            kind = c.get("kind", "manual")
            count = c.get("book_count", 0)
            btn = CollectionDropButton(cid, f"{name}  {count:,}")
            btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView if kind == "smart" else QStyle.SP_DirIcon))
            btn.books_dropped.connect(self.books_dropped_on_collection.emit)
            btn.clicked.connect(lambda checked, col_id=cid: self._on_collection_clicked(col_id))

            # Context menu for rename/delete
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pt, col_id=cid: self._show_collection_menu(pt, col_id))

            self._col_sec.add_widget(btn)
            self._collection_btns[cid] = btn

    def _show_collection_menu(self, pt, col_id: int) -> None:
        btn = self._collection_btns.get(col_id)
        if not btn:
            return
        menu = QMenu(self)
        a_rename = menu.addAction("Rename Collection…")
        a_delete = menu.addAction("Delete Collection")
        act = menu.exec(btn.mapToGlobal(pt))
        if act == a_rename:
            self.manage_collection_requested.emit("rename", col_id)
        elif act == a_delete:
            self.manage_collection_requested.emit("delete", col_id)

    def update_series(self, series_list: list[dict[str, Any]]) -> None:
        for btn in self._series_btns.values():
            btn.deleteLater()
        self._series_btns.clear()

        for s in series_list[:20]:
            sid = s["id"]
            name = s["name"]
            count = s.get("book_count", 0)
            btn = self._make_btn(f"{name}  {count:,}", lambda checked, s_id=sid: self._on_series_clicked(s_id))
            self._series_sec.add_widget(btn)
            self._series_btns[sid] = btn

    def update_tags(self, tags: list[dict[str, Any]]) -> None:
        for cb in self._tag_checks.values():
            cb.deleteLater()
        self._tag_checks.clear()

        for t in tags[:30]:
            tid = t["id"]
            name = t["name"]
            count = t.get("book_count", 0)
            cb = QCheckBox(f"#{name}  {count:,}")
            cb.setStyleSheet("font-size: 11px;")
            cb.toggled.connect(self._on_tag_toggled)
            self._tags_sec.add_widget(cb)
            self._tag_checks[tid] = cb

    def update_format_facets(self, facets: list[tuple[str, int]]) -> None:
        for cb in self._format_checks.values():
            cb.deleteLater()
        self._format_checks.clear()

        for fmt, count in facets[:20]:
            cb = QCheckBox(f"{fmt.upper()}  {count:,}")
            cb.setStyleSheet("font-size: 11px;")
            cb.toggled.connect(self._on_format_toggled)
            self._format_sec.add_widget(cb)
            self._format_checks[fmt] = cb

    def set_search(self, text: str) -> None:
        self._query.search = text
        self._emit()

    def current_query(self) -> LibraryQuery:
        return self._query

"""
lookup_review.py – Candidate chooser and review queue dialog.
"""
from __future__ import annotations

import json
import logging
from typing import Any
import urllib.request

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QRadioButton, QScrollArea, QSplitter,
    QStyle, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from booklib.covers.custom import save_custom_cover
from booklib.db.database import Database
from booklib.metadata.online.merge import apply_candidate, candidate_to_dict
from booklib.metadata.online.models import Candidate
from booklib.metadata.online.service import OnlineLookupService

logger = logging.getLogger(__name__)

FIELD_LABELS = [
    ("title", "Title"),
    ("author", "Author"),
    ("publisher", "Publisher"),
    ("year", "Year"),
    ("isbn", "ISBN"),
    ("pages", "Pages"),
    ("genre", "Genre"),
    ("language", "Language"),
    ("description", "Description"),
]


class CandidateCard(QFrame):
    """Card widget displaying a single online candidate."""
    selected = Signal(object)  # Candidate

    def __init__(self, candidate: Candidate, is_default: bool = False, parent=None):
        super().__init__(parent)
        self.candidate = candidate
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "CandidateCard { border: 1px solid palette(mid); border-radius: 6px; padding: 6px; margin: 4px; }"
            "CandidateCard:hover { border: 1px solid palette(highlight); }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Header: Radio + Provider + Score
        top_row = QHBoxLayout()
        self.radio = QRadioButton(f"{candidate.provider.title()}")
        self.radio.setChecked(is_default)
        self.radio.toggled.connect(self._on_radio_toggled)
        top_row.addWidget(self.radio)

        score_pct = int(candidate.score * 100)
        score_lbl = QLabel(f"{score_pct}% ({candidate.matched_by})")
        score_lbl.setStyleSheet("font-weight: bold; color: palette(highlight); font-size: 11px;")
        top_row.addStretch()
        top_row.addWidget(score_lbl)
        layout.addLayout(top_row)

        # Body: Info + Cover
        body_row = QHBoxLayout()
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        t_lbl = QLabel(candidate.title or "—")
        t_lbl.setWordWrap(True)
        t_lbl.setStyleSheet("font-weight: bold; font-size: 12px;")
        info_layout.addWidget(t_lbl)

        auth_str = "; ".join(candidate.authors) if candidate.authors else "—"
        a_lbl = QLabel(auth_str)
        a_lbl.setStyleSheet("font-size: 11px; color: palette(window-text);")
        info_layout.addWidget(a_lbl)

        pub_parts = []
        if candidate.publisher:
            pub_parts.append(candidate.publisher)
        if candidate.year:
            pub_parts.append(str(candidate.year))
        if pub_parts:
            info_layout.addWidget(QLabel(" · ".join(pub_parts)))

        if candidate.isbn:
            info_layout.addWidget(QLabel(f"ISBN: {candidate.isbn}"))

        info_layout.addStretch()
        body_row.addLayout(info_layout, stretch=1)

        # Cover thumbnail
        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(50, 75)
        self.cover_lbl.setStyleSheet("border: 1px solid palette(mid); background: #222;")
        self.cover_lbl.setAlignment(Qt.AlignCenter)
        self.cover_lbl.setText("No cover")
        body_row.addWidget(self.cover_lbl)

        layout.addLayout(body_row)

    def _on_radio_toggled(self, checked: bool) -> None:
        if checked:
            self.selected.emit(self.candidate)

    def mousePressEvent(self, event) -> None:
        self.radio.setChecked(True)
        super().mousePressEvent(event)


class LookupReviewDialog(QDialog):
    """
    Candidate Chooser and Review Queue Dialog.
    If book_ids has multiple books, acts as review queue with Next/Prev and skip actions.
    If single book, acts as chooser.
    """
    applied = Signal(int)  # book_id

    def __init__(self, book_ids: list[int], db: Database, parent=None):
        super().__init__(parent)
        self.book_ids = book_ids
        self.db = db
        self.current_idx = 0
        self.current_book: dict[str, Any] | None = None
        self.candidates: list[Candidate] = []
        self.selected_candidate: Candidate | None = None
        self.field_checkboxes: dict[str, QCheckBox] = {}

        self.setWindowTitle("Metadata Review Queue" if len(book_ids) > 1 else "Online Metadata Lookup")
        self.resize(850, 600)
        self._setup_ui()
        self._load_current_book()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Horizontal)

        # Left: Books list (if multiple)
        if len(self.book_ids) > 1:
            left_w = QWidget()
            left_l = QVBoxLayout(left_w)
            left_l.setContentsMargins(0, 0, 0, 0)
            left_l.addWidget(QLabel(f"Books to Review ({len(self.book_ids)}):"))
            self.book_list = QListWidget()
            self.book_list.currentRowChanged.connect(self._on_book_selected)
            left_l.addWidget(self.book_list)
            splitter.addWidget(left_w)
            splitter.setSizes([200, 650])
        else:
            self.book_list = None

        # Right / Center: Candidate review area
        right_w = QWidget()
        right_l = QVBoxLayout(right_w)

        # Book title header
        self.header_lbl = QLabel()
        self.header_lbl.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px;")
        right_l.addWidget(self.header_lbl)

        # Candidates scroll area
        cand_scroll = QScrollArea()
        cand_scroll.setWidgetResizable(True)
        cand_scroll.setMaximumHeight(180)
        self.cand_container = QWidget()
        self.cand_layout = QHBoxLayout(self.cand_container)
        cand_scroll.setWidget(self.cand_container)
        right_l.addWidget(cand_scroll)

        # Comparison table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Field", "Current Value", "Candidate Value", "Apply"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        right_l.addWidget(self.table)

        # Options row
        opt_row = QHBoxLayout()
        self.use_cover_cb = QCheckBox("Download & use candidate cover")
        self.use_cover_cb.setChecked(True)
        opt_row.addWidget(self.use_cover_cb)

        self.fill_only_cb = QCheckBox("Fill empty fields only")
        self.fill_only_cb.setChecked(True)
        self.fill_only_cb.toggled.connect(self._recalculate_apply_checks)
        opt_row.addWidget(self.fill_only_cb)
        opt_row.addStretch()
        right_l.addLayout(opt_row)

        # Buttons row
        btn_row = QHBoxLayout()
        self.btn_apply = QPushButton("Apply (Ctrl+Enter)")
        self.btn_apply.setDefault(True)
        self.btn_apply.clicked.connect(self._on_apply)
        btn_row.addWidget(self.btn_apply)

        self.btn_skip = QPushButton("Skip")
        self.btn_skip.clicked.connect(self._on_skip)
        btn_row.addWidget(self.btn_skip)

        self.btn_ignore = QPushButton("Not this book")
        self.btn_ignore.clicked.connect(self._on_ignore)
        btn_row.addWidget(self.btn_ignore)

        self.btn_search = QPushButton("Search manually…")
        self.btn_search.clicked.connect(self._on_search_manually)
        btn_row.addWidget(self.btn_search)

        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_close)
        right_l.addLayout(btn_row)

        splitter.addWidget(right_w)
        main_layout.addWidget(splitter)

        # Shortcut Ctrl+Enter
        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.activated.connect(self._on_apply)

        # Populate book list
        if self.book_list:
            conn = self.db.new_connection()
            try:
                for bid in self.book_ids:
                    row = conn.execute("SELECT title, author, filename FROM books WHERE id = ?", (bid,)).fetchone()
                    t = (row[0] or row[2]) if row else f"Book #{bid}"
                    a = f" ({row[1]})" if row and row[1] else ""
                    self.book_list.addItem(QListWidgetItem(f"{t}{a}"))
            finally:
                conn.close()

    def _load_current_book(self) -> None:
        if self.current_idx >= len(self.book_ids):
            self.accept()
            return

        book_id = self.book_ids[self.current_idx]
        conn = self.db.new_connection()
        try:
            row = conn.execute(
                """SELECT id, title, author, publisher, year, isbn, pages,
                          genre, language, description, field_sources, cover_path, cover_source
                   FROM books WHERE id = ?""",
                (book_id,),
            ).fetchone()

            if not row:
                self._next_book()
                return

            self.current_book = {
                "id": row[0],
                "title": row[1],
                "author": row[2],
                "publisher": row[3],
                "year": row[4],
                "isbn": row[5],
                "pages": row[6],
                "genre": row[7],
                "language": row[8],
                "description": row[9],
                "field_sources": json.loads(row[10]) if row[10] else {},
                "cover_path": row[11],
                "cover_source": row[12],
            }

            self.header_lbl.setText(f"{self.current_book.get('title') or 'Untitled'} – {self.current_book.get('author') or 'Unknown'}")

            # Load candidates from online_cache or perform search
            cache_row = conn.execute(
                "SELECT response FROM online_cache WHERE cache_key = ?",
                (f"cand:{book_id}",),
            ).fetchone()

            self.candidates = []
            if cache_row:
                try:
                    c_list = json.loads(cache_row[0])
                    for d in c_list:
                        cand = Candidate(
                            provider=d["provider"],
                            provider_id=d["provider_id"],
                            title=d.get("title"),
                            authors=d.get("authors", []),
                            publisher=d.get("publisher"),
                            year=d.get("year"),
                            isbn=d.get("isbn"),
                            pages=d.get("pages"),
                            genres=d.get("genres", []),
                            language=d.get("language"),
                            description=d.get("description"),
                            edition=d.get("edition"),
                            cover_url=d.get("cover_url"),
                            matched_by=d.get("matched_by", "title_author"),
                            score=d.get("score", 0.0),
                        )
                        self.candidates.append(cand)
                except Exception as e:
                    logger.debug("Failed to parse cached candidates: %s", e)

            if not self.candidates:
                # Run query live
                service = OnlineLookupService(db_conn=conn)
                _, ranked = service.lookup(self.current_book)
                self.candidates = ranked

            self._display_candidates()
        finally:
            conn.close()

    def _display_candidates(self) -> None:
        # Clear cand_layout
        while self.cand_layout.count():
            item = self.cand_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.candidates:
            self.cand_layout.addWidget(QLabel("No online candidates found."))
            self._populate_table(None)
            return

        self.candidate_group = QButtonGroup(self)
        for i, cand in enumerate(self.candidates):
            card = CandidateCard(cand, is_default=(i == 0))
            self.candidate_group.addButton(card.radio)
            card.selected.connect(self._on_candidate_chosen)
            self.cand_layout.addWidget(card)

        self.selected_candidate = self.candidates[0]
        self._populate_table(self.selected_candidate)

    def _on_candidate_chosen(self, cand: Candidate) -> None:
        self.selected_candidate = cand
        self._populate_table(cand)

    def _populate_table(self, cand: Candidate | None) -> None:
        self.table.setRowCount(0)
        self.field_checkboxes.clear()
        if not self.current_book:
            return

        cand_data = candidate_to_dict(cand) if cand else {}
        sources = self.current_book.get("field_sources", {})
        fill_only = self.fill_only_cb.isChecked()

        for row_idx, (f_key, f_label) in enumerate(FIELD_LABELS):
            self.table.insertRow(row_idx)

            # Field Label
            self.table.setItem(row_idx, 0, QTableWidgetItem(f_label))

            # Current value with source icon
            curr_val = self.current_book.get(f_key)
            src = sources.get(f_key, "file")
            curr_str = str(curr_val) if curr_val is not None else ""
            curr_item = QTableWidgetItem(curr_str)
            if src.startswith("online:"):
                curr_item.setIcon(self.style().standardIcon(QStyle.SP_DriveNetIcon))
            elif src == "manual":
                curr_item.setIcon(self.style().standardIcon(QStyle.SP_FileDialogInfoView))
            else:
                curr_item.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
            curr_item.setToolTip(f"Source: {src}")
            curr_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row_idx, 1, curr_item)

            # Candidate value
            cand_val = cand_data.get(f_key)
            cand_str = str(cand_val) if cand_val is not None else "—"
            cand_item = QTableWidgetItem(cand_str)
            cand_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row_idx, 2, cand_item)

            # Apply checkbox
            cb = QCheckBox()
            # Rules:
            # - If manual: disable and uncheck
            # - If cand_val is empty: uncheck
            # - If fill_only and curr_val has value: uncheck
            # - Else check
            is_manual = (src == "manual")
            has_cand = (cand_val is not None and str(cand_val).strip() != "")
            has_curr = (curr_val is not None and str(curr_val).strip() != "")

            if is_manual:
                cb.setChecked(False)
                cb.setEnabled(False)
                cb.setToolTip("Field was edited manually and is protected")
            elif not has_cand:
                cb.setChecked(False)
                cb.setEnabled(False)
            elif fill_only and has_curr:
                cb.setChecked(False)
            else:
                cb.setChecked(True)

            self.field_checkboxes[f_key] = cb
            w = QWidget()
            l = QHBoxLayout(w)
            l.setAlignment(Qt.AlignCenter)
            l.setContentsMargins(0, 0, 0, 0)
            l.addWidget(cb)
            self.table.setCellWidget(row_idx, 3, w)

    def _recalculate_apply_checks(self) -> None:
        self._populate_table(self.selected_candidate)

    def _on_apply(self) -> None:
        if not self.current_book or not self.selected_candidate:
            self._next_book()
            return

        book_id = self.current_book["id"]
        field_overrides = {k: cb.isChecked() for k, cb in self.field_checkboxes.items()}

        conn = self.db.new_connection()
        try:
            apply_candidate(
                conn,
                book_id,
                self.selected_candidate,
                batch_id="review_dialog",
                mode="replace",  # override checkboxes dictate which fields apply
                field_override=field_overrides,
            )

            # Cover download
            if self.use_cover_cb.isChecked() and self.selected_candidate.cover_url:
                try:
                    req = urllib.request.Request(
                        self.selected_candidate.cover_url,
                        headers={"User-Agent": "BookLib/3.0"},
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        c_bytes = resp.read()
                        if c_bytes:
                            save_custom_cover(conn, book_id, c_bytes, source="online")
                except Exception as e:
                    logger.debug("Failed to download candidate cover: %s", e)

            # Clear cache
            conn.execute("DELETE FROM online_cache WHERE cache_key = ?", (f"cand:{book_id}",))
            conn.commit()
            self.applied.emit(book_id)
        finally:
            conn.close()

        self._next_book()

    def _on_skip(self) -> None:
        self._next_book()

    def _on_ignore(self) -> None:
        if self.current_book:
            conn = self.db.new_connection()
            try:
                conn.execute(
                    "UPDATE books SET lookup_status = 'skipped', lookup_at = datetime('now') WHERE id = ?",
                    (self.current_book["id"],),
                )
                conn.execute("DELETE FROM online_cache WHERE cache_key = ?", (f"cand:{self.current_book['id']}",))
                conn.commit()
            finally:
                conn.close()
        self._next_book()

    def _on_search_manually(self) -> None:
        if not self.current_book:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Manual Online Search")
        layout = QVBoxLayout(dlg)

        grid = QGridLayout()
        grid.addWidget(QLabel("Title:"), 0, 0)
        t_edit = QLineEdit(self.current_book.get("title") or "")
        grid.addWidget(t_edit, 0, 1)

        grid.addWidget(QLabel("Author:"), 1, 0)
        a_edit = QLineEdit(self.current_book.get("author") or "")
        grid.addWidget(a_edit, 1, 1)

        grid.addWidget(QLabel("ISBN:"), 2, 0)
        i_edit = QLineEdit(self.current_book.get("isbn") or "")
        grid.addWidget(i_edit, 2, 1)

        layout.addLayout(grid)

        btns = QHBoxLayout()
        b_ok = QPushButton("Search")
        b_cancel = QPushButton("Cancel")
        b_ok.clicked.connect(dlg.accept)
        b_cancel.clicked.connect(dlg.reject)
        btns.addWidget(b_ok)
        btns.addWidget(b_cancel)
        layout.addLayout(btns)

        if dlg.exec() == QDialog.Accepted:
            temp_book = dict(self.current_book)
            temp_book["title"] = t_edit.text().strip() or None
            temp_book["author"] = a_edit.text().strip() or None
            temp_book["isbn"] = i_edit.text().strip() or None

            conn = self.db.new_connection()
            try:
                service = OnlineLookupService(db_conn=conn)
                _, ranked = service.lookup(temp_book)
                self.candidates = ranked
                self._display_candidates()
            finally:
                conn.close()

    def _next_book(self) -> None:
        self.current_idx += 1
        if self.book_list and self.current_idx < len(self.book_ids):
            self.book_list.setCurrentRow(self.current_idx)
        else:
            self._load_current_book()

    def _on_book_selected(self, row: int) -> None:
        if row >= 0 and row != self.current_idx:
            self.current_idx = row
            self._load_current_book()

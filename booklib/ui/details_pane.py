"""
details_pane.py – v3: Collapsible sections (Overview, Details, Organize, Progress, Notes, File)
with provenance icons, custom covers, series navigation, tags chips, and reading history.
"""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QBuffer, QIODevice, Qt, QTimer, Signal, QUrl
from PySide6.QtGui import (
    QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QGuiApplication,
    QImage, QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QStyle, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from booklib.config import COVERS_DIR
from booklib.covers.custom import (
    render_pdf_page_cover,
    restore_original_cover,
    save_custom_cover,
)
from booklib.db.repository import BookDetail, Repository
from booklib.recommend.service import RecommendationService
from booklib.stats.queries import book_reading_estimate
from booklib.ui.sidebar import CollapsibleSection
from booklib.ui.star_rating import StarRating
from booklib.ui.theme import badge_color
from booklib.utils.format import dash_if_none, human_size

logger = logging.getLogger(__name__)

COVER_MAX_H = 220


class _StatusButtons(QWidget):
    """Segmented want / reading / read buttons."""
    status_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._btns: dict[str, QPushButton] = {}
        self._current: str | None = None
        for status, label, color in [
            ("want", "Want", "#475569"),
            ("reading", "Reading", "#d97706"),
            ("read", "Read", "#059669"),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setMinimumWidth(0)
            btn.setStyleSheet(f"""
                QPushButton {{
                    font-size: 11px;
                    font-weight: 600;
                    border: 1px solid palette(mid);
                    border-radius: 6px;
                    padding: 4px 6px;
                    background: palette(button);
                    color: palette(window-text);
                }}
                QPushButton:hover:!checked {{
                    background: rgba(128, 128, 128, 0.15);
                    border-color: palette(highlight);
                }}
                QPushButton:checked {{
                    background: {color};
                    border: 1px solid {color};
                    color: #ffffff;
                }}
            """)
            btn.clicked.connect(lambda _, s=status: self._on_click(s))
            layout.addWidget(btn)
            self._btns[status] = btn

    def _on_click(self, status: str) -> None:
        new = None if status == self._current else status
        self.set_status(new)
        self.status_requested.emit(new)

    def set_status(self, status: str | None) -> None:
        self._current = status
        for s, btn in self._btns.items():
            btn.setChecked(s == status)


class CoverDropLabel(QLabel):
    """QLabel for cover that accepts dropped image files."""
    image_dropped = Signal(bytes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                if Path(path).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            try:
                data = Path(path).read_bytes()
                self.image_dropped.emit(data)
                event.acceptProposedAction()
                return
            except Exception:
                pass
        super().dropEvent(event)


class DetailsPane(QWidget):
    """
    Right-hand details pane with collapsible sections:
    1. Overview (cover with cover menu, title, author, status, stars)
    2. Details (metadata with source icons, description, fetch online, edit)
    3. Organize (tags chips editor, series navigation)
    4. Progress (page/percent controls, reading history, read again)
    5. Notes
    6. File (technical info, show in folder, open with)
    """

    status_changed = Signal(int, object)
    rating_changed = Signal(int, object)
    notes_saved = Signal(int, str)
    edit_requested = Signal(int)
    open_requested = Signal(int, object)
    lookup_requested = Signal(int)
    cover_changed = Signal(int)
    select_book_requested = Signal(int)  # For series navigation
    keep_offline_toggled = Signal(int, bool)
    remove_download_requested = Signal(int)

    def __init__(self, repo: Repository, parent=None, rec_service: RecommendationService | None = None) -> None:
        super().__init__(parent)
        self._repo = repo
        self._rec_service = rec_service
        self._detail: BookDetail | None = None
        self._current_pixmap: QPixmap = QPixmap()
        self._notes_timer = QTimer()
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(800)
        self._notes_timer.timeout.connect(self._save_notes)

        self.setMinimumWidth(240)
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 1. Independent Top Section: Overview (Cover, Title, Status, Rating) ──
        self._top_container = QWidget()
        top_layout = QVBoxLayout(self._top_container)
        top_layout.setContentsMargins(8, 8, 8, 4)
        top_layout.setSpacing(4)

        self._sec_overview = CollapsibleSection("OVERVIEW")
        # Cover + Menu
        cover_container = QWidget()
        cc_l = QVBoxLayout(cover_container)
        cc_l.setContentsMargins(0, 0, 0, 0)
        cc_l.setSpacing(2)

        self._cover_lbl = CoverDropLabel()
        self._cover_lbl.setAlignment(Qt.AlignCenter)
        self._cover_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._cover_lbl.setMinimumWidth(0)
        self._cover_lbl.setMinimumHeight(160)
        self._cover_lbl.image_dropped.connect(self._on_image_bytes_dropped)
        cc_l.addWidget(self._cover_lbl)

        cover_btn_row = QHBoxLayout()
        cover_btn_row.addStretch()
        self._cover_menu_btn = QPushButton("Cover ▾")
        self._cover_menu_btn.setFlat(True)
        self._cover_menu_btn.setStyleSheet("font-size: 11px; color: palette(highlight);")
        self._cover_menu = QMenu(self)
        self._setup_cover_menu()
        self._cover_menu_btn.setMenu(self._cover_menu)
        cover_btn_row.addWidget(self._cover_menu_btn)
        cover_btn_row.addStretch()
        cc_l.addLayout(cover_btn_row)
        self._sec_overview.add_widget(cover_container)

        self._title_lbl = QLabel()
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setAlignment(Qt.AlignCenter)
        f = self._title_lbl.font()
        f.setPointSize(12)
        f.setBold(True)
        f.setStyleStrategy(QFont.PreferAntialias)
        self._title_lbl.setFont(f)
        self._title_lbl.setStyleSheet("padding: 4px 2px 2px 2px;")
        self._sec_overview.add_widget(self._title_lbl)

        self._author_lbl = QLabel()
        self._author_lbl.setAlignment(Qt.AlignCenter)
        self._author_lbl.setWordWrap(True)
        f_auth = self._author_lbl.font()
        f_auth.setPointSize(10)
        f_auth.setStyleStrategy(QFont.PreferAntialias)
        self._author_lbl.setFont(f_auth)
        self._author_lbl.setStyleSheet("color: palette(placeholder-text); padding-bottom: 4px;")
        self._sec_overview.add_widget(self._author_lbl)

        self._status_btns = _StatusButtons()
        self._status_btns.status_requested.connect(self._on_status_request)
        self._sec_overview.add_widget(self._status_btns)

        self._stars = StarRating()
        self._stars.ratingChanged.connect(self._on_rating_change)
        self._sec_overview.add_widget(self._stars)

        top_layout.addWidget(self._sec_overview)
        outer.addWidget(self._top_container, 0)

        # Subtle divider between Overview and scrollable metadata
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background: palette(mid); max-height: 1px; border: none; margin: 4px 8px;")
        outer.addWidget(sep)

        # ── 2. Scrollable Metadata Section (Details, Organize, Progress, Notes, File) ──
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(6)

        # ── 2. Details ────────────────────────────────────────────────────────
        self._sec_details = CollapsibleSection("DETAILS")
        self._meta_rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key, label in [
            ("publisher", "Publisher"),
            ("year", "Year"),
            ("isbn", "ISBN"),
            ("pages", "Pages"),
            ("genre", "Genre"),
            ("language", "Language"),
        ]:
            row = QWidget()
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 0, 0, 0)
            k_lbl = QLabel(f"<b>{label}</b>")
            k_lbl.setFixedWidth(70)
            v_lbl = QLabel()
            v_lbl.setWordWrap(True)
            v_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            v_lbl.setMinimumWidth(0)
            src_lbl = QLabel()
            src_lbl.setFixedWidth(16)
            row_l.addWidget(k_lbl)
            row_l.addWidget(v_lbl, stretch=1)
            row_l.addWidget(src_lbl)
            self._sec_details.add_widget(row)
            self._meta_rows[key] = (v_lbl, src_lbl)

        # Description
        desc_box = QWidget()
        desc_l = QVBoxLayout(desc_box)
        desc_l.setContentsMargins(0, 4, 0, 0)
        desc_l.addWidget(QLabel("<b>Description:</b>"))
        self._desc_lbl = QLabel()
        self._desc_lbl.setWordWrap(True)
        self._desc_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._desc_lbl.setMinimumWidth(0)
        self._desc_lbl.setStyleSheet("font-size: 11px; color: palette(window-text);")
        desc_l.addWidget(self._desc_lbl)
        self._sec_details.add_widget(desc_box)

        det_btn_row = QHBoxLayout()
        self._btn_fetch_online = QPushButton("Fetch Online")
        self._btn_fetch_online.setStyleSheet("font-size: 11px;")
        self._btn_fetch_online.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._btn_fetch_online.clicked.connect(lambda: self._detail and self.lookup_requested.emit(self._detail.id))
        det_btn_row.addWidget(self._btn_fetch_online)

        self._btn_edit = QPushButton("Edit…")
        self._btn_edit.setStyleSheet("font-size: 11px;")
        self._btn_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._btn_edit.clicked.connect(lambda: self._detail and self.edit_requested.emit(self._detail.id))
        det_btn_row.addWidget(self._btn_edit)
        self._sec_details.body_layout().addLayout(det_btn_row)
        layout.addWidget(self._sec_details)

        # ── 3. Organize ───────────────────────────────────────────────────────
        self._sec_organize = CollapsibleSection("ORGANIZE")
        # Tags chip container
        self._tags_box = QWidget()
        self._tags_l = QVBoxLayout(self._tags_box)
        self._tags_l.setContentsMargins(0, 0, 0, 0)
        self._tags_chip_layout = QVBoxLayout()
        self._tags_chip_layout.setSpacing(4)
        self._tags_l.addLayout(self._tags_chip_layout)

        tag_input_row = QHBoxLayout()
        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText("Add tag… (Enter)")
        self._tag_input.returnPressed.connect(self._on_add_tag_entered)
        tag_input_row.addWidget(self._tag_input)
        self._tags_l.addLayout(tag_input_row)
        self._sec_organize.add_widget(self._tags_box)

        # Series display and navigation
        self._series_box = QWidget()
        sb_l = QHBoxLayout(self._series_box)
        sb_l.setContentsMargins(0, 4, 0, 0)
        self._series_lbl = QLabel("No series")
        self._series_lbl.setStyleSheet("font-size: 11px; font-style: italic;")
        sb_l.addWidget(self._series_lbl, stretch=1)
        self._btn_prev_series = QPushButton("◀")
        self._btn_prev_series.setFixedSize(22, 22)
        self._btn_prev_series.clicked.connect(self._on_prev_series)
        self._btn_next_series = QPushButton("▶")
        self._btn_next_series.setFixedSize(22, 22)
        self._btn_next_series.clicked.connect(self._on_next_series)
        sb_l.addWidget(self._btn_prev_series)
        sb_l.addWidget(self._btn_next_series)
        self._sec_organize.add_widget(self._series_box)
        layout.addWidget(self._sec_organize)

        # ── 4. Progress ───────────────────────────────────────────────────────
        self._sec_progress = CollapsibleSection("PROGRESS")
        prog_row = QHBoxLayout()
        self._prog_spin = QSpinBox()
        self._prog_spin.setRange(0, 100000)
        self._prog_spin.valueChanged.connect(self._on_progress_spin_changed)
        self._prog_lbl = QLabel("Page 0 of 0")
        prog_row.addWidget(self._prog_spin)
        prog_row.addWidget(self._prog_lbl)
        self._sec_progress.body_layout().addLayout(prog_row)

        self._prog_slider = QSlider(Qt.Horizontal)
        self._prog_slider.setRange(0, 100)
        self._prog_slider.valueChanged.connect(self._on_progress_slider_changed)
        self._sec_progress.add_widget(self._prog_slider)

        self._btn_read_again = QPushButton("Read Again")
        self._btn_read_again.setStyleSheet("font-size: 11px;")
        self._btn_read_again.clicked.connect(self._on_read_again)
        self._sec_progress.add_widget(self._btn_read_again)

        # Reading time estimate
        self._reading_time_lbl = QLabel("")
        self._reading_time_lbl.setStyleSheet("font-size: 11px; color: palette(window-text); padding: 2px 0;")
        self._sec_progress.add_widget(self._reading_time_lbl)

        # Reading log list
        self._log_lbl = QLabel("Reading History:")
        self._log_lbl.setStyleSheet("font-weight: bold; font-size: 11px;")
        self._sec_progress.add_widget(self._log_lbl)
        self._log_content_lbl = QLabel("—")
        self._log_content_lbl.setWordWrap(True)
        self._log_content_lbl.setStyleSheet("font-size: 10px; color: palette(window-text);")
        self._sec_progress.add_widget(self._log_content_lbl)
        layout.addWidget(self._sec_progress)

        # ── 5. Notes ──────────────────────────────────────────────────────────
        self._sec_notes = CollapsibleSection("NOTES")
        self._notes = QPlainTextEdit()
        self._notes.setPlaceholderText("Add notes…")
        self._notes.setMaximumHeight(85)
        self._notes.textChanged.connect(self._notes_changed)
        self._sec_notes.add_widget(self._notes)
        layout.addWidget(self._sec_notes)

        # ── 6. File ───────────────────────────────────────────────────────────
        self._sec_file = CollapsibleSection("FILE")
        self._file_rows: dict[str, QLabel] = {}
        for key, label in [
            ("source", "Source"),
            ("format", "Format"),
            ("size", "Size"),
            ("path", "Location"),
            ("cache", "Cache"),
            ("md5", "MD5 / Hash"),
        ]:
            row = QWidget()
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 0, 0, 0)
            k_lbl = QLabel(f"<b>{label}</b>")
            k_lbl.setFixedWidth(70)
            v_lbl = QLabel()
            v_lbl.setWordWrap(True)
            v_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            v_lbl.setMinimumWidth(0)
            v_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row_l.addWidget(k_lbl)
            row_l.addWidget(v_lbl, stretch=1)
            self._sec_file.add_widget(row)
            self._file_rows[key] = v_lbl

        file_btns = QHBoxLayout()
        self._open_btn = QToolButton()
        self._open_btn.setText("Open")
        self._open_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self._open_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._open_btn.clicked.connect(lambda: self._detail and self.open_requested.emit(self._detail.id, None))
        self._open_menu = QMenu()
        self._open_btn.setMenu(self._open_menu)
        file_btns.addWidget(self._open_btn)

        self._show_btn = QPushButton("Show in Folder")
        self._show_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._show_btn.clicked.connect(self._on_show_in_folder)
        file_btns.addWidget(self._show_btn)
        self._sec_file.body_layout().addLayout(file_btns)

        drive_box = QWidget()
        drive_l = QVBoxLayout(drive_box)
        drive_l.setContentsMargins(0, 2, 0, 0)
        drive_l.setSpacing(4)

        self._keep_offline_cb = QCheckBox("Keep offline")
        self._keep_offline_cb.toggled.connect(self._on_keep_offline_toggled)
        drive_l.addWidget(self._keep_offline_cb)

        d_btns_row = QHBoxLayout()
        d_btns_row.setContentsMargins(0, 0, 0, 0)
        d_btns_row.setSpacing(4)

        self._remove_download_btn = QPushButton("Remove download")
        self._remove_download_btn.setStyleSheet("font-size: 11px;")
        self._remove_download_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._remove_download_btn.clicked.connect(self._on_remove_download)
        d_btns_row.addWidget(self._remove_download_btn)

        self._open_drive_btn = QPushButton("Open in Drive")
        self._open_drive_btn.setStyleSheet("font-size: 11px;")
        self._open_drive_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._open_drive_btn.clicked.connect(self._on_open_in_drive)
        d_btns_row.addWidget(self._open_drive_btn)

        drive_l.addLayout(d_btns_row)
        self._sec_file.body_layout().addWidget(drive_box)
        layout.addWidget(self._sec_file)

        # ── 7. Similar Books ──────────────────────────────────────────────────
        self._sec_similar = CollapsibleSection("SIMILAR BOOKS")
        self._similar_container = QWidget()
        self._similar_layout = QVBoxLayout(self._similar_container)
        self._similar_layout.setContentsMargins(0, 2, 0, 2)
        self._similar_layout.setSpacing(4)
        self._sec_similar.add_widget(self._similar_container)
        layout.addWidget(self._sec_similar)

        layout.addStretch()

    def _setup_cover_menu(self) -> None:
        self._cover_menu.clear()
        self._cover_menu.addAction("From file…", self._on_cover_from_file)
        self._cover_menu.addAction("From clipboard", self._on_cover_from_clipboard)
        self._cover_menu.addAction("From PDF page…", self._on_cover_from_pdf_page)
        self._cover_menu.addSeparator()
        self._cover_menu.addAction("Restore original", self._on_cover_restore)

    # ── Display ───────────────────────────────────────────────────────────────

    def display(self, book_id: int | None) -> None:
        self._save_notes()
        if book_id is None:
            self._detail = None
            self._clear()
            return

        detail = self._repo.get_book_detail(book_id)
        self._detail = detail
        if detail is None:
            self._clear()
            return

        # Cover
        self._update_cover_display(detail)

        self._title_lbl.setText(detail.title or "Unknown")
        self._author_lbl.setText(detail.author or "—")
        self._status_btns.set_status(detail.status)
        self._stars.set_rating(detail.rating)

        # Metadata with provenance icons
        sources = detail.field_sources or {}
        for key in ["publisher", "year", "isbn", "pages", "genre", "language"]:
            v_lbl, src_lbl = self._meta_rows[key]
            val = getattr(detail, key, None)
            v_lbl.setText(dash_if_none(val))
            src = sources.get(key, "file")
            if src.startswith("online:"):
                src_lbl.setPixmap(self.style().standardIcon(QStyle.SP_DriveNetIcon).pixmap(14, 14))
            elif src == "manual":
                src_lbl.setPixmap(self.style().standardIcon(QStyle.SP_FileDialogInfoView).pixmap(14, 14))
            else:
                src_lbl.setPixmap(self.style().standardIcon(QStyle.SP_FileIcon).pixmap(14, 14))
            src_lbl.setToolTip(f"Source: {src}")

        self._desc_lbl.setText(detail.description or "—")

        # Organize: Tags
        self._render_tags(detail)

        # Organize: Series
        if detail.series_name:
            idx_str = f" {detail.series_index}" if detail.series_index is not None else ""
            self._series_lbl.setText(f"Book{idx_str} of <b>{detail.series_name}</b>")
            self._btn_prev_series.setEnabled(True)
            self._btn_next_series.setEnabled(True)
        else:
            self._series_lbl.setText("No series")
            self._btn_prev_series.setEnabled(False)
            self._btn_next_series.setEnabled(False)

        # Progress
        self._update_progress_display(detail)

        # Notes
        self._notes.blockSignals(True)
        self._notes.setPlainText(detail.notes or "")
        self._notes.blockSignals(False)

        # File
        is_gdrive = (detail.source in ("gdrive", "drive"))
        if is_gdrive:
            self._file_rows["source"].setText("Google Drive")
            self._file_rows["path"].setText(detail.drive_path or detail.path)
            self._file_rows["md5"].setText(detail.md5 or "—")
            if detail.is_cached:
                self._file_rows["cache"].setText(f"Downloaded ({human_size(detail.size_bytes)})")
            else:
                self._file_rows["cache"].setText("Drive only (Not downloaded)")
            self._keep_offline_cb.setVisible(True)
            self._keep_offline_cb.blockSignals(True)
            self._keep_offline_cb.setChecked(bool(detail.keep_offline))
            self._keep_offline_cb.blockSignals(False)
            self._remove_download_btn.setVisible(bool(detail.is_cached))
            self._open_drive_btn.setVisible(bool(detail.drive_web_link))
            self._show_btn.setText("Show Downloaded" if detail.is_cached else "Show in Folder")
            self._show_btn.setEnabled(bool(detail.is_cached))
        else:
            self._file_rows["source"].setText("Local File")
            self._file_rows["path"].setText(detail.path)
            self._file_rows["md5"].setText(detail.file_hash or detail.quick_hash or "—")
            self._file_rows["cache"].setText("Local on disk")
            self._keep_offline_cb.setVisible(False)
            self._remove_download_btn.setVisible(False)
            self._open_drive_btn.setVisible(False)
            self._show_btn.setText("Show in Folder")
            self._show_btn.setEnabled(True)

        self._file_rows["format"].setText(detail.format.upper())
        self._file_rows["size"].setText(human_size(detail.size_bytes))

        self._rebuild_open_menu(detail)
        self._update_similar_books(detail.id)

    def _update_cover_display(self, detail: BookDetail) -> None:
        px = QPixmap()
        if detail.cover_path:
            abs_path = COVERS_DIR / detail.cover_path
            if abs_path.exists():
                px.load(str(abs_path))
        if px.isNull():
            try:
                from booklib.covers.placeholder import generate_placeholder
                px.loadFromData(generate_placeholder(detail.format))
            except Exception:
                pass
        self._current_pixmap = px
        self._refresh_cover_display()

    def _refresh_cover_display(self) -> None:
        if self._current_pixmap.isNull():
            self._cover_lbl.clear()
            return
        pane_w = self.width() if self.width() > 50 else 240
        target_w = max(100, min(pane_w - 32, 220))
        scaled_px = self._current_pixmap.scaled(
            target_w, COVER_MAX_H, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._cover_lbl.setPixmap(scaled_px)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_cover_display()

    def _render_tags(self, detail: BookDetail) -> None:
        while self._tags_chip_layout.count():
            item = self._tags_chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                sub_l = item.layout()
                while sub_l.count():
                    sub_item = sub_l.takeAt(0)
                    if sub_item.widget():
                        sub_item.widget().deleteLater()

        current_row = None
        for i, t in enumerate(detail.tags):
            if i % 2 == 0:
                if current_row:
                    current_row.addStretch()
                row_widget = QWidget()
                current_row = QHBoxLayout(row_widget)
                current_row.setContentsMargins(0, 0, 0, 0)
                current_row.setSpacing(4)
                self._tags_chip_layout.addWidget(row_widget)
            t_name = t["name"]
            chip = QWidget()
            cl = QHBoxLayout(chip)
            cl.setContentsMargins(4, 2, 4, 2)
            cl.setSpacing(2)
            chip.setStyleSheet("background: palette(midlight); border-radius: 4px;")
            lbl = QLabel(f"#{t_name}")
            lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            cl.addWidget(lbl)
            del_btn = QPushButton("×")
            del_btn.setFixedSize(14, 14)
            del_btn.setStyleSheet("border: none; font-size: 11px; font-weight: bold; line-height: 12px;")
            del_btn.clicked.connect(lambda _, tn=t_name: self._on_remove_tag(tn))
            cl.addWidget(del_btn)
            current_row.addWidget(chip)
        if current_row:
            current_row.addStretch()

    def _update_progress_display(self, detail: BookDetail) -> None:
        self._prog_spin.blockSignals(True)
        self._prog_slider.blockSignals(True)

        pages = detail.pages or 0
        if pages > 0:
            self._prog_spin.setRange(0, pages)
            cur_p = detail.progress_page or 0
            self._prog_spin.setValue(cur_p)
            self._prog_lbl.setText(f"Page {cur_p} of {pages}")
            pct = int((cur_p / pages) * 100)
            self._prog_slider.setValue(pct)
        else:
            self._prog_spin.setRange(0, 100)
            pct = int(detail.progress_percent or 0)
            self._prog_spin.setValue(pct)
            self._prog_lbl.setText(f"{pct}%")
            self._prog_slider.setValue(pct)

        self._prog_spin.blockSignals(False)
        self._prog_slider.blockSignals(False)

        # Reading log list
        logs = detail.reading_log or []
        if logs:
            entries = []
            for e in reversed(logs):
                s = e.get("started_on") or "—"
                f = e.get("finished_on") or "reading…"
                entries.append(f"• Started: {s} | Finished: {f}")
            self._log_content_lbl.setText("\n".join(entries))
        else:
            self._log_content_lbl.setText("No reading history recorded.")

        # Reading time spent and estimate
        est = book_reading_estimate(self._repo._conn, detail.id)
        if est["total_seconds"] > 0 or est["time_left_text"]:
            spent = est["time_spent_text"]
            left = f" · {est['time_left_text']}" if est['time_left_text'] else ""
            self._reading_time_lbl.setText(f"Read: {spent}{left}")
            self._reading_time_lbl.show()
        else:
            self._reading_time_lbl.hide()

    def _clear(self) -> None:
        self._current_pixmap = QPixmap()
        self._cover_lbl.clear()
        self._title_lbl.clear()
        self._author_lbl.clear()
        self._status_btns.set_status(None)
        self._stars.set_rating(None)
        for v_lbl, src_lbl in self._meta_rows.values():
            v_lbl.clear()
            src_lbl.clear()
        self._desc_lbl.clear()
        self._notes.blockSignals(True)
        self._notes.clear()
        self._notes.blockSignals(False)
        self._open_menu.clear()
        while self._similar_layout.count():
            item = self._similar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        while self._tags_chip_layout.count():
            item = self._tags_chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                sub_l = item.layout()
                while sub_l.count():
                    sub_item = sub_l.takeAt(0)
                    if sub_item.widget():
                        sub_item.widget().deleteLater()
        self._series_lbl.setText("No series")
        self._btn_prev_series.setEnabled(False)
        self._btn_next_series.setEnabled(False)

    def _update_similar_books(self, book_id: int) -> None:
        while self._similar_layout.count():
            item = self._similar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._rec_service:
            lbl = QLabel("Recommendations unavailable.")
            lbl.setStyleSheet("font-size: 11px; font-style: italic; color: palette(window-text);")
            self._similar_layout.addWidget(lbl)
            return

        if not self._rec_service.is_enabled():
            lbl = QLabel("Recommendations disabled.")
            lbl.setStyleSheet("font-size: 11px; font-style: italic; color: palette(window-text);")
            self._similar_layout.addWidget(lbl)
            return

        try:
            similar = self._rec_service.get_similar_books(book_id, limit=4)
        except Exception as e:
            logger.warning("Failed to get similar books: %s", e)
            similar = []

        if not similar:
            lbl = QLabel("No similar books found.")
            lbl.setStyleSheet("font-size: 11px; font-style: italic; color: palette(window-text);")
            self._similar_layout.addWidget(lbl)
            return

        for book, reason in similar:
            btn = QPushButton()
            btn.setFlat(True)
            title = book.title or "Unknown"
            auth = f" · {book.author}" if book.author else ""
            btn.setText(f"{title}{auth}\n↳ {reason}")
            btn.setStyleSheet(
                "QPushButton { text-align: left; padding: 4px 6px; font-size: 11px; "
                "border: 1px solid palette(midlight); border-radius: 4px; } "
                "QPushButton:hover { background: palette(midlight); }"
            )
            btn.clicked.connect(lambda _, bid=book.id: self.select_book_requested.emit(bid))
            self._similar_layout.addWidget(btn)


    def _rebuild_open_menu(self, detail: BookDetail) -> None:
        self._open_menu.clear()
        self._open_menu.addAction("Open (default)", lambda: self.open_requested.emit(detail.id, None))
        self._open_menu.addSeparator()
        try:
            from booklib.readers.registry import get_registry
            readers = get_registry().readers_for(detail.format)
            for reader in readers:
                self._open_menu.addAction(reader.name, lambda r=reader: self.open_requested.emit(detail.id, r.key))
            self._open_menu.addSeparator()
        except Exception:
            pass
        self._open_menu.addAction("Choose another app…", lambda: self.open_requested.emit(detail.id, "chooser"))

    # ── Slots & Actions ───────────────────────────────────────────────────────

    def _on_status_request(self, status: str | None) -> None:
        if self._detail:
            self.status_changed.emit(self._detail.id, status)
            # Reload detail to refresh reading log
            self.display(self._detail.id)

    def _on_rating_change(self, rating: int | None) -> None:
        if self._detail:
            self.rating_changed.emit(self._detail.id, rating)

    def _notes_changed(self) -> None:
        self._notes_timer.start()

    def _save_notes(self) -> None:
        if self._detail:
            text = self._notes.toPlainText().strip()
            self.notes_saved.emit(self._detail.id, text)

    def _on_show_in_folder(self) -> None:
        if self._detail:
            from booklib.utils.fileops import show_in_folder
            if self._detail.source == "gdrive":
                if self._detail.cached_path:
                    show_in_folder(self._detail.cached_path)
            else:
                show_in_folder(self._detail.path)

    def _on_keep_offline_toggled(self, checked: bool) -> None:
        if self._detail:
            self.keep_offline_toggled.emit(self._detail.id, checked)
            self.display(self._detail.id)

    def _on_remove_download(self) -> None:
        if self._detail:
            self.remove_download_requested.emit(self._detail.id)
            self.display(self._detail.id)

    def _on_open_in_drive(self) -> None:
        if self._detail and self._detail.drive_web_link:
            QDesktopServices.openUrl(QUrl(self._detail.drive_web_link))

    def _on_add_tag_entered(self) -> None:
        if not self._detail:
            return
        tag_name = self._tag_input.text().strip().lstrip("#")
        if not tag_name:
            return
        self._repo.add_tag_to_books(tag_name, [self._detail.id])
        self._tag_input.clear()
        self.display(self._detail.id)

    def _on_remove_tag(self, tag_name: str) -> None:
        if not self._detail:
            return
        self._repo.remove_tag_from_books(tag_name, [self._detail.id])
        self.display(self._detail.id)

    def _on_prev_series(self) -> None:
        if not self._detail or not self._detail.series_id:
            return
        neighbors = self._repo.get_series_neighbors(self._detail.id, self._detail.series_id)
        if neighbors.get("prev_id"):
            self.select_book_requested.emit(neighbors["prev_id"])

    def _on_next_series(self) -> None:
        if not self._detail or not self._detail.series_id:
            return
        neighbors = self._repo.get_series_neighbors(self._detail.id, self._detail.series_id)
        if neighbors.get("next_id"):
            self.select_book_requested.emit(neighbors["next_id"])

    def _on_progress_spin_changed(self, val: int) -> None:
        if not self._detail:
            return
        pages = self._detail.pages or 0
        if pages > 0:
            pct = round((val / pages) * 100, 1)
            self._repo.set_progress(self._detail.id, page=val, percent=pct)
            self._prog_lbl.setText(f"Page {val} of {pages}")
        else:
            self._repo.set_progress(self._detail.id, page=None, percent=float(val))
            self._prog_lbl.setText(f"{val}%")

    def _on_progress_slider_changed(self, pct: int) -> None:
        if not self._detail:
            return
        pages = self._detail.pages or 0
        if pages > 0:
            page = int((pct / 100) * pages)
            self._prog_spin.setValue(page)
        else:
            self._prog_spin.setValue(pct)

    def _on_read_again(self) -> None:
        if not self._detail:
            return
        self._repo.read_again(self._detail.id)
        self.display(self._detail.id)

    # ── Custom Cover Slots ────────────────────────────────────────────────────

    def _on_image_bytes_dropped(self, raw_bytes: bytes) -> None:
        if not self._detail:
            return
        try:
            save_custom_cover(self._repo._conn, self._detail.id, raw_bytes, source="custom")
            self.cover_changed.emit(self._detail.id)
            self.display(self._detail.id)
        except Exception as e:
            QMessageBox.warning(self, "Invalid Image", str(e))

    def _on_cover_from_file(self) -> None:
        if not self._detail:
            return
        fn, _ = QFileDialog.getOpenFileName(
            self, "Choose Cover Image", "", "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if fn:
            try:
                data = Path(fn).read_bytes()
                save_custom_cover(self._repo._conn, self._detail.id, data, source="custom")
                self.cover_changed.emit(self._detail.id)
                self.display(self._detail.id)
            except Exception as e:
                QMessageBox.warning(self, "Failed to Set Cover", str(e))

    def _on_cover_from_clipboard(self) -> None:
        if not self._detail:
            return
        cb = QGuiApplication.clipboard()
        img = cb.image()
        if img.isNull():
            QMessageBox.information(self, "Clipboard", "No image found in clipboard.")
            return

        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        try:
            save_custom_cover(self._repo._conn, self._detail.id, bytes(buf.data()), source="custom")
            self.cover_changed.emit(self._detail.id)
            self.display(self._detail.id)
        except Exception as e:
            QMessageBox.warning(self, "Failed to Set Cover", str(e))

    def _on_cover_from_pdf_page(self) -> None:
        if not self._detail:
            return
        if self._detail.format != "pdf":
            QMessageBox.information(self, "PDF Only", "This book is not a PDF file.")
            return

        page_count = self._detail.pages or 1
        page_num, ok = QInputDialog.getInt(
            self, "Cover from PDF Page", f"Enter page number (1 to {page_count}):", 1, 1, page_count
        )
        if ok:
            try:
                jpeg_bytes = render_pdf_page_cover(self._detail.path, page_num - 1)
                save_custom_cover(self._repo._conn, self._detail.id, jpeg_bytes, source="custom")
                self.cover_changed.emit(self._detail.id)
                self.display(self._detail.id)
            except Exception as e:
                QMessageBox.warning(self, "Failed to Render Page", str(e))

    def _on_cover_restore(self) -> None:
        if not self._detail:
            return
        try:
            restore_original_cover(self._repo._conn, self._detail.id)
            self.cover_changed.emit(self._detail.id)
            self.display(self._detail.id)
        except Exception as e:
            QMessageBox.warning(self, "Failed to Restore Cover", str(e))

"""
main_window.py – Ratnodadhi v5 application main window.
Features: JobManager concurrency, Watchdog folder monitoring, Metadata lookup & review queue,
Duplicates resolution, Collections (manual & smart) with drag & drop, Series, Tags, Custom covers,
Rename engine, Export/Import, Statistics, Library health, Calibre conversion.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

# Ratnodadhi logo path
_LOGO_PATH = Path(__file__).parent.parent / "resources" / "ratnodadhi-logo.svg"

from PySide6.QtCore import QItemSelection, QModelIndex, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QFont, QIcon, QKeySequence, QPixmap, QUndoStack
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar,
    QPushButton, QSlider, QSplitter, QStackedWidget, QStatusBar, QStyle,
    QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from booklib.config import DB_PATH
from booklib.db.database import Database
from booklib.db.query import LibraryQuery, VALID_SORT_FIELDS
from booklib.db.repository import BookRow, Repository
from booklib.jobs.backfill_job import QuickHashBackfillJob
from booklib.jobs.lookup_job import OnlineLookupJob
from booklib.jobs.manager import BaseJob, get_job_manager
from booklib.jobs.scan_job import ScanJob
from booklib.metadata.extract import extract_metadata
from booklib.metadata.online.merge import undo_batch
from booklib.readers.launcher import launch, open_with_os_dialog
from booklib.readers.registry import get_registry
from booklib.recommend.service import RecommendationService
from booklib.ui.commands import EditMetadataCommand, SetRatingCommand, SetStatusCommand
from booklib.ui.details_pane import DetailsPane
from booklib.ui.duplicates_dialog import DuplicatesDialog
from booklib.ui.edit_dialog import BulkEditDialog, EditDialog
from booklib.ui.filter_chips import FilterChips
from booklib.ui.folders_dialog import FoldersDialog
from booklib.ui.library_model import (
    COL_IDX, COLUMNS, ROLE_BOOK_ID, ROLE_MISSING, LibraryModel,
)
from booklib.ui.library_view import LibraryTableView, LibraryView
from booklib.ui.annotations_view import AnnotationsView
from booklib.ui.inbook_search import InBookSearchDialog
from booklib.ui.lookup_review import LookupReviewDialog
from booklib.ui.readers_dialog import ReadersDialog
from booklib.ui.sidebar import Sidebar
from booklib.ui.theme import THEME_KEY, apply_theme
from booklib.utils.fileops import open_file, show_in_folder
from booklib.watcher.folder_watcher import FolderWatcher
from booklib.app import get_app_icon, _LOGO_PATH
from PySide6.QtSvgWidgets import QSvgWidget

logger = logging.getLogger(__name__)

_ORG = "Ratnodadhi"
_APP = "Ratnodadhi"


class MainWindow(QMainWindow):
    def __init__(self, db: Database) -> None:
        super().__init__()
        self._db = db
        self._conn = db.conn
        self._repo = Repository(self._conn)
        get_registry()._repo = self._repo

        self._query = LibraryQuery()
        self._undo_stack = QUndoStack(self)
        self._view_mode = "grid"
        self._auto_mark_reading = True
        self._last_lookup_batch_id: str | None = None

        self.setWindowTitle("Ratnodadhi")
        self.setMinimumSize(980, 640)

        # Window icon (title bar + taskbar + Alt+Tab)
        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        # 250ms search debounce timer
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._on_search_timer)

        # Recommendation Service
        self._rec_service = RecommendationService(self._repo)

        # Job Manager
        self._job_manager = get_job_manager()
        self._job_manager.job_started.connect(self._on_job_started)
        self._job_manager.job_progress.connect(self._on_job_progress)
        self._job_manager.job_finished.connect(self._on_job_finished)
        self._job_manager.job_error.connect(self._on_job_error)
        self._job_manager.idle.connect(self._on_job_idle)
        self._job_manager.library_changed.connect(self._reload_books)
        self._job_manager.library_changed.connect(lambda: self._rec_service.invalidate_cache())

        # Folder Watcher
        self._watcher = FolderWatcher(parent=self)
        self._watcher.batch_ready.connect(self._on_watched_folder_batch)

        self._setup_ui()
        self._setup_menus_and_shortcuts()
        self._restore_settings()
        self.setAcceptDrops(True)

        # Start watcher for folders with watch = 1 (local only)
        for f in self._repo.list_folders():
            if f.get("watch") and f.get("source", "local") == "local":
                self._watcher.add_folder(f["path"])
        self._watcher.start()

        # Drive periodic sync timer (15 minutes)
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(15 * 60 * 1000)
        self._sync_timer.timeout.connect(self._on_sync_drive)
        self._sync_timer.start()

        # Startup consistency & disk space check
        QTimer.singleShot(1500, self._startup_checks)

        # Initial load
        self._reload_books()
        self._refresh_sidebar_counts()

        # Startup backfill of quick_hash
        self._job_manager.submit(QuickHashBackfillJob(parent=self))

    # ── UI Setup ──────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        # ── Logo & app name ───────────────────────────────────────────────────
        if _LOGO_PATH.exists():
            logo_svg = QSvgWidget(str(_LOGO_PATH))
            logo_svg.setFixedSize(28, 28)
            logo_svg.setToolTip("Ratnodadhi (रत्नोदधि) — Your Personal Library")
            toolbar.addWidget(logo_svg)

            from booklib.ui.theme import load_jaini_font, is_dark
            jaini_family = load_jaini_font()
            _name_lbl = QLabel("रत्नोदधि")
            _name_lbl.setObjectName("appNameDevanagari")
            f_jaini = QFont(jaini_family, 18)
            f_jaini.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
            _name_lbl.setFont(f_jaini)
            brand_col = "#e07a5f" if is_dark() else "#b84e26"
            _name_lbl.setStyleSheet(f"font-family: '{jaini_family}', 'Jaini', sans-serif; color: {brand_col}; padding: 0 6px 0 2px;")
            _name_lbl.setToolTip("Ratnodadhi (रत्नोदधि) — Ocean of Gems")
            toolbar.addWidget(_name_lbl)
            toolbar.addSeparator()

        # Add Folder & Rescan
        self._btn_add_folder = QPushButton("Add Folder")
        self._btn_add_folder.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        self._btn_add_folder.setToolTip("Add a folder to scan for books")
        self._btn_add_folder.clicked.connect(self._on_add_folder)
        toolbar.addWidget(self._btn_add_folder)

        self._btn_rescan = QPushButton("Rescan")
        self._btn_rescan.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self._btn_rescan.setToolTip("Rescan all library folders")
        self._btn_rescan.clicked.connect(self._on_rescan)
        toolbar.addWidget(self._btn_rescan)

        toolbar.addSeparator()

        # Fetch Metadata button with drop menu
        self._btn_fetch_meta = QToolButton()
        self._btn_fetch_meta.setText("Fetch Metadata ▾")
        self._btn_fetch_meta.setIcon(self.style().standardIcon(QStyle.SP_FileDialogInfoView))
        self._btn_fetch_meta.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn_fetch_meta.setPopupMode(QToolButton.InstantPopup)
        self._fetch_meta_menu = QMenu(self)
        self._fetch_meta_menu.addAction("Fetch for Selected Books…", self._on_lookup_selected)
        self._fetch_meta_menu.addAction("Fetch for Incomplete Books…", self._on_lookup_incomplete)
        self._fetch_meta_menu.addAction("Open Review Queue…", self._on_open_review_queue)
        self._fetch_meta_menu.addSeparator()
        self._fetch_meta_menu.addAction("Undo Last Lookup Batch…", self._on_undo_metadata_batch)
        self._btn_fetch_meta.setMenu(self._fetch_meta_menu)
        toolbar.addWidget(self._btn_fetch_meta)

        toolbar.addSeparator()

        # Search Bar
        search_widget = QWidget()
        search_layout = QHBoxLayout(search_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(4)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search books, tags… (Ctrl+F)")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setFixedWidth(220)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        search_layout.addWidget(self._search_input)
        toolbar.addWidget(search_widget)

        toolbar.addSeparator()

        # Sort Dropdown
        sort_lbl = QLabel("Sort:")
        sort_lbl.setStyleSheet("font-size: 11px; color: palette(window-text);")
        toolbar.addWidget(sort_lbl)

        self._sort_combo = QComboBox()
        self._sort_combo.addItem("Title", "title")
        self._sort_combo.addItem("Author", "author")
        self._sort_combo.addItem("Series", "series")
        self._sort_combo.addItem("Progress", "progress")
        self._sort_combo.addItem("Year", "year")
        self._sort_combo.addItem("Size", "size_bytes")
        self._sort_combo.addItem("Format", "format")
        self._sort_combo.addItem("Date Added", "date_added")
        self._sort_combo.addItem("Rating", "rating")
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        toolbar.addWidget(self._sort_combo)

        self._btn_sort_dir = QPushButton()
        self._btn_sort_dir.setIcon(self.style().standardIcon(QStyle.SP_ArrowUp))
        self._btn_sort_dir.setIconSize(QSize(16, 16))
        self._btn_sort_dir.setToolTip("Sort Ascending (click to toggle)")
        self._btn_sort_dir.setFixedSize(28, 28)
        self._btn_sort_dir.setStyleSheet(
            "QPushButton { padding: 0px; border-radius: 5px; border: 1px solid palette(mid); background: palette(button); }"
            "QPushButton:hover { background: rgba(128, 128, 128, 0.20); border-color: palette(window-text); }"
        )
        self._btn_sort_dir.clicked.connect(self._on_sort_dir_toggle)
        toolbar.addWidget(self._btn_sort_dir)

        toolbar.addSeparator()

        # Grid / List View Toggle
        view_btn_style = """
            QPushButton {
                padding: 0px;
                border-radius: 5px;
                border: 1px solid palette(mid);
                background-color: palette(button);
            }
            QPushButton:hover:!checked {
                background-color: rgba(128, 128, 128, 0.18);
                border-color: palette(window-text);
            }
            QPushButton:checked {
                background-color: palette(alternate-base);
                border: 2px solid palette(window-text);
                color: palette(window-text);
            }
        """
        self._btn_grid_view = QPushButton()
        self._btn_grid_view.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self._btn_grid_view.setIconSize(QSize(16, 16))
        self._btn_grid_view.setToolTip("Grid View")
        self._btn_grid_view.setCheckable(True)
        self._btn_grid_view.setChecked(True)
        self._btn_grid_view.setFixedSize(28, 28)
        self._btn_grid_view.setStyleSheet(view_btn_style)

        self._btn_list_view = QPushButton()
        self._btn_list_view.setIcon(self.style().standardIcon(QStyle.SP_FileDialogListView))
        self._btn_list_view.setIconSize(QSize(16, 16))
        self._btn_list_view.setToolTip("List View")
        self._btn_list_view.setCheckable(True)
        self._btn_list_view.setFixedSize(28, 28)
        self._btn_list_view.setStyleSheet(view_btn_style)

        view_group = QButtonGroup(self)
        view_group.setExclusive(True)
        view_group.addButton(self._btn_grid_view)
        view_group.addButton(self._btn_list_view)
        self._btn_grid_view.clicked.connect(lambda: self._set_view_mode("grid"))
        self._btn_list_view.clicked.connect(lambda: self._set_view_mode("list"))

        toolbar.addWidget(self._btn_grid_view)
        toolbar.addWidget(self._btn_list_view)

        # Thumbnail Slider for Grid
        self._thumb_slider = QSlider(Qt.Horizontal)
        self._thumb_slider.setRange(80, 240)
        self._thumb_slider.setValue(120)
        self._thumb_slider.setFixedWidth(90)
        self._thumb_slider.setToolTip("Thumbnail size")
        self._thumb_slider.valueChanged.connect(self._on_thumb_size_changed)
        toolbar.addWidget(self._thumb_slider)

        toolbar.addSeparator()

        # Surprise Me button (clean, no emoji/icon)
        self._btn_surprise_me = QPushButton("Surprise Me")
        self._btn_surprise_me.setToolTip("Pick a random book to read next")
        self._btn_surprise_me.clicked.connect(self._on_surprise_me)
        toolbar.addWidget(self._btn_surprise_me)

        # Settings / Options Button
        settings_btn = QToolButton()
        settings_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        settings_btn.setToolTip("Settings & Preferences")
        settings_btn.setPopupMode(QToolButton.InstantPopup)
        self._settings_menu = QMenu(self)
        settings_btn.setMenu(self._settings_menu)
        toolbar.addWidget(settings_btn)

        # ── Central Splitter ──────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self._splitter)

        # Left: Sidebar
        self._sidebar = Sidebar(self)
        self._sidebar.query_changed.connect(self._on_sidebar_query_changed)
        self._sidebar.create_collection_requested.connect(self._on_create_collection)
        self._sidebar.books_dropped_on_collection.connect(self._on_books_dropped_on_collection)
        self._sidebar.manage_collection_requested.connect(self._on_manage_collection)
        self._sidebar.find_duplicates_requested.connect(self._on_find_duplicates)
        self._sidebar.highlights_notes_requested.connect(self._on_show_annotations_view)
        self._splitter.addWidget(self._sidebar)

        # Middle: Filter Chips + Views Stack
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        # Filter Chips Bar
        self._filter_chips = FilterChips(self)
        self._filter_chips.filter_cleared.connect(self._on_filter_cleared)
        self._filter_chips.clear_all_requested.connect(self._on_clear_all_filters)
        self._filter_chips.save_smart_collection_requested.connect(self._on_save_smart_collection)
        center_layout.addWidget(self._filter_chips)

        # Views Stack (Grid / List / Annotations)
        self._stack = QStackedWidget(self)
        self._model = LibraryModel(self)

        self._grid_view = LibraryView(self)
        self._grid_view.setModel(self._model)

        self._table_view = LibraryTableView(self)
        self._table_view.setModel(self._model)
        self._table_view.setSelectionModel(self._grid_view.selectionModel())

        self._annotations_view = AnnotationsView(lambda: self._conn, self)

        self._stack.addWidget(self._grid_view)
        self._stack.addWidget(self._table_view)
        self._stack.addWidget(self._annotations_view)
        center_layout.addWidget(self._stack, 1)

        self._splitter.addWidget(center_widget)

        # Right: Details Pane
        self._details = DetailsPane(self._repo, self, rec_service=self._rec_service)
        self._details.status_changed.connect(self._on_details_status_changed)
        self._details.rating_changed.connect(self._on_details_rating_changed)
        self._details.notes_saved.connect(self._on_details_notes_saved)
        self._details.edit_requested.connect(self._on_edit_book)
        self._details.open_requested.connect(self._on_open_book_requested)
        self._details.lookup_requested.connect(self._on_lookup_single)
        self._details.cover_changed.connect(lambda bid: self._reload_books())
        self._details.select_book_requested.connect(self._select_book_by_id)
        self._details.keep_offline_toggled.connect(self._on_keep_offline_toggled)
        self._details.remove_download_requested.connect(self._on_remove_download_requested)
        self._splitter.addWidget(self._details)

        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 4)
        self._splitter.setStretchFactor(2, 1)

        # View events
        self._grid_view.doubleClicked.connect(self._on_book_double_clicked)
        self._table_view.doubleClicked.connect(self._on_book_double_clicked)
        self._grid_view.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # Context menus
        self._grid_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._grid_view.customContextMenuRequested.connect(self._on_context_menu)
        self._table_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table_view.customContextMenuRequested.connect(self._on_context_menu)

        # Table header sorting
        self._table_view.horizontalHeader().sectionClicked.connect(self._on_table_header_clicked)

        # ── Status Bar ────────────────────────────────────────────────────────
        sb = QStatusBar(self)
        self.setStatusBar(sb)

        self._status_label = QLabel()
        self._status_label.setStyleSheet("padding: 2px 6px;")
        sb.addWidget(self._status_label)

        self._job_label = QLabel()
        self._job_label.setStyleSheet("font-size: 11px; padding: 2px 6px; color: palette(window-text);")
        self._job_label.hide()
        sb.addPermanentWidget(self._job_label)

        self._job_progress = QProgressBar()
        self._job_progress.setMaximumWidth(180)
        self._job_progress.hide()
        sb.addPermanentWidget(self._job_progress)

        self._btn_cancel_job = QPushButton("Cancel")
        self._btn_cancel_job.setIcon(self.style().standardIcon(QStyle.SP_DialogCancelButton))
        self._btn_cancel_job.setStyleSheet("color: #ef4444; font-weight: bold; font-size: 11px; padding: 2px 6px;")
        self._btn_cancel_job.hide()
        self._btn_cancel_job.clicked.connect(self._on_cancel_job)
        sb.addPermanentWidget(self._btn_cancel_job)

    def _setup_menus_and_shortcuts(self) -> None:
        mb = self.menuBar()

        # File Menu
        file_menu = mb.addMenu("&File")
        file_menu.addAction(self.style().standardIcon(QStyle.SP_FileIcon), "Add Files…", self._on_add_files, QKeySequence("Ctrl+O"))
        file_menu.addAction(self.style().standardIcon(QStyle.SP_FileDialogNewFolder), "Add Folder…", self._on_add_folder)
        file_menu.addAction(self.style().standardIcon(QStyle.SP_DriveNetIcon), "Add Google Drive Folder…", self._on_add_drive_folder)
        file_menu.addAction(self.style().standardIcon(QStyle.SP_BrowserReload), "Rescan All", self._on_rescan)
        file_menu.addAction(self.style().standardIcon(QStyle.SP_DirIcon), "Manage Folders…", self._on_folders_dialog)
        file_menu.addAction(self.style().standardIcon(QStyle.SP_TrashIcon), "Remove Missing Files", self._on_remove_missing)
        file_menu.addSeparator()
        act_exit = file_menu.addAction("Exit", self.close)
        act_exit.setShortcut(QKeySequence.Quit)

        # Edit Menu
        edit_menu = mb.addMenu("&Edit")
        act_undo = self._undo_stack.createUndoAction(self, "&Undo")
        act_undo.setShortcut(QKeySequence.Undo)
        edit_menu.addAction(act_undo)

        act_redo = self._undo_stack.createRedoAction(self, "&Redo")
        act_redo.setShortcut(QKeySequence.Redo)
        edit_menu.addAction(act_redo)

        edit_menu.addSeparator()
        act_edit = edit_menu.addAction("Edit Metadata…", self._on_edit_selected)
        act_edit.setShortcut(QKeySequence("Ctrl+E"))
        self.addAction(act_edit)

        act_revert = edit_menu.addAction("Revert to File Metadata", self._on_revert_selected)

        edit_menu.addSeparator()
        act_want = edit_menu.addAction("Mark as Want to Read", lambda: self._set_selected_status("want"))
        act_want.setShortcut(QKeySequence("Ctrl+1"))
        self.addAction(act_want)

        act_reading = edit_menu.addAction("Mark as Reading", lambda: self._set_selected_status("reading"))
        act_reading.setShortcut(QKeySequence("Ctrl+2"))
        self.addAction(act_reading)

        act_read = edit_menu.addAction("Mark as Read", lambda: self._set_selected_status("read"))
        act_read.setShortcut(QKeySequence("Ctrl+3"))
        self.addAction(act_read)

        act_clear_s = edit_menu.addAction("Clear Status", lambda: self._set_selected_status(None))
        act_clear_s.setShortcut(QKeySequence("Ctrl+0"))
        self.addAction(act_clear_s)

        # Metadata Menu
        meta_menu = mb.addMenu("&Metadata")
        act_lookup = meta_menu.addAction("Fetch Online Metadata for Selection…", self._on_lookup_selected)
        act_lookup.setShortcut(QKeySequence("Ctrl+M"))
        self.addAction(act_lookup)
        meta_menu.addAction("Fetch for Incomplete Books…", self._on_lookup_incomplete)
        meta_menu.addAction("Open Review Queue…", self._on_open_review_queue)
        meta_menu.addSeparator()
        meta_menu.addAction("Undo Last Lookup Batch…", self._on_undo_metadata_batch)

        # Library Menu (v5 operations)
        lib_menu = mb.addMenu("&Library")
        act_rename = lib_menu.addAction("Rename Files…", self._on_rename_files)
        act_conv = lib_menu.addAction(self.style().standardIcon(QStyle.SP_BrowserReload), "Convert Format…", self._on_convert_books)
        lib_menu.addSeparator()
        act_export = lib_menu.addAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "Export Library…", self._on_export)
        act_export.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.addAction(act_export)
        act_import = lib_menu.addAction(self.style().standardIcon(QStyle.SP_DialogOpenButton), "Import…", self._on_import)
        act_import.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self.addAction(act_import)
        lib_menu.addSeparator()
        act_stats = lib_menu.addAction("Statistics…", self._on_show_statistics)
        act_stats.setShortcut(QKeySequence("F6"))
        self.addAction(act_stats)
        lib_menu.addAction("Reading Goals…", self._on_reading_goals)
        lib_menu.addSeparator()
        lib_menu.addAction(self.style().standardIcon(QStyle.SP_FileDialogInfoView), "Library Health…", self._on_library_health)

        # View Menu
        view_menu = mb.addMenu("&View")
        view_menu.addAction("Grid View", lambda: self._set_view_mode("grid"))
        view_menu.addAction("List View", lambda: self._set_view_mode("list"))
        view_menu.addSeparator()

        self._act_toggle_sidebar = view_menu.addAction("Toggle Sidebar", self._toggle_sidebar)
        self._act_toggle_sidebar.setShortcut(QKeySequence("Ctrl+B"))
        self.addAction(self._act_toggle_sidebar)

        theme_menu = view_menu.addMenu("Theme")
        self._theme_group = QActionGroup(self)
        for t_key, t_label in [("system", "System Default"), ("light", "Light"), ("dark", "Dark")]:
            act = theme_menu.addAction(t_label, lambda k=t_key: self._set_theme(k))
            act.setCheckable(True)
            self._theme_group.addAction(act)
            if t_key == "system":
                act.setChecked(True)

        # Tools Menu
        tools_menu = mb.addMenu("&Tools")
        tools_menu.addAction("Surprise Me", self._on_surprise_me)
        tools_menu.addAction("Search Inside Books…", self._on_search_inside_books)
        tools_menu.addAction("Find Duplicates…", self._on_find_duplicates)
        tools_menu.addAction("Highlights & Notes…", self._on_show_annotations_view)
        tools_menu.addAction("Rebuild Search Index", self._on_rebuild_fts)
        tools_menu.addAction("Fix Reading Dates…", self._on_fix_dates)
        tools_menu.addSeparator()
        tools_menu.addAction(self.style().standardIcon(QStyle.SP_DriveNetIcon), "Sync Google Drive Now", self._on_sync_drive)
        tools_menu.addAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "Back Up / Restore Library…", self._on_backup_dialog)
        tools_menu.addAction("Google Drive & Storage Settings…", self._on_drive_settings)

        # Settings Menu
        settings_menu = mb.addMenu("&Settings")
        settings_menu.addAction("Reader Preferences…", self._on_readers_dialog)
        settings_menu.addAction("Recommendations…", self._on_recommendations_settings)
        settings_menu.addAction("Web Access & OPDS…", self._on_web_settings)
        settings_menu.addAction("Google Drive & Storage…", self._on_drive_settings)
        self._act_auto_mark = settings_menu.addAction("Auto-mark Reading on Open")
        self._act_auto_mark.setCheckable(True)
        self._act_auto_mark.setChecked(self._auto_mark_reading)
        self._act_auto_mark.toggled.connect(self._on_auto_mark_toggled)

        # Toolbar settings menu
        self._settings_menu.addAction("Reader Preferences…", self._on_readers_dialog)
        self._settings_menu.addAction("Recommendations…", self._on_recommendations_settings)
        self._settings_menu.addAction("Web Access & OPDS…", self._on_web_settings)
        self._settings_menu.addAction("Manage Folders…", self._on_folders_dialog)
        self._settings_menu.addAction("Google Drive & Storage…", self._on_drive_settings)
        self._settings_menu.addSeparator()
        self._settings_menu.addAction("Surprise Me", self._on_surprise_me)
        self._settings_menu.addAction("Search Inside Books…", self._on_search_inside_books)
        self._settings_menu.addAction("Find Duplicates…", self._on_find_duplicates)
        self._settings_menu.addAction("Rebuild Search Index", self._on_rebuild_fts)
        self._settings_menu.addAction("Remove Missing Files", self._on_remove_missing)
        self._settings_menu.addSeparator()
        self._settings_menu.addAction("About Ratnodadhi…", self._on_about)

        # Help Menu
        help_menu = mb.addMenu("&Help")
        act_palette = help_menu.addAction("Command Palette…", self._on_command_palette)
        act_palette.setShortcut(QKeySequence("Ctrl+K"))
        self.addAction(act_palette)

        act_cheat = help_menu.addAction("Keyboard Shortcuts…", self._on_shortcuts_cheat_sheet)
        act_cheat.setShortcut(QKeySequence("Ctrl+/"))
        self.addAction(act_cheat)

        help_menu.addAction("Configure Shortcuts…", self._on_configure_shortcuts)
        help_menu.addSeparator()
        help_menu.addAction("About Ratnodadhi…", self._on_about)

        # Shortcuts
        act_search = QAction("Find", self)
        act_search.setShortcut(QKeySequence("Ctrl+F"))
        act_search.triggered.connect(lambda: self._search_input.setFocus())
        self.addAction(act_search)

        act_inbook_search = QAction("Search Inside Books", self)
        act_inbook_search.setShortcut(QKeySequence("Ctrl+Shift+F"))
        act_inbook_search.triggered.connect(self._on_search_inside_books)
        self.addAction(act_inbook_search)

    # ── Job Manager Integration ───────────────────────────────────────────────

    def _on_job_started(self, name: str) -> None:
        self._job_label.setText(f"{name}…")
        self._job_label.show()
        self._job_progress.setValue(0)
        self._job_progress.show()
        self._btn_cancel_job.show()
        self._btn_add_folder.setEnabled(False)
        self._btn_rescan.setEnabled(False)

    def _on_job_progress(self, name: str, done: int, total: int, msg: str) -> None:
        self._job_progress.setMaximum(total)
        self._job_progress.setValue(done)
        self._job_label.setText(f"{name}: {done}/{total}")

    def _on_job_finished(self, name: str, summary: Any) -> None:
        if isinstance(summary, dict) and summary.get("batch_id"):
            self._last_lookup_batch_id = summary["batch_id"]

        from booklib.scanner.worker import ScanSummary
        if isinstance(summary, ScanSummary):
            msg = f"{name} complete: {summary.added} added, {summary.updated} updated, {summary.unchanged} unchanged."
            if summary.missing_marked:
                msg += f" ({summary.missing_marked} missing)"
            if summary.errors:
                msg += f" ({summary.errors} errors)"
            self.statusBar().showMessage(msg, 7000)
        else:
            self.statusBar().showMessage(f"{name} finished.", 5000)

        self._reload_books()
        self._refresh_sidebar_counts()

    def _on_job_error(self, name: str, err: str) -> None:
        logger.error("Job error (%s): %s", name, err)
        self.statusBar().showMessage(f"Error in {name}: {err}", 6000)

    def _on_job_idle(self) -> None:
        self._job_label.hide()
        self._job_progress.hide()
        self._btn_cancel_job.hide()
        self._btn_add_folder.setEnabled(True)
        self._btn_rescan.setEnabled(True)

    def _on_cancel_job(self) -> None:
        self._job_manager.cancel_current()

    # ── Selection and Helpers ─────────────────────────────────────────────────

    def _selected_book_ids(self) -> list[int]:
        view = self._grid_view if self._view_mode == "grid" else self._table_view
        indexes = view.selectionModel().selectedIndexes()
        ids: set[int] = set()
        for idx in indexes:
            b = self._model.book_at(self._model.index(idx.row(), 0))
            if b:
                ids.add(b.id)
        return list(ids)

    def _selected_book_rows(self) -> list[BookRow]:
        view = self._grid_view if self._view_mode == "grid" else self._table_view
        indexes = view.selectionModel().selectedIndexes()
        seen: set[int] = set()
        books: list[BookRow] = []
        for idx in indexes:
            row = idx.row()
            if row not in seen:
                seen.add(row)
                b = self._model.book_at(self._model.index(row, 0))
                if b:
                    books.append(b)
        return books

    def _select_book_by_id(self, book_id: int) -> None:
        idx = self._model.index_for_id(book_id)
        if idx.isValid():
            view = self._grid_view if self._view_mode == "grid" else self._table_view
            view.setCurrentIndex(idx)
            view.scrollTo(idx)
            self._details.display(book_id)

    # ── Data Loading & Model Refresh ──────────────────────────────────────────

    def _reload_books(self) -> None:
        if self._query.shelf == "recommended":
            recs = self._rec_service.get_recommendations(limit=40)
            books = [b for b, _ in recs]
            is_cold, msg = self._rec_service.check_cold_start()
            if is_cold:
                self._statusBar.showMessage(msg, 8000)
        else:
            books = self._repo.query_books(self._query)
        self._model.reset_books(books)
        self._filter_chips.set_query(self._query)
        self._update_status()

    def _update_status(self) -> None:
        total = self._repo.count_books()
        shown = len(self._model._books)
        if total == shown:
            self._status_label.setText(f"{total:,} book{'s' if total != 1 else ''}")
        else:
            self._status_label.setText(f"{shown:,} of {total:,} books")

    def _refresh_sidebar_counts(self) -> None:
        counts = self._repo.count_by_status()
        # count_by_status already provides 'needs_review' and 'incomplete';
        # map them to the keys expected by the sidebar.
        counts["review"] = counts.get("needs_review", 0)
        self._sidebar.update_counts(counts)

        # Update collections, series, tags
        self._sidebar.update_collections(self._repo.list_collections())
        self._sidebar.update_series(self._repo.list_series())
        self._sidebar.update_tags(self._repo.list_tags())

        # Update format facets
        facets = self._repo.facet_counts("format", self._query)
        self._sidebar.update_format_facets(facets)

    # ── Search & Filter Slots ─────────────────────────────────────────────────

    def _on_search_text_changed(self, text: str) -> None:
        self._search_timer.start()

    def _on_search_timer(self) -> None:
        self._query.search = self._search_input.text().strip()
        self._reload_books()

    def _on_sort_changed(self) -> None:
        field = self._sort_combo.currentData()
        if field in VALID_SORT_FIELDS:
            self._query.sort_field = field
            self._reload_books()

    def _on_sort_dir_toggle(self) -> None:
        self._query.sort_desc = not self._query.sort_desc
        icon = QStyle.SP_ArrowDown if self._query.sort_desc else QStyle.SP_ArrowUp
        self._btn_sort_dir.setIcon(self.style().standardIcon(icon))
        tip = "Sort Descending (click to toggle)" if self._query.sort_desc else "Sort Ascending (click to toggle)"
        self._btn_sort_dir.setToolTip(tip)
        self._reload_books()

    def _on_table_header_clicked(self, logical_index: int) -> None:
        if 0 <= logical_index < len(COLUMNS):
            col_key = COLUMNS[logical_index].key
            if col_key in VALID_SORT_FIELDS:
                if self._query.sort_field == col_key:
                    self._query.sort_desc = not self._query.sort_desc
                else:
                    self._query.sort_field = col_key
                    self._query.sort_desc = False

                idx = self._sort_combo.findData(col_key)
                if idx >= 0:
                    self._sort_combo.blockSignals(True)
                    self._sort_combo.setCurrentIndex(idx)
                    self._sort_combo.blockSignals(False)
                icon = QStyle.SP_ArrowDown if self._query.sort_desc else QStyle.SP_ArrowUp
                self._btn_sort_dir.setIcon(self.style().standardIcon(icon))
                tip = "Sort Descending (click to toggle)" if self._query.sort_desc else "Sort Ascending (click to toggle)"
                self._btn_sort_dir.setToolTip(tip)
                self._reload_books()

    def _on_sidebar_query_changed(self, new_query: LibraryQuery) -> None:
        if self._stack.currentWidget() == self._annotations_view:
            self._set_view_mode(self._view_mode)
        self._query = new_query
        self._reload_books()

    def _on_filter_cleared(self, kind: str, value: object) -> None:
        if kind == "search":
            self._search_input.clear()
            self._query.search = ""
        elif kind == "shelf":
            self._query.shelf = None
            self._sidebar._select_shelf("all")
        elif kind == "status":
            self._query.statuses.discard(str(value))
        elif kind == "format":
            self._query.formats.discard(str(value))
        elif kind == "min_rating":
            self._query.min_rating = None
            self._sidebar._rating_spin.setValue(0)
        elif kind == "tag_ids":
            self._query.tag_ids.clear()
            for cb in self._sidebar._tag_checks.values():
                cb.setChecked(False)
        elif kind == "series_id":
            self._query.series_id = None
        elif kind == "lookup_status":
            self._query.lookup_status = None
        elif kind == "incomplete":
            self._query.incomplete = False
        elif kind == "book_ids":
            self._query.book_ids.clear()

        self._reload_books()

    def _on_clear_all_filters(self) -> None:
        self._search_input.clear()
        self._query = LibraryQuery()
        self._sidebar._select_shelf("all")
        self._reload_books()

    def _on_search_inside_books(self) -> None:
        current_ids = [b.id for b in self._model._books]
        dlg = InBookSearchDialog(lambda: self._conn, parent=self, current_book_ids=current_ids)
        dlg.show_books_in_library_requested.connect(self._on_filter_by_book_ids)
        dlg.exec()

    def _on_filter_by_book_ids(self, book_ids: list[int]) -> None:
        if self._stack.currentWidget() == self._annotations_view:
            self._set_view_mode(self._view_mode)
        self._query = LibraryQuery()
        self._query.book_ids = set(book_ids)
        self._reload_books()

    # ── Collections & Series ──────────────────────────────────────────────────

    def _on_create_collection(self) -> None:
        name, ok = QInputDialog.getText(self, "New Collection", "Collection name:")
        if ok and name.strip():
            cid = self._repo.create_collection(name.strip(), kind="manual")
            self._refresh_sidebar_counts()
            self.statusBar().showMessage(f"Created collection '{name.strip()}'.", 3000)

    def _on_books_dropped_on_collection(self, col_id: int, book_ids: list[int]) -> None:
        self._repo.add_books_to_collection(col_id, book_ids)
        self._refresh_sidebar_counts()
        self.statusBar().showMessage(f"Added {len(book_ids)} book(s) to collection.", 3000)

    def _on_manage_collection(self, action: str, col_id: int) -> None:
        if action == "rename":
            name, ok = QInputDialog.getText(self, "Rename Collection", "New name:")
            if ok and name.strip():
                self._repo.rename_collection(col_id, name.strip())
                self._refresh_sidebar_counts()
        elif action == "delete":
            reply = QMessageBox.question(
                self, "Delete Collection",
                "Delete this collection?\nBooks inside it will NOT be removed.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._repo.delete_collection(col_id)
                self._refresh_sidebar_counts()
                self._reload_books()

    def _on_save_smart_collection(self) -> None:
        name, ok = QInputDialog.getText(self, "Save as Smart Collection", "Smart Collection Name:")
        if ok and name.strip():
            query_dict = self._query.to_dict()
            self._repo.create_collection(name.strip(), kind="smart", smart_query=json.dumps(query_dict))
            self._refresh_sidebar_counts()
            self.statusBar().showMessage(f"Saved smart collection '{name.strip()}'.", 3000)

    # ── Duplicates Resolution ─────────────────────────────────────────────────

    def _on_find_duplicates(self) -> None:
        dlg = DuplicatesDialog(self._db, self)
        dlg.resolved.connect(self._reload_books)
        dlg.exec()

    # ── Online Metadata Lookups ───────────────────────────────────────────────

    def _on_lookup_single(self, book_id: int) -> None:
        dlg = LookupReviewDialog([book_id], self._db, self)
        dlg.applied.connect(lambda bid: self._reload_books())
        dlg.exec()

    def _on_lookup_selected(self) -> None:
        ids = self._selected_book_ids()
        if not ids:
            QMessageBox.information(self, "No Selection", "Select one or more books first.")
            return

        if len(ids) == 1:
            self._on_lookup_single(ids[0])
            return

        # Bulk run via JobManager
        self._undo_stack.clear()
        job = OnlineLookupJob(book_ids=ids, scan_pdf_isbns=True, fill_mode="fill_only")
        self._job_manager.submit(job)

    def _on_lookup_incomplete(self) -> None:
        books = self._repo.query_books(LibraryQuery(incomplete=True))
        ids = [b.id for b in books]
        if not ids:
            QMessageBox.information(self, "Metadata Complete", "No books found with incomplete metadata.")
            return

        reply = QMessageBox.question(
            self, "Bulk Metadata Lookup",
            f"Start online lookup for {len(ids)} book(s) with incomplete metadata?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._undo_stack.clear()
            job = OnlineLookupJob(book_ids=ids, scan_pdf_isbns=True, fill_mode="fill_only")
            self._job_manager.submit(job)

    def _on_open_review_queue(self) -> None:
        books = self._repo.query_books(LibraryQuery(lookup_status="review"))
        ids = [b.id for b in books]
        if not ids:
            QMessageBox.information(self, "Review Queue", "The review queue is currently empty.")
            return
        dlg = LookupReviewDialog(ids, self._db, self)
        dlg.applied.connect(lambda bid: self._reload_books())
        dlg.exec()

    def _on_undo_metadata_batch(self) -> None:
        conn = self._db.new_connection()
        try:
            # Find recent batch IDs
            rows = conn.execute(
                "SELECT DISTINCT batch_id, created_at FROM metadata_history ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
            if not rows:
                QMessageBox.information(self, "Undo Lookup", "No lookup history found to undo.")
                return

            batches = [f"{r[0]} ({r[1]})" for r in rows]
            item, ok = QInputDialog.getItem(self, "Undo Lookup Batch", "Select batch to undo:", batches, 0, False)
            if ok and item:
                chosen_batch_id = item.split()[0]
                undone_count = undo_batch(conn, chosen_batch_id)
                self._reload_books()
                self._refresh_sidebar_counts()
                QMessageBox.information(self, "Undo Complete", f"Restored metadata for {undone_count} book(s).")
        finally:
            conn.close()

    # ── View Mode & Thumbnails ────────────────────────────────────────────────

    def _on_show_annotations_view(self) -> None:
        self._stack.setCurrentWidget(self._annotations_view)
        self._btn_grid_view.setChecked(False)
        self._btn_list_view.setChecked(False)
        self._thumb_slider.setEnabled(False)
        self._annotations_view.reload()

    def _set_view_mode(self, mode: str) -> None:
        self._view_mode = mode
        if mode == "grid":
            self._stack.setCurrentIndex(0)
            self._btn_grid_view.setChecked(True)
            self._btn_list_view.setChecked(False)
            self._thumb_slider.setEnabled(True)
        else:
            self._stack.setCurrentIndex(1)
            self._btn_grid_view.setChecked(False)
            self._btn_list_view.setChecked(True)
            self._thumb_slider.setEnabled(False)

    def _on_thumb_size_changed(self, val: int) -> None:
        self._grid_view.set_thumb_size(val)

    def _toggle_sidebar(self) -> None:
        self._sidebar.setVisible(not self._sidebar.isVisible())

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _set_theme(self, theme_key: str) -> None:
        apply_theme(theme_key)
        QSettings(_ORG, _APP).setValue(THEME_KEY, theme_key)
        self._grid_view.viewport().update()
        self._table_view.viewport().update()
        if self._details:
            self._details.update()

    # ── Selection & Details ───────────────────────────────────────────────────

    def _on_selection_changed(self, selected: QItemSelection, deselected: QItemSelection) -> None:
        selected_ids = self._selected_book_ids()
        if len(selected_ids) == 1:
            self._details.display(selected_ids[0])
        else:
            self._details.display(None)

    # ── Book Actions & Status ─────────────────────────────────────────────────

    def _set_selected_status(self, status: str | None) -> None:
        ids = self._selected_book_ids()
        if not ids:
            return
        old_map: dict[int, str | None] = {}
        for bid in ids:
            b = self._model.book_by_id(bid)
            old_map[bid] = b.status if b else None

        cmd = SetStatusCommand(
            repo=self._repo,
            book_ids=ids,
            new_status=status,
            old_statuses=old_map,
            callback=self._on_command_executed,
        )
        self._undo_stack.push(cmd)

    def _on_details_status_changed(self, book_id: int, status: str | None) -> None:
        b = self._model.book_by_id(book_id)
        old_status = b.status if b else None
        cmd = SetStatusCommand(
            repo=self._repo,
            book_ids=[book_id],
            new_status=status,
            old_statuses={book_id: old_status},
            callback=self._on_command_executed,
        )
        self._undo_stack.push(cmd)

    def _on_details_rating_changed(self, book_id: int, rating: int | None) -> None:
        b = self._model.book_by_id(book_id)
        old_rating = b.rating if b else None
        cmd = SetRatingCommand(
            repo=self._repo,
            book_id=book_id,
            new_rating=rating,
            old_rating=old_rating,
            callback=self._on_command_executed,
        )
        self._undo_stack.push(cmd)

    def _on_details_notes_saved(self, book_id: int, notes: str) -> None:
        self._repo.set_notes(book_id, notes)

    def _on_command_executed(self) -> None:
        self._reload_books()
        self._refresh_sidebar_counts()
        selected_ids = self._selected_book_ids()
        if len(selected_ids) == 1:
            self._details.display(selected_ids[0])

    # ── Opening Books ─────────────────────────────────────────────────────────

    def _on_book_double_clicked(self, index: QModelIndex) -> None:
        book = self._model.book_at(index)
        if book:
            self._open_book(book.id)

    def _on_open_book_requested(self, book_id: int, reader_key: str | None) -> None:
        self._open_book(book_id, reader_key)

    def _open_book(self, book_id: int, reader_key: str | None = None) -> None:
        detail = self._repo.get_book_detail(book_id)
        if not detail:
            return
        if detail.source in ("gdrive", "drive"):
            from booklib.drive.download import ensure_local
            from booklib.drive.auth import TokenStore, get_credentials
            from booklib.drive.client import DriveClient
            from booklib.ui.download_dialog import DownloadProgressDialog

            accounts = self._repo.list_drive_accounts()
            if not accounts:
                QMessageBox.warning(self, "Drive Account Required", "Please connect your Google Drive account first.")
                return

            account = accounts[0]
            try:
                creds = get_credentials(account["email"], TokenStore())
                client = DriveClient(creds)
            except Exception as exc:
                QMessageBox.warning(self, "Authentication Error", f"Drive sign-in needed:\n{exc}")
                return

            dlg = DownloadProgressDialog(detail.title or "Book", detail.size_bytes or 0, parent=self)

            def progress_cb(cur: int, tot: int) -> None:
                dlg.update_progress(cur, tot)
                QApplication.processEvents()

            def cancel_check() -> bool:
                return dlg.is_cancelled()

            dlg.show()
            try:
                cached_file = ensure_local(
                    self._repo, client, book_id,
                    progress_callback=progress_cb, cancel_check=cancel_check,
                )
                dlg.close()
                path = str(cached_file)
            except Exception as exc:
                dlg.close()
                QMessageBox.warning(self, "Download Failed", f"Could not download book:\n{exc}")
                return
        else:
            path = detail.path
            if not Path(path).exists():
                self._offer_remove_missing_book(detail)
                return

        success = False
        if reader_key == "chooser":
            success = open_with_os_dialog(path)
        elif reader_key is not None:
            readers = get_registry().readers_for(detail.format)
            chosen_reader = next((r for r in readers if r.key == reader_key), None)
            if chosen_reader and (chosen_reader.key == "builtin" or Path(chosen_reader.exe).exists()):
                if chosen_reader.key == "builtin":
                    from booklib.reader.manager import get_reader_manager
                    success = get_reader_manager(lambda: self._conn).open_book(book_id)
                else:
                    success = launch(chosen_reader, path)
            else:
                success = open_file(path)
        else:
            default_key = self._repo.get_format_default(detail.format)
            if default_key and default_key != "system":
                readers = get_registry().readers_for(detail.format)
                chosen_reader = next((r for r in readers if r.key == default_key), None)
                if chosen_reader and (chosen_reader.key == "builtin" or Path(chosen_reader.exe).exists()):
                    if chosen_reader.key == "builtin":
                        from booklib.reader.manager import get_reader_manager
                        success = get_reader_manager(lambda: self._conn).open_book(book_id)
                    else:
                        success = launch(chosen_reader, path)
                else:
                    success = open_file(path)
            else:
                readers = get_registry().readers_for(detail.format)
                builtin = next((r for r in readers if r.key == "builtin"), None)
                if builtin:
                    from booklib.reader.manager import get_reader_manager
                    success = get_reader_manager(lambda: self._conn).open_book(book_id)
                else:
                    success = open_file(path)

        if success:
            self._repo.record_open(book_id)
            if self._auto_mark_reading and (detail.status is None or detail.status == "want"):
                self._repo.set_status([book_id], "reading")
                self.statusBar().showMessage("Marked as Reading (Ctrl+Z to undo)", 4000)
            self._reload_books()
            self._refresh_sidebar_counts()
            if self._details:
                self._details.display(book_id)

    def _offer_remove_missing_book(self, book: Any) -> None:
        reply = QMessageBox.question(
            self, "File not found",
            f"The file no longer exists:\n{book.path}\n\nRemove it from the library?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._repo.mark_missing([book.path])
            self._repo.remove_missing()
            self._reload_books()
            self._refresh_sidebar_counts()
            self._details.display(None)

    # ── Metadata Editing ──────────────────────────────────────────────────────

    def _on_edit_selected(self) -> None:
        ids = self._selected_book_ids()
        if len(ids) == 1:
            self._on_edit_book(ids[0])
        elif len(ids) > 1:
            self._on_bulk_edit_books(ids)

    def _on_edit_book(self, book_id: int) -> None:
        detail = self._repo.get_book_detail(book_id)
        if not detail:
            return
        dlg = EditDialog(detail, parent=self)
        if dlg.exec() == EditDialog.Accepted:
            changes = dlg.get_changes()
            if not changes:
                return
            old_snapshot = {k: getattr(detail, k) for k in changes.keys()}
            cmd = EditMetadataCommand(
                repo=self._repo,
                book_ids=[book_id],
                new_fields=changes,
                old_snapshots={book_id: old_snapshot},
                callback=self._on_command_executed,
            )
            self._undo_stack.push(cmd)

    def _on_bulk_edit_books(self, book_ids: list[int]) -> None:
        dlg = BulkEditDialog(len(book_ids), parent=self)
        if dlg.exec() == BulkEditDialog.Accepted:
            changes = dlg.get_changes()
            if not changes:
                return
            old_snapshots = {}
            for bid in book_ids:
                d = self._repo.get_book_detail(bid)
                if d:
                    old_snapshots[bid] = {k: getattr(d, k) for k in changes.keys()}
            cmd = EditMetadataCommand(
                repo=self._repo,
                book_ids=book_ids,
                new_fields=changes,
                old_snapshots=old_snapshots,
                callback=self._on_command_executed,
            )
            self._undo_stack.push(cmd)

    def _on_revert_selected(self) -> None:
        ids = self._selected_book_ids()
        if not ids:
            return
        if QMessageBox.question(
            self, "Revert Metadata",
            f"Revert {len(ids)} book(s) to metadata from file?\nManual edits will be lost.",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        for bid in ids:
            d = self._repo.get_book_detail(bid)
            if not d:
                continue
            try:
                meta = extract_metadata(d.path, d.format)
                self._repo.revert_book(bid, {
                    "title": meta.title, "author": meta.author, "publisher": meta.publisher,
                    "year": meta.year, "isbn": meta.isbn, "pages": meta.pages,
                    "genre": meta.genre, "language": meta.language,
                })
            except Exception as e:
                logger.error("Failed to revert metadata for %s: %s", d.path, e)

        self._reload_books()
        if len(ids) == 1:
            self._details.display(ids[0])

    # ── Context Menu ──────────────────────────────────────────────────────────

    def _on_context_menu(self, pos) -> None:
        view = self._grid_view if self._view_mode == "grid" else self._table_view
        index = view.indexAt(pos)
        if not index.isValid():
            return

        books = self._selected_book_rows()
        if not books:
            b = self._model.book_at(index)
            if b:
                books = [b]

        if not books:
            return

        menu = QMenu(self)

        if len(books) == 1:
            book = books[0]
            act_open = menu.addAction(self.style().standardIcon(QStyle.SP_ArrowRight), "Open (Default)")
            act_open.triggered.connect(lambda: self._open_book(book.id))

            open_with_menu = menu.addMenu("Open with…")
            readers = get_registry().readers_for(book.format)
            for r in readers:
                open_with_menu.addAction(r.name, lambda rk=r.key: self._open_book(book.id, rk))
            open_with_menu.addSeparator()
            open_with_menu.addAction("Choose another app…", lambda: self._open_book(book.id, "chooser"))
            menu.addSeparator()

        # Mark as submenu
        mark_menu = menu.addMenu("Mark as…")
        mark_menu.addAction("Want to Read", lambda: self._set_selected_status("want"))
        mark_menu.addAction("Reading", lambda: self._set_selected_status("reading"))
        mark_menu.addAction("Read", lambda: self._set_selected_status("read"))
        mark_menu.addSeparator()
        mark_menu.addAction("Clear Status", lambda: self._set_selected_status(None))

        # Add to Collection
        cols = self._repo.list_collections()
        if cols:
            col_menu = menu.addMenu("Add to Collection")
            for c in cols:
                cid = c["id"]
                cname = c["name"]
                col_menu.addAction(cname, lambda col_id=cid: self._on_books_dropped_on_collection(col_id, [b.id for b in books]))

        # Tags submenu
        tag_menu = menu.addMenu("Tags")
        tag_menu.addAction("Add Tag…", lambda: self._on_bulk_add_tag([b.id for b in books]))
        tag_menu.addAction("Remove Tag…", lambda: self._on_bulk_remove_tag([b.id for b in books]))

        menu.addSeparator()
        act_lookup = menu.addAction(self.style().standardIcon(QStyle.SP_FileDialogInfoView), "Fetch Online Metadata…")
        act_lookup.triggered.connect(self._on_lookup_selected)

        menu.addSeparator()
        act_edit = menu.addAction(
            "Edit Metadata…" if len(books) == 1 else f"Bulk Edit ({len(books)} books)…"
        )
        act_edit.triggered.connect(self._on_edit_selected)

        act_revert = menu.addAction("Revert to File Metadata")
        act_revert.triggered.connect(self._on_revert_selected)

        if len(books) == 1:
            menu.addSeparator()
            b0 = books[0]
            if b0.source == "gdrive":
                if b0.is_cached and b0.cached_path:
                    act_show = menu.addAction(self.style().standardIcon(QStyle.SP_DirIcon), "Show Downloaded File")
                    act_show.triggered.connect(lambda: show_in_folder(b0.cached_path))
                if b0.drive_web_link:
                    from PySide6.QtGui import QDesktopServices
                    from PySide6.QtCore import QUrl
                    act_drive = menu.addAction(self.style().standardIcon(QStyle.SP_DriveNetIcon), "Open in Google Drive")
                    act_drive.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(b0.drive_web_link)))
            else:
                act_show = menu.addAction(self.style().standardIcon(QStyle.SP_DirIcon), "Show in Folder")
                act_show.triggered.connect(lambda: show_in_folder(b0.path))

        menu.addSeparator()
        rec_menu = menu.addMenu("Suggestions")
        rec_menu.addAction("Not interested in this book", lambda: self._on_recommendation_feedback(books, "not_interested"))
        rec_menu.addAction("Hide from suggestions", lambda: self._on_recommendation_feedback(books, "hide"))

        menu.addSeparator()
        act_remove = menu.addAction(self.style().standardIcon(QStyle.SP_TrashIcon), "Remove Missing Files")
        act_remove.triggered.connect(self._on_remove_missing)

        menu.exec(view.viewport().mapToGlobal(pos))

    def _on_bulk_add_tag(self, book_ids: list[int]) -> None:
        tag_name, ok = QInputDialog.getText(self, "Add Tag", "Tag name:")
        if ok and tag_name.strip():
            self._repo.add_tag_to_books(tag_name.strip(), book_ids)
            self._reload_books()
            self._refresh_sidebar_counts()

    def _on_bulk_remove_tag(self, book_ids: list[int]) -> None:
        tag_name, ok = QInputDialog.getText(self, "Remove Tag", "Tag name:")
        if ok and tag_name.strip():
            self._repo.remove_tag_from_books(tag_name.strip(), book_ids)
            self._reload_books()
            self._refresh_sidebar_counts()

    # ── Folder & Scanner Management ───────────────────────────────────────────

    def _on_add_folder(self) -> None:
        settings = QSettings(_ORG, _APP)
        last = settings.value("last_folder_pick", "")
        path = QFileDialog.getExistingDirectory(self, "Add Library Folder", last)
        if not path:
            return
        settings.setValue("last_folder_pick", path)
        folder_id = self._repo.add_folder(path)
        self._start_scan([{"id": folder_id, "path": path}])

    def _on_rescan(self) -> None:
        folders = self._repo.list_folders()
        drive_accounts = self._repo.list_drive_accounts()
        local_folders = [
            f for f in folders
            if f.get("kind", "local") != "drive" and not str(f.get("path", "")).startswith("gdrive://")
        ]

        if not local_folders and not drive_accounts:
            QMessageBox.information(self, "No Folders", "Add a library folder or link Google Drive first.")
            return

        if local_folders:
            self._start_scan(local_folders)

        if drive_accounts:
            self._on_sync_drive()

    def _on_folders_dialog(self) -> None:
        dlg = FoldersDialog(self._repo.list_folders(), self)
        dlg.folder_added.connect(self._add_folder_from_dialog)
        dlg.drive_folder_requested.connect(self._on_add_drive_folder)
        dlg.folder_removed.connect(self._remove_folder)
        dlg.watch_toggled.connect(self._on_folder_watch_toggled)
        dlg.auto_lookup_toggled.connect(self._on_folder_auto_lookup_toggled)
        dlg.exec()

    # ── Google Drive Integration ──────────────────────────────────────────────

    def _on_add_drive_folder(self) -> None:
        from booklib.ui.drive_folder_picker import DriveFolderPicker, DriveFolderSelection
        from booklib.drive.indexer import index_drive_folder
        from booklib.drive.auth import TokenStore, get_credentials
        from booklib.drive.client import DriveClient

        accounts = self._repo.list_drive_accounts()
        if not accounts:
            from booklib.ui.drive_connect_dialog import DriveConnectDialog
            conn_dlg = DriveConnectDialog(self._repo, parent=self)
            if not conn_dlg.exec():
                return

        picker = DriveFolderPicker(self._repo, parent=self)

        def on_selected(sel: DriveFolderSelection):
            fid = self._repo.add_drive_folder(
                account_id=sel.account_id,
                drive_folder_id=sel.folder_id,
                folder_name=sel.folder_name,
                include_subfolders=sel.include_subfolders,
                sync_auto=sel.sync_auto,
            )
            accounts_dict = {a["id"]: a for a in self._repo.list_drive_accounts()}
            acc = accounts_dict.get(sel.account_id)
            if acc:
                creds = get_credentials(acc["email"], TokenStore())
                client = DriveClient(creds)
                self.statusBar().showMessage(f"Indexing Drive folder '{sel.folder_name}'...", 5000)
                try:
                    stats = index_drive_folder(
                        self._repo, client, sel.account_id, fid, sel.folder_id,
                        folder_path=sel.folder_name,
                        include_subfolders=sel.include_subfolders,
                        create_collections=sel.create_collections,
                    )
                    self._reload_books()
                    self._refresh_sidebar_counts()
                    QMessageBox.information(
                        self, "Indexing Complete",
                        f"Indexed Drive folder '{sel.folder_name}':\n"
                        f"• Books indexed: {stats.books_indexed}\n"
                        f"• Subfolders: {stats.folders_indexed}\n"
                        f"• Google Docs skipped: {stats.google_docs_skipped}"
                    )
                except Exception as exc:
                    logger.exception("Error indexing drive folder")
                    QMessageBox.critical(self, "Indexing Error", f"Failed to index Drive folder:\n{exc}")

        picker.folder_selected.connect(on_selected)
        picker.exec()

    def _on_sync_drive(self) -> None:
        from booklib.drive.sync import sync_drive_changes
        from booklib.drive.auth import TokenStore, get_credentials
        from booklib.drive.client import DriveClient

        accounts = self._repo.list_drive_accounts()
        if not accounts:
            return

        total_upserted = 0
        total_missing = 0
        self.statusBar().showMessage("Syncing Google Drive changes...", 5000)
        for acc in accounts:
            try:
                creds = get_credentials(acc["email"], TokenStore())
                client = DriveClient(creds)
                res = sync_drive_changes(self._repo, client, acc["id"])
                total_upserted += res.books_upserted
                total_missing += res.books_marked_missing
            except Exception as exc:
                logger.exception("Sync failed for %s", acc["email"])

        self._reload_books()
        self._refresh_sidebar_counts()
        self.statusBar().showMessage(
            f"Drive sync complete: {total_upserted} updated, {total_missing} marked missing.",
            4000
        )

    def _on_drive_settings(self) -> None:
        from booklib.ui.drive_settings_page import DriveSettingsPage
        dlg = QDialog(self)
        dlg.setWindowTitle("Google Drive & Storage Settings")
        dlg.resize(600, 520)
        l = QVBoxLayout(dlg)
        page = DriveSettingsPage(self._repo, parent=dlg)
        page.accounts_changed.connect(lambda: (self._reload_books(), self._refresh_sidebar_counts()))
        l.addWidget(page)
        dlg.exec()

    def _on_backup_dialog(self) -> None:
        from booklib.ui.backup_dialog import BackupDialog
        dlg = BackupDialog(self._repo, parent=self)
        dlg.exec()

    def _on_keep_offline_toggled(self, book_id: int, checked: bool) -> None:
        from booklib.drive.cache import set_keep_offline
        set_keep_offline(self._repo, book_id, checked)
        self._reload_books()

    def _on_remove_download_requested(self, book_id: int) -> None:
        from booklib.drive.cache import evict_cached_book
        evict_cached_book(self._repo, book_id)
        self._reload_books()
        if self._details:
            self._details.display(book_id)

    def _check_disk_space(self) -> None:
        import shutil
        from booklib.config import DRIVE_CACHE_DIR
        try:
            free = shutil.disk_usage(DRIVE_CACHE_DIR).free
            min_free = 2 * 1024 * 1024 * 1024  # 2 GB
            if free < min_free:
                gb_free = free / (1024 * 1024 * 1024)
                self.statusBar().showMessage(
                    f"Low disk space: {gb_free:.1f} GB free on cache drive.",
                    10000
                )
        except Exception:
            pass

    def _startup_checks(self) -> None:
        self._check_disk_space()
        try:
            from booklib.storage.scheduler import run_startup_consistency_check
            run_startup_consistency_check(self._repo)
        except Exception:
            pass

    def _add_folder_from_dialog(self, path: str) -> None:
        folder_id = self._repo.add_folder(path)
        self._start_scan([{"id": folder_id, "path": path}])

    def _remove_folder(self, folder_id: int) -> None:
        self._repo.remove_folder(folder_id)
        self._reload_books()
        self._refresh_sidebar_counts()
        self._details.display(None)

    def _on_folder_watch_toggled(self, folder_id: int, watch: bool) -> None:
        self._repo.set_folder_watch(folder_id, watch)
        folder = next((f for f in self._repo.list_folders() if f["id"] == folder_id), None)
        if folder:
            if watch:
                self._watcher.add_folder(folder["path"])
            else:
                self._watcher.remove_folder(folder["path"])

    def _on_folder_auto_lookup_toggled(self, folder_id: int, auto_lookup: bool) -> None:
        self._repo.set_folder_auto_lookup(folder_id, auto_lookup)

    def _on_watched_folder_batch(self, events: list) -> None:
        logger.info("Watched folders quiet period elapsed; starting rescan for %d events", len(events))
        folders = self._repo.list_folders()
        watched = [f for f in folders if f.get("watch")]
        if watched:
            self._start_scan(watched)

    def _on_remove_missing(self) -> None:
        removed = self._repo.remove_missing()
        self._reload_books()
        self._refresh_sidebar_counts()
        self._details.display(None)
        QMessageBox.information(
            self, "Done",
            f"Removed {removed} missing entr{'ies' if removed != 1 else 'y'}."
        )

    def _on_readers_dialog(self) -> None:
        dlg = ReadersDialog(self._repo, self)
        dlg.exec()

    def _on_auto_mark_toggled(self, checked: bool) -> None:
        self._auto_mark_reading = checked

    def _on_rebuild_fts(self) -> None:
        self._repo.rebuild_fts()
        QMessageBox.information(self, "Search Index", "Full-text search index rebuilt.")

    def _start_scan(self, folders: list[dict]) -> None:
        self._undo_stack.clear()
        scan_job = ScanJob(folders, parent=self)
        self._job_manager.submit(scan_job)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _restore_settings(self) -> None:
        settings = QSettings(_ORG, _APP)
        geo = settings.value("window/geometry")
        if geo:
            self.restoreGeometry(geo)
        state = settings.value("window/state")
        if state:
            self.restoreState(state)
        splitter = settings.value("splitter/state")
        if splitter:
            self._splitter.restoreState(splitter)

        view_mode = settings.value("view_mode", "grid")
        self._set_view_mode(view_mode)

        thumb_size = settings.value("thumb_size", 120, type=int)
        self._thumb_slider.setValue(thumb_size)
        self._grid_view.set_thumb_size(thumb_size)

        auto_mark = settings.value("auto_mark_reading", True, type=bool)
        self._auto_mark_reading = auto_mark
        self._act_auto_mark.setChecked(auto_mark)

        header_state = settings.value("table/header_state")
        if header_state:
            self._table_view.horizontalHeader().restoreState(header_state)

        theme_key = settings.value(THEME_KEY, "system")
        apply_theme(theme_key)
        for act in self._theme_group.actions():
            if act.text().lower().startswith(theme_key):
                act.setChecked(True)

    def _save_settings(self) -> None:
        settings = QSettings(_ORG, _APP)
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("window/state", self.saveState())
        settings.setValue("splitter/state", self._splitter.saveState())
        settings.setValue("view_mode", self._view_mode)
        settings.setValue("thumb_size", self._thumb_slider.value())
        settings.setValue("auto_mark_reading", self._auto_mark_reading)
        settings.setValue("table/header_state", self._table_view.horizontalHeader().saveState())

    def closeEvent(self, event) -> None:
        self._watcher.stop()
        self._job_manager.cancel_current()
        self._save_settings()
        super().closeEvent(event)

    # ── V5: Add Files ──────────────────────────────────────────────────────────

    def _on_add_files(self) -> None:
        """Open a file picker to add individual book files to the library."""
        from booklib.config import SUPPORTED_EXTENSIONS
        ext_filter = "eBooks (" + " ".join(f"*.{e}" for e in sorted(SUPPORTED_EXTENSIONS)) + ")"
        settings = QSettings(_ORG, _APP)
        last_dir = settings.value("last_file_pick", "")
        paths, _ = __import__("PySide6.QtWidgets", fromlist=["QFileDialog"]).QFileDialog.getOpenFileNames(
            self, "Add Book Files", last_dir, ext_filter
        )
        if paths:
            settings.setValue("last_file_pick", str(Path(paths[0]).parent))
            self._add_loose_files(paths)

    def _add_loose_files(self, paths: list[str]) -> None:
        """Add a list of file paths to the library (copies loose files into library folder)."""
        import shutil
        import uuid
        from pathlib import Path as _Path
        from booklib.duplicates.hashing import compute_quick_hash
        from booklib.storage.guard import guard_add_files
        from booklib.storage.tempfiles import TempFileRegistry

        local_folders = [f for f in self._repo.list_folders() if f.get("source", "local") == "local"]
        if not local_folders:
            QMessageBox.information(
                self, "No Library Folder",
                "Please add a library folder first (File → Add Folder…) before adding individual files."
            )
            return

        target_folder = local_folders[0]
        dest_folder_path = _Path(target_folder["path"])
        dest_folder_path.mkdir(parents=True, exist_ok=True)

        added = 0
        skipped = 0
        errors: list[str] = []

        files_to_copy: list[_Path] = []
        for p_str in paths:
            p = _Path(p_str)
            if not p.exists() or not p.is_file():
                errors.append(f"Not found: {p.name}")
                continue

            # Duplicate check by size and quick_hash
            try:
                size = p.stat().st_size
                qhash = compute_quick_hash(p, size)
                if qhash:
                    dup = self._conn.execute(
                        "SELECT id, title FROM books WHERE size_bytes = ? AND quick_hash = ? AND is_missing = 0",
                        (size, qhash)
                    ).fetchone()
                    if dup:
                        skipped += 1
                        continue
            except Exception as exc:
                logger.debug("Quick hash check error: %s", exc)

            # Check if file is already inside any library folder
            inside_folder_id = None
            for f in local_folders:
                try:
                    p.relative_to(f["path"])
                    inside_folder_id = f["id"]
                    break
                except ValueError:
                    pass

            if inside_folder_id is not None:
                # File is already inside an existing library folder, just index it
                try:
                    from booklib.metadata.extract import extract_metadata
                    meta = extract_metadata(p)
                    self._repo.add_book(folder_id=inside_folder_id, path=str(p), metadata=meta)
                    added += 1
                except Exception as exc:
                    errors.append(f"{p.name}: {exc}")
            else:
                # File is outside library folders: copy into target_folder
                try:
                    guard_add_files([p], dest_folder_path, self._conn)

                    # Determine collision-free final target
                    final_name = p.name
                    target_file = dest_folder_path / final_name
                    counter = 2
                    while target_file.exists():
                        target_file = dest_folder_path / f"{p.stem} ({counter}){p.suffix}"
                        counter += 1

                    tmp_name = f"{target_file.name}.tmp-{uuid.uuid4()}"
                    tmp_file = dest_folder_path / tmp_name

                    reg = TempFileRegistry(self._conn)
                    reg.register(tmp_file, "copy")
                    try:
                        shutil.copy2(str(p), str(tmp_file))
                        tmp_file.replace(target_file)
                    finally:
                        reg.release(tmp_file)
                        if tmp_file.exists():
                            try:
                                tmp_file.unlink()
                            except OSError:
                                pass

                    if hasattr(self, "_watcher"):
                        self._watcher.add_own_change(target_file)

                    from booklib.metadata.extract import extract_metadata
                    meta = extract_metadata(target_file)
                    self._repo.add_book(folder_id=target_folder["id"], path=str(target_file), metadata=meta)
                    added += 1
                except Exception as exc:
                    errors.append(f"{p.name}: {exc}")

        if added:
            self._repo.commit()
            self._reload_books()

        msg = f"Added {added} file(s)."
        if skipped:
            msg += f" {skipped} duplicate(s) skipped."
        if errors:
            msg += f"\n{len(errors)} error(s):\n" + "\n".join(errors[:5])
        QMessageBox.information(self, "Add Files", msg)

    # ── Drag and Drop ──────────────────────────────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        """Accept dropped files and folders onto the main window."""
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            return
        event.acceptProposedAction()

        from booklib.config import SUPPORTED_EXTENSIONS
        file_paths: list[str] = []
        folder_paths: list[str] = []

        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            p = Path(local)
            if p.is_dir():
                folder_paths.append(str(p))
            elif p.is_file() and p.suffix.lstrip(".").lower() in SUPPORTED_EXTENSIONS:
                file_paths.append(str(p))

        if folder_paths:
            for folder in folder_paths:
                folder_id = self._repo.add_folder(folder)
                self._start_scan([{"id": folder_id, "path": folder}])
        if file_paths:
            self._add_loose_files(file_paths)

    # ── V5: Rename Files ───────────────────────────────────────────────────────

    def _on_rename_files(self) -> None:
        """Open the Rename Files dialog with a pattern builder and preview."""
        from booklib.ui.rename_wizard import RenameWizard
        wizard = RenameWizard(self._repo, self._conn, self)
        wizard.exec()
        self._reload_books()

    # ── V5: Convert Format ─────────────────────────────────────────────────────

    def _on_convert_books(self) -> None:
        """Open the format conversion dialog (requires Calibre)."""
        from booklib.ui.convert_dialog import ConvertDialog
        book_ids = self._selected_book_ids()
        dlg = ConvertDialog(book_ids, self._repo, self._conn, self)
        dlg.exec()

    # ── V5: Export ─────────────────────────────────────────────────────────────

    def _on_export(self) -> None:
        """Export library to CSV or JSON."""
        from PySide6.QtWidgets import QFileDialog
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export Library",
            "library-export",
            "JSON (*.json);;CSV (*.csv)"
        )
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                from booklib.porting.export_csv import export_csv
                count = export_csv(self._conn, Path(path))
            else:
                from booklib.porting.export_json import export_json
                count = export_json(self._conn, Path(path))
            QMessageBox.information(self, "Export Complete", f"Exported {count} book(s) to:\n{path}")
        except Exception as exc:
            logger.error("Export failed: %s", exc)
            QMessageBox.critical(self, "Export Error", str(exc))

    # ── V5: Import ─────────────────────────────────────────────────────────────

    def _on_import(self) -> None:
        """Import a CSV or JSON file into the library."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Library",
            "",
            "Supported files (*.json *.csv);;JSON (*.json);;CSV (*.csv)"
        )
        if not path:
            return
        try:
            from booklib.porting.import_reader import detect_and_parse
            from booklib.porting.matcher import match_rows
            from booklib.porting.apply import apply_import
            from booklib.porting.mapping import apply_mapping, PRESETS

            result = detect_and_parse(Path(path))
            if result.error:
                QMessageBox.warning(self, "Import Error", result.error)
                return

            # For CSV: apply the appropriate mapping
            rows = result.rows
            if result.kind == "goodreads_csv":
                rows = [apply_mapping(r, PRESETS["goodreads"]) for r in rows]
            elif result.kind == "booklib_csv":
                rows = [apply_mapping(r, PRESETS["booklib"]) for r in rows]

            matches = match_rows(self._conn, rows)
            matched = sum(1 for m in matches if m.status == "matched")
            ambiguous = sum(1 for m in matches if m.status == "ambiguous")
            unmatched = sum(1 for m in matches if m.status == "unmatched")

            reply = QMessageBox.question(
                self, "Import Preview",
                f"Found {len(rows)} row(s):\n"
                f"  • {matched} matched to existing books\n"
                f"  • {ambiguous} ambiguous (will be skipped)\n"
                f"  • {unmatched} unmatched (no book found)\n\n"
                "Apply import to matched books?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

            summary = apply_import(self._conn, matches, result.kind)
            self._reload_books()
            QMessageBox.information(
                self, "Import Complete",
                f"Updated {summary['changed']} book(s) ({summary['fields_changed']} field(s) changed)."
            )
        except Exception as exc:
            logger.error("Import failed: %s", exc)
            QMessageBox.critical(self, "Import Error", str(exc))

    # ── V5: Statistics ─────────────────────────────────────────────────────────

    def _on_show_statistics(self) -> None:
        """Show the Statistics dashboard in a dialog."""
        from booklib.ui.stats_view import StatsView
        dlg = QDialog(self)
        dlg.setWindowTitle("Statistics — Ratnodadhi")
        dlg.setMinimumSize(900, 600)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)
        view = StatsView(self._conn, dlg)
        view.drill_down.connect(lambda f: (dlg.close(), self._apply_drill_down(f)))
        layout.addWidget(view)
        dlg.exec()

    def _apply_drill_down(self, filter_dict: dict) -> None:
        """Apply a filter from a statistics drill-down click."""
        if "author" in filter_dict:
            self._query.author_filter = filter_dict["author"]
        if "genre" in filter_dict:
            self._query.genre = filter_dict["genre"]
        self._reload_books()

    # ── V5: Reading Goals ──────────────────────────────────────────────────────

    def _on_reading_goals(self) -> None:
        """Open a simple reading goals editor dialog."""
        from booklib.stats.goals import list_goals, upsert_goal, delete_goal, goal_progress
        from datetime import date
        dlg = QDialog(self)
        dlg.setWindowTitle("Reading Goals")
        dlg.setFixedSize(400, 350)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        from PySide6.QtWidgets import QSpinBox, QFormLayout, QGroupBox

        form = QFormLayout()
        year_spin = QSpinBox()
        year_spin.setRange(2000, 2099)
        year_spin.setValue(date.today().year)
        target_spin = QSpinBox()
        target_spin.setRange(1, 9999)
        target_spin.setValue(24)
        form.addRow("Year:", year_spin)
        form.addRow("Books goal:", target_spin)

        set_btn = QPushButton("Set / Update Goal")

        def _set_goal():
            try:
                upsert_goal(self._conn, year_spin.value(), "books", target_spin.value())
                _refresh()
            except Exception as exc:
                QMessageBox.warning(dlg, "Error", str(exc))

        set_btn.clicked.connect(_set_goal)
        layout.addLayout(form)
        layout.addWidget(set_btn)

        status_label = QLabel()
        status_label.setWordWrap(True)
        layout.addWidget(status_label)

        def _refresh():
            goals = list_goals(self._conn)
            lines = []
            for g in goals:
                p = goal_progress(self._conn, g)
                from booklib.stats.goals import pace_text
                pct = int(p.done / g.target * 100) if g.target else 0
                lines.append(
                    f"<b>{g.year} — {g.kind}:</b> {p.done}/{g.target} ({pct}%) — {pace_text(p)}"
                )
            status_label.setText("<br>".join(lines) if lines else "No goals set yet.")

        _refresh()
        layout.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        dlg.exec()

    # ── V5: Library Health ─────────────────────────────────────────────────────

    def _on_library_health(self) -> None:
        """Run library health checks and show results."""
        from booklib.maintenance.health import run_all_checks
        from PySide6.QtWidgets import QTextEdit

        dlg = QDialog(self)
        dlg.setWindowTitle("Library Health")
        dlg.setMinimumSize(540, 400)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)

        running_label = QLabel("Running health checks…")
        layout.addWidget(running_label)
        report_text = QTextEdit()
        report_text.setReadOnly(True)
        layout.addWidget(report_text)

        run_btn = QPushButton("Re-run checks")
        fix_btn = QPushButton("Compact database (VACUUM)")

        def _run():
            running_label.setText("Running…")
            QApplication.processEvents()
            try:
                report = run_all_checks(self._conn)
                running_label.setText(f"Last checked: {report.run_at}")
                lines = []
                for r in report.results:
                    icon = {"ok": "[OK]", "info": "[INFO]", "warning": "[WARN]", "error": "[ERROR]"}.get(r.severity, "[?]")
                    color = {"ok": "green", "info": "steelblue", "warning": "orange", "error": "red"}.get(r.severity, "")
                    lines.append(
                        f'<span style="color:{color}; font-weight:bold;">{icon}</span> '
                        f'<b>{r.check}</b>: {r.count} issue(s)'
                        + (f' — {r.detail}' if r.detail else '')
                    )
                report_text.setHtml("<br>".join(lines))
            except Exception as exc:
                running_label.setText("Error running checks")
                report_text.setPlainText(str(exc))

        run_btn.clicked.connect(_run)
        fix_btn.clicked.connect(self._on_vacuum_db)

        btn_row = QHBoxLayout()
        btn_row.addWidget(run_btn)
        btn_row.addWidget(fix_btn)
        btn_row.addStretch()

        close_btns = QDialogButtonBox(QDialogButtonBox.Close)
        close_btns.rejected.connect(dlg.reject)

        layout.addLayout(btn_row)
        layout.addWidget(close_btns)

        _run()
        dlg.exec()

    def _on_vacuum_db(self) -> None:
        """Compact the database with VACUUM."""
        try:
            self._conn.execute("VACUUM")
            self._conn.commit()
            QMessageBox.information(self, "Compact", "Database compacted successfully.")
        except Exception as exc:
            QMessageBox.warning(self, "Compact Failed", str(exc))

    # ── V5: Fix Reading Dates ──────────────────────────────────────────────────

    def _on_fix_dates(self) -> None:
        """Show undated reads and let the user add finish dates."""
        from booklib.stats.queries import undated_read_books
        undated = undated_read_books(self._conn)
        if not undated:
            QMessageBox.information(self, "Fix Reading Dates",
                                    "All 'Read' books have at least one finish date. Nothing to fix!")
            return

        msg = (
            f"{len(undated)} book(s) are marked as Read but have no finish date recorded:\n\n"
            + "\n".join(f"• {b['title'] or 'Untitled'}" for b in undated[:10])
            + ("\n  …and more" if len(undated) > 10 else "")
            + "\n\nWould you like to set today's date as their finish date?"
        )
        if QMessageBox.question(self, "Fix Reading Dates", msg,
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            from datetime import date
            today = date.today().isoformat()
            for b in undated:
                self._conn.execute(
                    "INSERT INTO reading_log (book_id, finished_on) VALUES (?, ?)",
                    (b["id"], today)
                )
            self._conn.commit()
            QMessageBox.information(self, "Done", f"Added finish date to {len(undated)} book(s).")

    # ── V5: Backup & Storage Dialogs ───────────────────────────────────────────

    def _on_backup_dialog(self) -> None:
        """Open the Backup & Restore dialog."""
        from booklib.ui.backup_dialog import BackupDialog
        dlg = BackupDialog(self._repo, parent=self)
        dlg.exec()

    def _on_drive_settings(self) -> None:
        """Open the Google Drive & Storage settings dialog with tabs."""
        from PySide6.QtWidgets import QTabWidget
        from booklib.ui.drive_settings_page import DriveSettingsPage
        from booklib.ui.storage_page import StoragePage

        dlg = QDialog(self)
        dlg.setWindowTitle("Google Drive & Storage — Ratnodadhi")
        dlg.resize(750, 560)
        from booklib.ui.theme import apply_window_rounding
        apply_window_rounding(dlg)
        layout = QVBoxLayout(dlg)
        tabs = QTabWidget(dlg)

        drive_tab = DriveSettingsPage(self._repo, parent=dlg)
        drive_tab.accounts_changed.connect(lambda: (self._reload_books(), self._refresh_sidebar_counts()))
        tabs.addTab(drive_tab, "Google Drive")

        storage_tab = StoragePage(self._conn, self._repo, parent=dlg)
        tabs.addTab(storage_tab, "Storage & Cache")

        layout.addWidget(tabs)
        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(dlg.reject)
        layout.addWidget(btn_box)

        dlg.exec()

    # ── V5: Command Palette & Shortcuts ────────────────────────────────────────

    def _on_command_palette(self) -> None:
        """Open the Ctrl+K command palette."""
        from booklib.ui.command_palette import CommandPalette
        palette = CommandPalette(self, parent=self)
        palette.action_triggered.connect(self._dispatch_action)
        geo = self.geometry()
        x = geo.x() + (geo.width() - palette.width()) // 2
        y = geo.y() + 80
        palette.move(x, y)
        palette.show()

    def _dispatch_action(self, action_id: str) -> None:
        """Route an action_id triggered from the command palette to its handler."""
        handlers = {
            "file.add_files": self._on_add_files,
            "file.add_folder": self._on_add_folder,
            "file.open_book": self._on_open_selected,
            "file.settings": self._on_drive_settings,
            "edit.undo": lambda: self._undo_stack.undo(),
            "edit.redo": lambda: self._undo_stack.redo(),
            "edit.edit_metadata": self._on_edit_selected,
            "edit.fetch_metadata": self._on_lookup_selected,
            "edit.rename_file": self._on_rename_files,
            "view.statistics": self._on_show_statistics,
            "view.toggle_sidebar": self._toggle_sidebar,
            "view.focus_search": lambda: self._search_input.setFocus(),
            "status.want": lambda: self._set_selected_status("want"),
            "status.reading": lambda: self._set_selected_status("reading"),
            "status.read": lambda: self._set_selected_status("read"),
            "status.clear": lambda: self._set_selected_status(None),
            "library.rescan": self._on_rescan,
            "library.sync_drive": self._on_sync_drive,
            "library.rename": self._on_rename_files,
            "library.convert": self._on_convert_books,
            "library.export": self._on_export,
            "library.import_": self._on_import,
            "library.health": self._on_library_health,
            "library.find_dupes": self._on_find_duplicates,
            "tools.backup": self._on_backup_dialog,
            "tools.restore": self._on_backup_dialog,
            "tools.compact_db": self._on_vacuum_db,
            "tools.fix_dates": self._on_fix_dates,
            "tools.surprise_me": self._on_surprise_me,
            "settings.recommendations": self._on_recommendations_settings,
            "settings.web": self._on_web_settings,
            "storage.clean_now": self._on_clean_storage_now,
            "storage.open_settings": self._on_drive_settings,
            "help.palette": self._on_command_palette,
            "help.cheat_sheet": self._on_shortcuts_cheat_sheet,
            "help.about": self._on_about,
        }
        h = handlers.get(action_id)
        if h:
            h()

    def _on_clean_storage_now(self) -> None:
        """Quick clean storage action from command palette."""
        from booklib.ui.storage_page import StoragePage
        sp = StoragePage(self._conn, self._repo)
        sp._clean_now()

    def _on_shortcuts_cheat_sheet(self) -> None:
        """Open the shortcuts cheat sheet dialog (Ctrl+/)."""
        from booklib.ui.shortcuts_page import ShortcutsCheatSheet
        dlg = ShortcutsCheatSheet(self)
        dlg.exec()

    def _on_configure_shortcuts(self) -> None:
        """Open the shortcuts configuration editor dialog."""
        from booklib.ui.shortcuts_page import ShortcutsEditorDialog
        dlg = ShortcutsEditorDialog(self)
        dlg.exec()

    # ── V6: Recommendation Handlers ──────────────────────────────────────────

    def _on_surprise_me(self) -> None:
        """Pick a surprise book to read next."""
        pick = self._rec_service.get_surprise_me()
        if not pick:
            QMessageBox.information(self, "Surprise Me", "No eligible unread books found in your library.")
            return
        book, reason = pick
        self._select_book_by_id(book.id)
        self._statusBar.showMessage(f"Surprise pick: '{book.title}' — {reason}", 8000)

    def _on_recommendation_feedback(self, books: list[BookRow], verdict: str) -> None:
        """Record user feedback ('hide' or 'not_interested') for books."""
        for b in books:
            self._rec_service.record_feedback(b.id, verdict)
        label = "hidden from suggestions" if verdict == "hide" else "marked as not interested"
        title = books[0].title if len(books) == 1 else f"{len(books)} books"
        self._statusBar.showMessage(f"'{title}' {label}.", 6000)
        if self._query.shelf == "recommended":
            self._reload_books()

    def _on_recommendations_settings(self) -> None:
        """Show dialog for recommendation preferences and feedback reset."""
        from PySide6.QtWidgets import QCheckBox, QSpinBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Recommendations Settings — Ratnodadhi")
        dlg.setFixedWidth(380)
        l = QVBoxLayout(dlg)
        l.setSpacing(12)

        enabled_cb = QCheckBox("Enable reading recommendations")
        enabled_cb.setChecked(self._rec_service.is_enabled())
        l.addWidget(enabled_cb)

        row = QHBoxLayout()
        row.addWidget(QLabel("Minimum ratings for tailored suggestions:"))
        spin = QSpinBox()
        spin.setRange(1, 20)
        spin.setValue(self._rec_service.get_min_ratings())
        row.addWidget(spin)
        l.addLayout(row)

        l.addSpacing(6)
        btn_reset = QPushButton("Reset All Feedback ('Hide' / 'Not Interested')")
        def _on_reset():
            if QMessageBox.question(dlg, "Confirm Reset", "Reset all 'Hide' and 'Not interested' feedback?") == QMessageBox.Yes:
                self._rec_service.reset_all_feedback()
                QMessageBox.information(dlg, "Reset", "Feedback has been reset.")
                if self._query.shelf == "recommended":
                    self._reload_books()
        btn_reset.clicked.connect(_on_reset)
        l.addWidget(btn_reset)

        l.addSpacing(10)
        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbox.accepted.connect(dlg.accept)
        bbox.rejected.connect(dlg.reject)
        l.addWidget(bbox)

        if dlg.exec():
            self._rec_service.set_enabled(enabled_cb.isChecked())
            self._rec_service.set_min_ratings(spin.value())
            if self._query.shelf == "recommended":
                self._reload_books()

    def _on_web_settings(self) -> None:
        """Open the Web Access & OPDS settings dialog."""
        from booklib.ui.web_settings_page import WebSettingsPage
        dlg = QDialog(self)
        dlg.setWindowTitle("Web Access & OPDS — Ratnodadhi")
        dlg.resize(600, 520)
        l = QVBoxLayout(dlg)
        page = WebSettingsPage(self._repo, parent=dlg)
        l.addWidget(page)
        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(dlg.reject)
        l.addWidget(btn_box)
        dlg.exec()

    def _on_shortcuts_cheat_sheet(self) -> None:
        """Show read-only keyboard shortcuts reference dialog (Ctrl+/)."""
        from booklib.ui.shortcuts_page import ShortcutsCheatSheet
        dlg = ShortcutsCheatSheet(parent=self)
        dlg.exec()

    def _on_configure_shortcuts(self) -> None:
        """Open keyboard shortcuts configuration editor."""
        from booklib.ui.shortcuts_page import ShortcutsEditorDialog
        dlg = ShortcutsEditorDialog(parent=self)
        dlg.exec()

    def _on_about(self) -> None:
        """Show About Ratnodadhi dialog with modern circular corners, Jaini font branding, and developer details."""
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QFrame, QDialogButtonBox
        from booklib.app import get_app_icon
        from booklib.ui.modern_dialog import ModernDialog
        from booklib.ui.theme import load_jaini_font, is_dark

        dlg = ModernDialog(self, title="About Ratnodadhi")
        dlg.setFixedSize(500, 520)
        layout = dlg.content_layout

        # Header with icon and title
        header = QHBoxLayout()
        header.setSpacing(16)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_app_icon().pixmap(64, 64))
        header.addWidget(icon_lbl)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)

        jaini_family = load_jaini_font()
        brand_col = "#e07a5f" if is_dark() else "#b84e26"

        app_devanagari = QLabel("रत्नोदधि")
        app_devanagari.setObjectName("aboutAppDevanagari")
        f_jaini = QFont(jaini_family, 28)
        f_jaini.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
        app_devanagari.setFont(f_jaini)
        app_devanagari.setStyleSheet(
            f"font-family: '{jaini_family}', 'Jaini', sans-serif; "
            f"font-size: 28px; font-weight: 600; color: {brand_col}; line-height: 1;"
        )

        app_name = QLabel("<span style='font-size: 14px; font-weight: bold;'>Ratnodadhi</span> <span style='font-size: 11px; color: palette(placeholder-text);'>· Version 1.0.0</span>")
        app_sub = QLabel("<span style='font-size: 11px; color: palette(placeholder-text);'>Digital Library & Reading Environment</span>")

        title_layout.addWidget(app_devanagari)
        title_layout.addWidget(app_name)
        title_layout.addWidget(app_sub)
        header.addLayout(title_layout)
        header.addStretch()
        layout.addLayout(header)

        # Description with Devanagari text rendered strictly with Jaini font
        desc_lbl = QLabel(
            f"Named after <span style=\"font-family: '{jaini_family}', 'Jaini', sans-serif; font-size: 15px; font-weight: bold; color: {brand_col};\">रत्नोदधि</span> "
            f"(<i>Ratnodadhi</i>, meaning \"Ocean of Gems\"), the celebrated "
            f"nine-story library of ancient Nalanda University. Built as an offline-first, "
            f"privacy-focused desktop digital library and reader."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 12px; line-height: 1.4;")
        layout.addWidget(desc_lbl)

        # Developer Details Card
        dev_card = QFrame()
        dev_card.setObjectName("devCard")
        dev_card.setStyleSheet("QFrame#devCard { background: palette(alternate-base); border-radius: 10px; border: 1px solid palette(mid); } QLabel { border: none; }")
        card_l = QVBoxLayout(dev_card)
        card_l.setContentsMargins(14, 12, 14, 12)
        card_l.setSpacing(8)

        card_title = QLabel("<b>Developer Details</b>")
        card_title.setStyleSheet("font-size: 12px; font-weight: bold;")
        card_l.addWidget(card_title)

        dev_name = QLabel("<b>Developer:</b> Mritunjay Pandey")
        dev_name.setStyleSheet("font-size: 12px;")
        card_l.addWidget(dev_name)

        dev_github = QLabel("<b>GitHub:</b> <a href='https://github.com/mritunjaylive' style='color:#38bdf8; text-decoration:none;'>@mritunjaylive</a>")
        dev_github.setOpenExternalLinks(True)
        dev_github.setStyleSheet("font-size: 12px;")
        card_l.addWidget(dev_github)

        dev_web = QLabel("<b>Website:</b> <a href='https://mritunjaylive.in' style='color:#38bdf8; text-decoration:none;'>mritunjaylive.in</a>")
        dev_web.setOpenExternalLinks(True)
        dev_web.setStyleSheet("font-size: 12px;")
        card_l.addWidget(dev_web)

        dev_email = QLabel("<b>Email:</b> <a href='mailto:mritunjay@mritunjaylive.in' style='color:#38bdf8; text-decoration:none;'>mritunjay@mritunjaylive.in</a>")
        dev_email.setOpenExternalLinks(True)
        dev_email.setStyleSheet("font-size: 12px;")
        card_l.addWidget(dev_email)

        layout.addWidget(dev_card)

        layout.addStretch()
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        btn_box.accepted.connect(dlg.accept)
        layout.addWidget(btn_box)

        dlg.exec()




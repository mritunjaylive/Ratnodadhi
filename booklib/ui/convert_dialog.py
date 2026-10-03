"""
ui/convert_dialog.py – Book format conversion dialog using Calibre's ebook-convert.
"""
from __future__ import annotations

import logging
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from booklib.convert.calibre import find_ebook_convert, get_version, CONVERSION_MATRIX
from booklib.convert.runner import run_conversion, ConversionError

logger = logging.getLogger(__name__)

_SETTINGS_KEY = "calibre/exe_path"
_ORG = "Ratnodadhi"
_APP = "Ratnodadhi"


class ConvertWorker(QThread):
    progress = Signal(int)
    book_finished = Signal(str, str)   # title, status ("ok" or error)
    all_done = Signal(int, int)        # succeeded, failed

    def __init__(
        self,
        exe: Path,
        books: list[dict],
        to_format: str,
        dest_folder: Path,
        repo,
        conn,
        carry_over: dict[str, bool],
    ):
        super().__init__()
        self._exe = exe
        self._books = books
        self._to_format = to_format
        self._dest_folder = dest_folder
        self._repo = repo
        self._conn = conn
        self._carry = carry_over
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        succeeded = 0
        failed = 0

        for b in self._books:
            if self._is_cancelled:
                break
            src_path = Path(b["path"])
            if not src_path.exists():
                self.book_finished.emit(b.get("title", src_path.name), "Source file not found")
                failed += 1
                continue

            # Record running in conversion_log
            log_id = None
            try:
                cur = self._conn.execute(
                    """INSERT INTO conversion_log (source_book_id, from_format, to_format, status)
                       VALUES (?, ?, ?, 'running')""",
                    (b["id"], b.get("format", src_path.suffix.lstrip(".")), self._to_format),
                )
                self._conn.commit()
                log_id = cur.lastrowid
            except Exception:
                pass

            try:
                cover_p = Path(b["cover_path"]) if b.get("cover_path") and Path(b["cover_path"]).exists() else None
                out_path = run_conversion(
                    exe=self._exe,
                    src_path=src_path,
                    dest_folder=self._dest_folder,
                    to_format=self._to_format,
                    book=b,
                    cover_path=cover_p,
                    on_progress=lambda p: self.progress.emit(p),
                )

                # Add converted book to library linked by converted_from
                from booklib.metadata.extract import extract_metadata
                meta = extract_metadata(out_path)
                folder_id = b.get("folder_id", 1)
                new_id = self._repo.add_book(folder_id=folder_id, path=str(out_path), metadata=meta)

                # Link converted_from
                self._conn.execute(
                    "UPDATE books SET converted_from = ? WHERE id = ?",
                    (b["id"], new_id),
                )

                # Carry over requested user data
                if self._carry.get("rating") and b.get("rating"):
                    self._conn.execute("UPDATE books SET rating = ? WHERE id = ?", (b["rating"], new_id))
                if self._carry.get("series") and b.get("series_id"):
                    self._conn.execute(
                        "UPDATE books SET series_id = ?, series_index = ? WHERE id = ?",
                        (b["series_id"], b.get("series_index"), new_id),
                    )

                # Update conversion_log
                if log_id:
                    self._conn.execute(
                        "UPDATE conversion_log SET output_book_id = ?, status = 'done', finished_at = datetime('now') WHERE id = ?",
                        (new_id, log_id),
                    )
                self._conn.commit()

                self.book_finished.emit(b.get("title", src_path.name), "ok")
                succeeded += 1

            except Exception as exc:
                logger.error("Conversion failed for %s: %s", b.get("title"), exc)
                tail = getattr(exc, "tail", str(exc))
                if log_id:
                    self._conn.execute(
                        "UPDATE conversion_log SET status = 'failed', error_tail = ?, finished_at = datetime('now') WHERE id = ?",
                        (tail[:500], log_id),
                    )
                    self._conn.commit()
                self.book_finished.emit(b.get("title", src_path.name), str(exc))
                failed += 1

        self.all_done.emit(succeeded, failed)


class ConvertDialog(QDialog):
    """Calibre-powered format conversion dialog."""

    def __init__(self, book_ids: list[int], repo, conn, parent=None) -> None:
        super().__init__(parent)
        self._book_ids = book_ids
        self._repo = repo
        self._conn = conn
        self._worker: ConvertWorker | None = None

        self.setWindowTitle("Convert Books — Ratnodadhi")
        self.resize(540, 480)
        self._setup_ui()
        self._check_calibre()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Calibre Status Banner ─────────────────────────────────────────────
        self._status_banner = QLabel("Checking for Calibre installation…")
        self._status_banner.setWordWrap(True)
        self._status_banner.setStyleSheet("padding: 8px; border-radius: 4px; background: palette(midlight);")
        layout.addWidget(self._status_banner)

        # ── Book Selection Info ───────────────────────────────────────────────
        self._info_label = QLabel()
        layout.addWidget(self._info_label)

        # ── Target Format ─────────────────────────────────────────────────────
        format_group = QGroupBox("Target Format")
        f_layout = QVBoxLayout(format_group)
        self._format_combo = QComboBox()
        self._format_combo.addItems(["EPUB", "AZW3", "PDF", "MOBI", "TXT", "DOCX"])
        self._format_combo.currentTextChanged.connect(self._on_format_changed)
        f_layout.addWidget(self._format_combo)

        self._quality_note = QLabel()
        self._quality_note.setStyleSheet("color: palette(mid); font-size: 11px;")
        f_layout.addWidget(self._quality_note)
        layout.addWidget(format_group)

        # ── Carry Over Options ────────────────────────────────────────────────
        carry_group = QGroupBox("Carry Over to Converted Book")
        c_layout = QVBoxLayout(carry_group)
        self._carry_tags = QCheckBox("Tags")
        self._carry_tags.setChecked(True)
        self._carry_series = QCheckBox("Series & Index")
        self._carry_series.setChecked(True)
        self._carry_rating = QCheckBox("Rating")
        self._carry_rating.setChecked(True)
        c_layout.addWidget(self._carry_tags)
        c_layout.addWidget(self._carry_series)
        c_layout.addWidget(self._carry_rating)
        layout.addWidget(carry_group)

        # ── DRM Note ──────────────────────────────────────────────────────────
        drm_label = QLabel("ℹ <i>Note: DRM-protected books cannot be converted and will be skipped.</i>")
        drm_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(drm_label)

        # ── Progress ──────────────────────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_box = QDialogButtonBox()
        self._convert_btn = btn_box.addButton("Start Conversion", QDialogButtonBox.AcceptRole)
        self._convert_btn.clicked.connect(self._on_start_convert)
        self._cancel_btn = btn_box.addButton("Close", QDialogButtonBox.RejectRole)
        self._cancel_btn.clicked.connect(self.reject)
        layout.addWidget(btn_box)

        self._update_book_info()
        self._on_format_changed()

    def _check_calibre(self) -> None:
        settings = QSettings(_ORG, _APP)
        path_str = settings.value(_SETTINGS_KEY, "")
        exe = find_ebook_convert(path_str)
        if exe:
            ver = get_version(exe) or "Installed"
            self._status_banner.setText(f"Calibre detected: <b>{ver}</b> ({exe})")
            self._status_banner.setStyleSheet("padding: 8px; border-radius: 4px; background: rgba(34, 197, 94, 0.15); color: #16a34a;")
            self._calibre_exe = exe
            self._convert_btn.setEnabled(True)
        else:
            self._status_banner.setText(
                "Calibre's <code>ebook-convert</code> tool was not found.<br>"
                "Please install Calibre from <a href='https://calibre-ebook.com/download'>calibre-ebook.com</a> "
                "or specify the executable path."
            )
            self._status_banner.setStyleSheet("padding: 8px; border-radius: 4px; background: rgba(239, 68, 68, 0.15); color: #dc2626;")
            self._calibre_exe = None
            self._convert_btn.setEnabled(False)

    def _update_book_info(self) -> None:
        if self._book_ids:
            self._info_label.setText(f"<b>{len(self._book_ids)}</b> book(s) selected for conversion.")
        else:
            self._info_label.setText("No books currently selected. Please select one or more books first.")
            self._convert_btn.setEnabled(False)

    def _on_format_changed(self) -> None:
        to_fmt = self._format_combo.currentText().lower()
        note = CONVERSION_MATRIX.get(("epub", to_fmt), "Standard conversion")
        self._quality_note.setText(f"Quality: {note}")

    def _on_start_convert(self) -> None:
        if not self._calibre_exe or not self._book_ids:
            return

        placeholders = ",".join("?" * len(self._book_ids))
        rows = self._conn.execute(
            f"SELECT * FROM books WHERE id IN ({placeholders}) AND is_missing = 0",
            self._book_ids,
        ).fetchall()
        books = [dict(r) for r in rows]
        if not books:
            QMessageBox.information(self, "No Books", "Selected books are missing or not local.")
            return

        dest_folder = Path(books[0]["path"]).parent
        to_fmt = self._format_combo.currentText().lower()
        carry = {
            "tags": self._carry_tags.isChecked(),
            "series": self._carry_series.isChecked(),
            "rating": self._carry_rating.isChecked(),
        }

        self._convert_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)

        self._worker = ConvertWorker(
            exe=self._calibre_exe,
            books=books,
            to_format=to_fmt,
            dest_folder=dest_folder,
            repo=self._repo,
            conn=self._conn,
            carry_over=carry,
        )
        self._worker.progress.connect(self._progress_bar.setValue)

        def _done(succ, fail):
            self._progress_bar.setVisible(False)
            self._convert_btn.setEnabled(True)
            msg = f"Conversion finished:\n  • {succ} succeeded\n"
            if fail:
                msg += f"  • {fail} failed (check conversion_log for details)"
            QMessageBox.information(self, "Conversion Complete", msg)
            self.accept()

        self._worker.all_done.connect(_done)
        self._worker.start()

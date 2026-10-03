"""
ui/stats_view.py – Statistics main view widget.

Shows a statistics dashboard:
  - Year filter dropdown + "All time" option
  - Goal progress bar for the selected year
  - Summary tiles: finished, pages, avg rating, avg days
  - Bar chart: books finished per month
  - Horizontal bar lists: top authors, top genres
  - Library overview footer
  - Undated reads note with "Fix dates…" link
  - Click a bar / author / genre to open matching books in library
"""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView,
    QHorizontalBarSeries,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from booklib.stats.queries import (
    available_years, books_per_month, calculate_reading_streak, library_overview,
    reading_heatmap, reading_time_stats, summary_stats, top_authors,
    top_genres, top_read_books_by_time, undated_read_books,
)
from booklib.stats.goals import all_goals_progress, pace_text
from booklib.ui.reading_heatmap import ReadingHeatmapWidget

logger = logging.getLogger(__name__)

_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class StatsTile(QFrame):
    """A small summary tile: label over a big number."""

    def __init__(self, label: str, value: str = "—", parent=None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setMinimumWidth(120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        self._val_label = QLabel(value)
        self._val_label.setStyleSheet("font-size: 24px; font-weight: 700;")
        self._val_label.setAlignment(Qt.AlignCenter)

        lbl = QLabel(label)
        lbl.setStyleSheet("font-size: 11px; color: palette(mid);")
        lbl.setAlignment(Qt.AlignCenter)

        layout.addWidget(self._val_label)
        layout.addWidget(lbl)

    def set_value(self, value: str) -> None:
        self._val_label.setText(value)


class StatsView(QWidget):
    """
    Full statistics panel, embedded as an alternative main view.
    Emits drill_down(filter_dict) when the user clicks a bar/author/genre.
    """

    drill_down = Signal(dict)   # open library with this filter

    def __init__(self, conn, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._current_year: int | None = None
        self._setup_ui()
        self._refresh()

    def set_conn(self, conn) -> None:
        self._conn = conn
        self._refresh()

    # ── UI setup ──────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        # ── Top bar: year selector + goal progress ────────────────────────────
        top_bar = QHBoxLayout()

        year_label = QLabel("Year:")
        self._year_combo = QComboBox()
        self._year_combo.setMinimumWidth(100)
        self._year_combo.currentIndexChanged.connect(self._on_year_changed)
        top_bar.addWidget(year_label)
        top_bar.addWidget(self._year_combo)
        top_bar.addSpacing(20)

        self._goal_label = QLabel("")
        self._goal_progress = QProgressBar()
        self._goal_progress.setMaximumWidth(200)
        self._goal_progress.setTextVisible(True)
        self._pace_label = QLabel("")
        self._pace_label.setStyleSheet("font-size: 11px; color: palette(mid);")
        top_bar.addWidget(self._goal_label)
        top_bar.addWidget(self._goal_progress)
        top_bar.addWidget(self._pace_label)
        top_bar.addStretch()

        root.addLayout(top_bar)

        # ── Reading Time & Streak tiles ───────────────────────────────────────
        time_bar = QHBoxLayout()
        self._tile_time_today = StatsTile("Time today")
        self._tile_time_week = StatsTile("This week")
        self._tile_time_total = StatsTile("Total time")
        self._tile_streak = StatsTile("Current streak")
        self._tile_longest_streak = StatsTile("Longest streak")
        for tile in [self._tile_time_today, self._tile_time_week, self._tile_time_total, self._tile_streak, self._tile_longest_streak]:
            time_bar.addWidget(tile)
        root.addLayout(time_bar)

        # ── Summary tiles ─────────────────────────────────────────────────────
        tiles_bar = QHBoxLayout()
        self._tile_finished = StatsTile("Books finished")
        self._tile_pages    = StatsTile("Pages read")
        self._tile_rating   = StatsTile("Avg rating")
        self._tile_days     = StatsTile("Avg days to finish")
        for tile in [self._tile_finished, self._tile_pages, self._tile_rating, self._tile_days]:
            tiles_bar.addWidget(tile)
        root.addLayout(tiles_bar)

        # ── 52-Week Reading Heatmap ───────────────────────────────────────────
        heatmap_header = QLabel("Reading Activity (Last 52 Weeks)")
        heatmap_header.setStyleSheet("font-weight: 600;")
        root.addWidget(heatmap_header)

        self._heatmap_widget = ReadingHeatmapWidget(self)
        root.addWidget(self._heatmap_widget)

        # ── Month bar chart ───────────────────────────────────────────────────
        chart_label = QLabel("Books finished per month")
        chart_label.setStyleSheet("font-weight: 600;")
        root.addWidget(chart_label)

        self._month_chart_view = QChartView()
        self._month_chart_view.setFixedHeight(160)
        self._month_chart_view.setRenderHint(QPainter.Antialiasing)
        root.addWidget(self._month_chart_view)

        # ── Author & genre top lists ──────────────────────────────────────────
        side_grid = QGridLayout()
        side_grid.setSpacing(12)

        author_lbl = QLabel("Top authors")
        author_lbl.setStyleSheet("font-weight: 600;")
        self._author_list = _HBarWidget(label="author")
        self._author_list.item_clicked.connect(
            lambda name: self.drill_down.emit({"author": name})
        )
        side_grid.addWidget(author_lbl, 0, 0)
        side_grid.addWidget(self._author_list, 1, 0)

        genre_lbl = QLabel("Top genres")
        genre_lbl.setStyleSheet("font-weight: 600;")
        self._genre_list = _HBarWidget(label="genre")
        self._genre_list.item_clicked.connect(
            lambda name: self.drill_down.emit({"genre": name})
        )
        side_grid.addWidget(genre_lbl, 0, 1)
        side_grid.addWidget(self._genre_list, 1, 1)

        root.addLayout(side_grid)

        # ── Library overview footer ───────────────────────────────────────────
        self._overview_label = QLabel()
        self._overview_label.setStyleSheet("font-size: 11px; color: palette(mid);")
        root.addWidget(self._overview_label)

        # ── Undated reads notice ──────────────────────────────────────────────
        self._undated_bar = QHBoxLayout()
        self._undated_label = QLabel()
        self._undated_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        self._fix_dates_btn = QPushButton("Fix dates…")
        self._fix_dates_btn.setFlat(True)
        self._fix_dates_btn.setStyleSheet(
            "color: palette(highlight); font-size: 11px; text-decoration: underline;"
        )
        self._fix_dates_btn.hide()
        self._undated_bar.addWidget(self._undated_label)
        self._undated_bar.addWidget(self._fix_dates_btn)
        self._undated_bar.addStretch()
        root.addLayout(self._undated_bar)

        root.addStretch()

    # ── Data refresh ──────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        if self._conn is None:
            return
        try:
            self._populate_year_combo()
            self._refresh_data()
        except Exception as exc:
            logger.error("Stats refresh error: %s", exc)

    def _populate_year_combo(self) -> None:
        self._year_combo.blockSignals(True)
        self._year_combo.clear()
        self._year_combo.addItem("All time", None)
        years = available_years(self._conn)
        for y in reversed(years):
            self._year_combo.addItem(str(y), y)
        # Select current year if available
        from datetime import date
        cur_year = date.today().year
        idx = self._year_combo.findData(cur_year)
        if idx >= 0:
            self._year_combo.setCurrentIndex(idx)
        self._year_combo.blockSignals(False)
        self._current_year = self._year_combo.currentData()

    def _on_year_changed(self) -> None:
        self._current_year = self._year_combo.currentData()
        self._refresh_data()

    def _refresh_data(self) -> None:
        year = self._current_year
        conn = self._conn

        # Reading time & streaks
        tstats = reading_time_stats(conn)
        streak = calculate_reading_streak(conn)

        today_text = f"{tstats.seconds_today // 60}m" if tstats.seconds_today < 3600 else f"{tstats.seconds_today / 3600:.1f}h"
        week_text = f"{tstats.seconds_this_week // 60}m" if tstats.seconds_this_week < 3600 else f"{tstats.seconds_this_week / 3600:.1f}h"
        total_text = f"{tstats.seconds_total // 60}m" if tstats.seconds_total < 3600 else f"{tstats.seconds_total / 3600:.1f}h"

        self._tile_time_today.set_value(today_text)
        self._tile_time_week.set_value(week_text)
        self._tile_time_total.set_value(total_text)
        self._tile_streak.set_value(f"{streak.current_streak_days}d")
        self._tile_longest_streak.set_value(f"{streak.longest_streak_days}d")

        # 52-week heatmap
        self._heatmap_widget.load_from_db(conn)

        # Summary
        s = summary_stats(conn, year)
        self._tile_finished.set_value(str(s.finished))
        self._tile_pages.set_value(f"{s.pages:,}" if s.pages else "—")
        self._tile_rating.set_value(
            f"{s.avg_rating:.1f} / 5" if s.avg_rating else "—"
        )
        self._tile_days.set_value(
            f"{s.avg_days:.0f}" if s.avg_days is not None else "—"
        )

        # Goals
        self._refresh_goal(year)

        # Month chart
        if year:
            months = books_per_month(conn, year)
            month_map = {m.month: m.books for m in months}
            values = [month_map.get(i, 0) for i in range(1, 13)]
            self._update_month_chart(values, year)
        else:
            self._month_chart_view.hide()

        # Author & genre
        authors = top_authors(conn, year)
        self._author_list.set_data([(a["author"], a["count"]) for a in authors])

        genres = top_genres(conn, year)
        self._genre_list.set_data([(g["genre"], g["count"]) for g in genres])

        # Overview footer
        ov = library_overview(conn)
        source_str = ", ".join(f"{s}: {c}" for s, c in ov.by_source.items())
        self._overview_label.setText(
            f"Library: {ov.total_books:,} books · "
            f"{ov.total_size_bytes / (1024**3):.1f} GB · "
            f"{ov.read_count} read · "
            f"{ov.want_count} want to read  |  {source_str}"
        )

        # Undated reads
        undated = undated_read_books(conn)
        if undated:
            self._undated_label.setText(
                f"ⓘ {len(undated)} book(s) marked Read have no finish date"
            )
            self._fix_dates_btn.show()
        else:
            self._undated_label.setText("")
            self._fix_dates_btn.hide()

    def _refresh_goal(self, year: int | None) -> None:
        if year is None:
            self._goal_label.hide()
            self._goal_progress.hide()
            self._pace_label.hide()
            return
        progresses = all_goals_progress(self._conn)
        year_goals = [p for p in progresses if p.goal.year == year and p.goal.kind == "books"]
        if not year_goals:
            self._goal_label.hide()
            self._goal_progress.hide()
            self._pace_label.hide()
            return
        p = year_goals[0]
        self._goal_label.setText(f"Goal {year}:")
        self._goal_label.show()
        self._goal_progress.setMaximum(p.goal.target)
        self._goal_progress.setValue(min(p.done, p.goal.target))
        self._goal_progress.setFormat(f"{p.done} / {p.goal.target} books")
        self._goal_progress.show()
        self._pace_label.setText(pace_text(p))
        self._pace_label.show()

    def _update_month_chart(self, values: list[int], year: int) -> None:
        bar_set = QBarSet(str(year))
        for v in values:
            bar_set.append(v)

        series = QBarSeries()
        series.append(bar_set)

        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("")
        chart.legend().hide()
        chart.setMargins(__import__("PySide6.QtCore", fromlist=["QMargins"]).QMargins(4, 4, 4, 4))

        axis_x = QBarCategoryAxis()
        axis_x.append(_MONTH_NAMES)
        chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)

        self._month_chart_view.setChart(chart)
        self._month_chart_view.show()


class _HBarWidget(QWidget):
    """Simple horizontal bar list widget for top authors/genres."""

    item_clicked = Signal(str)

    def __init__(self, label: str = "", parent=None) -> None:
        super().__init__(parent)
        self._label = label
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

    def set_data(self, items: list[tuple[str, int]]) -> None:
        """Set (name, count) pairs."""
        # Clear existing
        while self._layout.count():
            w = self._layout.takeAt(0)
            if w.widget():
                w.widget().deleteLater()

        if not items:
            lbl = QLabel("No data")
            lbl.setStyleSheet("color: palette(mid);")
            self._layout.addWidget(lbl)
            return

        max_count = max(c for _, c in items) or 1
        for name, count in items[:8]:
            row = QHBoxLayout()
            row.setSpacing(6)

            bar = QFrame()
            bar.setFixedHeight(14)
            width = int(120 * count / max_count)
            bar.setFixedWidth(max(width, 4))
            bar.setStyleSheet(
                "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #4a9eff, stop:1 #6dc0ff); border-radius: 2px;"
            )

            btn = QPushButton(f"{name}  {count}")
            btn.setFlat(True)
            btn.setStyleSheet("text-align: left; padding: 0; font-size: 11px;")
            btn.clicked.connect(lambda checked=False, n=name: self.item_clicked.emit(n))

            row.addWidget(bar)
            row.addWidget(btn)
            row.addStretch()

            container = QWidget()
            container.setLayout(row)
            self._layout.addWidget(container)

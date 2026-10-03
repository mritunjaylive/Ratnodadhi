"""
tests/test_v6_stats.py – Tests for Milestone 11 Reading-time statistics:
- Reading time aggregates (today, week, month, year, total)
- Streak calculation (consecutive days, threshold, current & longest)
- Heatmap continuous sequence and level assignment
- Per-book reading speed and time-left estimation
"""
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
import pytest

from booklib.db.database import Database
from booklib.stats.queries import (
    calculate_reading_streak,
    reading_heatmap,
    reading_time_stats,
    top_read_books_by_time,
    book_reading_estimate,
)
from booklib.ui.reading_heatmap import ReadingHeatmapWidget


@pytest.fixture
def test_db(tmp_path: Path):
    db_path = tmp_path / "test_stats.db"
    db = Database(db_path)
    conn = db.connect()
    with conn:
        conn.execute("INSERT INTO folders (id, path) VALUES (1, '/books')")
        conn.execute(
            """
            INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime, title, author, pages, progress_percent)
            VALUES (1, 1, '/books/b1.pdf', 'b1.pdf', 'pdf', 1000, 0, 'Clean Code', 'Robert Martin', 400, 50.0)
            """
        )
        conn.execute(
            """
            INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime, title, author, pages, progress_percent)
            VALUES (2, 1, '/books/b2.pdf', 'b2.pdf', 'pdf', 1000, 0, 'Design Patterns', 'GoF', 300, 10.0)
            """
        )
    return db


def test_reading_time_stats(test_db):
    conn = test_db.conn
    now = datetime.now()
    today_iso = now.isoformat()
    three_days_ago = (now - timedelta(days=3)).isoformat()
    forty_days_ago = (now - timedelta(days=40)).isoformat()

    with conn:
        # Today: 1800s (30m)
        conn.execute(
            "INSERT INTO reading_sessions (book_id, started_at, active_seconds, start_progress, end_progress) VALUES (1, ?, 1800, 0.0, 0.1)",
            (today_iso,),
        )
        # 3 days ago: 3600s (1h)
        conn.execute(
            "INSERT INTO reading_sessions (book_id, started_at, active_seconds, start_progress, end_progress) VALUES (1, ?, 3600, 0.1, 0.3)",
            (three_days_ago,),
        )
        # 40 days ago: 7200s (2h)
        conn.execute(
            "INSERT INTO reading_sessions (book_id, started_at, active_seconds, start_progress, end_progress) VALUES (2, ?, 7200, 0.0, 0.2)",
            (forty_days_ago,),
        )

    stats = reading_time_stats(conn)
    assert stats.seconds_today == 1800
    assert stats.seconds_this_week == 1800 + 3600
    assert stats.seconds_total == 1800 + 3600 + 7200


def test_calculate_reading_streak(test_db):
    conn = test_db.conn
    today = date.today()

    # Insert 3 consecutive days reading >= 300s
    with conn:
        for i in range(3):
            d = (today - timedelta(days=i)).isoformat() + "T10:00:00"
            conn.execute(
                "INSERT INTO reading_sessions (book_id, started_at, active_seconds) VALUES (1, ?, 600)",
                (d,),
            )

    streak = calculate_reading_streak(conn, min_seconds_per_day=300)
    assert streak.current_streak_days == 3
    assert streak.longest_streak_days == 3
    assert streak.last_read_date == today.isoformat()


def test_reading_heatmap(test_db):
    conn = test_db.conn
    today = date.today()

    # Insert sessions for today and 10 days ago
    with conn:
        conn.execute(
            "INSERT INTO reading_sessions (book_id, started_at, active_seconds) VALUES (1, ?, 1200)",
            (today.isoformat() + "T14:00:00",),  # 20m -> level 2
        )
        t_10 = (today - timedelta(days=10)).isoformat() + "T14:00:00"
        conn.execute(
            "INSERT INTO reading_sessions (book_id, started_at, active_seconds) VALUES (1, ?, 6000)",
            (t_10,),  # 100m -> level 4
        )

    days = reading_heatmap(conn, total_days=30)
    assert len(days) == 30
    assert days[-1].date_str == today.isoformat()
    assert days[-1].level == 2

    day_10 = next(d for d in days if d.date_str == (today - timedelta(days=10)).isoformat())
    assert day_10.level == 4


def test_book_reading_estimate(test_db):
    conn = test_db.conn
    now = datetime.now().isoformat()

    # 1800 seconds, 0.1 progress delta on Book 1 (400 pages total -> 40 pages read)
    with conn:
        conn.execute(
            "INSERT INTO reading_sessions (book_id, started_at, active_seconds, start_progress, end_progress) VALUES (1, ?, 1800, 0.0, 0.1)",
            (now,),
        )

    est = book_reading_estimate(conn, 1)
    assert est["total_seconds"] == 1800
    assert est["speed_pages_per_hour"] > 0
    assert est["est_seconds_left"] is not None
    assert est["time_spent_text"] == "30m"
    assert "left" in est["time_left_text"]


def test_top_read_books(test_db):
    conn = test_db.conn
    now = datetime.now().isoformat()

    with conn:
        conn.execute(
            "INSERT INTO reading_sessions (book_id, started_at, active_seconds) VALUES (1, ?, 5000)",
            (now,),
        )
        conn.execute(
            "INSERT INTO reading_sessions (book_id, started_at, active_seconds) VALUES (2, ?, 2000)",
            (now,),
        )

    top = top_read_books_by_time(conn)
    assert len(top) == 2
    assert top[0].book_id == 1
    assert top[0].total_seconds == 5000
    assert top[1].book_id == 2


def test_reading_heatmap_widget(test_db, qapp):
    widget = ReadingHeatmapWidget()
    widget.load_from_db(test_db.conn)
    assert widget.height() > 0
    assert widget.width() > 0

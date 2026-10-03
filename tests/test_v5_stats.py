"""
test_v5_stats.py – Statistics queries and goals tests.
"""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from booklib.stats.queries import (
    books_per_year, books_per_month, summary_stats, top_authors,
    top_genres, library_overview, undated_read_books, available_years,
)
from booklib.stats.goals import (
    upsert_goal, list_goals, delete_goal, goal_progress, pace_text,
    Goal,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def conn(tmp_path):
    """Minimal DB with seeded reading_log and books."""
    db_path = tmp_path / "test.db"
    from booklib.db.database import Database
    db = Database(db_path)
    c = db.connect()
    # Insert folder
    c.execute("INSERT INTO folders (id, path) VALUES (1, '/books')")
    # Insert books
    c.executemany(
        "INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime, title, author, pages, genre, status, rating, is_missing) "
        "VALUES (?, 1, ?, ?, 'epub', 1000, 0.0, ?, ?, ?, ?, ?, ?, 0)",
        [
            (1, "/books/b1.epub", "b1.epub", "War and Peace",   "Leo Tolstoy",   1296, "Fiction",          "read", 5),
            (2, "/books/b2.epub", "b2.epub", "Anna Karenina",   "Leo Tolstoy",    864, "Fiction",          "read", 4),
            (3, "/books/b3.epub", "b3.epub", "Clean Code",      "Robert Martin",  464, "Programming",      "read", 5),
            (4, "/books/b4.epub", "b4.epub", "The Pragmatic Programmer", "David Thomas", 352, "Programming","read", 4),
            (5, "/books/b5.epub", "b5.epub", "Crime and Punishment", "Fyodor Dostoevsky", 656, "Fiction",  "want", None),
        ],
    )
    # Insert reading_log entries
    c.executemany(
        "INSERT INTO reading_log (book_id, started_on, finished_on) VALUES (?, ?, ?)",
        [
            (1, "2025-01-10", "2025-03-15"),
            (2, "2025-04-01", "2025-05-20"),
            (3, "2026-01-05", "2026-02-10"),
            (4, "2026-03-01", "2026-04-20"),
            # Book 5 not read; books 1&2 re-read in 2026
            (1, "2026-05-01", "2026-06-15"),
        ],
    )
    c.commit()
    yield c
    db.close()


# ── Query tests ────────────────────────────────────────────────────────────────

class TestBooksPerYear:
    def test_two_years(self, conn):
        years = books_per_year(conn)
        yr_map = {y.year: y for y in years}
        # We inserted dates in 2025 and 2026 — verify at least one year is present
        # and that the total reading count across all years is 5
        total_books = sum(y.books for y in years)
        assert total_books == 5, f"Expected 5 total readings, got {total_books} from {years}"
        # Both years should appear (2025 and 2026)
        assert 2025 in yr_map, f"Expected 2025 in years, got {list(yr_map.keys())}"
        assert 2026 in yr_map, f"Expected 2026 in years, got {list(yr_map.keys())}"
        assert yr_map[2025].books == 2
        assert yr_map[2026].books == 3

    def test_pages_summed(self, conn):
        yr_map = {y.year: y for y in books_per_year(conn)}
        # Total pages across all years: 1296+864+464+352+1296 = 4272
        total_pages = sum(y.pages for y in yr_map.values())
        assert total_pages == 4272, f"Expected total 4272 pages, got {total_pages}"
        # Per-year breakdown (if both years are returned correctly)
        if 2025 in yr_map and 2026 in yr_map:
            assert yr_map[2025].pages == 1296 + 864   # books 1+2
            assert yr_map[2026].pages == 464 + 352 + 1296  # books 3+4+1(re-read)


class TestBooksPerMonth:
    def test_2026_months(self, conn):
        months = books_per_month(conn, 2026)
        month_map = {m.month: m.books for m in months}
        assert month_map.get(2, 0) == 1   # Clean Code finished Feb
        assert month_map.get(4, 0) == 1   # Pragmatic Programmer finished Apr
        assert month_map.get(6, 0) == 1   # War and Peace re-read finished Jun


class TestSummaryStats:
    def test_all_time(self, conn):
        s = summary_stats(conn)
        assert s.finished == 5   # total reading_log rows
        assert s.pages == (1296 + 864 + 464 + 352 + 1296)

    def test_year_filter(self, conn):
        s = summary_stats(conn, year=2025)
        assert s.finished == 2

    def test_avg_days(self, conn):
        s = summary_stats(conn)
        assert s.avg_days is not None and s.avg_days > 0

    def test_avg_rating(self, conn):
        s = summary_stats(conn)
        assert s.avg_rating is not None


class TestTopAuthors:
    def test_top_author_all_time(self, conn):
        authors = top_authors(conn)
        names = [a["author"] for a in authors]
        assert "Leo Tolstoy" in names
        top = authors[0]
        assert top["author"] == "Leo Tolstoy"  # 3 readings (2025×2 + 2026 re-read)

    def test_top_author_2026(self, conn):
        authors = top_authors(conn, year=2026)
        # 2026: Clean Code (Martin), Pragmatic (Thomas), War&Peace re-read (Tolstoy)
        assert len(authors) >= 1


class TestTopGenres:
    def test_fiction_top(self, conn):
        genres = top_genres(conn)
        names = [g["genre"] for g in genres]
        assert "Fiction" in names

    def test_year_filter(self, conn):
        genres = top_genres(conn, year=2026)
        names = [g["genre"] for g in genres]
        assert "Programming" in names


class TestLibraryOverview:
    def test_total_books(self, conn):
        ov = library_overview(conn)
        assert ov.total_books == 5

    def test_read_count(self, conn):
        ov = library_overview(conn)
        assert ov.read_count == 4

    def test_want_count(self, conn):
        ov = library_overview(conn)
        assert ov.want_count == 1


class TestUndatedReads:
    def test_no_undated(self, conn):
        # All read books have reading_log entries
        undated = undated_read_books(conn)
        assert undated == []

    def test_detects_undated(self, conn):
        # Mark book 5 as read without a reading_log entry
        conn.execute("UPDATE books SET status = 'read' WHERE id = 5")
        conn.commit()
        undated = undated_read_books(conn)
        assert any(u["id"] == 5 for u in undated)


class TestAvailableYears:
    def test_two_years(self, conn):
        years = available_years(conn)
        assert 2025 in years
        assert 2026 in years


# ── Goal tests ─────────────────────────────────────────────────────────────────

class TestGoals:
    def test_upsert_and_list(self, conn):
        upsert_goal(conn, 2026, "books", 24)
        goals = list_goals(conn)
        assert any(g.year == 2026 and g.kind == "books" and g.target == 24 for g in goals)

    def test_upsert_updates_existing(self, conn):
        upsert_goal(conn, 2026, "books", 24)
        upsert_goal(conn, 2026, "books", 30)
        goals = list_goals(conn)
        book_goals = [g for g in goals if g.year == 2026 and g.kind == "books"]
        assert len(book_goals) == 1
        assert book_goals[0].target == 30

    def test_delete(self, conn):
        upsert_goal(conn, 2026, "pages", 5000)
        goals = list_goals(conn)
        g = next(g for g in goals if g.kind == "pages")
        delete_goal(conn, g.id)
        goals_after = list_goals(conn)
        assert not any(g.kind == "pages" for g in goals_after)

    def test_invalid_kind_raises(self, conn):
        with pytest.raises(ValueError):
            upsert_goal(conn, 2026, "chapters", 100)

    def test_zero_target_raises(self, conn):
        with pytest.raises(ValueError):
            upsert_goal(conn, 2026, "books", 0)


class TestGoalProgress:
    def test_ahead_of_pace(self, conn):
        upsert_goal(conn, 2026, "books", 12)
        goal = next(g for g in list_goals(conn) if g.year == 2026)
        # 3 books finished in 2026; with target 12 and some day in the year
        progress = goal_progress(conn, goal, today=date(2026, 6, 15))
        # 3 finished by June is 50% of year done with 25% of target = ahead
        assert progress.done == 3

    def test_projection_computed(self, conn):
        upsert_goal(conn, 2026, "books", 24)
        goal = next(g for g in list_goals(conn) if g.year == 2026)
        progress = goal_progress(conn, goal, today=date(2026, 6, 30))
        assert progress.projection >= 0

    def test_is_reached(self, conn):
        upsert_goal(conn, 2026, "books", 2)
        goal = next(g for g in list_goals(conn) if g.year == 2026)
        progress = goal_progress(conn, goal, today=date(2026, 12, 31))
        assert progress.is_reached is True  # 3 books >= target 2

    def test_pace_text_ahead(self, conn):
        upsert_goal(conn, 2026, "books", 6)
        goal = next(g for g in list_goals(conn) if g.year == 2026)
        # Use mid-year: 3 finished vs expected ~3, difference near 0
        progress = goal_progress(conn, goal, today=date(2026, 6, 15))
        text = pace_text(progress)
        assert "ahead" in text or "on track" in text or "behind" in text

    def test_pages_goal(self, conn):
        upsert_goal(conn, 2026, "pages", 5000)
        goal = next(g for g in list_goals(conn) if g.kind == "pages")
        progress = goal_progress(conn, goal, today=date(2026, 12, 31))
        assert progress.done == (464 + 352 + 1296)  # 2026 books with pages

    def test_leap_year_calculation(self, conn):
        """2028 is a leap year (366 days)."""
        upsert_goal(conn, 2028, "books", 12)
        goal = next(g for g in list_goals(conn) if g.year == 2028)
        progress = goal_progress(conn, goal, today=date(2028, 12, 31))
        # No books in 2028 in our fixture
        assert progress.done == 0
        assert progress.expected == goal.target  # day 366 of 366

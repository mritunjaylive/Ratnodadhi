"""
stats/queries.py – Pure SQL statistics queries.

All functions take a sqlite3.Connection and return small dataclasses or plain dicts.
No caching; recomputed on demand (fast at 20,000 books).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


# ── Per-year/month aggregates ─────────────────────────────────────────────────

@dataclass
class YearStats:
    year: int
    books: int
    pages: int


@dataclass
class MonthStats:
    month: int      # 1-12
    books: int


def books_per_year(conn: sqlite3.Connection) -> list[YearStats]:
    rows = conn.execute(
        """
        SELECT CAST(substr(r.finished_on, 1, 4) AS INTEGER) AS yr,
               COUNT(*) AS books,
               COALESCE(SUM(b.pages), 0) AS pages
        FROM reading_log r
        JOIN books b ON b.id = r.book_id
        WHERE r.finished_on IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """
    ).fetchall()
    return [YearStats(r[0], r[1], r[2]) for r in rows]


def books_per_month(conn: sqlite3.Connection, year: int) -> list[MonthStats]:
    rows = conn.execute(
        """
        SELECT CAST(substr(r.finished_on, 6, 2) AS INTEGER) AS month,
               COUNT(*) AS books
        FROM reading_log r
        WHERE substr(r.finished_on, 1, 4) = ?
          AND r.finished_on IS NOT NULL
        GROUP BY month
        ORDER BY month
        """,
        (str(year),),
    ).fetchall()
    return [MonthStats(r["month"], r["books"]) for r in rows]


# ── Summary stats ─────────────────────────────────────────────────────────────

@dataclass
class SummaryStats:
    finished: int
    pages: int
    avg_rating: float | None
    avg_days: float | None
    books_no_pages: int     # finished books excluded from page total


def summary_stats(conn: sqlite3.Connection, year: int | None = None) -> SummaryStats:
    where = "WHERE r.finished_on IS NOT NULL"
    params: list = []
    if year is not None:
        where += " AND substr(r.finished_on, 1, 4) = ?"
        params.append(str(year))

    row = conn.execute(
        f"""
        SELECT COUNT(*) AS finished,
               COALESCE(SUM(b.pages), 0) AS pages,
               COUNT(CASE WHEN b.pages IS NULL OR b.pages = 0 THEN 1 END) AS no_pages
        FROM reading_log r
        JOIN books b ON b.id = r.book_id
        {where}
        """,
        params,
    ).fetchone()

    avg_rating_row = conn.execute(
        """
        SELECT AVG(CAST(rating AS REAL)) FROM books
        WHERE rating IS NOT NULL AND rating > 0 AND is_missing = 0
        """
    ).fetchone()

    avg_days_row = conn.execute(
        f"""
        SELECT AVG(julianday(r.finished_on) - julianday(r.started_on))
        FROM reading_log r
        {where}
          {'AND' if where else 'WHERE'} r.started_on IS NOT NULL
          AND julianday(r.finished_on) >= julianday(r.started_on)
        """,
        params,
    ).fetchone()

    return SummaryStats(
        finished=row["finished"] if row else 0,
        pages=row["pages"] if row else 0,
        avg_rating=avg_rating_row[0],
        avg_days=avg_days_row[0],
        books_no_pages=row["no_pages"] if row else 0,
    )


# ── Top lists ─────────────────────────────────────────────────────────────────

def top_authors(conn: sqlite3.Connection, year: int | None = None, limit: int = 10) -> list[dict]:
    where = "WHERE r.finished_on IS NOT NULL"
    params: list = []
    if year is not None:
        where += " AND substr(r.finished_on, 1, 4) = ?"
        params.append(str(year))
    rows = conn.execute(
        f"""
        SELECT b.author, COUNT(*) AS cnt
        FROM reading_log r
        JOIN books b ON b.id = r.book_id
        {where} AND b.author IS NOT NULL
        GROUP BY b.author
        ORDER BY cnt DESC
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    return [{"author": r["author"], "count": r["cnt"]} for r in rows]


def top_genres(conn: sqlite3.Connection, year: int | None = None, limit: int = 10) -> list[dict]:
    # genres may be comma-separated; we split in Python
    where = "WHERE r.finished_on IS NOT NULL"
    params: list = []
    if year is not None:
        where += " AND substr(r.finished_on, 1, 4) = ?"
        params.append(str(year))
    rows = conn.execute(
        f"""
        SELECT b.genre
        FROM reading_log r
        JOIN books b ON b.id = r.book_id
        {where} AND b.genre IS NOT NULL
        """,
        params,
    ).fetchall()

    genre_counts: dict[str, int] = {}
    for r in rows:
        for g in [x.strip() for x in (r["genre"] or "").split(",") if x.strip()]:
            genre_counts[g] = genre_counts.get(g, 0) + 1

    sorted_genres = sorted(genre_counts.items(), key=lambda x: -x[1])[:limit]
    return [{"genre": g, "count": c} for g, c in sorted_genres]


# ── Library overview ──────────────────────────────────────────────────────────

@dataclass
class LibraryOverview:
    total_books: int
    total_size_bytes: int
    read_count: int
    want_count: int
    by_source: dict[str, int]        # source → count
    books_added_last_30: int
    undated_reads: int               # Read books without finish date


def library_overview(conn: sqlite3.Connection) -> LibraryOverview:
    total = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM books WHERE is_missing = 0"
    ).fetchone()

    status_counts = {
        r["status"]: r["cnt"]
        for r in conn.execute(
            """SELECT COALESCE(status,'none') AS status, COUNT(*) AS cnt
               FROM books WHERE is_missing=0 GROUP BY status"""
        ).fetchall()
    }

    by_source = {
        r["source"]: r["cnt"]
        for r in conn.execute(
            "SELECT COALESCE(source,'local') AS source, COUNT(*) AS cnt FROM books WHERE is_missing=0 GROUP BY source"
        ).fetchall()
    }

    recent = conn.execute(
        "SELECT COUNT(*) FROM books WHERE is_missing=0 AND date_added >= datetime('now','-30 days')"
    ).fetchone()[0]

    undated = conn.execute(
        """SELECT COUNT(*) FROM books b
           WHERE b.status = 'read' AND b.is_missing = 0
             AND NOT EXISTS (
               SELECT 1 FROM reading_log r
               WHERE r.book_id = b.id AND r.finished_on IS NOT NULL
             )"""
    ).fetchone()[0]

    return LibraryOverview(
        total_books=total[0],
        total_size_bytes=total[1],
        read_count=status_counts.get("read", 0),
        want_count=status_counts.get("want", 0),
        by_source=by_source,
        books_added_last_30=recent,
        undated_reads=undated,
    )


def undated_read_books(conn: sqlite3.Connection) -> list[dict]:
    """Books marked Read but with no finish date in reading_log."""
    rows = conn.execute(
        """SELECT b.id, b.title, b.author, b.status_changed_at, b.date_added
           FROM books b
           WHERE b.status = 'read' AND b.is_missing = 0
             AND NOT EXISTS (
               SELECT 1 FROM reading_log r
               WHERE r.book_id = b.id AND r.finished_on IS NOT NULL
             )
           ORDER BY b.title COLLATE NOCASE"""
    ).fetchall()
    return [dict(r) for r in rows]


def available_years(conn: sqlite3.Connection) -> list[int]:
    """All years that have at least one finished reading."""
    rows = conn.execute(
        """SELECT DISTINCT CAST(substr(finished_on, 1, 4) AS INTEGER) AS year
           FROM reading_log WHERE finished_on IS NOT NULL ORDER BY year"""
    ).fetchall()
    return [r["year"] for r in rows]


# ── v6 Reading Sessions & Time Queries ────────────────────────────────────────

@dataclass
class ReadingTimeStats:
    seconds_today: int
    seconds_this_week: int
    seconds_this_month: int
    seconds_this_year: int
    seconds_total: int


def reading_time_stats(conn: sqlite3.Connection) -> ReadingTimeStats:
    """Calculate aggregated reading times across various periods."""
    try:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN date(started_at) IN (date('now'), date('now', 'localtime')) THEN active_seconds ELSE 0 END), 0) AS sec_today,
                COALESCE(SUM(CASE WHEN started_at >= datetime('now', '-7 days') OR started_at >= datetime('now', 'localtime', '-7 days') THEN active_seconds ELSE 0 END), 0) AS sec_week,
                COALESCE(SUM(CASE WHEN started_at >= datetime('now', '-30 days') OR started_at >= datetime('now', 'localtime', '-30 days') THEN active_seconds ELSE 0 END), 0) AS sec_month,
                COALESCE(SUM(CASE WHEN strftime('%Y', started_at) IN (strftime('%Y', 'now'), strftime('%Y', 'now', 'localtime')) THEN active_seconds ELSE 0 END), 0) AS sec_year,
                COALESCE(SUM(active_seconds), 0) AS sec_total
            FROM reading_sessions
            """
        ).fetchone()
        if row:
            return ReadingTimeStats(
                seconds_today=int(row["sec_today"]),
                seconds_this_week=int(row["sec_week"]),
                seconds_this_month=int(row["sec_month"]),
                seconds_this_year=int(row["sec_year"]),
                seconds_total=int(row["sec_total"]),
            )
    except Exception:
        pass

    return ReadingTimeStats(0, 0, 0, 0, 0)


@dataclass
class ReadingStreak:
    current_streak_days: int
    longest_streak_days: int
    last_read_date: str | None


def calculate_reading_streak(conn: sqlite3.Connection, min_seconds_per_day: int = 300) -> ReadingStreak:
    """
    Calculate current and longest consecutive reading day streaks.
    A day counts towards the streak if total reading duration >= min_seconds_per_day.
    """
    try:
        rows = conn.execute(
            """
            SELECT date(started_at) as day_str, SUM(active_seconds) as total_sec
            FROM reading_sessions
            GROUP BY day_str
            HAVING total_sec >= ?
            ORDER BY day_str ASC
            """,
            (min_seconds_per_day,),
        ).fetchall()
    except Exception:
        return ReadingStreak(0, 0, None)

    if not rows:
        return ReadingStreak(0, 0, None)

    from datetime import date, datetime, timedelta

    days = [datetime.strptime(r["day_str"], "%Y-%m-%d").date() for r in rows]
    if not days:
        return ReadingStreak(0, 0, None)

    today = date.today()
    yesterday = today - timedelta(days=1)

    # 1. Longest streak
    longest = 1
    current_run = 1
    for i in range(1, len(days)):
        if days[i] == days[i - 1] + timedelta(days=1):
            current_run += 1
            if current_run > longest:
                longest = current_run
        elif days[i] > days[i - 1] + timedelta(days=1):
            current_run = 1

    # 2. Current streak (anchored at today or yesterday)
    last_day = days[-1]
    current_streak = 0
    if last_day in (today, yesterday):
        current_streak = 1
        curr_idx = len(days) - 1
        while curr_idx > 0 and days[curr_idx] == days[curr_idx - 1] + timedelta(days=1):
            current_streak += 1
            curr_idx -= 1

    return ReadingStreak(
        current_streak_days=current_streak,
        longest_streak_days=longest,
        last_read_date=last_day.isoformat(),
    )


@dataclass
class HeatmapDay:
    date_str: str          # YYYY-MM-DD
    duration_seconds: int
    level: int             # 0 to 4


def reading_heatmap(conn: sqlite3.Connection, total_days: int = 365) -> list[HeatmapDay]:
    """
    Generate daily reading activity sequence for the past total_days.
    Level: 0 (0m), 1 (1-15m), 2 (15-45m), 3 (45-90m), 4 (>90m).
    """
    from datetime import date, timedelta

    daily_totals: dict[str, int] = {}
    try:
        rows = conn.execute(
            """
            SELECT date(started_at) as day_str, SUM(active_seconds) as total_sec
            FROM reading_sessions
            WHERE started_at >= datetime('now', ? || ' days')
            GROUP BY day_str
            """,
            (f"-{total_days}",),
        ).fetchall()
        for r in rows:
            daily_totals[r["day_str"]] = int(r["total_sec"])
    except Exception:
        pass

    today = date.today()
    start_date = today - timedelta(days=total_days - 1)

    result = []
    curr = start_date
    while curr <= today:
        d_str = curr.isoformat()
        sec = daily_totals.get(d_str, 0)
        minutes = sec // 60
        if minutes == 0:
            lvl = 0
        elif minutes < 15:
            lvl = 1
        elif minutes < 45:
            lvl = 2
        elif minutes < 90:
            lvl = 3
        else:
            lvl = 4

        result.append(HeatmapDay(date_str=d_str, duration_seconds=sec, level=lvl))
        curr += timedelta(days=1)

    return result


@dataclass
class BookReadingTime:
    book_id: int
    title: str
    author: str
    total_seconds: int
    sessions_count: int


def top_read_books_by_time(conn: sqlite3.Connection, limit: int = 10) -> list[BookReadingTime]:
    """Return books with the most reading time recorded."""
    try:
        rows = conn.execute(
            """
            SELECT s.book_id, b.title, b.author,
                   SUM(s.active_seconds) as total_sec,
                   COUNT(s.id) as sessions
            FROM reading_sessions s
            JOIN books b ON s.book_id = b.id
            GROUP BY s.book_id
            ORDER BY total_sec DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            BookReadingTime(
                book_id=r["book_id"],
                title=r["title"] or "Untitled",
                author=r["author"] or "Unknown",
                total_seconds=int(r["total_sec"]),
                sessions_count=int(r["sessions"]),
            )
            for r in rows
        ]
    except Exception:
        return []


def book_reading_estimate(conn: sqlite3.Connection, book_id: int) -> dict[str, Any]:
    """
    Calculate reading time spent and estimate remaining time for a book.
    Returns:
    {
        "total_seconds": int,
        "speed_pages_per_hour": float,
        "est_seconds_left": int | None,
        "time_spent_text": str,
        "time_left_text": str,
    }
    """
    row = conn.execute(
        """
        SELECT b.pages, b.progress_percent,
               COALESCE(SUM(s.active_seconds), 0) as total_sec,
               COALESCE(SUM(CASE WHEN s.end_progress > s.start_progress THEN s.end_progress - s.start_progress ELSE 0 END), 0) as total_prog
        FROM books b
        LEFT JOIN reading_sessions s ON b.id = s.book_id
        WHERE b.id = ?
        GROUP BY b.id
        """,
        (book_id,),
    ).fetchone()

    if not row:
        return {
            "total_seconds": 0,
            "speed_pages_per_hour": 0.0,
            "est_seconds_left": None,
            "time_spent_text": "0m",
            "time_left_text": "",
        }

    total_sec = int(row["total_sec"])
    book_pages = row["pages"]
    progress_pct = row["progress_percent"] or 0.0
    total_prog = float(row["total_prog"])

    # Format time spent
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    spent_text = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"

    # Speed calculation (pages per hour)
    speed_pph = 0.0
    if total_sec >= 120 and book_pages and total_prog > 0:
        pages_read = total_prog * book_pages
        speed_pph = round((pages_read / total_sec) * 3600.0, 1)

    est_left_sec = None
    left_text = ""

    if progress_pct >= 99.0:
        left_text = "Finished"
    elif speed_pph > 0 and book_pages and book_pages > 0:
        remaining_pages = max(0, book_pages - int(book_pages * (progress_pct / 100.0)))
        est_left_sec = int((remaining_pages / speed_pph) * 3600)
        l_hrs = est_left_sec // 3600
        l_mins = (est_left_sec % 3600) // 60
        left_text = f"~{l_hrs}h {l_mins}m left" if l_hrs > 0 else f"~{l_mins}m left"
    elif total_sec >= 300 and 0.0 < progress_pct < 99.0:
        # Fallback to progress fraction
        fraction_read = progress_pct / 100.0
        est_total_sec = total_sec / fraction_read
        est_left_sec = max(0, int(est_total_sec - total_sec))
        l_hrs = est_left_sec // 3600
        l_mins = (est_left_sec % 3600) // 60
        left_text = f"~{l_hrs}h {l_mins}m left" if l_hrs > 0 else f"~{l_mins}m left"

    return {
        "total_seconds": total_sec,
        "speed_pages_per_hour": speed_pph,
        "est_seconds_left": est_left_sec,
        "time_spent_text": spent_text,
        "time_left_text": left_text,
    }


"""
stats/goals.py – Reading goal management and progress/pace calculation.
"""
from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class Goal:
    id: int
    year: int
    kind: str          # 'books' | 'pages'
    target: int


@dataclass
class GoalProgress:
    goal: Goal
    done: int              # books finished or pages read this year
    expected: int          # where you should be today to be on track
    difference: int        # done - expected  (positive = ahead)
    projection: int        # projected total at year end
    is_reached: bool


# ── CRUD ──────────────────────────────────────────────────────────────────────

def list_goals(conn: sqlite3.Connection) -> list[Goal]:
    rows = conn.execute(
        "SELECT id, year, kind, target FROM goals ORDER BY year DESC, kind"
    ).fetchall()
    return [Goal(**dict(r)) for r in rows]


def upsert_goal(conn: sqlite3.Connection, year: int, kind: str, target: int) -> None:
    """Create or update a goal."""
    if kind not in ("books", "pages"):
        raise ValueError(f"Invalid goal kind: {kind!r}")
    if target <= 0:
        raise ValueError("Target must be > 0")
    conn.execute(
        """INSERT INTO goals (year, kind, target) VALUES (?, ?, ?)
           ON CONFLICT(year, kind) DO UPDATE SET target = excluded.target""",
        (year, kind, target),
    )
    conn.commit()


def delete_goal(conn: sqlite3.Connection, goal_id: int) -> None:
    conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    conn.commit()


# ── Progress ──────────────────────────────────────────────────────────────────

def goal_progress(
    conn: sqlite3.Connection,
    goal: Goal,
    today: date | None = None,
) -> GoalProgress:
    today = today or date.today()
    year = goal.year

    # Count finished books or pages this year
    if goal.kind == "books":
        row = conn.execute(
            """
            SELECT COUNT(*) FROM reading_log r
            WHERE substr(r.finished_on, 1, 4) = ? AND r.finished_on IS NOT NULL
            """,
            (str(year),),
        ).fetchone()
        done = row[0]
    else:  # pages
        row = conn.execute(
            """
            SELECT COALESCE(SUM(b.pages), 0)
            FROM reading_log r JOIN books b ON b.id = r.book_id
            WHERE substr(r.finished_on, 1, 4) = ? AND r.finished_on IS NOT NULL
              AND b.pages IS NOT NULL
            """,
            (str(year),),
        ).fetchone()
        done = row[0]

    # Pace calculation
    days_in_year = 366 if calendar.isleap(year) else 365
    if today.year == year:
        day_of_year = today.timetuple().tm_yday
    elif today.year > year:
        day_of_year = days_in_year  # year is complete
    else:
        day_of_year = 1  # year hasn't started

    expected = int(goal.target * day_of_year / days_in_year)
    difference = done - expected

    if day_of_year > 0:
        projection = int(done / day_of_year * days_in_year)
    else:
        projection = 0

    return GoalProgress(
        goal=goal,
        done=done,
        expected=expected,
        difference=difference,
        projection=projection,
        is_reached=(done >= goal.target),
    )


def pace_text(progress: GoalProgress) -> str:
    """Human-readable pace string, e.g. '2 books ahead of schedule'."""
    g = progress.goal
    unit = g.kind[:-1] if g.kind.endswith("s") else g.kind  # 'book' | 'page'
    diff = abs(progress.difference)

    if progress.difference > 0:
        return f"{diff} {unit}{'s' if diff != 1 else ''} ahead of schedule"
    elif progress.difference < 0:
        return f"{diff} {unit}{'s' if diff != 1 else ''} behind schedule"
    return "on track"


def all_goals_progress(
    conn: sqlite3.Connection,
    today: date | None = None,
) -> list[GoalProgress]:
    """Progress for all goals, current year first."""
    goals = list_goals(conn)
    return [goal_progress(conn, g, today) for g in goals]

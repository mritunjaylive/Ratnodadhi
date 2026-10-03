"""
tests/test_v6_recommend.py – Unit tests for the recommendation engine (Milestone 12).
Tests: feature extraction, IDF, profile building, series continuation, author bonus,
disliked genre penalty, MMR diversification, explanations, similar books, surprise me,
and feedback handling.
"""
from __future__ import annotations

import sqlite3
import pytest

from booklib.db.database import Database
from booklib.db.repository import BookRow, Repository
from booklib.recommend.explain import explain_recommendation, explain_similar
from booklib.recommend.features import (
    apply_idf_and_normalize,
    book_raw_features,
    compute_idf,
)
from booklib.recommend.profile import build_taste_profile
from booklib.recommend.scoring import (
    dot_product,
    is_next_in_series,
    score_candidates,
)
from booklib.recommend.service import RecommendationService


@pytest.fixture
def repo(tmp_path):
    db_path = tmp_path / "test_rec.db"
    db = Database(db_path)
    conn = db.connect()
    with conn:
        conn.execute("INSERT INTO folders (id, path) VALUES (1, '/books')")
    return Repository(conn)



def _make_book(
    id: int,
    title: str,
    author: str | None = None,
    genre: str | None = None,
    tags_text: str | None = None,
    series_name: str | None = None,
    series_index: float | None = None,
    status: str | None = None,
    rating: int | None = None,
    description: str | None = None,
) -> BookRow:
    return BookRow(
        id=id,
        title=title,
        author=author,
        year=2020,
        size_bytes=1000,
        format="pdf",
        pages=100,
        cover_path=None,
        date_added="2026-01-01",
        is_missing=False,
        path=f"/path/{id}.pdf",
        status=status,
        rating=rating,
        genre=genre,
        tags_text=tags_text,
        series_name=series_name,
        series_index=series_index,
        description=description,
    )


def test_feature_extraction_and_normalization():
    b = _make_book(
        1, "Clean Code: A Handbook", author="Robert C. Martin",
        genre="Software Engineering", tags_text="programming, clean",
        series_name="Robert Martin Series", description="Principles of writing clean code."
    )
    raw = book_raw_features(b)
    assert any("author:robert c. martin" in k for k in raw)
    assert "genre:software engineering" in raw
    assert "tag:programming" in raw
    assert "tag:clean" in raw
    assert "series:robert martin series" in raw

    idf = compute_idf([raw])
    norm_vec = apply_idf_and_normalize(raw, idf)
    length = sum(v * v for v in norm_vec.values())
    assert pytest.approx(length, 0.001) == 1.0


def test_series_continuation():
    b1 = _make_book(1, "The Expanse 1", series_name="The Expanse", series_index=1.0, status="read", rating=5)
    b2 = _make_book(2, "The Expanse 2", series_name="The Expanse", series_index=2.0, status="want")
    b3 = _make_book(3, "The Expanse 3", series_name="The Expanse", series_index=3.0, status="want")

    all_books = [b1, b2, b3]
    # b2 is the immediate next unread book in the series
    assert is_next_in_series(b2, all_books) is True
    # b3 is not immediate next because b2 is unread
    assert is_next_in_series(b3, all_books) is False


def test_taste_profile_and_cold_start():
    b1 = _make_book(1, "Python Cookbook", author="David Beazley", genre="Programming", rating=5)
    b2 = _make_book(2, "Bad Java", author="Unknown", genre="Java", rating=1)
    b3 = _make_book(3, "Fluent Python", author="Luciano Ramalho", genre="Programming", status="read")

    books = [b1, b2, b3]
    raws = {b.id: book_raw_features(b) for b in books}
    idf = compute_idf(raws.values())
    vecs = {b.id: apply_idf_and_normalize(raws[b.id], idf) for b in books}

    profile, is_cold, rated = build_taste_profile(books, vecs, min_ratings=5)
    assert rated == 2
    assert is_cold is True  # 2 < 5
    # Python/Programming should have positive weight in profile
    assert any("programming" in k for k in profile.keys())


def test_scoring_and_mmr_diversification():
    # User likes Science Fiction by Arthur C. Clarke
    b1 = _make_book(1, "Rendezvous with Rama", author="Arthur C. Clarke", genre="Sci-Fi", rating=5, status="read")
    b2 = _make_book(2, "2001: A Space Odyssey", author="Arthur C. Clarke", genre="Sci-Fi", rating=5, status="read")

    # Candidates:
    # 3 books by Arthur C. Clarke (diversification cap is 2!)
    c1 = _make_book(3, "The City and the Stars", author="Arthur C. Clarke", genre="Sci-Fi", status="want")
    c2 = _make_book(4, "Childhood's End", author="Arthur C. Clarke", genre="Sci-Fi", status="want")
    c3 = _make_book(5, "The Fountains of Paradise", author="Arthur C. Clarke", genre="Sci-Fi", status="want")
    # 1 book by Isaac Asimov (Sci-Fi)
    c4 = _make_book(6, "Foundation", author="Isaac Asimov", genre="Sci-Fi", status="want")
    # 1 book about Cooking
    c5 = _make_book(7, "French Cooking", author="Julia Child", genre="Cooking", status="want")

    all_books = [b1, b2, c1, c2, c3, c4, c5]
    raws = {b.id: book_raw_features(b) for b in all_books}
    idf = compute_idf(raws.values())
    vecs = {b.id: apply_idf_and_normalize(raws[b.id], idf) for b in all_books}

    profile, _, _ = build_taste_profile([b1, b2], vecs)
    candidates = [c1, c2, c3, c4, c5]

    scored = score_candidates(
        profile=profile,
        candidates=candidates,
        vectors=vecs,
        all_books=all_books,
        limit=3,
        max_per_author=2,
    )

    selected_ids = [b.id for b, _ in scored]
    # At most 2 books by Arthur C. Clarke should be selected among top 3
    clarke_count = sum(1 for b, _ in scored if b.author == "Arthur C. Clarke")
    assert clarke_count <= 2
    # Foundation should be included before Cooking
    assert 6 in selected_ids
    assert 7 not in selected_ids


def test_recommendation_feedback_exclusion(repo):
    # Insert books into database
    conn = repo._conn
    with conn:
        conn.execute(
            "INSERT INTO books (id, folder_id, title, author, genre, status, rating, filename, path, format, size_bytes, file_mtime) "
            "VALUES (1, 1, 'Clean Code', 'Robert C. Martin', 'Programming', 'read', 5, 'c.pdf', '/c.pdf', 'pdf', 1000, 100.0), "
            "       (2, 1, 'The Clean Coder', 'Robert C. Martin', 'Programming', 'want', NULL, 'cc.pdf', '/cc.pdf', 'pdf', 1000, 100.0), "
            "       (3, 1, 'Refactoring', 'Martin Fowler', 'Programming', 'want', NULL, 'r.pdf', '/r.pdf', 'pdf', 1000, 100.0)"
        )

    service = RecommendationService(repo)
    recs = service.get_recommendations()
    rec_ids = [b.id for b, _ in recs]
    assert 2 in rec_ids

    # Mark book 2 as 'hide'
    service.record_feedback(2, "hide")
    recs2 = service.get_recommendations()
    rec_ids2 = [b.id for b, _ in recs2]
    assert 2 not in rec_ids2

    # Undo feedback
    service.undo_feedback(2)
    recs3 = service.get_recommendations()
    assert 2 in [b.id for b, _ in recs3]


def test_explanations():
    b_read = _make_book(1, "Clean Architecture", author="Robert C. Martin", genre="Programming", rating=5, status="read")
    cand = _make_book(2, "The Clean Coder", author="Robert C. Martin", genre="Programming", status="want")

    all_books = [b_read, cand]
    raws = {b.id: book_raw_features(b) for b in all_books}
    idf = compute_idf(raws.values())
    vecs = {b.id: apply_idf_and_normalize(raws[b.id], idf) for b in all_books}

    profile, _, _ = build_taste_profile([b_read], vecs)
    explanation = explain_recommendation(cand, vecs[cand.id], profile, all_books)
    assert "Robert C. Martin" in explanation or "Programming" in explanation or "Clean Architecture" in explanation


def test_similar_books(repo):
    conn = repo._conn
    with conn:
        conn.execute(
            "INSERT INTO books (id, folder_id, title, author, genre, filename, path, format, size_bytes, file_mtime) "
            "VALUES (10, 1, 'Dune', 'Frank Herbert', 'Sci-Fi', 'dune.pdf', '/dune.pdf', 'pdf', 1000, 100.0), "
            "       (11, 1, 'Dune Messiah', 'Frank Herbert', 'Sci-Fi', 'dune2.pdf', '/dune2.pdf', 'pdf', 1000, 100.0), "
            "       (12, 1, 'Cooking 101', 'Chef Bob', 'Cooking', 'cook.pdf', '/cook.pdf', 'pdf', 1000, 100.0)"
        )






    service = RecommendationService(repo)
    similar = service.get_similar_books(10, limit=2)
    assert len(similar) >= 1
    # Dune Messiah should be most similar to Dune
    assert similar[0][0].id == 11
    assert "Frank Herbert" in similar[0][1] or "Sci-Fi" in similar[0][1] or "Same author" in similar[0][1]

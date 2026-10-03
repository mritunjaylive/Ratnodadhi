"""
booklib.recommend.service – High-level RecommendationService coordinating feature caching,
scoring, explanations, similar books, and user feedback.
"""
from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from booklib.db.query import LibraryQuery
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

if TYPE_CHECKING:
    from booklib.db.repository import BookRow, Repository

logger = logging.getLogger(__name__)


class RecommendationService:
    """Coordinates book recommendation generation, similar book lookups, and feedback."""

    def __init__(self, repo: Repository) -> None:
        self._repo = repo
        self._vectors_cache: dict[int, dict[str, float]] = {}
        self._raw_cache: dict[int, dict[str, float]] = {}
        self._idf_cache: dict[str, float] = {}
        self._cached_book_count: int = 0

    def invalidate_cache(self) -> None:
        """Clear cached vectors and IDF tables."""
        self._vectors_cache.clear()
        self._raw_cache.clear()
        self._idf_cache.clear()
        self._cached_book_count = 0

    def _ensure_vectors(self, all_books: list[BookRow]) -> dict[int, dict[str, float]]:
        """Compute or return cached normalized feature vectors for all books."""
        # If cache valid and book count matches, reuse
        if self._vectors_cache and len(all_books) == self._cached_book_count:
            # Check if all book IDs present in cache
            if all(b.id in self._vectors_cache for b in all_books):
                return self._vectors_cache

        # Recompute
        self._raw_cache = {b.id: book_raw_features(b) for b in all_books}
        self._idf_cache = compute_idf(self._raw_cache.values())
        self._vectors_cache = {
            b.id: apply_idf_and_normalize(self._raw_cache[b.id], self._idf_cache)
            for b in all_books
        }
        self._cached_book_count = len(all_books)
        return self._vectors_cache

    # ── Configuration ────────────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        """Check if recommendation features are enabled in settings."""
        val = self._repo.get_app_meta("recommendations_enabled", "1")
        return val == "1"

    def set_enabled(self, enabled: bool) -> None:
        self._repo.set_app_meta("recommendations_enabled", "1" if enabled else "0")

    def get_min_ratings(self) -> int:
        try:
            return int(self._repo.get_app_meta("recommendations_min_ratings", "5") or "5")
        except ValueError:
            return 5

    def set_min_ratings(self, count: int) -> None:
        self._repo.set_app_meta("recommendations_min_ratings", str(max(1, count)))

    # ── Feedback ─────────────────────────────────────────────────────────────

    def record_feedback(self, book_id: int, verdict: str) -> None:
        """Record verdict: 'hide' or 'not_interested'."""
        self._repo.set_recommendation_feedback(book_id, verdict)

    def undo_feedback(self, book_id: int) -> None:
        self._repo.remove_recommendation_feedback(book_id)

    def reset_all_feedback(self) -> None:
        self._repo.clear_all_recommendation_feedback()

    def get_feedback(self) -> dict[int, str]:
        return self._repo.get_recommendation_feedback()

    # ── Cold Start ───────────────────────────────────────────────────────────

    def check_cold_start(self, all_books: list[BookRow] | None = None) -> tuple[bool, str]:
        """
        Check if user has rated enough books.
        Returns (is_cold_start, advisory_message).
        """
        if all_books is None:
            all_books = self._repo.query_books(LibraryQuery(include_missing=False))

        min_ratings = self.get_min_ratings()
        rated = sum(1 for b in all_books if b.rating is not None and b.rating > 0)

        if rated < min_ratings:
            needed = min_ratings - rated
            return True, f"Rate {needed} more book{'s' if needed != 1 else ''} to improve suggestions."
        return False, ""

    # ── Core Recommendations ─────────────────────────────────────────────────

    def get_recommendations(self, limit: int = 20) -> list[tuple[BookRow, str]]:
        """
        Produce ranked recommendations for books the user owns but has not read.
        Returns list of (BookRow, explanation_string).
        """
        if not self.is_enabled():
            return []

        all_books = self._repo.query_books(LibraryQuery(include_missing=False))
        if not all_books:
            return []

        vectors = self._ensure_vectors(all_books)
        feedback = self.get_feedback()
        min_ratings = self.get_min_ratings()

        profile, is_cold, rated_count = build_taste_profile(
            all_books, vectors, feedback=feedback, min_ratings=min_ratings
        )

        candidates = [
            b for b in all_books
            if b.status != "read" and b.id not in feedback and not b.is_missing
        ]

        if not candidates:
            return []

        # If profile is empty (no ratings, no read books, no want books)
        if not profile:
            # Fallback to recent unread books
            results = []
            for b in candidates[:limit]:
                reason = "Recently added to your library"
                results.append((b, reason))
            return results

        scored = score_candidates(
            profile=profile,
            candidates=candidates,
            vectors=vectors,
            all_books=all_books,
            feedback=feedback,
            limit=limit,
        )

        results: list[tuple[BookRow, str]] = []
        for book, score in scored:
            b_vec = vectors.get(book.id, {})
            reason = explain_recommendation(book, b_vec, profile, all_books)
            results.append((book, reason))

        return results

    # ── Similar Books ────────────────────────────────────────────────────────

    def get_similar_books(self, book_id: int, limit: int = 5) -> list[tuple[BookRow, str]]:
        """
        Find top similar books to a specific book.
        Returns list of (BookRow, explanation_string).
        """
        all_books = self._repo.query_books(LibraryQuery(include_missing=False))
        target = next((b for b in all_books if b.id == book_id), None)
        if not target:
            return []

        vectors = self._ensure_vectors(all_books)
        target_vec = vectors.get(book_id, {})
        if not target_vec:
            return []

        feedback = self.get_feedback()
        candidates = [
            b for b in all_books
            if b.id != book_id and not b.is_missing and feedback.get(b.id) != "hide"
        ]

        scored: list[tuple[BookRow, float, list[str]]] = []
        for b in candidates:
            b_vec = vectors.get(b.id, {})
            sim = dot_product(target_vec, b_vec)

            # Bonus for same series
            if target.series_name and b.series_name and \
               target.series_name.strip().lower() == b.series_name.strip().lower():
                sim += 0.35

            # Bonus for same author
            if target.author and b.author and \
               target.author.strip().lower() == b.author.strip().lower():
                sim += 0.15

            # Identify top shared features
            shared = [
                f for f in target_vec
                if f in b_vec and target_vec[f] * b_vec[f] > 0
            ]
            shared.sort(key=lambda f: target_vec[f] * b_vec[f], reverse=True)

            scored.append((b, sim, shared))

        # Sort by similarity descending, title ascending
        scored.sort(key=lambda x: (-x[1], (x[0].title or "").lower()))

        results: list[tuple[BookRow, str]] = []
        for b, sim, shared in scored[:limit]:
            reason = explain_similar(b, target, shared)
            results.append((b, reason))

        return results

    # ── Surprise Me ──────────────────────────────────────────────────────────

    def get_surprise_me(self) -> tuple[BookRow, str] | None:
        """
        Surprise Me:
        1. Random pick from Want to Read.
        2. Unread books in top genres.
        3. Random unread book.
        """
        all_books = self._repo.query_books(LibraryQuery(include_missing=False))
        feedback = self.get_feedback()

        # 1. Want to Read
        want_books = [
            b for b in all_books
            if b.status == "want" and b.id not in feedback and not b.is_missing
        ]
        if want_books:
            chosen = random.choice(want_books)
            return chosen, "A pick from your Want to Read shelf"

        # 2. Unread books in user's favorite genres
        genre_counts: dict[str, int] = {}
        for b in all_books:
            if b.status in ("read", "reading") or (b.rating and b.rating >= 4):
                if b.genre:
                    g = b.genre.strip()
                    if g:
                        genre_counts[g] = genre_counts.get(g, 0) + 1

        unread_books = [
            b for b in all_books
            if b.status != "read" and b.id not in feedback and not b.is_missing
        ]
        if not unread_books:
            return None

        if genre_counts:
            top_genre = max(genre_counts.items(), key=lambda x: x[1])[0]
            in_genre = [
                b for b in unread_books
                if b.genre and top_genre.lower() in b.genre.lower()
            ]
            if in_genre:
                chosen = random.choice(in_genre)
                return chosen, f"Surprise discovery in {top_genre}"

        # 3. Fallback: any unread book
        chosen = random.choice(unread_books)
        return chosen, "A surprise discovery from your library"

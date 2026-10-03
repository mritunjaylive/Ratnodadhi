"""
booklib.recommend.scoring – Candidate scoring, bonus adjustments, and MMR diversification.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from booklib.recommend.features import normalize_term

if TYPE_CHECKING:
    from booklib.db.repository import BookRow


def dot_product(v1: dict[str, float], v2: dict[str, float]) -> float:
    """Compute dot product between two sparse vectors."""
    if len(v1) > len(v2):
        v1, v2 = v2, v1
    return sum(val * v2[f] for f, val in v1.items() if f in v2)


def is_next_in_series(candidate: BookRow, all_books: list[BookRow]) -> bool:
    """
    Check if candidate is the next unread book in an active series.
    Active means an earlier book in the series was read or rated >= 4.
    """
    if not candidate.series_name or candidate.series_index is None:
        return False

    c_sname = normalize_term(candidate.series_name)
    c_idx = candidate.series_index

    # Find books in the same series
    series_books = [
        b for b in all_books
        if b.series_name and normalize_term(b.series_name) == c_sname and b.series_index is not None
    ]

    # Earlier books
    earlier_books = [b for b in series_books if b.series_index < c_idx]
    if not earlier_books:
        return False

    # Check if any earlier book was read or liked (>= 4 stars)
    has_read_prior = any(
        b.status == "read" or (b.rating is not None and b.rating >= 4)
        for b in earlier_books
    )
    if not has_read_prior:
        return False

    # Check if there is an unread book with an index strictly between the highest read book and candidate
    max_read_idx = max(
        (b.series_index for b in earlier_books if b.status == "read" or (b.rating is not None and b.rating >= 4)),
        default=0.0
    )
    # Are there any unread books between max_read_idx and c_idx?
    unread_between = any(
        max_read_idx < b.series_index < c_idx and b.status != "read"
        for b in series_books
    )
    return not unread_between


def compute_author_avg_ratings(all_books: list[BookRow]) -> dict[str, float]:
    """Calculate average user rating per normalized author."""
    author_ratings: dict[str, list[int]] = {}
    for b in all_books:
        if b.author and b.rating is not None and b.rating > 0:
            for auth in re.split(r"[,;&]|\band\b", b.author, flags=re.IGNORECASE):
                a_clean = normalize_term(auth)
                if a_clean:
                    author_ratings.setdefault(a_clean, []).append(b.rating)

    return {
        author: sum(ratings) / len(ratings)
        for author, ratings in author_ratings.items()
    }


def compute_disliked_genres(all_books: list[BookRow]) -> set[str]:
    """
    Identify genres with at least one 1-2 star rating and an average rating < 3.0.
    """
    genre_ratings: dict[str, list[int]] = {}
    for b in all_books:
        if b.genre and b.rating is not None and b.rating > 0:
            for g in re.split(r"[,;/]", b.genre):
                g_clean = normalize_term(g)
                if g_clean:
                    genre_ratings.setdefault(g_clean, []).append(b.rating)

    disliked = set()
    for g, ratings in genre_ratings.items():
        if any(r <= 2 for r in ratings) and (sum(ratings) / len(ratings)) < 3.0:
            disliked.add(g)
    return disliked


def score_candidates(
    profile: dict[str, float],
    candidates: list[BookRow],
    vectors: dict[int, dict[str, float]],
    all_books: list[BookRow],
    feedback: dict[int, str] | None = None,
    limit: int = 20,
    lambda_param: float = 0.75,
    max_per_author: int = 2,
    max_per_series: int = 2,
) -> list[tuple[BookRow, float]]:
    """
    Score candidates and apply MMR diversification.
    Returns list of (BookRow, final_score).
    """
    feedback = feedback or {}
    author_avgs = compute_author_avg_ratings(all_books)
    disliked_genres = compute_disliked_genres(all_books)

    scored_candidates: list[tuple[BookRow, float, dict[str, float]]] = []

    for book in candidates:
        if book.is_missing or book.status == "read":
            continue
        if book.id in feedback and feedback[book.id] in ("hide", "not_interested"):
            continue

        b_vec = vectors.get(book.id, {})
        base_sim = dot_product(profile, b_vec)

        # Series continuation bonus
        series_bonus = 0.30 if is_next_in_series(book, all_books) else 0.0

        # Author affinity bonus: 0.10 * (avg_rating - 3) / 2
        author_bonus = 0.0
        if book.author:
            for auth in re.split(r"[,;&]|\band\b", book.author, flags=re.IGNORECASE):
                a_clean = normalize_term(auth)
                if a_clean in author_avgs:
                    author_bonus = max(author_bonus, 0.10 * (author_avgs[a_clean] - 3.0) / 2.0)

        # Disliked genre penalty
        genre_penalty = 0.0
        if book.genre:
            for g in re.split(r"[,;/]", book.genre):
                if normalize_term(g) in disliked_genres:
                    genre_penalty = 0.20
                    break

        final_score = base_sim + series_bonus + author_bonus - genre_penalty
        scored_candidates.append((book, final_score, b_vec))

    if not scored_candidates:
        return []

    # Maximal Marginal Relevance (MMR) Diversification
    selected: list[tuple[BookRow, float]] = []
    selected_vecs: list[dict[str, float]] = []
    author_counts: dict[str, int] = {}
    series_counts: dict[str, int] = {}

    remaining = list(scored_candidates)

    while remaining and len(selected) < limit:
        best_candidate = None
        best_idx = -1
        best_mmr = -float("inf")

        # First try: strictly respect the author and series caps
        candidates_pool = []
        for i, (b, s, v) in enumerate(remaining):
            primary_auth = normalize_term(re.split(r"[,;&]", b.author)[0]) if b.author else ""
            series = normalize_term(b.series_name) if b.series_name else ""
            if (primary_auth and author_counts.get(primary_auth, 0) >= max_per_author) or \
               (series and series_counts.get(series, 0) >= max_per_series):
                continue
            candidates_pool.append(i)

        # If all remaining are capped, allow them
        if not candidates_pool:
            candidates_pool = list(range(len(remaining)))

        for i in candidates_pool:
            b, s, v = remaining[i]
            sim_to_sel = max((dot_product(v, sv) for sv in selected_vecs), default=0.0)
            mmr = lambda_param * s - (1.0 - lambda_param) * sim_to_sel

            # Deterministic tie-breaker: mmr, title, id
            if mmr > best_mmr:
                best_mmr = mmr
                best_candidate = (b, s, v)
                best_idx = i
            elif abs(mmr - best_mmr) < 1e-9:
                if best_candidate and (b.title or "").lower() < (best_candidate[0].title or "").lower():
                    best_mmr = mmr
                    best_candidate = (b, s, v)
                    best_idx = i

        if best_idx >= 0 and best_candidate:
            b, s, v = remaining.pop(best_idx)
            selected.append((b, s))
            selected_vecs.append(v)
            if b.author:
                primary_auth = normalize_term(re.split(r"[,;&]", b.author)[0])
                author_counts[primary_auth] = author_counts.get(primary_auth, 0) + 1
            if b.series_name:
                series = normalize_term(b.series_name)
                series_counts[series] = series_counts.get(series, 0) + 1
        else:
            break

    return selected

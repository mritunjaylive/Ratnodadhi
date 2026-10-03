"""
booklib.recommend.explain – Human-readable explanations for recommendations.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from booklib.recommend.features import normalize_term
from booklib.recommend.scoring import is_next_in_series

if TYPE_CHECKING:
    from booklib.db.repository import BookRow


def explain_recommendation(
    candidate: BookRow,
    candidate_vec: dict[str, float],
    profile: dict[str, float],
    all_books: list[BookRow],
) -> str:
    """
    Produce a concise, user-friendly explanation line for a recommended book.
    """
    # 1. Series continuation
    if is_next_in_series(candidate, all_books):
        idx_str = f" (Book {candidate.series_index:g})" if candidate.series_index is not None else ""
        return f"Next in the {candidate.series_name} series{idx_str}"

    # 2. Top contributing feature to dot product
    contributions = [
        (f, profile[f] * candidate_vec[f])
        for f in candidate_vec
        if f in profile and profile[f] * candidate_vec[f] > 0
    ]
    contributions.sort(key=lambda x: x[1], reverse=True)

    rated_books = [b for b in all_books if b.rating is not None and b.rating >= 4]
    read_books = [b for b in all_books if b.status == "read"]

    for feat, score in contributions:
        if feat.startswith("author:"):
            auth_key = feat[7:]
            # Look for highest-rated book by this author
            author_liked = [
                b for b in rated_books
                if b.author and auth_key in normalize_term(b.author)
            ]
            if author_liked:
                best = max(author_liked, key=lambda b: b.rating or 0)
                stars = f"{best.rating} stars" if best.rating != 1 else "1 star"
                return f"Because you rated '{best.title}' {stars} by {candidate.author}"

            author_read = [
                b for b in read_books
                if b.author and auth_key in normalize_term(b.author)
            ]
            if author_read:
                return f"Because you read '{author_read[0].title}' by {candidate.author}"

            return f"Because you enjoy books by {candidate.author}"

        elif feat.startswith("genre:"):
            genre_key = feat[6:]
            genre_display = genre_key.title()
            liked_in_genre = [
                b for b in rated_books
                if b.genre and genre_key in normalize_term(b.genre)
            ]
            if liked_in_genre:
                best = max(liked_in_genre, key=lambda b: b.rating or 0)
                stars = f"{best.rating} stars" if best.rating != 1 else "1 star"
                return f"Because you rated '{best.title}' {stars} and read other {genre_display} books"

            read_in_genre = [
                b for b in read_books
                if b.genre and genre_key in normalize_term(b.genre)
            ]
            if read_in_genre:
                return f"Because you read other {genre_display} books"

            return f"Because you enjoy {genre_display} books"

        elif feat.startswith("tag:"):
            tag_key = feat[4:]
            liked_with_tag = [
                b for b in rated_books
                if b.tags_text and tag_key in normalize_term(b.tags_text)
            ]
            if liked_with_tag:
                best = max(liked_with_tag, key=lambda b: b.rating or 0)
                return f"Because you enjoyed '{best.title}' and books tagged #{tag_key}"
            return f"Matches your interest in #{tag_key}"

        elif feat.startswith("series:"):
            return f"From the {candidate.series_name} series"

        elif feat.startswith("word:"):
            word_key = feat[5:]
            liked_with_word = [
                b for b in rated_books
                if word_key in (b.title or "").lower() or word_key in (b.description or "").lower()
            ]
            if liked_with_word:
                best = max(liked_with_word, key=lambda b: b.rating or 0)
                return f"Matches themes in '{best.title}' that you enjoyed"

    # Fallbacks
    if candidate.author:
        for b in read_books:
            if b.author and normalize_term(b.author) == normalize_term(candidate.author):
                return f"Because you enjoy books by {candidate.author}"

    if candidate.genre:
        return f"Because you enjoy {candidate.genre} books"

    return "Recommended based on your reading library"


def explain_similar(
    candidate: BookRow,
    target: BookRow,
    shared_features: list[str],
) -> str:
    """Explain why a candidate book is similar to target book."""
    if target.series_name and candidate.series_name and \
       normalize_term(target.series_name) == normalize_term(candidate.series_name):
        return f"Same series: {candidate.series_name}"

    if target.author and candidate.author and \
       normalize_term(target.author) == normalize_term(candidate.author):
        return f"Same author: {candidate.author}"

    # Check shared genre or tag
    shared_genres = [f[6:].title() for f in shared_features if f.startswith("genre:")]
    if shared_genres:
        return f"Similar genre: {', '.join(shared_genres[:2])}"

    shared_tags = [f"#{f[4:]}" for f in shared_features if f.startswith("tag:")]
    if shared_tags:
        return f"Shared tags: {', '.join(shared_tags[:3])}"

    return "Similar themes and topics"

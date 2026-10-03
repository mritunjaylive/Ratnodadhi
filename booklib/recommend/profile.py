"""
booklib.recommend.profile – Builds the user taste profile from ratings, reading history and feedback.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from booklib.db.repository import BookRow


def build_taste_profile(
    books: list[BookRow],
    vectors: dict[int, dict[str, float]],
    feedback: dict[int, str] | None = None,
    min_ratings: int = 5,
) -> tuple[dict[str, float], bool, int]:
    """
    Build user taste profile vector from books and their normalized feature vectors.

    Returns:
      (profile_vector, is_cold_start, rated_books_count)
    """
    feedback = feedback or {}
    profile: dict[str, float] = {}
    rated_count = 0

    for book in books:
        vec = vectors.get(book.id)
        if not vec:
            continue

        verdict = feedback.get(book.id)
        if verdict == "not_interested":
            # Negative signal for taste profile
            w = -1.5
            for f, val in vec.items():
                profile[f] = profile.get(f, 0.0) + w * val
            continue
        elif verdict == "hide":
            # Just ignore hidden books from building positive profile
            continue

        if book.rating is not None and book.rating > 0:
            rated_count += 1
            w = float(book.rating - 3)  # 1..5 stars -> -2..+2
            if w != 0:
                for f, val in vec.items():
                    profile[f] = profile.get(f, 0.0) + w * val
        elif book.status == "read":
            w = 0.5
            for f, val in vec.items():
                profile[f] = profile.get(f, 0.0) + w * val
        elif book.status == "reading":
            w = 0.4
            for f, val in vec.items():
                profile[f] = profile.get(f, 0.0) + w * val
        elif book.status == "want":
            w = 0.3
            for f, val in vec.items():
                profile[f] = profile.get(f, 0.0) + w * val

    is_cold_start = rated_count < min_ratings

    # L2-normalize the profile vector
    sum_sq = sum(v * v for v in profile.values())
    if sum_sq > 0:
        norm = math.sqrt(sum_sq)
        profile = {f: v / norm for f, v in profile.items()}
    else:
        profile = {}

    return profile, is_cold_start, rated_count

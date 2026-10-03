"""
scoring.py – Match scoring and decision logic for online metadata candidates.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

from booklib.metadata.online.models import Candidate


def _normalize_str(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r'[^\w\s]', '', s.lower())
    return re.sub(r'\s+', ' ', s).strip()


def _extract_surnames(author_str: str | list[str] | None) -> set[str]:
    if not author_str:
        return set()
    raw_list: list[str] = [author_str] if isinstance(author_str, str) else list(author_str)
    surnames = set()
    for item in raw_list:
        if not item:
            continue
        # Split on commas, semicolons, 'and'
        parts = re.split(r'[,;]|\band\b', item, flags=re.IGNORECASE)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if tokens:
                # The last token or if "Last, First" was split, the first token could be surname
                # Clean token
                clean_tokens = [_normalize_str(t) for t in tokens if _normalize_str(t)]
                if clean_tokens:
                    surnames.add(clean_tokens[-1])
                    surnames.add(clean_tokens[0])
    return {s for s in surnames if len(s) > 1}


def score_candidate(local_book: dict[str, Any], candidate: Candidate) -> float:
    """
    Score candidate against local book dict (0.0 to 1.0).
    Local book can have keys: 'isbn', 'title', 'author', 'year', 'pages'.
    """
    local_isbn = local_book.get("isbn")
    if local_isbn and candidate.isbn:
        clean_local = re.sub(r'[\s\-]+', '', local_isbn)
        clean_cand = re.sub(r'[\s\-]+', '', candidate.isbn)
        if clean_local and clean_cand and (clean_local == clean_cand or clean_local[-10:] == clean_cand[-10:]):
            return 1.0

    weights: list[tuple[float, float]] = []  # (weight, score)

    # 1. Title similarity (0.60)
    local_title = local_book.get("title")
    if local_title and candidate.title:
        norm_l = _normalize_str(local_title)
        norm_c = _normalize_str(candidate.title)
        ratio = difflib.SequenceMatcher(None, norm_l, norm_c).ratio()
        weights.append((0.60, ratio))
    elif local_title:
        weights.append((0.60, 0.0))

    # 2. Author match (0.25)
    local_author = local_book.get("author")
    if local_author:
        local_surnames = _extract_surnames(local_author)
        cand_surnames = _extract_surnames(candidate.authors)
        overlap = bool(local_surnames & cand_surnames)
        weights.append((0.25, 1.0 if overlap else 0.0))

    # 3. Year within ±2 (0.10)
    local_year = local_book.get("year")
    if local_year is not None:
        try:
            ly = int(local_year)
            if candidate.year is not None:
                diff = abs(ly - candidate.year)
                weights.append((0.10, 1.0 if diff <= 2 else 0.0))
            else:
                weights.append((0.10, 0.0))
        except (ValueError, TypeError):
            pass

    # 4. Page count within ±15% (0.05)
    local_pages = local_book.get("pages")
    if local_pages is not None:
        try:
            lp = int(local_pages)
            if lp > 0 and candidate.pages is not None:
                pdiff = abs(lp - candidate.pages) / lp
                weights.append((0.05, 1.0 if pdiff <= 0.15 else 0.0))
            else:
                weights.append((0.05, 0.0))
        except (ValueError, TypeError):
            pass

    if not weights:
        return 0.0

    total_weight = sum(w for w, _ in weights)
    if total_weight <= 0.0:
        return 0.0

    score = sum(w * s for w, s in weights) / total_weight
    return round(score, 4)


def decide_candidates(
    candidates: list[Candidate],
    threshold: float = 0.90,
    margin: float = 0.10,
) -> tuple[str, list[Candidate]]:
    """
    Evaluates sorted candidates (highest score first).
    Returns (decision, candidates), where decision is 'apply', 'review', or 'not_found'.
    """
    if not candidates:
        return "not_found", []

    # Sort descending by score
    sorted_cands = sorted(candidates, key=lambda c: c.score, reverse=True)
    best = sorted_cands[0]

    # Exact ISBN match
    if best.score >= 0.99 and best.matched_by == "isbn":
        return "apply", sorted_cands

    # Auto-apply condition
    second_score = sorted_cands[1].score if len(sorted_cands) > 1 else 0.0
    if best.score >= threshold and (best.score - second_score) >= margin:
        return "apply", sorted_cands

    # Review condition
    if best.score >= 0.60:
        return "review", sorted_cands[:5]

    return "not_found", sorted_cands[:5]

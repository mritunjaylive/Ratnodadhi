"""
fulltext/query.py – Query builder and search inside books execution with BM25 ranking.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from booklib.fulltext.snippets import make_snippet
from booklib.fulltext.store import FullTextStore

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    chunk_id: int
    book_id: int
    page_number: int
    chapter_index: int
    chunk_index: int
    token_start: int
    token_end: int
    snippet: str
    raw_text: str
    rank: float


@dataclass
class SearchResultGroup:
    book_id: int
    total_hits: int
    hits: list[SearchHit]


def build_fts5_query(user_query: str) -> str:
    """
    Transform raw user search string into a valid, safe FTS5 MATCH query.
    Handles:
    - Quoted phrases: "hello world"
    - Negations: -word or NOT word
    - Disjunctions: OR
    - Prefix: word*
    - Removes dangling punctuation and quotes.
    """
    q = user_query.strip()
    if not q:
        return ""

    tokens = []
    # Tokenize preserving quoted phrases
    pattern = re.compile(r'("[^"]*"|\S+)')
    raw_tokens = pattern.findall(q)

    for tok in raw_tokens:
        tok = tok.strip()
        if not tok:
            continue

        if tok.startswith('"') and tok.endswith('"') and len(tok) > 2:
            # Exact phrase
            phrase_inner = tok[1:-1].replace('"', '""')
            tokens.append(f'"{phrase_inner}"')
        elif tok.upper() == "OR":
            tokens.append("OR")
        elif tok.upper() == "NOT":
            tokens.append("NOT")
        elif tok.startswith("-") and len(tok) > 1:
            neg_term = re.sub(r'[^\w]', '', tok[1:])
            if neg_term:
                tokens.append(f'NOT "{neg_term}"')
        elif tok.endswith("*") and len(tok) > 1:
            prefix_term = re.sub(r'[^\w]', '', tok[:-1])
            if prefix_term:
                tokens.append(f'"{prefix_term}"*')
        else:
            word = re.sub(r'[^\w]', '', tok)
            if word:
                tokens.append(f'"{word}"')

    # Remove invalid leading/trailing boolean operators
    while tokens and tokens[0] in ("OR", "NOT"):
        tokens.pop(0)
    while tokens and tokens[-1] in ("OR", "NOT"):
        tokens.pop(-1)

    return " ".join(tokens)


def search_inside_books(
    store: FullTextStore,
    user_query: str,
    book_ids: list[int] | None = None,
    limit_books: int = 50,
    max_chunks_per_book: int = 5,
) -> list[SearchResultGroup]:
    """
    Execute full-text search across books index and return grouped hits.
    """
    safe_query = build_fts5_query(user_query)
    if not safe_query:
        return []

    conn = store.connect()
    where_parts = ["chunk_fts MATCH ?"]
    params: list[Any] = [safe_query]

    if book_ids is not None:
        if not book_ids:
            return []
        placeholders = ",".join("?" for _ in book_ids)
        where_parts.append(f"c.book_id IN ({placeholders})")
        params.extend(book_ids)

    where_clause = " AND ".join(where_parts)
    sql = f"""
    SELECT
        c.id,
        c.book_id,
        c.page_number,
        c.chapter_index,
        c.chunk_index,
        c.token_start,
        c.token_end,
        c.text,
        fts.rank
    FROM chunk_fts fts
    JOIN chunks c ON fts.rowid = c.id
    WHERE {where_clause}
    ORDER BY c.book_id ASC, fts.rank ASC
    """

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("FTS query failed: %s with query: %s", exc, safe_query)
        return []

    # Group by book_id
    grouped_hits: dict[int, list[SearchHit]] = {}
    for r in rows:
        bid = r["book_id"]
        raw = r["text"]
        snippet = make_snippet(raw, user_query)
        hit = SearchHit(
            chunk_id=r["id"],
            book_id=bid,
            page_number=r["page_number"] or 0,
            chapter_index=r["chapter_index"] or 0,
            chunk_index=r["chunk_index"] or 0,
            token_start=r["token_start"] or 0,
            token_end=r["token_end"] or 0,
            snippet=snippet,
            raw_text=raw,
            rank=r["rank"],
        )
        grouped_hits.setdefault(bid, []).append(hit)

    results: list[SearchResultGroup] = []
    for bid, hits in list(grouped_hits.items())[:limit_books]:
        # Sort each book's hits by rank
        hits.sort(key=lambda h: h.rank)
        results.append(
            SearchResultGroup(
                book_id=bid,
                total_hits=len(hits),
                hits=hits[:max_chunks_per_book],
            )
        )

    # Sort groups by best hit rank
    results.sort(key=lambda g: g.hits[0].rank if g.hits else 0)
    return results

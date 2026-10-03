"""
fulltext/snippets.py – Highlight matched terms and format context snippets.
"""
from __future__ import annotations

import html
import re


def extract_search_terms(query: str) -> list[str]:
    """Extract individual search words from a user query string."""
    cleaned = re.sub(r'["\']', " ", query)
    tokens = cleaned.split()
    terms = []
    for t in tokens:
        up = t.upper()
        if up in ("AND", "OR", "NOT") or t.startswith("-"):
            continue
        sub = re.sub(r"[^\w]", "", t).strip()
        if sub:
            terms.append(sub)
    return terms


def make_snippet(text: str, query: str, max_chars: int = 180) -> str:
    """
    Generate an HTML-safe context snippet with matching terms enclosed in <b>...</b>.
    """
    if not text:
        return ""

    terms = extract_search_terms(query)
    if not terms:
        # Return initial slice
        slice_text = text[:max_chars].strip()
        suffix = "…" if len(text) > max_chars else ""
        return html.escape(slice_text) + suffix

    # Find the earliest matching position
    lower_text = text.lower()
    first_pos = -1
    matched_term = ""
    for t in terms:
        pos = lower_text.find(t.lower())
        if pos != -1 and (first_pos == -1 or pos < first_pos):
            first_pos = pos
            matched_term = t

    if first_pos == -1:
        slice_text = text[:max_chars].strip()
        suffix = "…" if len(text) > max_chars else ""
        return html.escape(slice_text) + suffix

    # Calculate window around first match
    half = max_chars // 2
    start = max(0, first_pos - half)
    end = min(len(text), first_pos + half)

    # Align to word boundaries if possible
    if start > 0:
        space_before = text.rfind(" ", 0, start)
        if space_before != -1 and start - space_before < 20:
            start = space_before + 1

    if end < len(text):
        space_after = text.find(" ", end)
        if space_after != -1 and space_after - end < 20:
            end = space_after

    window = text[start:end].strip()
    escaped = html.escape(window)

    # Highlight matching terms
    for t in sorted(terms, key=len, reverse=True):
        pattern = re.compile(rf"\b({re.escape(html.escape(t))})\b", re.IGNORECASE)
        escaped = pattern.sub(r"<b>\1</b>", escaped)

    prefix = "… " if start > 0 else ""
    suffix = " …" if end < len(text) else ""
    return prefix + escaped + suffix

"""
reader/annotations.py – Annotations (highlights & notes), anchoring, export, and PDF import/export.
"""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import re
import sqlite3
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from booklib.reader.backend import Locator

logger = logging.getLogger(__name__)


# ── Text Tokenization & Anchoring Algorithm ───────────────────────────────────

def _normalize_token(text: str) -> str:
    """Normalize token: NFKC, lowercase, remove punctuation and hyphens."""
    n = unicodedata.normalize("NFKC", text or "").lower()
    # Strip punctuation and hyphens
    return re.sub(r"[^\w\s]", "", n).strip()


def anchor(
    words: list[str],
    quote: str,
    prefix: str = "",
    suffix: str = "",
    hint: tuple[int, int] | None = None,
) -> tuple[int, int] | None:
    """
    Pure anchoring algorithm to locate selected quote in a chapter's words list.

    1. Normalize quote and word tokens.
    2. Try exact token sequence match near hint range first, then full list.
    3. If multiple matches, disambiguate using prefix and suffix context.
    4. If no exact match, fallback to fuzzy match (similarity >= 0.85).
    5. Return (start_idx, end_idx) or None (orphaned).
    """
    if not words or not quote.strip():
        return None

    norm_words = [_normalize_token(w) for w in words]
    q_tokens = [_normalize_token(t) for t in quote.split() if _normalize_token(t)]
    if not q_tokens:
        return None

    q_len = len(q_tokens)
    norm_prefix = [_normalize_token(t) for t in prefix.split() if _normalize_token(t)]
    norm_suffix = [_normalize_token(t) for t in suffix.split() if _normalize_token(t)]

    # 1. Exact matches
    matches: list[int] = []
    # Search around hint first
    search_indices = list(range(len(norm_words) - q_len + 1))
    if hint is not None:
        h_start, _ = hint
        # Order by proximity to hint
        search_indices.sort(key=lambda idx: abs(idx - h_start))

    for i in search_indices:
        if norm_words[i:i + q_len] == q_tokens:
            matches.append(i)

    if matches:
        if len(matches) == 1:
            return (matches[0], matches[0] + q_len - 1)

        # Disambiguate multiple matches with prefix/suffix
        best_match = matches[0]
        best_score = -1.0
        for m in matches:
            score = 0.0
            # Check prefix
            if norm_prefix:
                p_ctx = norm_words[max(0, m - len(norm_prefix)):m]
                score += SequenceMatcher(None, p_ctx, norm_prefix).ratio()
            # Check suffix
            if norm_suffix:
                s_ctx = norm_words[m + q_len:m + q_len + len(norm_suffix)]
                score += SequenceMatcher(None, s_ctx, norm_suffix).ratio()

            if score > best_score:
                best_score = score
                best_match = m

        return (best_match, best_match + q_len - 1)

    # 2. Fuzzy match
    joined_quote = " ".join(q_tokens)
    best_fuzzy_idx = -1
    best_fuzzy_ratio = 0.0

    # Test windows of length q_len
    for i in range(len(norm_words) - q_len + 1):
        window = " ".join(norm_words[i:i + q_len])
        ratio = SequenceMatcher(None, window, joined_quote).ratio()
        if ratio > best_fuzzy_ratio:
            best_fuzzy_ratio = ratio
            best_fuzzy_idx = i

    if best_fuzzy_ratio >= 0.85 and best_fuzzy_idx >= 0:
        return (best_fuzzy_idx, best_fuzzy_idx + q_len - 1)

    return None  # Orphaned


# ── Database Operations ───────────────────────────────────────────────────────

def add_annotation(
    conn: sqlite3.Connection,
    book_id: int,
    kind: str,
    color: str,
    quote: str,
    prefix: str = "",
    suffix: str = "",
    locator: Locator | None = None,
    note: str | None = None,
    origin: str = "app",
) -> int:
    """Insert annotation and return its ID."""
    loc_json = locator.to_json() if locator else "{}"
    with conn:
        cur = conn.execute(
            """
            INSERT INTO annotations (book_id, kind, color, quote, prefix, suffix, locator, note, state, origin, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?, datetime('now'), datetime('now'))
            """,
            (book_id, kind, color, quote, prefix, suffix, loc_json, note, origin),
        )
        return cur.lastrowid


def update_annotation(
    conn: sqlite3.Connection,
    annot_id: int,
    note: str | None = None,
    color: str | None = None,
    state: str | None = None,
) -> None:
    """Update fields of an annotation."""
    updates = []
    params: list[Any] = []
    if note is not None:
        updates.append("note = ?")
        params.append(note)
    if color is not None:
        updates.append("color = ?")
        params.append(color)
    if state is not None:
        updates.append("state = ?")
        params.append(state)

    if not updates:
        return

    updates.append("updated_at = datetime('now')")
    params.append(annot_id)
    with conn:
        conn.execute(f"UPDATE annotations SET {', '.join(updates)} WHERE id = ?", params)


def delete_annotation(conn: sqlite3.Connection, annot_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM annotations WHERE id = ?", (annot_id,))


def list_annotations(
    conn: sqlite3.Connection,
    book_id: int | None = None,
    query: str | None = None,
    color: str | None = None,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    """List annotations with optional filters and FTS search."""
    where = []
    params: list[Any] = []

    if book_id is not None:
        where.append("a.book_id = ?")
        params.append(book_id)

    if color:
        where.append("a.color = ?")
        params.append(color)

    if kind:
        where.append("a.kind = ?")
        params.append(kind)

    if query and query.strip():
        # Search via annotations_fts
        safe_q = f'"{query.strip()}"'
        where.append("a.id IN (SELECT rowid FROM annotations_fts WHERE annotations_fts MATCH ?)")
        params.append(safe_q)

    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT a.*, b.title as book_title, b.author as book_author
        FROM annotations a
        JOIN books b ON a.book_id = b.id
        {where_clause}
        ORDER BY a.id ASC
    """
    rows = conn.execute(sql, params).fetchall()
    res = []
    for r in rows:
        d = dict(r)
        d["locator_obj"] = Locator.from_json(r["locator"])
        res.append(d)
    return res


# ── Export Formats ────────────────────────────────────────────────────────────

def export_markdown(annotations: list[dict[str, Any]], book_title: str = "", author: str = "") -> str:
    """Format annotations as clean Markdown."""
    lines = []
    if book_title:
        header = f"# {book_title}"
        if author:
            header += f" – {author}"
        lines.append(header)
        lines.append("")

    for a in annotations:
        loc = a.get("locator_obj") or Locator.from_json(a.get("locator", "{}"))
        page_str = f"Page {(loc.page or 0) + 1}" if loc.page is not None else ""
        date_str = (a.get("created_at") or "")[:10]
        meta_str = f"— {page_str}, {date_str}".strip(", ")

        color = a.get("color", "yellow")
        lines.append(f"> {a.get('quote', '')}")
        lines.append(f"> *{meta_str}* ({color})")
        if a.get("note"):
            lines.append("")
            lines.append(f"**Note:** {a['note']}")
        lines.append("")

    return "\n".join(lines)


def export_html(annotations: list[dict[str, Any]], book_title: str = "", author: str = "") -> str:
    """Format annotations as standalone HTML."""
    out = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        f"<title>{html.escape(book_title or 'Highlights')}</title>",
        "<style>",
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; max-width: 720px; margin: 40px auto; padding: 0 20px; }",
        "blockquote { margin: 16px 0; padding: 12px 16px; border-left: 4px solid #ffeb3b; background: #fffde7; }",
        ".meta { color: #666; font-size: 0.9em; margin-top: 4px; }",
        ".note { background: #f5f5f5; padding: 10px 14px; border-radius: 4px; margin-top: 8px; }",
        "</style></head><body>",
        f"<h1>{html.escape(book_title)}</h1>",
    ]
    if author:
        out.append(f"<h3>{html.escape(author)}</h3>")

    for a in annotations:
        loc = a.get("locator_obj") or Locator.from_json(a.get("locator", "{}"))
        p = f"Page {(loc.page or 0) + 1}" if loc.page is not None else ""
        out.append("<blockquote>")
        out.append(f"<div>{html.escape(a.get('quote', ''))}</div>")
        out.append(f"<div class='meta'>{html.escape(p)} · {html.escape(a.get('created_at', '')[:10])}</div>")
        if a.get("note"):
            out.append(f"<div class='note'><strong>Note:</strong> {html.escape(a['note'])}</div>")
        out.append("</blockquote>")

    out.append("</body></html>")
    return "\n".join(out)


def export_csv(annotations: list[dict[str, Any]]) -> str:
    """Export annotations as CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "Book ID", "Title", "Author", "Kind", "Color", "Quote", "Note", "Page", "Created At"])
    for a in annotations:
        loc = a.get("locator_obj") or Locator.from_json(a.get("locator", "{}"))
        p = (loc.page + 1) if loc.page is not None else ""
        writer.writerow([
            a.get("id", ""),
            a.get("book_id", ""),
            a.get("book_title", ""),
            a.get("book_author", ""),
            a.get("kind", ""),
            a.get("color", ""),
            a.get("quote", ""),
            a.get("note", ""),
            p,
            a.get("created_at", ""),
        ])
    return buf.getvalue()


def export_json(annotations: list[dict[str, Any]]) -> str:
    """Export annotations as JSON."""
    clean = []
    for a in annotations:
        d = {k: v for k, v in a.items() if k not in ("locator_obj",)}
        clean.append(d)
    return json.dumps(clean, indent=2, ensure_ascii=False)


# ── PDF Annotated Copy & Import ───────────────────────────────────────────────

def export_annotated_pdf(source_pdf_path: str, output_pdf_path: str, annotations: list[dict[str, Any]]) -> bool:
    """
    Create a new PDF copy containing native highlight annotations.
    The original file is NEVER modified.
    """
    src_p = Path(source_pdf_path)
    if not src_p.exists():
        return False

    try:
        doc = fitz.open(source_pdf_path)
        for a in annotations:
            loc = a.get("locator_obj") or Locator.from_json(a.get("locator", "{}"))
            if loc.page is not None and 0 <= loc.page < len(doc):
                page = doc[loc.page]
                # Look for stored fractional rects or search for quote
                quote = a.get("quote", "")
                rects = page.search_for(quote)
                if rects:
                    for r in rects:
                        annot = page.add_highlight_annot(r)
                        if a.get("note"):
                            annot.set_info(content=a["note"])
                        annot.update()

        doc.save(output_pdf_path)
        doc.close()
        return True
    except Exception as exc:
        logger.error("Failed to export annotated PDF copy: %s", exc)
        return False


def import_pdf_highlights(conn: sqlite3.Connection, book_id: int, pdf_path: str) -> int:
    """
    Import existing PDF highlights from file into database with origin='file'.
    The original file is untouched.
    Returns number of imported highlights.
    """
    if not Path(pdf_path).exists():
        return 0

    imported = 0
    try:
        doc = fitz.open(pdf_path)
        for pno in range(len(doc)):
            page = doc[pno]
            for annot in page.annots():
                # Highlight, underline, strikeout, text
                atype = annot.type[0]  # (8, 'Highlight'), (9, 'Underline'), (10, 'StrikeOut'), (0, 'Text')
                if atype in (8, 9, 10, 0):
                    content = annot.info.get("content", "")
                    rect = annot.rect
                    quote = page.get_text("text", clip=rect).strip() or content
                    loc = Locator(t="pdf", page=pno, y=float(rect.y0) / max(page.rect.height, 1.0))
                    kind = "highlight" if atype == 8 else ("underline" if atype == 9 else "note")
                    add_annotation(
                        conn,
                        book_id=book_id,
                        kind=kind,
                        color="yellow",
                        quote=quote,
                        locator=loc,
                        note=content if content != quote else "",
                        origin="file",
                    )
                    imported += 1
        doc.close()
    except Exception as exc:
        logger.warning("Failed to import PDF annotations: %s", exc)

    return imported

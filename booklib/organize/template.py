"""
organize/template.py – Parse and render rename/folder patterns.

Pattern syntax:
  {field}                 – insert field value
  {author:first}          – first author only
  {author:last}           – surname of first author
  {author:sort}           – "Surname, First" form
  {title:main}            – title before ": "
  {title:60}              – shorten to N chars at word boundary
  {series_index:02}       – zero-padded number
  {genre:first}           – first genre
  {field|fallback}        – literal text when field is empty
  [ ... ]                 – optional group: included only when every field inside is non-empty
  \\[ \\{                   – literal bracket / brace
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


# ── Tokenizer ──────────────────────────────────────────────────────────────────

@dataclass
class _Token:
    kind: str   # 'field' | 'literal' | 'opt_open' | 'opt_close'
    text: str   # raw text (for literals) or field spec
    field: str = ""
    modifier: str = ""
    fallback: str = ""


_FIELD_RE = re.compile(
    r"""
    \{
      (?P<field>[a-z_]+)
      (?::(?P<mod>[a-z0-9]+))?
      (?:\|(?P<fb>[^}]*))?
    \}
    """,
    re.VERBOSE,
)


def _tokenize(pattern: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "\\" and i + 1 < n:
            tokens.append(_Token("literal", pattern[i + 1]))
            i += 2
        elif ch == "[":
            tokens.append(_Token("opt_open", "["))
            i += 1
        elif ch == "]":
            tokens.append(_Token("opt_close", "]"))
            i += 1
        elif ch == "{":
            m = _FIELD_RE.match(pattern, i)
            if m:
                tok = _Token(
                    kind="field",
                    text=m.group(0),
                    field=m.group("field"),
                    modifier=m.group("mod") or "",
                    fallback=m.group("fb") or "",
                )
                tokens.append(tok)
                i = m.end()
            else:
                tokens.append(_Token("literal", ch))
                i += 1
        else:
            tokens.append(_Token("literal", ch))
            i += 1
    return tokens


# ── Field resolver ─────────────────────────────────────────────────────────────

def _resolve_field(field: str, modifier: str, book: dict[str, Any]) -> str | None:
    """Return the rendered field value, or None if empty (no fallback)."""
    raw = book.get(field) or ""

    if field == "author":
        raw = str(raw)
        authors = [a.strip() for a in raw.replace(";", ",").split(",") if a.strip()]
        if not authors:
            return None
        if modifier == "first":
            return authors[0]
        elif modifier == "last":
            parts = authors[0].split()
            return parts[-1] if parts else authors[0]
        elif modifier == "sort":
            parts = authors[0].split()
            if len(parts) >= 2:
                return f"{parts[-1]}, {' '.join(parts[:-1])}"
            return authors[0]
        else:
            return authors[0]

    if field == "title":
        raw = str(raw)
        if modifier == "main":
            return raw.split(":")[0].strip() or raw
        if modifier.isdigit():
            limit = int(modifier)
            if len(raw) <= limit:
                return raw
            truncated = raw[:limit]
            last_space = truncated.rfind(" ")
            return truncated[:last_space].rstrip() if last_space > 0 else truncated
        return raw or None

    if field == "series_index":
        val = book.get("series_index")
        if val is None:
            return None
        try:
            num = float(val)
            if modifier and modifier.isdigit():
                # Zero-pad integer part
                width = int(modifier)
                if num == int(num):
                    return str(int(num)).zfill(width)
                return f"{num:0{width}.1f}"
            return str(int(num)) if num == int(num) else str(num)
        except (ValueError, TypeError):
            return None

    if field == "genre":
        raw = str(book.get("genre") or "")
        genres = [g.strip() for g in raw.split(",") if g.strip()]
        if not genres:
            return None
        if modifier == "first":
            return genres[0]
        return genres[0]

    if field == "year":
        val = book.get("year")
        return str(val) if val else None

    # Generic field
    val = book.get(field)
    if val is None or str(val).strip() == "":
        return None
    return str(val).strip()


# ── Renderer ───────────────────────────────────────────────────────────────────

class RenderError(Exception):
    """Raised when a required field is missing and has no fallback."""
    def __init__(self, field: str) -> None:
        super().__init__(f"Missing required field: {field!r}")
        self.field = field


def render(pattern: str, book: dict[str, Any]) -> str:
    """
    Render *pattern* with data from *book*.

    Raises RenderError if a required field is empty.
    Returns the rendered string (unsanitized).
    """
    tokens = _tokenize(pattern)
    return _render_tokens(tokens, book)


def _render_tokens(tokens: list[_Token], book: dict[str, Any]) -> str:
    result = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.kind == "literal":
            result.append(tok.text)
        elif tok.kind == "field":
            value = _resolve_field(tok.field, tok.modifier, book)
            if value is None:
                if tok.fallback:
                    result.append(tok.fallback)
                else:
                    raise RenderError(tok.field)
            else:
                result.append(value)
        elif tok.kind == "opt_open":
            # Collect until matching opt_close
            depth = 1
            j = i + 1
            while j < len(tokens) and depth > 0:
                if tokens[j].kind == "opt_open":
                    depth += 1
                elif tokens[j].kind == "opt_close":
                    depth -= 1
                j += 1
            group_tokens = tokens[i + 1: j - 1]
            try:
                group_text = _render_tokens(group_tokens, book)
                result.append(group_text)
            except RenderError:
                pass  # optional group: skip if any field is missing
            i = j
            continue
        elif tok.kind == "opt_close":
            pass  # handled above
        i += 1
    return "".join(result)


# ── Public helpers ─────────────────────────────────────────────────────────────

PRESETS = {
    "Author - Title (Year)": "{author} - {title}[ ({year})]",
    "Title - Author":        "{title}[ - {author}]",
    "Series/Index - Title":  "{series}/{series_index:02} - {title}",
    "Author (folder) / Title": "{author:sort}/{title}",
}

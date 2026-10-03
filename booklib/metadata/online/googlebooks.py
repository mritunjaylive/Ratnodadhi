"""
googlebooks.py – Google Books metadata provider.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any

from booklib.metadata.online.base import Provider
from booklib.metadata.online.http import HttpClient
from booklib.metadata.online.models import Candidate

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(r'\b(1[89]\d\d|20\d\d)\b')
_HTML_TAGS = re.compile(r'<[^>]+>')


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = _HTML_TAGS.sub(' ', text)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned or None


def _parse_year(val: Any) -> int | None:
    if val is None:
        return None
    s = str(val)
    m = _YEAR_RE.search(s)
    return int(m.group(1)) if m else None


class GoogleBooksProvider(Provider):
    name = "googlebooks"

    def __init__(
        self,
        api_key: str | None = None,
        http_client: HttpClient | None = None,
        db_conn: Any = None,
    ):
        self.api_key = api_key
        self.http = http_client or HttpClient(provider_name="googlebooks", rate_limit_sec=1.0)
        self.db_conn = db_conn

    def lookup_isbn(self, isbn: str) -> list[Candidate]:
        clean = re.sub(r'[\s\-]+', '', isbn)
        cache_key = f"googlebooks:isbn:{clean}"
        url = "https://www.googleapis.com/books/v1/volumes"
        params: dict[str, Any] = {"q": f"isbn:{clean}"}
        if self.api_key:
            params["key"] = self.api_key

        data = self.http.get_json(url, params=params, cache_key=cache_key, db_conn=self.db_conn)
        return self._parse_items(data, matched_by="isbn")

    def search(self, title: str, author: str | None) -> list[Candidate]:
        if not title:
            return []
        norm_t = title.strip().lower()
        norm_a = (author or "").strip().lower()
        cache_key = f"googlebooks:search:{norm_t}:{norm_a}"

        # Prepare query
        q_parts = [f'intitle:"{title}"']
        if author:
            q_parts.append(f'inauthor:"{author}"')
        q = " ".join(q_parts)

        url = "https://www.googleapis.com/books/v1/volumes"
        params: dict[str, Any] = {"q": q, "maxResults": 5}
        if self.api_key:
            params["key"] = self.api_key

        data = self.http.get_json(url, params=params, cache_key=cache_key, db_conn=self.db_conn)
        return self._parse_items(data, matched_by="title_author")

    def _parse_items(self, data: Any, matched_by: str) -> list[Candidate]:
        if not data or not isinstance(data, dict):
            return []
        items = data.get("items", [])
        if not isinstance(items, list):
            return []

        candidates: list[Candidate] = []
        for item in items[:5]:
            if not isinstance(item, dict):
                continue

            vol = item.get("volumeInfo") or {}
            if not isinstance(vol, dict):
                continue

            title = vol.get("title")
            authors = vol.get("authors") or []
            if isinstance(authors, str):
                authors = [authors]

            publisher = vol.get("publisher")
            year = _parse_year(vol.get("publishedDate"))

            pages = vol.get("pageCount")
            if pages is not None:
                try:
                    pages = int(pages)
                    if pages <= 0:
                        pages = None
                except (ValueError, TypeError):
                    pages = None

            # ISBNs
            identifiers = vol.get("industryIdentifiers") or []
            isbn = None
            if isinstance(identifiers, list):
                # Prefer ISBN_13
                for ident in identifiers:
                    if isinstance(ident, dict) and ident.get("type") == "ISBN_13":
                        isbn = ident.get("identifier")
                        break
                if not isbn:
                    for ident in identifiers:
                        if isinstance(ident, dict) and ident.get("type") == "ISBN_10":
                            isbn = ident.get("identifier")
                            break
            if isbn:
                isbn = re.sub(r'[\s\-]+', '', isbn)

            categories = vol.get("categories") or []
            if not isinstance(categories, list):
                categories = []

            lang = vol.get("language")
            if lang and isinstance(lang, str):
                lang = lang.strip().lower()[:2]
            else:
                lang = None

            desc = _strip_html(vol.get("description"))

            # Cover
            img_links = vol.get("imageLinks") or {}
            cover_url = None
            if isinstance(img_links, dict):
                raw_cover = (
                    img_links.get("extraLarge")
                    or img_links.get("large")
                    or img_links.get("medium")
                    or img_links.get("thumbnail")
                    or img_links.get("smallThumbnail")
                )
                if raw_cover:
                    # Switch http:// to https://
                    cover_url = re.sub(r'^http://', 'https://', raw_cover)

            cand = Candidate(
                provider="googlebooks",
                provider_id=item.get("id", ""),
                title=title,
                authors=[str(a) for a in authors],
                publisher=publisher,
                year=year,
                isbn=isbn,
                pages=pages,
                genres=[str(c) for c in categories],
                language=lang,
                description=desc,
                edition=None,
                cover_url=cover_url,
                matched_by=matched_by,
            )
            candidates.append(cand)

        return candidates

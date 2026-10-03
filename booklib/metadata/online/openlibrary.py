"""
openlibrary.py – Open Library metadata provider.
"""
from __future__ import annotations

import logging
import re
from typing import Any
import urllib.parse

from booklib.metadata.online.base import Provider
from booklib.metadata.online.http import HttpClient
from booklib.metadata.online.models import Candidate

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(r'\b(1[89]\d\d|20\d\d)\b')


def _parse_year(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, int):
        return val if 1000 <= val <= 2100 else None
    s = str(val)
    m = _YEAR_RE.search(s)
    return int(m.group(1)) if m else None


def _clean_lang(val: Any) -> str | None:
    if not val:
        return None
    s = str(val).strip().lower()
    if s in ("eng", "en"):
        return "en"
    if s in ("fre", "fra", "fr"):
        return "fr"
    if s in ("spa", "es"):
        return "es"
    if s in ("ger", "deu", "de"):
        return "de"
    if s in ("ita", "it"):
        return "it"
    if len(s) == 2:
        return s
    if len(s) == 3:
        return s[:2]
    return None


class OpenLibraryProvider(Provider):
    name = "openlibrary"

    def __init__(self, http_client: HttpClient | None = None, db_conn: Any = None):
        self.http = http_client or HttpClient(provider_name="openlibrary", rate_limit_sec=1.0)
        self.db_conn = db_conn

    def lookup_isbn(self, isbn: str) -> list[Candidate]:
        clean = re.sub(r'[\s\-]+', '', isbn)
        cache_key = f"openlibrary:isbn:{clean}"
        url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{clean}&format=json&jscmd=data"

        data = self.http.get_json(url, cache_key=cache_key, db_conn=self.db_conn)
        if not data or not isinstance(data, dict):
            return []

        item = data.get(f"ISBN:{clean}")
        if not item or not isinstance(item, dict):
            return []

        title = item.get("title")
        authors = [a.get("name") for a in item.get("authors", []) if isinstance(a, dict) and a.get("name")]
        publishers = [p.get("name") for p in item.get("publishers", []) if isinstance(p, dict) and p.get("name")]
        publisher = publishers[0] if publishers else None

        year = _parse_year(item.get("publish_date"))
        pages = item.get("number_of_pages")
        if pages is not None:
            try:
                pages = int(pages)
                if pages <= 0:
                    pages = None
            except (ValueError, TypeError):
                pages = None

        subjects = [s.get("name") for s in item.get("subjects", []) if isinstance(s, dict) and s.get("name")]
        cover_dict = item.get("cover") or {}
        cover_url = cover_dict.get("large") or cover_dict.get("medium")
        if not cover_url and clean:
            cover_url = f"https://covers.openlibrary.org/b/isbn/{clean}-L.jpg?default=false"

        cand = Candidate(
            provider="openlibrary",
            provider_id=item.get("key", f"ISBN:{clean}"),
            title=title,
            authors=authors,
            publisher=publisher,
            year=year,
            isbn=clean,
            pages=pages,
            genres=subjects,
            language=None,
            description=None,
            edition=None,
            cover_url=cover_url,
            matched_by="isbn",
        )
        return [cand]

    def search(self, title: str, author: str | None) -> list[Candidate]:
        if not title:
            return []
        norm_t = title.strip().lower()
        norm_a = (author or "").strip().lower()
        cache_key = f"openlibrary:search:{norm_t}:{norm_a}"

        params: dict[str, Any] = {"title": title, "limit": 5}
        if author:
            params["author"] = author

        url = "https://openlibrary.org/search.json"
        data = self.http.get_json(url, params=params, cache_key=cache_key, db_conn=self.db_conn)
        if not data or not isinstance(data, dict):
            return []

        docs = data.get("docs", [])
        if not isinstance(docs, list):
            return []

        candidates: list[Candidate] = []
        for doc in docs[:5]:
            if not isinstance(doc, dict):
                continue

            c_title = doc.get("title")
            c_authors = doc.get("author_name") or []
            if isinstance(c_authors, str):
                c_authors = [c_authors]

            c_publishers = doc.get("publisher") or []
            c_pub = c_publishers[0] if c_publishers and isinstance(c_publishers, list) else None

            c_year = _parse_year(doc.get("first_publish_year"))
            c_pages = doc.get("number_of_pages_median")
            if c_pages is not None:
                try:
                    c_pages = int(c_pages)
                    if c_pages <= 0:
                        c_pages = None
                except (ValueError, TypeError):
                    c_pages = None

            c_isbns = doc.get("isbn") or []
            c_isbn = None
            if isinstance(c_isbns, list) and c_isbns:
                # Prefer ISBN-13
                thirteens = [i for i in c_isbns if isinstance(i, str) and len(re.sub(r'[\s\-]+', '', i)) == 13]
                c_isbn = thirteens[0] if thirteens else str(c_isbns[0])
                c_isbn = re.sub(r'[\s\-]+', '', c_isbn)

            c_genres = doc.get("subject") or []
            if not isinstance(c_genres, list):
                c_genres = []

            c_lang_list = doc.get("language") or []
            c_lang = _clean_lang(c_lang_list[0]) if (isinstance(c_lang_list, list) and c_lang_list) else None

            cover_i = doc.get("cover_i")
            cover_url = None
            if cover_i:
                cover_url = f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg?default=false"
            elif c_isbn:
                cover_url = f"https://covers.openlibrary.org/b/isbn/{c_isbn}-L.jpg?default=false"

            cand = Candidate(
                provider="openlibrary",
                provider_id=doc.get("key", ""),
                title=c_title,
                authors=c_authors,
                publisher=c_pub,
                year=c_year,
                isbn=c_isbn,
                pages=c_pages,
                genres=[str(g) for g in c_genres],
                language=c_lang,
                description=None,
                edition=None,
                cover_url=cover_url,
                matched_by="title_author",
            )
            candidates.append(cand)

        return candidates

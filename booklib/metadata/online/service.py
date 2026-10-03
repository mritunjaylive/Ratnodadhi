"""
service.py – Online lookup orchestration service.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from booklib.metadata.filename import is_junk_title
from booklib.metadata.online.base import Provider
from booklib.metadata.online.googlebooks import GoogleBooksProvider
from booklib.metadata.online.http import HttpClient, OfflineError
from booklib.metadata.online.models import Candidate
from booklib.metadata.online.openlibrary import OpenLibraryProvider
from booklib.metadata.online.scoring import decide_candidates, score_candidate

logger = logging.getLogger(__name__)


def clean_query_title(title: str | None) -> str | None:
    if not title or is_junk_title(title):
        return None
    # Strip bracketed tags [PDF], (2nd Edition), etc.
    t = re.sub(r'\[[^\]]*\]|\([^\)]*(?:edition|ed\.|vol\.|v\.)[^\)]*\)', '', title, flags=re.IGNORECASE)
    t = re.sub(r'\b(?:z-lib|libgen|org|epub|pdf)\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'[\s_]+', ' ', t).strip()
    return t or title.strip()


def extract_primary_author(author: str | None) -> str | None:
    if not author:
        return None
    # Pick first author before comma or semicolon or 'and'
    first = re.split(r'[,;]|\band\b', author, flags=re.IGNORECASE)[0].strip()
    return first or None


class OnlineLookupService:
    """
    Coordinates Open Library and Google Books providers to find,
    score, and rank metadata candidates for a given book.
    """

    def __init__(
        self,
        providers: list[Provider] | None = None,
        google_api_key: str | None = None,
        db_conn: Any = None,
    ):
        self.db_conn = db_conn
        if providers is not None:
            self.providers = providers
        else:
            ol_http = HttpClient("openlibrary", rate_limit_sec=1.0)
            gb_http = HttpClient("googlebooks", rate_limit_sec=1.0)
            self.providers = [
                OpenLibraryProvider(http_client=ol_http, db_conn=db_conn),
                GoogleBooksProvider(api_key=google_api_key, http_client=gb_http, db_conn=db_conn),
            ]

    def lookup(
        self,
        book: dict[str, Any],
        threshold: float = 0.90,
        margin: float = 0.10,
    ) -> tuple[str, list[Candidate]]:
        """
        Look up candidates for *book*.
        Returns (decision, candidates), where decision is 'apply', 'review', 'not_found', or 'offline'.
        """
        isbn = book.get("isbn")
        raw_title = book.get("title")
        raw_author = book.get("author")

        cleaned_title = clean_query_title(raw_title)
        primary_author = extract_primary_author(raw_author)

        candidates: list[Candidate] = []
        matched_by_isbn = False

        # 1. Try ISBN first if available
        if isbn:
            clean_isbn_val = re.sub(r'[\s\-]+', '', isbn)
            if len(clean_isbn_val) in (10, 13):
                for p in self.providers:
                    try:
                        res = p.lookup_isbn(clean_isbn_val)
                        if res:
                            candidates.extend(res)
                            matched_by_isbn = True
                    except OfflineError:
                        return "offline", []
                    except Exception as exc:
                        logger.warning("Error from %s lookup_isbn: %s", p.name, exc)

        # 2. If no ISBN matches, search by title and author
        if not matched_by_isbn and cleaned_title:
            for p in self.providers:
                try:
                    res = p.search(cleaned_title, primary_author)
                    if res:
                        candidates.extend(res)
                except OfflineError:
                    return "offline", []
                except Exception as exc:
                    logger.warning("Error from %s search: %s", p.name, exc)

            # If subtitle was present and no results, try prefix before colon
            if not candidates and ":" in cleaned_title:
                prefix_title = cleaned_title.split(":", 1)[0].strip()
                if prefix_title and len(prefix_title) > 3:
                    for p in self.providers:
                        try:
                            res = p.search(prefix_title, primary_author)
                            if res:
                                candidates.extend(res)
                        except OfflineError:
                            return "offline", []
                        except Exception as exc:
                            logger.warning("Error from %s search with prefix title: %s", p.name, exc)

        if not candidates:
            return "not_found", []

        # 3. Deduplicate candidates by provider + provider_id
        unique_cands: list[Candidate] = []
        seen = set()
        for c in candidates:
            key = (c.provider, c.provider_id)
            if key not in seen:
                seen.add(key)
                # Score candidate
                c.score = score_candidate(book, c)
                unique_cands.append(c)

        # 4. Decide outcome
        decision, ranked = decide_candidates(unique_cands, threshold=threshold, margin=margin)
        return decision, ranked

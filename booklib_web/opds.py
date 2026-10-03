"""
booklib_web.opds – OPDS 1.2 catalog feeds (Atom XML) for mobile e-reader applications.
Includes root catalog, acquisition feeds, search, and HTTP Basic authentication.
"""
from __future__ import annotations

import base64
import html
from datetime import datetime, timezone
from urllib.parse import quote

from flask import Blueprint, Response, abort, current_app, make_response, request

from booklib.db.query import LibraryQuery
from booklib_web.routes_files import _get_mimetype

opds_bp = Blueprint("opds", __name__, url_prefix="/opds")

ATOM_CONTENT_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition;charset=utf-8"
NAV_CONTENT_TYPE = "application/atom+xml;profile=opds-catalog;kind=navigation;charset=utf-8"


def _check_opds_auth() -> bool:
    """Validate HTTP Basic Auth for OPDS. Username: 'booklib', password: OPDS key."""
    repo = current_app.config["BOOKLIB_REPO"]
    web_cfg = current_app.config["BOOKLIB_CONFIG"]

    stored_key = web_cfg.opds_key or repo.get_app_meta("web.opds_key")

    # If no key set and loopback, allow
    if not stored_key and (request.remote_addr in ("127.0.0.1", "::1", "localhost")):
        return True

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Basic "):
        return False

    try:
        encoded = auth_header.split(" ", 1)[1].strip()
        decoded = base64.b64decode(encoded).decode("utf-8")
        username, password = decoded.split(":", 1)
        if username == "booklib" and password == stored_key:
            return True
    except Exception:
        return False

    return False


def _require_opds_auth():
    if not _check_opds_auth():
        resp = Response("Authentication Required for OPDS Catalog", 401)
        resp.headers["WWW-Authenticate"] = 'Basic realm="BookLib OPDS"'
        abort(resp)


def _xml_escape(text: str | None) -> str:
    return html.escape(text or "")


def _format_atom_date(dt_str: str | None) -> str:
    if not dt_str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@opds_bp.route("")
@opds_bp.route("/")
def root_catalog():
    """Root navigation catalog feed."""
    _require_opds_auth()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opds="http://opds-spec.org/2010/catalog">
  <id>urn:booklib:catalog:root</id>
  <title>Ratnodadhi Book Library</title>
  <updated>{now_iso}</updated>
  <author><name>Ratnodadhi</name></author>
  <link rel="self" href="/opds" type="{NAV_CONTENT_TYPE}"/>
  <link rel="start" href="/opds" type="{NAV_CONTENT_TYPE}"/>
  <link rel="search" href="/opds/search?q={{searchTerms}}" type="{ATOM_CONTENT_TYPE}" title="Search Library"/>

  <entry>
    <title>All Books</title>
    <id>urn:booklib:all</id>
    <updated>{now_iso}</updated>
    <content type="text">Browse all books in the library</content>
    <link rel="subsection" href="/opds/all" type="{ATOM_CONTENT_TYPE}"/>
  </entry>
  <entry>
    <title>Continue Reading</title>
    <id>urn:booklib:continue</id>
    <updated>{now_iso}</updated>
    <content type="text">Books currently in progress</content>
    <link rel="subsection" href="/opds/continue" type="{ATOM_CONTENT_TYPE}"/>
  </entry>
  <entry>
    <title>Recently Added</title>
    <id>urn:booklib:recent</id>
    <updated>{now_iso}</updated>
    <content type="text">Books added recently</content>
    <link rel="subsection" href="/opds/recent" type="{ATOM_CONTENT_TYPE}"/>
  </entry>
  <entry>
    <title>Want to Read</title>
    <id>urn:booklib:want</id>
    <updated>{now_iso}</updated>
    <content type="text">Reading wishlist</content>
    <link rel="subsection" href="/opds/want" type="{ATOM_CONTENT_TYPE}"/>
  </entry>
  <entry>
    <title>By Author</title>
    <id>urn:booklib:authors</id>
    <updated>{now_iso}</updated>
    <content type="text">Browse books grouped by author</content>
    <link rel="subsection" href="/opds/authors" type="{NAV_CONTENT_TYPE}"/>
  </entry>
</feed>
"""
    resp = make_response(xml)
    resp.headers["Content-Type"] = NAV_CONTENT_TYPE
    return resp


def _render_acquisition_feed(feed_id: str, title: str, books: list, self_url: str) -> Response:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries_xml = []
    for b in books:
        b_id = b.id
        b_title = _xml_escape(b.title or b.filename)
        b_author = _xml_escape(b.author or "Unknown")
        b_date = _format_atom_date(b.date_added)
        b_desc = _xml_escape(b.description or "")
        mime = _get_mimetype(b.format)

        entry = f"""  <entry>
    <title>{b_title}</title>
    <id>urn:booklib:book:{b_id}</id>
    <updated>{b_date}</updated>
    <author><name>{b_author}</name></author>
    <content type="text">{b_desc}</content>
    <link rel="http://opds-spec.org/image" href="/covers/{b_id}.jpg" type="image/jpeg"/>
    <link rel="http://opds-spec.org/image/thumbnail" href="/covers/{b_id}.jpg" type="image/jpeg"/>
    <link rel="http://opds-spec.org/acquisition" href="/book/{b_id}/download" type="{mime}"/>
  </entry>"""
        entries_xml.append(entry)

    feed_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opds="http://opds-spec.org/2010/catalog">
  <id>{feed_id}</id>
  <title>{_xml_escape(title)}</title>
  <updated>{now_iso}</updated>
  <author><name>Ratnodadhi</name></author>
  <link rel="self" href="{self_url}" type="{ATOM_CONTENT_TYPE}"/>
  <link rel="start" href="/opds" type="{NAV_CONTENT_TYPE}"/>
{chr(10).join(entries_xml)}
</feed>
"""
    resp = make_response(feed_xml)
    resp.headers["Content-Type"] = ATOM_CONTENT_TYPE
    return resp


@opds_bp.route("/all")
def all_books():
    _require_opds_auth()
    repo = current_app.config["BOOKLIB_REPO"]
    books = repo.query_books(LibraryQuery(sort_field="title", sort_desc=False))
    return _render_acquisition_feed("urn:booklib:all", "All Books", books, "/opds/all")


@opds_bp.route("/recent")
def recent_books():
    _require_opds_auth()
    repo = current_app.config["BOOKLIB_REPO"]
    books = repo.query_books(LibraryQuery(shelf="recent"))
    return _render_acquisition_feed("urn:booklib:recent", "Recently Added", books, "/opds/recent")


@opds_bp.route("/continue")
def continue_reading():
    _require_opds_auth()
    repo = current_app.config["BOOKLIB_REPO"]
    books = repo.query_books(LibraryQuery(shelf="continue"))
    return _render_acquisition_feed("urn:booklib:continue", "Continue Reading", books, "/opds/continue")


@opds_bp.route("/want")
def want_to_read():
    _require_opds_auth()
    repo = current_app.config["BOOKLIB_REPO"]
    books = repo.query_books(LibraryQuery(statuses={"want"}))
    return _render_acquisition_feed("urn:booklib:want", "Want to Read", books, "/opds/want")


@opds_bp.route("/search")
def search_books():
    _require_opds_auth()
    query = request.args.get("q", "").strip()
    repo = current_app.config["BOOKLIB_REPO"]
    books = repo.query_books(LibraryQuery(search=query)) if query else []
    return _render_acquisition_feed(
        f"urn:booklib:search:{quote(query)}",
        f"Search: {query}",
        books,
        f"/opds/search?q={quote(query)}",
    )


@opds_bp.route("/authors")
def list_authors():
    _require_opds_auth()
    repo = current_app.config["BOOKLIB_REPO"]
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    authors = repo.facet_counts("author", LibraryQuery())
    entries = []
    for auth, count in authors:
        if not auth:
            continue
        entries.append(f"""  <entry>
    <title>{_xml_escape(auth)} ({count})</title>
    <id>urn:booklib:author:{_xml_escape(auth)}</id>
    <updated>{now_iso}</updated>
    <link rel="subsection" href="/opds/author/{quote(auth)}" type="{ATOM_CONTENT_TYPE}"/>
  </entry>""")

    feed_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opds="http://opds-spec.org/2010/catalog">
  <id>urn:booklib:authors</id>
  <title>Authors</title>
  <updated>{now_iso}</updated>
  <author><name>Ratnodadhi</name></author>
  <link rel="self" href="/opds/authors" type="{NAV_CONTENT_TYPE}"/>
  <link rel="start" href="/opds" type="{NAV_CONTENT_TYPE}"/>
{chr(10).join(entries)}
</feed>
"""
    resp = make_response(feed_xml)
    resp.headers["Content-Type"] = NAV_CONTENT_TYPE
    return resp


@opds_bp.route("/author/<path:author_name>")
def books_by_author(author_name: str):
    _require_opds_auth()
    repo = current_app.config["BOOKLIB_REPO"]
    books = repo.query_books(LibraryQuery(authors={author_name}))
    return _render_acquisition_feed(
        f"urn:booklib:author:{quote(author_name)}",
        f"Books by {author_name}",
        books,
        f"/opds/author/{quote(author_name)}",
    )

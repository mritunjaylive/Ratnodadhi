"""
booklib_web.routes_files – Serves covers and book file downloads with HTTP Range support,
Tier 0 lease holding, daily budget tracking, and safe Unicode Content-Disposition headers.
"""
from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import quote

from flask import (
    Blueprint, Response, abort, current_app, make_response,
    request, send_file,
)

from booklib.config import COVERS_DIR
from booklib.covers.placeholder import generate_placeholder
from booklib.db.query import LibraryQuery
from booklib_web.security import is_authenticated_request

files_bp = Blueprint("files", __name__)

_MIME_MAP = {
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "mobi": "application/x-mobipocket-ebook",
    "azw3": "application/vnd.amazon.ebook",
    "cbz": "application/vnd.comicbook+zip",
    "txt": "text/plain; charset=utf-8",
    "fb2": "application/x-fictionbook+xml",
}


def _get_mimetype(format_str: str) -> str:
    fmt = format_str.lower().strip()
    return _MIME_MAP.get(fmt, mimetypes.guess_type(f"file.{fmt}")[0] or "application/octet-stream")


def _sanitize_ascii_filename(filename: str) -> str:
    """Generate safe ASCII-only fallback filename for Content-Disposition."""
    clean = re.sub(r"[^\w\s.-]", "", filename).strip()
    return clean or "book_file"


@files_bp.route("/covers/<int:book_id>.jpg")
def get_cover(book_id: int):
    """Serve book cover thumbnail with HTTP caching headers."""
    repo = current_app.config["BOOKLIB_REPO"]
    web_cfg = current_app.config["BOOKLIB_CONFIG"]

    if not is_authenticated_request(repo, web_cfg, request):
        abort(401)

    book = repo.get_book_detail(book_id)
    if not book:
        abort(404)

    # 1. Custom or extracted cover
    if book.cover_path:
        cover_path = COVERS_DIR / book.cover_path
        if cover_path.exists():
            resp = make_response(send_file(cover_path, mimetype="image/jpeg"))
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp

    # 2. On-demand SVG/JPEG placeholder
    placeholder_bytes = generate_placeholder(book.format)
    resp = make_response(placeholder_bytes)
    resp.headers["Content-Type"] = "image/jpeg"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@files_bp.route("/book/<int:book_id>/download")
def download_book(book_id: int):
    """
    Download book file with:
    - HTTP Range support (206 Partial Content, suffix ranges)
    - Safe Content-Disposition
    - Daily web budget enforcement
    - Cloud cache lease renewal (without bumping last_opened_at)
    """
    repo = current_app.config["BOOKLIB_REPO"]
    web_cfg = current_app.config["BOOKLIB_CONFIG"]

    if not is_authenticated_request(repo, web_cfg, request):
        abort(401)

    book = repo.get_book_detail(book_id)
    if not book or book.is_missing:
        abort(404)

    # Determine on-disk path
    file_path = None
    if book.source == "local":
        p = Path(book.path)
        if p.exists() and p.is_file():
            file_path = p
    elif book.source == "gdrive":
        if book.is_cached and book.cached_path:
            p = Path(book.cached_path)
            if p.exists() and p.is_file():
                file_path = p
                # Renew lease on cached file for 10 minutes while downloading
                with repo._conn:
                    repo._conn.execute(
                        "UPDATE drive_cache SET in_use_until = datetime('now', '+10 minutes') WHERE book_id = ?",
                        (book_id,),
                    )

    if not file_path:
        abort(404, description="Book file is not available locally on the server.")

    file_size = file_path.stat().st_size

    # Check daily download budget
    if not repo.can_download_web_bytes(file_size, web_cfg.daily_budget_bytes):
        abort(429, description="Daily web download budget exceeded. Try again tomorrow or raise the limit in settings.")

    # Record bytes (only once per complete or initial download request)
    range_header = request.headers.get("Range")
    if not range_header or range_header.startswith("bytes=0-"):
        repo.record_web_download_bytes(file_size)

    # Determine filename
    base_name = f"{book.title or book.filename}"
    if not base_name.lower().endswith(f".{book.format.lower()}"):
        base_name = f"{base_name}.{book.format.lower()}"
    ascii_name = _sanitize_ascii_filename(base_name)
    utf8_name = quote(base_name)
    content_disp = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"
    mimetype = _get_mimetype(book.format)

    # ── Handle HTTP Range Request ─────────────────────────────────────────────
    if range_header:
        range_match = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not range_match:
            abort(416, description="Invalid Range header")

        start_str, end_str = range_match.groups()
        if start_str and end_str:
            start = int(start_str)
            end = int(end_str)
        elif start_str:
            start = int(start_str)
            end = file_size - 1
        elif end_str:
            # Suffix range: last N bytes
            suffix_len = int(end_str)
            start = max(0, file_size - suffix_len)
            end = file_size - 1
        else:
            abort(416, description="Invalid Range header")

        if start >= file_size or end >= file_size or start > end:
            resp = make_response("", 416)
            resp.headers["Content-Range"] = f"bytes */{file_size}"
            return resp

        length = end - start + 1

        def stream_range():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                chunk_size = 64 * 1024
                while remaining > 0:
                    read_len = min(chunk_size, remaining)
                    data = f.read(read_len)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        resp = Response(stream_range(), status=206, mimetype=mimetype)
        resp.headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        resp.headers["Content-Length"] = str(length)
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Content-Disposition"] = content_disp
        return resp

    # ── Standard Full File Response ───────────────────────────────────────────
    resp = make_response(send_file(file_path, mimetype=mimetype, as_attachment=False))
    resp.headers["Content-Disposition"] = content_disp
    resp.headers["Accept-Ranges"] = "bytes"
    resp.headers["Content-Length"] = str(file_size)
    return resp

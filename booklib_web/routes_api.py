"""
booklib_web.routes_api – JSON API for books, details, and optional metadata updates.
"""
from __future__ import annotations

from flask import Blueprint, abort, current_app, jsonify, request

from booklib.db.query import LibraryQuery
from booklib_web.security import is_authenticated_request, validate_csrf

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/books")
def list_books():
    repo = current_app.config["BOOKLIB_REPO"]
    web_cfg = current_app.config["BOOKLIB_CONFIG"]

    if not is_authenticated_request(repo, web_cfg, request):
        abort(401)

    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()
    fmt = request.args.get("format", "").strip()
    sort_field = request.args.get("sort", "title").strip()
    sort_desc = request.args.get("desc", "0") in ("1", "true", "True")

    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(10, int(request.args.get("per_page", 60))))
    except ValueError:
        page, per_page = 1, 60

    q = LibraryQuery(
        search=search,
        statuses={status} if status else set(),
        formats={fmt} if fmt else set(),
        sort_field=sort_field,
        sort_desc=sort_desc,
    )

    all_books = repo.query_books(q)
    total = len(all_books)
    start = (page - 1) * per_page
    paged = all_books[start : start + per_page]

    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "books": [
            {
                "id": b.id,
                "title": b.title or b.filename,
                "author": b.author,
                "format": b.format,
                "year": b.year,
                "pages": b.pages,
                "rating": b.rating,
                "status": b.status,
                "size_bytes": b.size_bytes,
                "series_name": b.series_name,
                "series_index": b.series_index,
            }
            for b in paged
        ],
    })


@api_bp.route("/books/<int:book_id>")
def get_book(book_id: int):
    repo = current_app.config["BOOKLIB_REPO"]
    web_cfg = current_app.config["BOOKLIB_CONFIG"]

    if not is_authenticated_request(repo, web_cfg, request):
        abort(401)

    b = repo.get_book_detail(book_id)
    if not b:
        abort(404)

    return jsonify({
        "id": b.id,
        "title": b.title or b.filename,
        "author": b.author,
        "format": b.format,
        "year": b.year,
        "publisher": b.publisher,
        "isbn": b.isbn,
        "genre": b.genre,
        "language": b.language,
        "description": b.description,
        "rating": b.rating,
        "status": b.status,
        "notes": b.notes,
        "size_bytes": b.size_bytes,
        "series_name": b.series_name,
        "series_index": b.series_index,
        "tags": [t["name"] for t in b.tags],
    })


def _require_allow_changes(web_cfg, repo):
    """Enforce allow_changes setting."""
    allowed = web_cfg.allow_changes or (repo.get_app_meta("web.allow_changes", "0") == "1")
    if not allowed:
        abort(403, description="Modifying library records is disabled in web access settings.")


@api_bp.route("/books/<int:book_id>/status", methods=["POST"])
def update_status(book_id: int):
    repo = current_app.config["BOOKLIB_REPO"]
    web_cfg = current_app.config["BOOKLIB_CONFIG"]

    if not is_authenticated_request(repo, web_cfg, request):
        abort(401)
    if not validate_csrf(request):
        abort(400, description="Invalid CSRF token")
    _require_allow_changes(web_cfg, repo)

    data = request.get_json(silent=True) or request.form
    new_status = data.get("status")
    if new_status and new_status not in ("want", "reading", "read"):
        abort(400, description="Invalid status")

    repo.set_status([book_id], new_status or None)
    return jsonify({"success": True, "status": new_status})


@api_bp.route("/books/<int:book_id>/rating", methods=["POST"])
def update_rating(book_id: int):
    repo = current_app.config["BOOKLIB_REPO"]
    web_cfg = current_app.config["BOOKLIB_CONFIG"]

    if not is_authenticated_request(repo, web_cfg, request):
        abort(401)
    if not validate_csrf(request):
        abort(400, description="Invalid CSRF token")
    _require_allow_changes(web_cfg, repo)

    data = request.get_json(silent=True) or request.form
    raw_rating = data.get("rating")
    new_rating = int(raw_rating) if raw_rating else None
    if new_rating is not None and not (1 <= new_rating <= 5):
        abort(400, description="Rating must be between 1 and 5")

    repo.set_rating(book_id, new_rating)
    return jsonify({"success": True, "rating": new_rating})


@api_bp.route("/books/<int:book_id>/notes", methods=["POST"])
def update_notes(book_id: int):
    repo = current_app.config["BOOKLIB_REPO"]
    web_cfg = current_app.config["BOOKLIB_CONFIG"]

    if not is_authenticated_request(repo, web_cfg, request):
        abort(401)
    if not validate_csrf(request):
        abort(400, description="Invalid CSRF token")
    _require_allow_changes(web_cfg, repo)

    data = request.get_json(silent=True) or request.form
    notes = data.get("notes", "")

    repo.set_notes(book_id, notes)
    return jsonify({"success": True, "notes": notes})


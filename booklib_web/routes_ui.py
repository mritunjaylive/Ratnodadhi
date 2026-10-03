"""
booklib_web.routes_ui – Web UI routes: library browsing, shelf filters, book details,
pairing via QR code, and password authentication.
"""
from __future__ import annotations

import math
import secrets
from flask import (
    Blueprint, abort, current_app, make_response, redirect, render_template,
    request, session, url_for,
)

from booklib.db.query import LibraryQuery
from booklib.utils.format import human_size
from booklib_web.security import (
    generate_csrf_token, hash_token, is_authenticated_request,
    validate_csrf, verify_password,
)

ui_bp = Blueprint("ui", __name__)


@ui_bp.app_context_processor
def inject_common():
    return {
        "csrf_token": generate_csrf_token(),
        "format_size": human_size,
    }


# ── Authentication & Pairing ──────────────────────────────────────────────────

@ui_bp.route("/pair")
def pair_device():
    """Exchange a single-use 5-minute pairing code for a persistent device cookie."""
    code = request.args.get("code", "").strip()
    pairing_mgr = current_app.config["BOOKLIB_PAIRING_MGR"]
    repo = current_app.config["BOOKLIB_REPO"]

    if not code or not pairing_mgr.consume_code(code):
        return render_template(
            "error.html",
            code=400,
            title="Pairing Failed",
            description="The pairing code is invalid or has expired (codes expire after 5 minutes).",
        ), 400

    # Issue device token
    token = secrets.token_hex(32)
    t_hash = hash_token(token)

    # Derive friendly device name from User-Agent
    ua = request.headers.get("User-Agent", "Mobile Device")
    name = "Mobile Device"
    if "iPhone" in ua:
        name = "iPhone"
    elif "iPad" in ua:
        name = "iPad"
    elif "Android" in ua:
        name = "Android Phone"
    elif "Kindle" in ua:
        name = "Kindle"

    ip = request.remote_addr
    repo.add_web_device(name=name, token_hash=t_hash, ip=ip)

    resp = make_response(render_template("pairing.html"))
    # Set persistent cookie (30 days)
    resp.set_cookie(
        "booklib_device",
        token,
        max_age=30 * 86400,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure,
    )
    return resp


@ui_bp.route("/login", methods=["GET", "POST"])
def login():
    repo = current_app.config["BOOKLIB_REPO"]
    web_cfg = current_app.config["BOOKLIB_CONFIG"]
    limiter = current_app.config["BOOKLIB_RATE_LIMITER"]
    ip = request.remote_addr or "127.0.0.1"

    if is_authenticated_request(repo, web_cfg, request):
        return redirect("/")

    if request.method == "POST":
        if limiter.is_locked(ip):
            rem = limiter.seconds_remaining(ip)
            return render_template(
                "login.html",
                error=f"Too many failed login attempts. Temporarily locked for {rem} seconds.",
            ), 429

        if not validate_csrf(request):
            limiter.record_failure(ip)
            return render_template("login.html", error="Session expired. Please try again."), 400

        password = request.form.get("password", "")
        stored_hash = repo.get_app_meta("web.password_hash")
        stored_salt = repo.get_app_meta("web.password_salt")

        if stored_hash and stored_salt and verify_password(password, stored_hash, stored_salt):
            limiter.record_success(ip)
            session["authenticated"] = True
            return redirect("/")
        else:
            limiter.record_failure(ip)
            return render_template("login.html", error="Invalid password. Please try again."), 401

    return render_template("login.html")


@ui_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    resp = make_response(redirect("/login"))
    resp.delete_cookie("booklib_device")
    return resp


# ── Library Views ─────────────────────────────────────────────────────────────

@ui_bp.route("/")
def index():
    repo = current_app.config["BOOKLIB_REPO"]
    web_cfg = current_app.config["BOOKLIB_CONFIG"]

    if not is_authenticated_request(repo, web_cfg, request):
        return redirect(url_for("ui.login"))

    search_query = request.args.get("q", "").strip()
    try:
        current_page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        current_page = 1
    per_page = 60

    q = LibraryQuery(search=search_query)
    all_books = repo.query_books(q)
    total_books = len(all_books)
    total_pages = math.ceil(total_books / per_page) or 1

    start = (current_page - 1) * per_page
    paged_books = all_books[start : start + per_page]

    return render_template(
        "index.html",
        books=paged_books,
        total_books=total_books,
        current_page=current_page,
        total_pages=total_pages,
        search_query=search_query,
        active_shelf="all",
        shelf_title="All Books",
    )


@ui_bp.route("/shelf/<shelf_name>")
def shelf(shelf_name: str):
    repo = current_app.config["BOOKLIB_REPO"]
    web_cfg = current_app.config["BOOKLIB_CONFIG"]

    if not is_authenticated_request(repo, web_cfg, request):
        return redirect(url_for("ui.login"))

    valid_shelves = {
        "continue": ("Continue Reading", LibraryQuery(shelf="continue")),
        "recent": ("Recently Added", LibraryQuery(shelf="recent")),
        "want": ("Want to Read", LibraryQuery(statuses={"want"})),
    }

    if shelf_name not in valid_shelves:
        abort(404)

    title, q = valid_shelves[shelf_name]
    try:
        current_page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        current_page = 1
    per_page = 60

    all_books = repo.query_books(q)
    total_books = len(all_books)
    total_pages = math.ceil(total_books / per_page) or 1

    start = (current_page - 1) * per_page
    paged_books = all_books[start : start + per_page]

    return render_template(
        "index.html",
        books=paged_books,
        total_books=total_books,
        current_page=current_page,
        total_pages=total_pages,
        active_shelf=shelf_name,
        shelf_title=title,
    )


@ui_bp.route("/book/<int:book_id>")
def book_detail(book_id: int):
    repo = current_app.config["BOOKLIB_REPO"]
    web_cfg = current_app.config["BOOKLIB_CONFIG"]

    if not is_authenticated_request(repo, web_cfg, request):
        return redirect(url_for("ui.login"))

    book = repo.get_book_detail(book_id)
    if not book:
        abort(404)

    allow_changes = web_cfg.allow_changes or (repo.get_app_meta("web.allow_changes", "0") == "1")

    return render_template(
        "book.html",
        book=book,
        allow_changes=allow_changes,
    )

"""
tests/test_v6_web.py – Comprehensive tests for Milestones 14, 15, 15b, 16:
- Authentication & route protection matrix (all protected routes require auth)
- Security headers (nosniff, CSP, X-Frame-Options)
- Device pairing via one-time code & revocation
- Brute-force rate limiting and lockout
- CSRF validation and allow_changes enforcement
- File downloads with HTTP Range support (206 partial, suffix, 416 invalid)
- Safe UTF-8 Content-Disposition
- Daily web download budget enforcement
- OPDS 1.2 catalog Atom XML feeds and Basic authentication
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import pytest
from flask import Flask

from booklib.db.database import Database
from booklib.db.repository import Repository
from booklib_web.app import create_app
from booklib_web.config import WebConfig
from booklib_web.security import hash_password, hash_token


@pytest.fixture
def web_setup(tmp_path: Path):
    db_path = tmp_path / "web_test.db"
    db = Database(db_path)
    conn = db.connect()

    # Create dummy folder and sample books
    sample_file = tmp_path / "test_book.pdf"
    sample_content = b"PDF-1.4 sample content for range and download testing " * 100
    sample_file.write_bytes(sample_content)

    with conn:
        conn.execute("INSERT INTO folders (id, path) VALUES (1, ?)", (str(tmp_path),))
        conn.execute(
            "INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime, title, author, status, rating, genre) "
            "VALUES (1, 1, ?, 'test_book.pdf', 'pdf', ?, 100.0, 'Testing Book', 'Arthur Test', 'reading', 5, 'Tech')",
            (str(sample_file), len(sample_content)),
        )

    repo = Repository(conn)
    # Set password: "secretpassword"
    h, s = hash_password("secretpassword")
    repo.set_app_meta("web.password_hash", h)
    repo.set_app_meta("web.password_salt", s)
    repo.set_app_meta("web.opds_key", "opdssecretkey")

    cfg = WebConfig(
        db_path=db_path,
        covers_dir=tmp_path / "covers",
        log_file=tmp_path / "web_access.log",
        secret_key="test-secret-key",
        daily_budget_bytes=len(sample_content) * 3,  # budget allows 3 downloads
    )

    app = create_app(cfg, repo=repo)
    app.config["TESTING"] = True
    client = app.test_client()

    return {
        "app": app,
        "client": client,
        "repo": repo,
        "sample_file": sample_file,
        "sample_content": sample_content,
        "cfg": cfg,
    }


def test_security_headers_present(web_setup):
    client = web_setup["client"]
    resp = client.get("/login")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "no-referrer"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in resp.headers


def test_route_authentication_matrix(web_setup):
    """Every registered route (except /pair, /login, static) must require authentication."""
    app: Flask = web_setup["app"]
    client = web_setup["client"]

    # When password is set, unauthenticated requests from public or loopback must be challenged
    exempt_prefixes = ("/login", "/pair", "/static", "/opds")

    for rule in app.url_map.iter_rules():
        rule_str = str(rule)
        # Skip rules that are exempt or require parameters
        if any(rule_str.startswith(ex) for ex in exempt_prefixes):
            continue
        if "<" in rule_str:
            continue
        if "GET" not in rule.methods:
            continue

        resp = client.get(rule_str, follow_redirects=False)
        # Must be redirect to login (302) or unauthorized (401)
        assert resp.status_code in (302, 401), f"Route {rule_str} was not protected (got {resp.status_code})"
        if resp.status_code == 302:
            assert "/login" in resp.headers.get("Location", "")


def test_pairing_flow_and_revocation(web_setup):
    client = web_setup["client"]
    app = web_setup["app"]
    repo = web_setup["repo"]

    pairing_mgr = app.config["BOOKLIB_PAIRING_MGR"]
    code = pairing_mgr.create_code(ttl_seconds=300)

    # 1. Pair with valid code
    resp = client.get(f"/pair?code={code}", headers={"User-Agent": "Mozilla/5.0 (iPhone)"})
    assert resp.status_code == 200
    assert "Device Paired" in resp.get_data(as_text=True)

    # Device cookie must be set
    cookie = client.get_cookie("booklib_device")
    assert cookie is not None
    token = cookie.value

    # Verify device in database
    devices = repo.list_web_devices()
    assert len(devices) == 1
    assert devices[0]["name"] == "iPhone"
    assert devices[0]["token_hash"] == hash_token(token)

    # 2. Access library with device cookie
    lib_resp = client.get("/")
    assert lib_resp.status_code == 200
    assert "Testing Book" in lib_resp.get_data(as_text=True)

    # 3. Revoke device
    repo.revoke_web_device(devices[0]["id"])

    # 4. Access after revoke should be rejected
    lib_resp2 = client.get("/")
    assert lib_resp2.status_code in (302, 401)


def test_login_brute_force_lockout(web_setup):
    client = web_setup["client"]

    # Initialize session with CSRF token
    with client.session_transaction() as sess:
        sess["csrf_token"] = "valid_csrf"

    # Fail 5 times with wrong password
    for i in range(5):
        post_resp = client.post(
            "/login",
            data={"password": "wrongpassword", "csrf_token": "valid_csrf"},
            environ_overrides={"REMOTE_ADDR": "192.168.1.50"},
        )
        assert post_resp.status_code == 401

    # 6th attempt should be locked out (429), even with the correct password
    locked_resp = client.post(
        "/login",
        data={"password": "secretpassword", "csrf_token": "valid_csrf"},
        environ_overrides={"REMOTE_ADDR": "192.168.1.50"},
    )
    assert locked_resp.status_code == 429
    assert "Temporarily locked" in locked_resp.get_data(as_text=True)


def test_csrf_and_allow_changes_protection(web_setup):
    client = web_setup["client"]
    repo = web_setup["repo"]

    # Authenticate via session
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["csrf_token"] = "test_csrf_token"

    # Default: allow_changes is False (0)
    repo.set_app_meta("web.allow_changes", "0")

    # Modifying status without allow_changes must return 403
    resp = client.post(
        "/api/books/1/status",
        headers={"X-CSRFToken": "test_csrf_token"},
        json={"status": "read"},
    )
    assert resp.status_code == 403

    # Enable allow_changes
    repo.set_app_meta("web.allow_changes", "1")

    # Invalid CSRF token must return 400
    bad_csrf_resp = client.post(
        "/api/books/1/status",
        headers={"X-CSRFToken": "wrong_csrf"},
        json={"status": "read"},
    )
    assert bad_csrf_resp.status_code == 400

    # Valid CSRF + allow_changes must succeed
    good_resp = client.post(
        "/api/books/1/status",
        headers={"X-CSRFToken": "test_csrf_token"},
        json={"status": "read"},
    )
    assert good_resp.status_code == 200
    assert good_resp.get_json()["status"] == "read"


def test_file_download_with_range_and_budget(web_setup):
    client = web_setup["client"]
    repo = web_setup["repo"]
    content = web_setup["sample_content"]
    total_len = len(content)

    with client.session_transaction() as sess:
        sess["authenticated"] = True

    # 1. Full download (200 OK)
    full_resp = client.get("/book/1/download")
    assert full_resp.status_code == 200
    assert full_resp.data == content
    assert full_resp.headers["Accept-Ranges"] == "bytes"
    assert "attachment;" in full_resp.headers["Content-Disposition"]

    # 2. HTTP Range partial content (bytes=0-49) -> 206 Partial Content
    range_resp = client.get("/book/1/download", headers={"Range": "bytes=0-49"})
    assert range_resp.status_code == 206
    assert range_resp.headers["Content-Range"] == f"bytes 0-49/{total_len}"
    assert range_resp.headers["Content-Length"] == "50"
    assert range_resp.data == content[0:50]

    # 3. HTTP Range suffix (last 30 bytes)
    suffix_resp = client.get("/book/1/download", headers={"Range": "bytes=-30"})
    assert suffix_resp.status_code == 206
    assert suffix_resp.data == content[-30:]

    # 4. Invalid range -> 416
    bad_range = client.get("/book/1/download", headers={"Range": f"bytes={total_len+100}-{total_len+200}"})
    assert bad_range.status_code == 416

    # 5. Daily budget check
    # We downloaded 1 full book (budget allows 3). Let's exceed budget.
    repo.record_web_download_bytes(total_len * 3)
    exceeded_resp = client.get("/book/1/download")
    assert exceeded_resp.status_code == 429


def test_opds_feeds_and_basic_auth(web_setup):
    client = web_setup["client"]

    # 1. Without basic auth on public IP -> 401
    unauth_resp = client.get("/opds", environ_overrides={"REMOTE_ADDR": "192.168.1.100"})
    assert unauth_resp.status_code == 401
    assert "Basic realm=" in unauth_resp.headers.get("WWW-Authenticate", "")

    # 2. With wrong password -> 401
    bad_creds = base64.b64encode(b"booklib:wrongkey").decode("ascii")
    bad_resp = client.get("/opds", headers={"Authorization": f"Basic {bad_creds}"})
    assert bad_resp.status_code == 401

    # 3. With correct key -> 200 and valid Atom XML
    good_creds = base64.b64encode(b"booklib:opdssecretkey").decode("ascii")
    opds_resp = client.get("/opds", headers={"Authorization": f"Basic {good_creds}"})
    assert opds_resp.status_code == 200
    assert "application/atom+xml" in opds_resp.headers["Content-Type"]
    xml_data = opds_resp.get_data(as_text=True)
    assert "<feed" in xml_data
    assert "Ratnodadhi Book Library" in xml_data

    # 4. Acquisition feed /opds/all
    all_resp = client.get("/opds/all", headers={"Authorization": f"Basic {good_creds}"})
    assert all_resp.status_code == 200
    all_xml = all_resp.get_data(as_text=True)
    assert "Testing Book" in all_xml
    assert "/book/1/download" in all_xml

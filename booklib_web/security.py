"""
booklib_web.security – Authentication, password hashing, device pairing,
CSRF protection, brute-force rate limiting, and security headers.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import TYPE_CHECKING, Any

from flask import Request, Response, current_app, redirect, request, session, url_for

if TYPE_CHECKING:
    from booklib.db.repository import Repository
    from booklib_web.config import WebConfig

logger = logging.getLogger("booklib_web.security")


# ── Password Hashing ──────────────────────────────────────────────────────────

def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """
    Hash password using scrypt (with salt).
    Returns (hex_hash, hex_salt).
    """
    if salt is None:
        salt = os.urandom(16)
    try:
        derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
    except AttributeError:
        # Fallback if scrypt not supported
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return derived.hex(), salt.hex()


def verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    """Verify password against stored hex hash and hex salt."""
    try:
        salt = bytes.fromhex(stored_salt)
        computed_hash, _ = hash_password(password, salt=salt)
        return hmac.compare_digest(computed_hash, stored_hash)
    except Exception:
        return False


def hash_token(token: str) -> str:
    """Compute SHA-256 hash of a device or session token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── Pairing Codes ─────────────────────────────────────────────────────────────

class PairingManager:
    """Manages single-use pairing codes that expire after 5 minutes."""

    def __init__(self) -> None:
        self._codes: dict[str, float] = {}  # code -> expiry timestamp

    def create_code(self, ttl_seconds: int = 300) -> str:
        """Generate a random 8-character single-use uppercase code."""
        code = secrets.token_hex(4).upper()
        self._codes[code] = time.time() + ttl_seconds
        return code

    def consume_code(self, code: str) -> bool:
        """Validate and consume a pairing code."""
        code = code.strip().upper()
        now = time.time()
        expiry = self._codes.pop(code, None)
        if expiry and expiry >= now:
            return True
        return False

    def cleanup(self) -> None:
        now = time.time()
        expired = [c for c, exp in self._codes.items() if exp < now]
        for c in expired:
            self._codes.pop(c, None)


# ── Rate Limiter / Brute Force Protection ─────────────────────────────────────

class RateLimiter:
    """Tracks failed login attempts per IP. Locks out after 5 failures for 10 minutes."""

    def __init__(self, max_attempts: int = 5, lockout_seconds: int = 600) -> None:
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._attempts: dict[str, list[float]] = {}  # ip -> timestamps of failures

    def is_locked(self, ip: str) -> bool:
        now = time.time()
        failures = [t for t in self._attempts.get(ip, []) if now - t < self.lockout_seconds]
        return len(failures) >= self.max_attempts

    def seconds_remaining(self, ip: str) -> int:
        now = time.time()
        failures = [t for t in self._attempts.get(ip, []) if now - t < self.lockout_seconds]
        if len(failures) >= self.max_attempts:
            oldest = min(failures)
            return max(0, int(self.lockout_seconds - (now - oldest)))
        return 0

    def record_failure(self, ip: str) -> None:
        now = time.time()
        failures = [t for t in self._attempts.get(ip, []) if now - t < self.lockout_seconds]
        failures.append(now)
        self._attempts[ip] = failures
        logger.warning("Failed login attempt from IP %s (total: %d)", ip, len(failures))

    def record_success(self, ip: str) -> None:
        self._attempts.pop(ip, None)


# ── CSRF Protection ───────────────────────────────────────────────────────────

def generate_csrf_token() -> str:
    """Generate or retrieve CSRF token in session."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(24)
    return session["csrf_token"]


def validate_csrf(req: Request) -> bool:
    """Validate CSRF token on modifying requests."""
    if req.method in ("GET", "HEAD", "OPTIONS"):
        return True

    expected = session.get("csrf_token")
    if not expected:
        return False

    received = req.form.get("csrf_token") or req.headers.get("X-CSRFToken")
    if not received or not hmac.compare_digest(received, expected):
        logger.warning("CSRF validation failed for path %s", req.path)
        return False
    return True


# ── Security Headers ──────────────────────────────────────────────────────────

def apply_security_headers(response: Response) -> Response:
    """Set secure HTTP response headers."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
    )
    return response


# ── Request Authentication Helper ─────────────────────────────────────────────

def get_authenticated_device(repo: Repository, req: Request) -> dict[str, Any] | None:
    """
    Check if the request comes from an authenticated device cookie.
    Cookie name: 'booklib_device'
    """
    token = req.cookies.get("booklib_device")
    if not token:
        return None

    t_hash = hash_token(token)
    row = repo.get_web_device_by_hash(t_hash)
    if row and not row.get("revoked_at"):
        # Update last seen
        ip = req.remote_addr
        repo.update_web_device_seen(row["id"], ip=ip)
        return row
    return None


def is_authenticated_request(repo: Repository, config: WebConfig, req: Request) -> bool:
    """
    Returns True if request has a valid password session or paired device cookie.
    If no password is set on the server and host is loopback, access is allowed.
    """
    # 1. Device cookie check
    dev = get_authenticated_device(repo, req)
    if dev is not None:
        return True

    # 2. Session cookie check
    if session.get("authenticated") is True:
        return True

    # 3. If no password is set and running on loopback, allow local access
    stored_hash = repo.get_app_meta("web.password_hash")
    if not stored_hash and (req.remote_addr in ("127.0.0.1", "::1", "localhost")):
        return True

    return False

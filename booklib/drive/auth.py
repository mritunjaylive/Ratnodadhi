"""
auth.py – Google OAuth authentication, token storage via system keyring, and credentials import.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from booklib.config import GOOGLE_CLIENT_FILE, DATA_DIR
from booklib.drive.models import AuthExpired, DriveError

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.appdata",
]

KEYRING_SERVICE_NAME = "BookLib"


class TokenStore:
    """Wrapper around system credential store (Windows Credential Manager / keyring) with secure local fallback."""

    def _fallback_file(self) -> Path:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return DATA_DIR / ".tokens.json"

    def _read_fallback(self) -> dict[str, str]:
        f = self._fallback_file()
        if not f.exists():
            return {}
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_fallback(self, data: dict[str, str]) -> None:
        f = self._fallback_file()
        try:
            f.write_text(json.dumps(data), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to write token fallback file: %s", e)

    def get_refresh_token(self, email: str) -> str | None:
        try:
            import keyring
            token = keyring.get_password(KEYRING_SERVICE_NAME, email)
            if token:
                return token
        except Exception as e:
            logger.error("Could not access system credential store: %s", e)
        # Check fallback
        tokens = self._read_fallback()
        return tokens.get(email)

    def set_refresh_token(self, email: str, refresh_token: str) -> None:
        try:
            import keyring
            keyring.set_password(KEYRING_SERVICE_NAME, email, refresh_token)
        except Exception as e:
            logger.warning("Could not write to system credential store: %s", e)
        # Always maintain fallback copy
        tokens = self._read_fallback()
        tokens[email] = refresh_token
        self._write_fallback(tokens)

    save_refresh_token = set_refresh_token

    def delete_refresh_token(self, email: str) -> None:
        try:
            import keyring
            try:
                keyring.delete_password(KEYRING_SERVICE_NAME, email)
            except keyring.errors.PasswordDeleteError:
                pass
        except Exception as e:
            logger.warning("Error deleting token from keyring: %s", e)
        tokens = self._read_fallback()
        if email in tokens:
            tokens.pop(email, None)
            self._write_fallback(tokens)


class InMemoryTokenStore(TokenStore):
    """In-memory token store for unit testing."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def get_refresh_token(self, email: str) -> str | None:
        return self._tokens.get(email)

    def set_refresh_token(self, email: str, refresh_token: str) -> None:
        self._tokens[email] = refresh_token

    save_refresh_token = set_refresh_token

    def delete_refresh_token(self, email: str) -> None:
        self._tokens.pop(email, None)


_default_token_store: TokenStore = TokenStore()


def get_token_store() -> TokenStore:
    return _default_token_store


def set_token_store(store: TokenStore) -> None:
    global _default_token_store
    _default_token_store = store


def import_credentials_file(src_path: Path) -> Path:
    """
    Validate and import client_secret.json to the app's data folder.
    Raises ValueError if JSON format is invalid.
    """
    if not src_path.exists():
        raise FileNotFoundError(f"File not found: {src_path}")

    try:
        content = json.loads(src_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Invalid JSON file: {e}")

    # Must contain 'installed' with client_id, client_secret, token_uri
    client_info = content.get("installed") or content.get("web")
    if not client_info:
        raise ValueError("OAuth client secrets file must contain an 'installed' or 'web' section.")

    required_keys = ["client_id", "client_secret"]
    for k in required_keys:
        if k not in client_info:
            raise ValueError(f"Missing required key '{k}' in client secret file.")

    GOOGLE_CLIENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if src_path.resolve() != GOOGLE_CLIENT_FILE.resolve():
        shutil.copy2(str(src_path), str(GOOGLE_CLIENT_FILE))
    logger.info("Successfully imported Google client credentials")
    return GOOGLE_CLIENT_FILE


import_client_secrets = import_credentials_file


def import_credentials_raw(client_id: str, client_secret: str) -> Path:
    """Save raw client_id and client_secret to GOOGLE_CLIENT_FILE."""
    cid = client_id.strip()
    csec = client_secret.strip()
    if not cid or not csec:
        raise ValueError("Both Client ID and Client Secret are required.")

    data = {
        "installed": {
            "client_id": cid,
            "client_secret": csec,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": ["http://localhost", "http://127.0.0.1"],
        }
    }
    GOOGLE_CLIENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    GOOGLE_CLIENT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Successfully saved client credentials from Client ID and Secret")
    return GOOGLE_CLIENT_FILE


def load_client_info() -> dict[str, Any]:
    """Load client_id and client_secret from GOOGLE_CLIENT_FILE."""
    if not GOOGLE_CLIENT_FILE.exists():
        raise FileNotFoundError("Google client credentials not imported. Please import client_secret.json in Settings.")

    data = json.loads(GOOGLE_CLIENT_FILE.read_text(encoding="utf-8"))
    info = data.get("installed") or data.get("web") or {}
    return info


def get_credentials(email: str, token_store: TokenStore | None = None) -> Any:
    """
    Rebuild google.oauth2.credentials.Credentials using the refresh token stored in keyring.
    """
    from google.oauth2.credentials import Credentials

    store = token_store or get_token_store()
    refresh_token = store.get_refresh_token(email)
    if not refresh_token:
        raise AuthExpired(f"No refresh token found for account {email}. Please sign in again.")

    info = load_client_info()
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=info.get("client_id"),
        client_secret=info.get("client_secret"),
        token_uri=info.get("token_uri", "https://oauth2.googleapis.com/token"),
        scopes=SCOPES,
    )


def run_oauth_flow(
    port: int = 0,
    timeout_seconds: int = 180,
    token_store: TokenStore | None = None,
    client_file: Path | None = None,
    **kwargs: Any,
) -> tuple[str, str, str | None]:
    """
    Run Desktop loopback OAuth flow using google_auth_oauthlib.
    Returns (email, refresh_token, display_name).
    """
    from google_auth_oauthlib.flow import InstalledAppFlow
    import requests

    target_file = client_file if isinstance(client_file, Path) else GOOGLE_CLIENT_FILE
    if not target_file.exists():
        raise FileNotFoundError("Google credentials file not found. Please import client_secret.json first.")

    flow = InstalledAppFlow.from_client_secrets_file(str(target_file), SCOPES)
    actual_port = port if isinstance(port, int) else 0
    actual_timeout = timeout_seconds if isinstance(timeout_seconds, (int, float)) else 180

    creds = flow.run_local_server(
        host="127.0.0.1",
        port=actual_port,
        access_type="offline",
        prompt="consent",
        open_browser=True,
        timeout_seconds=actual_timeout,
    )

    if not creds:
        raise DriveError("Google authentication failed: no credentials returned.")

    # Fetch user email and display name from Drive API
    headers = {"Authorization": f"Bearer {creds.token}"}
    resp = requests.get(
        "https://www.googleapis.com/drive/v3/about?fields=user(emailAddress,displayName)",
        headers=headers,
        timeout=15,
    )
    if not resp.ok:
        raise DriveError(f"Failed to fetch account info from Drive API: {resp.status_code}")

    user_info = resp.json().get("user", {})
    email = user_info.get("emailAddress")
    if not email:
        raise DriveError("Could not determine user email from Drive API response.")
    display_name = user_info.get("displayName")

    refresh_token = creds.refresh_token
    store = token_store or get_token_store()
    if not refresh_token:
        # Fallback to existing refresh token if re-authorizing
        refresh_token = store.get_refresh_token(email)

    if not refresh_token:
        raise DriveError("Google did not return a refresh token. Please sign in with consent granted.")

    store.set_refresh_token(email, refresh_token)
    return (email, refresh_token, display_name)


def interactive_auth(ui_callbacks: Any = None, token_store: TokenStore | None = None) -> Any:
    """Interactive authentication helper returning Google Credentials object."""
    email, refresh_token, display_name = run_oauth_flow(token_store=token_store)
    return get_credentials(email, token_store=token_store)


def disconnect_account(
    conn_or_repo: Any,
    account_id: int,
    arg3: Any = None,
    arg4: Any = None,
    remove_books: bool = True,
    token_store: TokenStore | None = None,
    **kwargs: Any,
) -> None:
    """
    Disconnect account, remove token from credential store, and optionally purge its books/cache.
    Supports both (conn, account_id, remove_books=True, token_store=None) and
    (repo, account_id, email, token_store, remove_books=True) calling patterns.
    """
    conn = getattr(conn_or_repo, "_conn", conn_or_repo)
    if hasattr(conn_or_repo, "conn"):
        conn = conn_or_repo.conn

    actual_store = token_store
    actual_remove = remove_books

    if isinstance(arg3, bool):
        actual_remove = arg3
    if isinstance(arg4, TokenStore):
        actual_store = arg4
    elif isinstance(arg3, TokenStore):
        actual_store = arg3

    store = actual_store or get_token_store()

    row = conn.execute("SELECT email FROM drive_accounts WHERE id = ?", (account_id,)).fetchone()
    if row:
        email = row[0]
        store.delete_refresh_token(email)
    elif isinstance(arg3, str) and "@" in arg3:
        store.delete_refresh_token(arg3)

    if actual_remove:
        # Delete folders and books belonging to account
        conn.execute("DELETE FROM drive_accounts WHERE id = ?", (account_id,))
    else:
        conn.execute("UPDATE drive_accounts SET state = 'disconnected' WHERE id = ?", (account_id,))
    conn.commit()

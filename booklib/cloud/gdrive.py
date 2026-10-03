"""
booklib.cloud.gdrive – Google Drive CloudProvider implementation.
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
from booklib.drive.client import DriveClient
from booklib.drive.models import DriveFile

logger = logging.getLogger(__name__)


def _drive_file_to_remote_item(f: DriveFile) -> RemoteItem:
    parent_id = f.parents[0] if f.parents else None
    return RemoteItem(
        id=f.id,
        name=f.name,
        parent_id=parent_id,
        is_folder=f.is_folder,
        size=f.size,
        modified=f.modified_time,
        hash_kind="md5" if f.md5 else None,
        hash_value=f.md5,
        mime=f.mime_type,
        web_url=f.web_view_link,
    )


class GoogleDriveProvider:
    """
    CloudProvider implementation wrapping Google Drive API v3.
    """
    key: str = "gdrive"
    name: str = "Google Drive"

    def __init__(self, client_factory: Any = None) -> None:
        self._client_factory = client_factory or DriveClient

    def _get_client(self, acct: Account) -> DriveClient:
        return self._client_factory(email=acct.email)

    def authorize(self, ui_callbacks: Any = None) -> Account:
        from booklib.drive.auth import interactive_auth
        creds = interactive_auth(ui_callbacks=ui_callbacks)
        client = DriveClient(credentials=creds)
        about = client.get_about()
        email = about.get("emailAddress", "")
        display = about.get("displayName", "")
        return Account(
            provider=self.key,
            email=email,
            display_name=display,
            state="ok",
        )

    def list_children(self, acct: Account, folder_id: str, page: str | None = None) -> Page:
        client = self._get_client(acct)
        # DriveClient.list_folder_contents lists non-trashed children
        drive_files = client.list_folder_contents([folder_id])
        items = [_drive_file_to_remote_item(df) for df in drive_files]
        return Page(items=items, next_page=None)

    def initial_cursor(self, acct: Account) -> str:
        client = self._get_client(acct)
        return client.get_changes_start_token()

    def list_changes(self, acct: Account, cursor: str) -> ChangePage:
        client = self._get_client(acct)
        raw_changes, new_token = client.list_changes(cursor)
        changes: list[RemoteChange] = []
        for ch in raw_changes:
            file_id = ch.get("fileId", "")
            removed = bool(ch.get("removed"))
            raw_file = ch.get("file")
            item = None
            if raw_file and not removed:
                df = client._parse_file(raw_file)
                item = _drive_file_to_remote_item(df)
            changes.append(RemoteChange(file_id=file_id, removed=removed, item=item))
        return ChangePage(changes=changes, next_cursor=new_token, has_more=False)

    def open_download(self, acct: Account, item: RemoteItem, offset: int = 0) -> requests.Response:
        client = self._get_client(acct)
        return client.download_file_stream(item.id, start_byte=offset)

    def thumbnail(self, acct: Account, item: RemoteItem) -> bytes | None:
        client = self._get_client(acct)
        try:
            meta = client.get_file_metadata(item.id, fields="hasThumbnail,thumbnailLink")
            if meta.has_thumbnail and meta.thumbnail_link:
                resp = requests.get(meta.thumbnail_link, timeout=15)
                if resp.ok:
                    return resp.content
        except Exception as exc:
            logger.debug("Failed to fetch thumbnail for %s: %s", item.id, exc)
        return None

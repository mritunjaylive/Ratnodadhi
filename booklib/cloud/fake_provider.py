"""
booklib.cloud.fake_provider – In-memory mock cloud provider for unit and conformance testing.
"""
from __future__ import annotations

import io
from typing import Any
from booklib.cloud.provider import (
    Account,
    ChangePage,
    CloudProvider,
    Page,
    RemoteChange,
    RemoteItem,
    compute_quickxor_hash,
)


class FakeStream(io.BytesIO):
    """BytesIO wrapper that mimics a requests.Response raw stream."""
    def __init__(self, data: bytes) -> None:
        super().__init__(data)

    def iter_content(self, chunk_size: int = 1024):
        while True:
            chunk = self.read(chunk_size)
            if not chunk:
                break
            yield chunk


class FakeProvider:
    """
    In-memory CloudProvider implementation used for conformance tests and offline mocking.
    """
    key: str = "fake"
    name: str = "Fake Cloud Storage"

    def __init__(self) -> None:
        self.items: dict[str, RemoteItem] = {}
        self.files_data: dict[str, bytes] = {}
        self.thumbnails: dict[str, bytes] = {}
        self.change_history: list[RemoteChange] = []
        self._cursor_counter: int = 0

    def add_folder(self, folder_id: str, name: str, parent_id: str | None = None) -> RemoteItem:
        """Create a mock folder."""
        item = RemoteItem(
            id=folder_id,
            name=name,
            parent_id=parent_id,
            is_folder=True,
            size=0,
            mime="application/vnd.fake-folder",
        )
        self.items[folder_id] = item
        self.change_history.append(RemoteChange(file_id=folder_id, removed=False, item=item))
        return item

    def add_file(
        self,
        file_id: str,
        name: str,
        data: bytes,
        parent_id: str | None = None,
        mime: str = "application/pdf",
        thumb: bytes | None = None,
        hash_kind: str = "quickxor",
    ) -> RemoteItem:
        """Add a mock file with data and computed hash."""
        h_val = compute_quickxor_hash(data) if hash_kind == "quickxor" else "test-hash"
        item = RemoteItem(
            id=file_id,
            name=name,
            parent_id=parent_id,
            is_folder=False,
            size=len(data),
            hash_kind=hash_kind,
            hash_value=h_val,
            mime=mime,
        )
        self.items[file_id] = item
        self.files_data[file_id] = data
        if thumb:
            self.thumbnails[file_id] = thumb
        self.change_history.append(RemoteChange(file_id=file_id, removed=False, item=item))
        return item

    def remove_item(self, item_id: str) -> None:
        """Simulate deletion of a file or folder."""
        if item_id in self.items:
            del self.items[item_id]
        self.files_data.pop(item_id, None)
        self.thumbnails.pop(item_id, None)
        self.change_history.append(RemoteChange(file_id=item_id, removed=True, item=None))

    def move_item(self, item_id: str, new_parent_id: str | None) -> RemoteItem:
        """Simulate moving an item to a new parent."""
        item = self.items[item_id]
        item.parent_id = new_parent_id
        self.change_history.append(RemoteChange(file_id=item_id, removed=False, item=item))
        return item

    # ── CloudProvider Protocol Methods ────────────────────────────────────────

    def authorize(self, ui_callbacks: Any = None) -> Account:
        return Account(
            id=1,
            provider=self.key,
            email="tester@fakecloud.com",
            display_name="Tester Fake",
            state="ok",
        )

    def list_children(self, acct: Account, folder_id: str, page: str | None = None) -> Page:
        children = [item for item in self.items.values() if item.parent_id == folder_id]
        # Sort folders first, then alphabetically
        children.sort(key=lambda x: (not x.is_folder, x.name.lower()))

        page_size = 50
        offset = int(page) if page else 0
        paged_items = children[offset : offset + page_size]
        next_page = str(offset + page_size) if offset + page_size < len(children) else None
        return Page(items=paged_items, next_page=next_page)

    def initial_cursor(self, acct: Account) -> str:
        return str(len(self.change_history))

    def list_changes(self, acct: Account, cursor: str) -> ChangePage:
        try:
            start_idx = int(cursor)
        except ValueError:
            start_idx = 0

        changes = self.change_history[start_idx:]
        next_cursor = str(len(self.change_history))
        return ChangePage(changes=changes, next_cursor=next_cursor, has_more=False)

    def open_download(self, acct: Account, item: RemoteItem, offset: int = 0) -> FakeStream:
        data = self.files_data.get(item.id, b"")
        sliced = data[offset:]
        return FakeStream(sliced)

    def thumbnail(self, acct: Account, item: RemoteItem) -> bytes | None:
        return self.thumbnails.get(item.id)

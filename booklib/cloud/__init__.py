"""
booklib.cloud – Cloud storage provider abstraction, implementations, and helpers.
"""
from __future__ import annotations

from booklib.cloud.provider import (
    Account,
    ChangePage,
    CloudProvider,
    Page,
    RemoteChange,
    RemoteItem,
    compare_remote_hashes,
    compute_dropbox_content_hash,
    compute_quickxor_hash,
    get_provider,
    is_cloud_path,
    list_providers,
    make_virtual_cloud_path,
    parse_virtual_cloud_path,
    register_provider,
)
from booklib.cloud.fake_provider import FakeProvider
from booklib.cloud.gdrive import GoogleDriveProvider
from booklib.cloud.onedrive import OneDriveProvider
from booklib.cloud.dropbox import DropboxProvider

# Register default cloud providers
register_provider(FakeProvider())
register_provider(GoogleDriveProvider())
register_provider(OneDriveProvider())
register_provider(DropboxProvider())

__all__ = [
    "Account",
    "ChangePage",
    "CloudProvider",
    "Page",
    "RemoteChange",
    "RemoteItem",
    "compare_remote_hashes",
    "compute_dropbox_content_hash",
    "compute_quickxor_hash",
    "get_provider",
    "is_cloud_path",
    "list_providers",
    "make_virtual_cloud_path",
    "parse_virtual_cloud_path",
    "register_provider",
    "FakeProvider",
    "GoogleDriveProvider",
    "OneDriveProvider",
    "DropboxProvider",
]

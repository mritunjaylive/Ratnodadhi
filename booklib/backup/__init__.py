"""
booklib/backup – Pluggable backup, restore, safety snapshots, and scheduling.
"""
from booklib.backup.snapshot import take_db_snapshot, SnapshotError
from booklib.backup.package import build_backup_zip, verify_backup_zip, BackupPackageError
from booklib.backup.destinations import (
    BackupInfo,
    BackupDestination,
    LocalFolderDestination,
    GoogleDriveDestination,
)
from booklib.backup.safety import (
    take_safety_snapshot,
    list_safety_snapshots,
    restore_safety_snapshot,
    prune_safety_snapshots,
)
from booklib.backup.restore import (
    verify_and_prepare_restore,
    apply_staged_restore,
    check_and_apply_pending_restore,
    RestoreError,
)
from booklib.backup.scheduler import (
    should_run_backup,
    run_scheduled_backup,
    mark_dirty,
    clear_dirty,
    is_dirty,
)

__all__ = [
    "take_db_snapshot",
    "SnapshotError",
    "build_backup_zip",
    "verify_backup_zip",
    "BackupPackageError",
    "BackupInfo",
    "BackupDestination",
    "LocalFolderDestination",
    "GoogleDriveDestination",
    "take_safety_snapshot",
    "list_safety_snapshots",
    "restore_safety_snapshot",
    "prune_safety_snapshots",
    "verify_and_prepare_restore",
    "apply_staged_restore",
    "check_and_apply_pending_restore",
    "RestoreError",
    "should_run_backup",
    "run_scheduled_backup",
    "mark_dirty",
    "clear_dirty",
    "is_dirty",
]

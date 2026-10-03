"""
duplicates package.
"""
from booklib.duplicates.hashing import compute_quick_hash, compute_full_hash
from booklib.duplicates.finder import find_duplicate_groups, DuplicateGroup
from booklib.duplicates.merge import merge_book_user_data
from booklib.duplicates.actions import remove_from_library, send_to_recycle_bin, ignore_group

__all__ = [
    "compute_quick_hash",
    "compute_full_hash",
    "find_duplicate_groups",
    "DuplicateGroup",
    "merge_book_user_data",
    "remove_from_library",
    "send_to_recycle_bin",
    "ignore_group",
]

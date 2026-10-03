"""
booklib.extract – Crash-isolated background extraction workers and helpers.
"""
from booklib.extract.pool import (
    get_extractor_pool,
    run_in_extractor,
    run_in_extractor_sync,
    sweep_extractor_temp_dir,
    shutdown_extractor_pool,
)

__all__ = [
    "get_extractor_pool",
    "run_in_extractor",
    "run_in_extractor_sync",
    "sweep_extractor_temp_dir",
    "shutdown_extractor_pool",
]

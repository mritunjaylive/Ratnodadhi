"""
extract/pool.py – Extractor process pool for crash-isolated background work.

Isolates native file parsing (PyMuPDF, zip, etc.) in separate worker processes
so a corrupt file or native crash cannot crash the main application process.

Features:
- Fixed pool of 2 worker processes using the 'spawn' start method.
- Dedicated per-worker temp directory in <app data>/tmp/extract/<pid>-<uid>.
- 500 MB per-file temp usage guard.
- Startup sweep of orphaned extractor temp folders.
- Clean shutdown on app exit.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
import shutil
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, Future
from pathlib import Path
from typing import Any, Callable

from booklib.config import EXTRACT_TMP_DIR

logger = logging.getLogger(__name__)

_MAX_WORKERS = 2
_PER_FILE_TEMP_LIMIT_BYTES = 500 * 1024 * 1024  # 500 MB
_ORPHAN_TEMP_MAX_AGE_SECONDS = 24 * 3600         # 1 day

_pool_executor: ProcessPoolExecutor | None = None
_mp_context: mp.context.BaseContext | None = None


def _worker_init(base_tmp_dir: str) -> None:
    """Initialize a worker process: create its dedicated temp directory and set env."""
    pid = os.getpid()
    Path(base_tmp_dir).mkdir(parents=True, exist_ok=True)
    worker_tmp = Path(tempfile.mkdtemp(prefix=f"{pid}-", dir=base_tmp_dir))
    os.environ["BOOKLIB_EXTRACT_TMP"] = str(worker_tmp)
    os.environ["TMPDIR"] = str(worker_tmp)
    os.environ["TEMP"] = str(worker_tmp)
    os.environ["TMP"] = str(worker_tmp)


def _worker_exec_wrapper(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Wrapper executed in worker to guard temp directory usage."""
    worker_tmp = os.environ.get("BOOKLIB_EXTRACT_TMP")
    try:
        res = fn(*args, **kwargs)
        if worker_tmp and Path(worker_tmp).exists():
            usage = sum(f.stat().st_size for f in Path(worker_tmp).rglob("*") if f.is_file())
            if usage > _PER_FILE_TEMP_LIMIT_BYTES:
                raise RuntimeError(
                    f"Temp directory usage exceeded limit ({usage} > {_PER_FILE_TEMP_LIMIT_BYTES} bytes)"
                )
        return res
    finally:
        # Clean any files created in the worker temp during this task
        if worker_tmp and Path(worker_tmp).exists():
            for item in Path(worker_tmp).iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                except Exception:
                    pass


def get_extractor_pool() -> ProcessPoolExecutor:
    """Return the global extractor ProcessPoolExecutor (lazy init)."""
    global _pool_executor, _mp_context
    if _pool_executor is None:
        _mp_context = mp.get_context("spawn")
        EXTRACT_TMP_DIR.mkdir(parents=True, exist_ok=True)
        _pool_executor = ProcessPoolExecutor(
            max_workers=_MAX_WORKERS,
            mp_context=_mp_context,
            initializer=_worker_init,
            initargs=(str(EXTRACT_TMP_DIR),),
        )
        logger.info("Extractor process pool started with %d workers", _MAX_WORKERS)
    return _pool_executor


def run_in_extractor(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
    """
    Submit a top-level callable to the extractor process pool.

    Returns a concurrent.futures.Future.
    """
    pool = get_extractor_pool()
    return pool.submit(_worker_exec_wrapper, fn, *args, **kwargs)


def run_in_extractor_sync(fn: Callable[..., Any], *args: Any, timeout: float | None = 30.0, **kwargs: Any) -> Any:
    """
    Run a top-level callable synchronously in the extractor pool.
    Catches process termination/errors and raises RuntimeError on crash.
    """
    future = run_in_extractor(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except Exception as exc:
        logger.warning("Extractor task %s failed: %s", fn.__name__, exc)
        raise


def sweep_extractor_temp_dir() -> int:
    """
    Sweep orphaned worker temp folders at startup.
    Removes folders belonging to non-running PIDs or older than 1 day.
    Returns the number of cleaned folders.
    """
    if not EXTRACT_TMP_DIR.exists():
        return 0

    now = time.time()
    cleaned = 0

    for item in EXTRACT_TMP_DIR.iterdir():
        if not item.is_dir():
            continue
        parts = item.name.split("-")
        try:
            pid = int(parts[0])
        except (ValueError, IndexError):
            pid = None

        is_orphan = False
        # Age check
        try:
            age = now - item.stat().st_mtime
            if age > _ORPHAN_TEMP_MAX_AGE_SECONDS:
                is_orphan = True
        except Exception:
            pass

        # PID liveness check
        if pid is not None and not is_orphan:
            if not _is_pid_alive(pid):
                is_orphan = True

        if is_orphan:
            try:
                shutil.rmtree(item, ignore_errors=True)
                cleaned += 1
                logger.info("Swept orphaned extractor temp folder: %s", item.name)
            except Exception as exc:
                logger.warning("Failed to remove orphan temp %s: %s", item.name, exc)

    return cleaned


def shutdown_extractor_pool() -> None:
    """Gracefully shutdown the extractor pool."""
    global _pool_executor
    if _pool_executor is not None:
        try:
            _pool_executor.shutdown(wait=False, cancel_futures=True)
        except Exception as exc:
            logger.warning("Error shutting down extractor pool: %s", exc)
        _pool_executor = None


def _is_pid_alive(pid: int) -> bool:
    """Check if process with given PID is alive."""
    if pid <= 0:
        return False
    import sys
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not process:
            return False
        kernel32.CloseHandle(process)
        return True
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

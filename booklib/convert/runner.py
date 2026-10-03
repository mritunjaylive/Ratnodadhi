"""
convert/runner.py – Build the ebook-convert command and run it.

- Builds the argument list from available metadata fields only
- Reads progress from output lines matching r"(\\d{1,3})%"
- Keeps the last 40 lines for error_tail on failure
- Cancel: terminates the process + child processes
- Timeout: default 600 seconds (configurable)
- Maps failure messages to friendly strings
"""
from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_PROGRESS_RE = re.compile(r"(\d{1,3})%")
_TAIL_LINES = 40
DEFAULT_TIMEOUT = 600   # seconds


class ConversionError(Exception):
    """Raised when Calibre exits with an error."""
    def __init__(self, message: str, tail: str = "") -> None:
        super().__init__(message)
        self.friendly = message
        self.tail = tail


def run_conversion(
    exe: Path,
    src_path: Path,
    dest_folder: Path,
    to_format: str,
    book: dict,                       # book metadata dict
    extra_args: list[str] | None = None,
    cover_path: Path | None = None,
    on_progress: Callable[[int], None] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Path:
    """
    Run ebook-convert and return the path of the output file.

    The output is first written to a temp name (registered in the temp_files table
    via the caller), then atomically renamed to the final name.

    Raises ConversionError on failure.
    """
    ext = to_format.lower().lstrip(".")
    safe_title = (book.get("title") or src_path.stem)[:80]
    tmp_name = f"{safe_title}.tmp-{uuid.uuid4()}.{ext}"
    tmp_out = dest_folder / tmp_name
    final_name = f"{safe_title}.{ext}"
    final_out = dest_folder / final_name
    # Handle conflicts
    if final_out.exists():
        counter = 2
        while (dest_folder / f"{safe_title} ({counter}).{ext}").exists():
            counter += 1
        final_out = dest_folder / f"{safe_title} ({counter}).{ext}"

    cmd = _build_cmd(exe, src_path, tmp_out, book, cover_path, extra_args or [])
    logger.info("Running Calibre: %s", " ".join(str(c) for c in cmd))

    # Platform-specific process creation
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **kwargs,
    )

    tail_lines: list[str] = []
    deadline = time.monotonic() + timeout

    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            tail_lines.append(line)
            if len(tail_lines) > _TAIL_LINES:
                tail_lines.pop(0)

            m = _PROGRESS_RE.search(line)
            if m and on_progress:
                on_progress(int(m.group(1)))

            if time.monotonic() > deadline:
                _kill(proc)
                raise ConversionError("Conversion timed out", "".join(tail_lines))
    except ConversionError:
        tmp_out.unlink(missing_ok=True)
        raise

    proc.wait()
    tail_str = "".join(tail_lines)

    if proc.returncode != 0:
        tmp_out.unlink(missing_ok=True)
        raise ConversionError(_friendly_error(tail_str), tail_str)

    # Atomic rename to final name
    try:
        os.rename(str(tmp_out), str(final_out))
    except OSError as exc:
        tmp_out.unlink(missing_ok=True)
        raise ConversionError(f"Could not rename output file: {exc}", tail_str)

    return final_out


def _build_cmd(
    exe: Path,
    src: Path,
    tmp_out: Path,
    book: dict,
    cover_path: Path | None,
    extra_args: list[str],
) -> list[str]:
    cmd: list[str] = [str(exe), str(src), str(tmp_out)]

    def add(flag: str, val: str | None) -> None:
        if val and str(val).strip():
            cmd.extend([flag, str(val).strip()])

    add("--title",        book.get("title"))
    add("--authors",      book.get("author"))
    add("--publisher",    book.get("publisher"))
    add("--isbn",         book.get("isbn"))
    add("--language",     book.get("language"))
    add("--series",       book.get("series_name") or book.get("series"))
    si = book.get("series_index")
    if si is not None:
        add("--series-index", str(si))
    tags = book.get("tags_text") or book.get("tags")
    if isinstance(tags, list):
        tags = ", ".join(str(t) for t in tags)
    add("--tags", tags)

    # Cover: only if it's a real file (not placeholder)
    if cover_path and cover_path.is_file() and book.get("cover_source") not in ("placeholder", None):
        add("--cover", str(cover_path))

    # Extra args (never through a shell)
    if extra_args:
        cmd.extend(extra_args)

    return cmd


def _kill(proc: subprocess.Popen) -> None:
    """Terminate process and all children."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True, timeout=5,
            )
        else:
            import signal, os
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception as exc:
        logger.warning("Could not kill Calibre process: %s", exc)
        proc.terminate()


def _friendly_error(tail: str) -> str:
    """Map Calibre error output to a friendly message."""
    low = tail.lower()
    if "drm" in low:
        return "This book is DRM-protected and cannot be converted."
    if "unsupported input format" in low or "no input plugin" in low:
        return "This input format is not supported by your Calibre version."
    if "no space left" in low or "disk full" in low:
        return "Not enough disk space to complete the conversion."
    if "permission denied" in low:
        return "Permission denied — check that the file is not open in another application."
    if "is not a known input format" in low:
        return "Calibre does not recognize this file format."
    return "Calibre returned an error. See the conversion log for details."

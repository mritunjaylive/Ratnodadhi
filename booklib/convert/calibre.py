"""
convert/calibre.py – Detect ebook-convert and verify its version.

Search order:
  1. Path stored in QSettings ("calibre/exe_path")
  2. shutil.which("ebook-convert")
  3. Standard install locations (Windows, macOS, Linux)
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_STANDARD_LOCATIONS = []
if sys.platform == "win32":
    _STANDARD_LOCATIONS = [
        Path(r"C:\Program Files\Calibre2\ebook-convert.exe"),
        Path(r"C:\Program Files (x86)\Calibre2\ebook-convert.exe"),
    ]
elif sys.platform == "darwin":
    _STANDARD_LOCATIONS = [
        Path("/Applications/calibre.app/Contents/MacOS/ebook-convert"),
        Path("/usr/local/bin/ebook-convert"),
    ]
else:
    _STANDARD_LOCATIONS = [
        Path("/usr/bin/ebook-convert"),
        Path("/usr/local/bin/ebook-convert"),
        Path("/opt/calibre/ebook-convert"),
    ]

_SETTINGS_KEY = "calibre/exe_path"


def find_ebook_convert(settings_path: str = "") -> Path | None:
    """
    Try to locate ebook-convert. Returns the Path if found, else None.
    *settings_path*: value from QSettings (may be empty).
    """
    candidates: list[Path] = []

    if settings_path:
        candidates.append(Path(settings_path))

    which = shutil.which("ebook-convert")
    if which:
        candidates.append(Path(which))

    candidates.extend(_STANDARD_LOCATIONS)

    for p in candidates:
        if p.is_file():
            return p
    return None


def get_version(exe: Path) -> str | None:
    """
    Run `ebook-convert --version` and return the version string, or None on failure.
    """
    try:
        result = subprocess.run(
            [str(exe), "--version"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines() + result.stderr.splitlines():
            if "calibre" in line.lower() or line.strip().startswith("ebook-convert"):
                return line.strip()
        return result.stdout.strip() or result.stderr.strip() or "Unknown"
    except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError) as exc:
        logger.warning("Calibre version check failed: %s", exc)
        return None


# ── Conversion matrix ─────────────────────────────────────────────────────────

# (from_format, to_format) → quality note shown in the dialog
CONVERSION_MATRIX: dict[tuple[str, str], str] = {
    ("epub", "azw3"):  "Good — standard Kindle format",
    ("epub", "mobi"):  "Good — legacy Kindle format",
    ("epub", "pdf"):   "Good — layout depends on page settings",
    ("epub", "txt"):   "Good — plain text, no formatting",
    ("epub", "docx"):  "Good",
    ("mobi", "epub"):  "Good for books without DRM",
    ("mobi", "azw3"):  "Good for books without DRM",
    ("mobi", "pdf"):   "Good",
    ("azw3", "epub"):  "Good for books without DRM",
    ("azw3", "pdf"):   "Good",
    ("docx", "epub"):  "Good",
    ("docx", "pdf"):   "Good",
    ("txt",  "epub"):  "Good — basic structure only",
    ("txt",  "pdf"):   "Good",
    ("pdf",  "epub"):  "Varies: columns, tables, scanned pages often poor",
    ("pdf",  "azw3"):  "Varies: may need manual review",
    ("pdf",  "txt"):   "Good for text-layer PDFs; fails for scanned pages",
    ("pdf",  "docx"):  "Varies: formatting usually lost",
}

QUALITY_WARNINGS = {
    "pdf_source":   "PDF conversion quality varies greatly. Scanned or complex PDFs may not convert usefully.",
    "pdf_dest":     "PDF output is a fixed-layout file, not reflowable.",
    "drm_note":     "DRM-protected books will fail to convert. This app does not remove DRM.",
    "mobi_legacy":  "MOBI is a legacy format; AZW3 is preferred for modern Kindles.",
}


def available_targets(from_format: str) -> list[str]:
    """Return a list of target formats for *from_format*."""
    fmt = from_format.lower()
    return [to for (frm, to) in CONVERSION_MATRIX if frm == fmt]


def quality_note(from_format: str, to_format: str) -> str:
    """Return the quality note for a conversion pair."""
    return CONVERSION_MATRIX.get(
        (from_format.lower(), to_format.lower()),
        "Quality depends on Calibre version and source quality",
    )

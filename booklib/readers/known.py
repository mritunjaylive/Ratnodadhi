"""
known.py – well-known readers and their standard install paths.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from booklib.readers.models import Reader

# (name, exe_name, look_in_dirs, formats)
_KNOWN_READERS = [
    ("SumatraPDF",            "SumatraPDF.exe",
     ["SumatraPDF"],          frozenset({"pdf", "epub", "mobi", "djvu", "cbz"})),
    ("Adobe Acrobat",         "Acrobat.exe",
     ["Adobe/Acrobat DC/Acrobat", "Adobe/Acrobat Reader DC/Reader"],
     frozenset({"pdf"})),
    ("Foxit PDF Reader",      "FoxitPDFReader.exe",
     ["Foxit Software/Foxit PDF Reader"],   frozenset({"pdf"})),
    ("Calibre Viewer",        "ebook-viewer.exe",
     ["Calibre2", "calibre"],
     frozenset({"epub", "mobi", "azw3", "pdf", "cbz", "txt"})),
    ("Thorium Reader",        "Thorium.exe",
     ["Programs/Thorium"],    frozenset({"epub"})),
    ("Kindle for PC",         "Kindle.exe",
     ["Amazon/Kindle"],       frozenset({"mobi", "azw3"})),
    ("Okular",                "okular.exe",
     ["KDE/Okular"],          frozenset({"pdf", "epub", "djvu"})),
]


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        val = os.environ.get(env)
        if val:
            roots.append(Path(val))
    return roots


def detect_known() -> list[Reader]:
    """Return well-known readers that exist on this machine."""
    readers: list[Reader] = []
    roots = _candidate_roots()

    for name, exe_name, subdirs, formats in _KNOWN_READERS:
        found: str | None = None

        # 1. Check standard install locations
        for root in roots:
            for sub in subdirs:
                candidate = root / sub / exe_name
                if candidate.exists():
                    found = str(candidate)
                    break
            if found:
                break

        # 2. Check PATH
        if not found:
            found = shutil.which(exe_name)

        if found:
            readers.append(Reader(
                key=f"detected:{found}",
                name=name,
                exe=found,
                formats=formats,
            ))
    return readers

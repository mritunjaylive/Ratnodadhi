"""
booklib.reader – Built-in document reader package.
"""
from booklib.reader.backend import (
    DocumentBackend,
    Hit,
    Link,
    Locator,
    TextWord,
    TocEntry,
)
from booklib.reader.mupdf_backend import MuPdfBackend

__all__ = [
    "DocumentBackend",
    "Locator",
    "TextWord",
    "Hit",
    "Link",
    "TocEntry",
    "MuPdfBackend",
]

"""
config.py – application-wide paths, constants and supported extensions.
"""
from __future__ import annotations

import platformdirs

APP_NAME = "BookLib"
APP_AUTHOR = "BookLib"

# ── App-data directories ─────────────────────────────────────────────────────
DATA_DIR = platformdirs.user_data_path(APP_NAME, APP_AUTHOR)
LOG_FILE = DATA_DIR / "app.log"
DB_PATH = DATA_DIR / "library.db"
COVERS_DIR = DATA_DIR / "covers"
DRIVE_CACHE_DIR = DATA_DIR / "drive_cache"
GOOGLE_CLIENT_FILE = DATA_DIR / "google_client.json"
CACHE_MARKER_FILE = ".booklib-cache"
SAFETY_DIR = DATA_DIR / "safety"  # v5 safety snapshots
FULLTEXT_DB_PATH = DATA_DIR / "fulltext.db"
EXTRACT_TMP_DIR = DATA_DIR / "tmp" / "extract"
WEB_LOG_FILE = DATA_DIR / "web_access.log"

# ── Supported file extensions (lower-case, without the dot) ──────────────────
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {"pdf", "epub", "mobi", "azw3", "djvu", "cbz", "txt"}
)

# ── Cover thumbnail settings ─────────────────────────────────────────────────
COVER_WIDTH = 300          # pixels, keep aspect ratio
COVER_QUALITY = 85         # JPEG quality
COVER_PLACEHOLDER_HEIGHT = 450  # for generated placeholders

# ── Scanner ──────────────────────────────────────────────────────────────────
SCAN_BATCH_SIZE = 25       # commit every N books during a scan

# ── Junk-title patterns ──────────────────────────────────────────────────────
JUNK_TITLE_PREFIXES: tuple[str, ...] = (
    "microsoft word",
    "untitled",
)
JUNK_TITLE_SUFFIXES: tuple[str, ...] = (
    ".doc",
    ".docx",
    ".indd",
)

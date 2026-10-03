"""
booklib_web.config – Configuration dataclass and defaults for the BookLib web server.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from booklib.config import COVERS_DIR, DB_PATH, WEB_LOG_FILE


@dataclass
class WebConfig:
    db_path: Path = field(default_factory=lambda: DB_PATH)
    covers_dir: Path = field(default_factory=lambda: COVERS_DIR)
    log_file: Path = field(default_factory=lambda: WEB_LOG_FILE)
    host: str = "127.0.0.1"
    port: int = 8765
    secret_key: str = field(default_factory=lambda: secrets.token_hex(32))
    allow_changes: bool = False
    allow_cloud_downloads: bool = False
    daily_budget_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GB
    auto_off_minutes: int = 240  # 4 hours
    opds_key: str | None = None
    password_hash: str | None = None
    password_salt: str | None = None

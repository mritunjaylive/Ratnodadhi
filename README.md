# Ratnodadhi (BookLib)

[![Version](https://img.shields.io/badge/version-6.0-blue.svg)]()
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Qt 6](https://img.shields.io/badge/GUI-PySide6%20%28Qt6%29-green.svg)](https://wiki.qt.io/Qt_for_Python)
[![Reader](https://img.shields.io/badge/Engine-PyMuPDF-orange.svg)](https://pymupdf.readthedocs.io/)
[![Search](https://img.shields.io/badge/FTS-SQLite5%20BM25-yellowgreen.svg)](https://www.sqlite.org/fts5.html)
[![Web](https://img.shields.io/badge/Server-Flask%20%2B%20Waitress-red.svg)](https://flask.palletsprojects.com/)
[![Windows Installer](https://img.shields.io/badge/Windows-Inno%20Setup%207-0078d4.svg)](https://jrsoftware.org/isdl.php)
[![Tests](https://img.shields.io/badge/Tests-270%20passing-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> *Named after **Ratnodadhi** ("Ocean of Gems"), the legendary nine-story library of ancient Nalanda University.*

**Ratnodadhi** is an offline-first, privacy-focused, high-performance desktop digital library and reading environment. It combines powerful catalog management, a built-in multi-format reader, in-book full-text search, local recommendation algorithms, reading-streak analytics, cloud storage synchronization, and a secure local web / OPDS 1.2 catalog server.

---

## Key Features

### 1. Built-in Multi-Format Reader
- **Universal Format Support**: Opens **PDF**, **EPUB**, **MOBI**, **FB2**, **CBZ** (comics), and **TXT** files natively via PyMuPDF.
- **Viewing Modes**: Single-page, continuous vertical scrolling, and facing two-page spreads.
- **Reflowable Books (EPUB / MOBI / FB2 / TXT)**:
  - Custom font size, line height, and margin adjustments.
  - Paginated and smooth-scroll reading modes.
  - Multiple color themes: *Light*, *Sepia*, *Dark*, and *OLED Black*.
- **Interactive Tools**:
  - Full text selection, clipboard copy, and clickable link navigation.
  - In-book search with hit highlighting and next/previous jump navigation.
  - Table of contents panel, visual page thumbnail bar, page rotation, and zoom controls (*Fit Width*, *Fit Page*, custom %).
  - Password prompt for encrypted PDF documents.
  - Multi-document tabbed reading interface.

### 2. Annotations, Bookmarks & Reading Position
- **Layout-Independent Locators**: Resuming reading works across window resizing, screen orientation, and font-size changes.
- **Non-Destructive Highlights & Notes**:
  - Annotations live securely in the database; original book files are **never modified**.
  - Highlights in customizable colors with attached notes.
  - Robust fuzzy token-sequence anchoring survives text reflow and formatting changes.
  - Orphan handling preserves annotations even if the underlying book file is replaced.
- **Exporting & Integration**:
  - Export annotations to **Markdown**, **HTML**, **CSV**, or **JSON**.
  - **Export Annotated PDF**: Generates a standard PDF copy with native PDF highlight annotations.
  - **Import Highlights**: Reads and imports existing highlights embedded in external PDFs.
- **Bookmarks**: Quick-toggle ribbons with custom titles and jump list.

### 3. Full-Text Search Inside Books
- **High-Performance FTS5 Engine**: Contentless SQLite FTS5 index stored in a separate, rebuildable `fulltext.db`.
- **Advanced Query Syntax (`Ctrl+Shift+F`)**:
  - Exact phrase search: `"machine learning"`
  - Term exclusion: `python -django`
  - Prefix matching: `comput*`
  - Boolean combinations: `algorithm OR data`
- **Smart Snippets**: Dynamic on-demand snippet generation with highlighted matching terms.
- **Index Management**: Background indexing runs in isolated worker processes with automatic battery pausing, 2 GB size guard, auto-trimming by recency, and incremental auto-vacuum compaction.

### 4. Reading-Time Statistics & Analytics
- **Active Session Tracking**: Automatically measures true reading time, discarding idle pauses (>60s).
- **Reading Streaks**: Tracks current streak and all-time longest streak with automatic grace-period handling.
- **Visual Analytics**:
  - 12-month GitHub-style reading activity heatmap.
  - Daily, weekly, monthly, and yearly reading duration summary cards.
  - Per-book estimated time to finish based on personalized reading pace.
  - Annual reading goals and progress projections.

### 5. Heuristic Recommendation Engine
- **100% Local & Private**: No data or reading habits ever leave your device.
- **Hybrid Content Scoring**: Evaluates genre overlap, author affinity, tags, and gives series continuation bonuses for books you own but haven't read.
- **Diversity by Design**: Uses Maximal Marginal Relevance (MMR) diversification to prevent narrow recommendation bubbles.
- **Plain-Language Explanations**: Understand why a book is recommended (*"Because you rated Clean Code 5 stars and read other Programming books"*).
- **Discovery Tools**: "Surprise Me" random picker, "Similar Books" pane, and negative feedback ("Not interested" / "Hide from suggestions").

### 6. Local Web Access & OPDS 1.2 Catalog
- **Read Anywhere on Your Home Network**:
  - Browse, filter, search, and download books from your phone or tablet on local Wi-Fi.
  - Responsive, touch-friendly, dark-mode web interface with zero CDN dependencies.
- **OPDS 1.2 Catalog**:
  - Compatible with mobile e-reading apps (e.g. Moon+ Reader, KOReader, KyBook, Librera).
  - Atom XML feeds for Recently Added, Continue Reading, Want to Read, Authors, Series, and OpenSearch.
  - Separate revocable HTTP Basic authentication key (`booklib:<opds_key>`).
- **Home Network Security**:
  - Default loopback binding; LAN access requires explicit opt-in.
  - scrypt password hashing and single-use 5-minute QR pairing codes.
  - Brute-force IP rate-limiting and temporary lockout (HTTP 429).
  - CSRF protection on mutating endpoints, strict Content Security Policy, and HTTP security headers (`nosniff`, `X-Frame-Options: DENY`).
  - Resumable downloads via HTTP `Range` (partial 206, suffix ranges, 416 bounds checking).
  - 2 GB daily web download budget protection and rotating access logs.
- **Headless Mode**: Can run without a GUI on a Raspberry Pi or home server (`python -m booklib_web`).

### 7. Multi-Cloud Synchronization & Storage Management
- **Unified Provider Abstraction**: Generic `CloudProvider` protocol powering cloud sources:
  - **Google Drive**: Drive API v3 sync, change tokens, thumbnails, and streaming downloads.
  - **Microsoft OneDrive**: Microsoft Graph API delta sync and Microsoft QuickXorHash integrity checking.
  - **Dropbox**: Dropbox API v2 cursors, 4 MB chunked `content_hash` verification.
- **Tier 0 Cloud Leases**: Books currently open in the reader or streaming over web access hold protective leases that prevent cache eviction.
- **Storage Guard**: Proactive disk space checks, cache pruning policies, temp file sweeps, and safety snapshots before database migrations.

### 8. Core Library & Resilient Scanning Engine
- **High-Performance Rescan Engine**: Optimized scanning for large collections (3,000+ books) with smart missing-book bypass and transactional database commit batching (eliminating disk fsync bottlenecks).
- **Automated Directory Watchers**: Recursively watches library folders with background file-system watchers to detect newly added or removed books in real time.
- **Multi-Source Library Sync**: Watches and rescans both local directories and Google Drive cloud folders simultaneously.
- **Rich Cover Generation**: Extracts embedded cover art or renders elegant typographic SVG/JPEG placeholders.
- **Metadata Fetching**: Online lookups via OpenLibrary and Google Books with cover downloads.
- **Batch Tools**: Calibre format conversion (`ebook-convert`), batch file renaming with undo, duplicate file detector, and library health diagnostics.
- **Action Registry & Command Palette**: Quick access to any command via `Ctrl+K`, with fully customizable keyboard shortcuts.

---

## Architecture & Project Structure

```
book-library/
├── booklib/                      # Core Desktop Application (Qt6 / PySide6)
│   ├── actions.py                # Central action registry and shortcut bindings
│   ├── app.py                    # Qt Application bootstrap and startup maintenance
│   ├── config.py                 # Paths, constants, and supported format definitions
│   ├── services.py               # Background service manager (indexer, web server)
│   ├── backup/                   # Automated backups, safety snapshots, and restore
│   ├── cloud/                    # Multi-cloud provider abstraction & implementations
│   │   ├── provider.py           # CloudProvider Protocol, RemoteItem, and hash utilities
│   │   ├── gdrive.py             # Google Drive provider implementation
│   │   ├── onedrive.py           # Microsoft OneDrive Graph provider
│   │   ├── dropbox.py            # Dropbox API v2 provider
│   │   └── fake_provider.py      # In-memory mock provider for testing
│   ├── convert/                  # Calibre ebook-convert integration
│   ├── covers/                   # Cover art extraction, scaling, and placeholder generators
│   ├── db/                       # SQLite connection, repositories, and migrations 1–6b
│   ├── drive/                    # Google Drive integration (auth, cache, sync)
│   ├── duplicates/               # Exact and fuzzy duplicate book detection
│   ├── extract/                  # Crash-isolated worker process extraction pool
│   ├── fulltext/                 # SQLite FTS5 engine, chunking, scheduler, and compacting
│   ├── jobs/                     # Background job manager with prioritized lanes
│   ├── metadata/                 # Embedded metadata extractors and online ISBN lookups
│   ├── organize/                 # File organizer and rule-based renamer
│   ├── reader/                   # Built-in document reader engine
│   │   ├── backend.py            # DocumentBackend protocol
│   │   ├── fitz_backend.py       # PyMuPDF implementation
│   │   ├── locators.py           # Resilient reading position locators
│   │   ├── annotations.py        # Non-destructive highlights and fuzzy re-anchoring
│   │   ├── sessions.py           # Active reading time measurement
│   │   ├── export.py             # Annotation export (MD, HTML, CSV, JSON, PDF)
│   │   ├── pdf_view.py           # PDF continuous / single / facing render widget
│   │   ├── reflow_view.py        # EPUB / MOBI / TXT reflowable render widget
│   │   └── reader_window.py      # Multi-tab reader main window
│   ├── recommend/                # Heuristic recommendations (profile, scoring, MMR)
│   ├── stats/                    # Reading statistics, streaks, and heatmap computation
│   ├── storage/                  # Disk space guards, cache policies, and temp sweepers
│   ├── ui/                       # PySide6 desktop UI (MainWindow, Dialogs, Widgets)
│   └── watcher/                  # Real-time directory filesystem watcher
├── booklib_web/                  # Local Web & OPDS Server (Qt-free, Flask + Waitress)
│   ├── app.py                    # Flask application factory
│   ├── config.py                 # Web configuration dataclass
│   ├── security.py               # Auth, scrypt hashing, CSRF, rate-limiting, pairing
│   ├── opds.py                   # OPDS 1.2 Atom XML catalog feeds
│   ├── routes_ui.py              # Web browser HTML routes (library, shelves, details)
│   ├── routes_api.py             # REST API routes (books, status, ratings, notes)
│   ├── routes_files.py           # HTTP Range file streaming and download budget
│   ├── server.py                 # Background thread server runner
│   ├── static/                   # Pure CSS and JavaScript assets (no external CDNs)
│   └── templates/                # Jinja2 responsive HTML templates
├── tests/                        # Comprehensive test suite (270 unit & integration tests)
├── build_installer.py            # Automated build script for PyInstaller + Inno Setup 7
├── installer.iss                 # Inno Setup 7 Windows installer compiler script
├── ratnodadhi.spec               # PyInstaller standalone application specification
├── ratnodadhi-onefile.spec       # PyInstaller single-file portable specification
├── main.py                       # Desktop application entry point
├── requirements.txt              # Production and development dependencies
└── pytest.ini                    # Test suite configuration
```

---

## Installation & Distribution

### Option A: Windows Installer (Recommended for Users)

Download and run the official Windows setup installer:

- **Installer File**: `Ratnodadhi-Setup-v6.0.exe` (available in `dist-installer/` or GitHub Releases).
- **Dual-Mode Setup**: Supports installation for Current User (`AppData\Local\Programs\Ratnodadhi` – no admin rights required) or System-Wide for all users (`Program Files\Ratnodadhi`).
- **Seamless In-Place Upgrades**:
  - Running a newer installer updates existing binaries directly without requiring manual uninstallation.
  - User data, SQLite databases (`library.db`, `fulltext.db`), custom annotations, bookmarks, reading statistics, and settings are preserved safely in `%LocalAppData%\BookLib` and are **never deleted or overwritten during upgrades or uninstalls**.
  - Built-in Windows Restart Manager integration closes running application instances gracefully before updating files.

---

### Option B: Building the Standalone App & Installer from Source

You can build the standalone executable and Windows installer with a single command:

#### Prerequisites
1. **Python 3.10+** (Python 3.10 to 3.13 supported)
2. **PyInstaller**:
   ```bash
   pip install pyinstaller
   ```
3. **Inno Setup 7** (or Inno Setup 6):
   - Install via Winget:
     ```powershell
     winget install JRSoftware.InnoSetup
     ```
   - Or download from [JRSoftware Inno Setup](https://jrsoftware.org/isdl.php).

#### Build Command
Run the build script:

```bash
python build_installer.py
```

The script will automatically:
1. Bundle the Python application and all native dependencies (PySide6, PyMuPDF, etc.) into `dist/Ratnodadhi/` using PyInstaller.
2. Locate the Inno Setup compiler (`ISCC.exe`) on your system or registry.
3. Compile `installer.iss` with ultra LZMA2 solid compression into:
   ```
   dist-installer/Ratnodadhi-Setup-v6.0.exe
   ```

*Tip*: To recompile only the Windows installer when the PyInstaller bundle is already built, run:
```bash
python build_installer.py --installer-only
```

---

### Option C: Developer Setup (Running from Source)

#### 1. Clone & Set Up Virtual Environment

```bash
# Clone the repository
git clone https://github.com/your-username/book-library.git
cd book-library

# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (cmd):
.venv\Scripts\activate.bat
# Linux / macOS:
source .venv/bin/activate
```

#### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Usage

### Running the Desktop App

Launch the full desktop application:

```bash
python main.py
```

### Running the Web / OPDS Server Headless

To run the web and OPDS server on a home server, NAS, or Raspberry Pi without launching the desktop UI:

```bash
# Listen on local network (port 8765)
python -m booklib_web --host 0.0.0.0 --port 8765
```

Access the web interface at `http://<your-ip>:8765` or connect your mobile reading app to `http://<your-ip>:8765/opds`.

---

## Useful Keyboard Shortcuts

| Shortcut | Context | Action |
|---|---|---|
| `Ctrl+O` | Global | Add book files |
| `Ctrl+Shift+O` | Global | Add folder to library |
| `Return` | Library | Open selected book |
| `Ctrl+R` | Library | Open in built-in reader |
| `Ctrl+Shift+F` | Global | **Search inside books (Full-Text)** |
| `Ctrl+F` | Global | Focus library filter / search bar |
| `Ctrl+K` | Global | **Command Palette** |
| `Ctrl+/` | Global | Keyboard Shortcuts settings |
| `Ctrl+B` | Global | Toggle sidebar |
| `F4` | Global | Toggle details pane |
| `F5` | Global | Rescan folders |
| `F6` | Global | Reading Statistics & Heatmap |
| `Ctrl+1` / `2` / `3` | Library | Mark as Want / Reading / Read |
| `Alt+1` – `Alt+5` | Library | Rate 1 to 5 stars |
| `Ctrl+Alt+R` | Global | Surprise Me (Random book) |
| `Escape` | Global | Clear search / close modal |

---

## Running the Test Suite

The test suite contains **270 automated tests** covering migrations, parsing, reader engine, annotations, full-text search, recommendations, web security, cloud providers, and storage managers.

Run all tests:

```bash
pytest -v
```

Run specific test modules:

```bash
# Reader & Annotation tests
pytest tests/test_v6_reader.py tests/test_v6_annotations.py -v

# Full-text search engine tests
pytest tests/test_v6_fulltext.py -v

# Web server & OPDS security tests
pytest tests/test_v6_web.py -v

# Cloud provider tests
pytest tests/test_v6_cloud.py -v
```

---

## Security & Privacy Guarantees

1. **Local-First**: All metadata, full-text indexes, annotations, and reading logs reside exclusively on your machine in SQLite databases. No telemetry is sent to any remote server.
2. **Non-Destructive**: The app treats your book files as read-only. Annotations and bookmarks are saved in the database; files on disk are never altered.
3. **Protected Web Access**:
   - The web server defaults to loopback only (`127.0.0.1`).
   - Pairing with mobile devices uses single-use 5-minute QR codes.
   - Remote mutations (status, ratings, notes) require explicit activation of "Allow changes" and are CSRF protected.
   - Downloads enforce a configurable daily bandwidth budget (default 2 GB) and check available disk space.

---

## Developer & Maintainer

- **Developer**: Mritunjay Pandey
- **GitHub**: [@mritunjaylive](https://github.com/mritunjaylive)
- **Website**: [mritunjaylive.in](https://mritunjaylive.in)
- **Email**: [mritunjay@mritunjaylive.in](mailto:mritunjay@mritunjaylive.in)

---

## License

This software is released under the **MIT License**. Third-party libraries (such as PyMuPDF, PySide6, and Flask) are subject to their respective open-source licenses.

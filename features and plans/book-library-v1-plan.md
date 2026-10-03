# Book Library App: Version 1 Plan (Core Local Library)

**Goal of v1:** Point the app at one or more folders, scan them for books, and browse them in a grid with cover thumbnails, a details pane and sorting. Books open in the system default app.

**Out of scope for v1** (planned for later versions): reading status, "open with" other readers, search and filters, online metadata lookup, Google Drive, tags and collections.

---

## 1. Feature List

### 1.1 Library folders
- Add a folder through a folder-picker dialog; subfolders are scanned recursively.
- Support multiple library folders. Show them in a simple "Manage folders" dialog with add and remove.
- Removing a folder removes its books from the library database only, never from disk.

### 1.2 Scanning
- Recognize these formats by extension: `pdf`, `epub`, `mobi`, `azw3`, `djvu`, `cbz`, `txt`.
- Scan in a background thread with a progress bar and a Cancel button; the UI must never freeze.
- **Incremental rescan:** skip files whose size and modified time have not changed; add new files; update changed files; mark files that no longer exist as missing.
- **Rescan** button re-runs the scan on all folders.
- **Remove missing** button deletes database entries for files that are gone.

### 1.3 Metadata (per book)
| Field | EPUB | PDF | Other formats |
|---|---|---|---|
| Title | OPF `dc:title` | PDF info `title` | Parsed from filename |
| Author | OPF `dc:creator` | PDF info `author` | Parsed from filename |
| Publisher | OPF `dc:publisher` | Usually empty | Empty |
| Year | OPF `dc:date` (first 4 digits) | PDF creation date (fallback only) | Empty |
| ISBN | OPF `dc:identifier` if it looks like an ISBN | Empty | Empty |
| Genre | OPF `dc:subject` | Empty | Empty |
| Language | OPF `dc:language` | Empty | Empty |
| Pages | Empty in v1 | Page count | Empty |
| Edition | Empty in v1 (edited manually in v2, lookup in v3) | Empty | Empty |
| Size, format, path | From the file system | From the file system | From the file system |

Rules:
- Blank or junk values are stored as `NULL`, not as empty strings.
- If the title is missing or looks useless (for example `Microsoft Word - doc1`, `untitled`), fall back to the filename without extension, with underscores turned into spaces.
- Filename parsing: if the name matches `Author - Title`, split it; otherwise use the whole name as the title.

### 1.4 Cover thumbnails
- **EPUB:** extract the declared cover image from the archive.
- **PDF:** render page 1 to an image.
- **CBZ:** use the first image file in the archive (sorted by name).
- **Others (MOBI, AZW3, DJVU, TXT):** generate a placeholder cover showing the format label on a colored background. Real covers for these formats can come later.
- Thumbnails are resized to 300 px wide (keep aspect ratio), saved as JPEG in a cache folder, and generated once. If the cover file is missing, regenerate it lazily.

### 1.5 Library view
- Grid of cover thumbnails with the title (and author in smaller text) under each cover.
- Smooth scrolling with thousands of books (see the model/view design in section 5).
- Selecting a book updates the details pane.
- Double-click opens the book in the default app.

### 1.6 Details pane
Shows for the selected book: large cover, title, author, publisher, year, edition, ISBN, number of pages, genre, language, file size (human readable, for example `4.2 MB`), format, full file path, and date added. Empty fields show a dash. Include a **Show in folder** button and an **Open** button.

### 1.7 Sorting
- Sort by: title, author, year, size, format, pages, date added.
- Ascending/descending toggle.
- Case-insensitive; numbers sort naturally (`Book 2` before `Book 10`); books with empty values always go last regardless of direction.
- The chosen sort is remembered between launches.

### 1.8 Open book
- Double-click, an Open button, or the right-click menu opens the file with the system default app.
- If the file no longer exists, show a friendly message and offer to remove it from the library.

### 1.9 Other basics
- Window size, splitter position and sort order are remembered between launches.
- Status bar showing the total book count and scan progress.
- Errors on individual files are logged and skipped; one bad file must never stop a scan.

---

## 2. Tech Stack and Dependencies

| Purpose | Choice |
|---|---|
| Language | Python 3.11+ |
| GUI | PySide6 (Qt 6) |
| Database | SQLite (standard `sqlite3` module) |
| PDF metadata and covers | PyMuPDF (`pymupdf`) |
| EPUB | Standard `zipfile` + `xml.etree.ElementTree` (no extra dependency, and full control) |
| Images | Pillow |
| App data folders | `platformdirs` |
| Testing | `pytest` |

```
pip install PySide6 pymupdf Pillow platformdirs pytest
```

---

## 3. Project Structure

```
booklib/
├── main.py                  # entry point
├── booklib/
│   ├── __init__.py
│   ├── app.py               # QApplication setup, settings
│   ├── config.py            # paths, constants, supported extensions
│   ├── db/
│   │   ├── database.py      # connection, migrations
│   │   ├── schema.sql
│   │   └── repository.py    # all SQL lives here (books, folders)
│   ├── scanner/
│   │   ├── walker.py        # find candidate files, compare with DB
│   │   ├── worker.py        # QRunnable / QThread scan job
│   │   └── pipeline.py      # per-file: metadata -> cover -> DB
│   ├── metadata/
│   │   ├── base.py          # BookMeta dataclass
│   │   ├── epub.py
│   │   ├── pdf.py
│   │   ├── filename.py      # filename parsing + junk-title detection
│   │   └── extract.py       # picks the right extractor by format
│   ├── covers/
│   │   ├── cache.py         # cache paths, resize, save
│   │   └── placeholder.py   # generated placeholder covers
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── library_model.py # QAbstractListModel
│   │   ├── library_view.py  # QListView (icon mode) + delegate
│   │   ├── details_pane.py
│   │   ├── folders_dialog.py
│   │   └── sort_bar.py
│   └── utils/
│       ├── fileops.py       # open file, show in folder
│       └── format.py        # human-readable size, etc.
└── tests/
    ├── fixtures/            # small sample epub, pdf, cbz
    └── test_*.py
```

**Design rule:** the `db`, `scanner`, `metadata` and `covers` packages must not import anything from `ui`. This keeps the data layer reusable for a future web view (v6).

---

## 4. Database Design

The schema includes columns for later versions so you will not need painful migrations. v1 simply leaves them `NULL` or at their defaults.

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE folders (
    id              INTEGER PRIMARY KEY,
    path            TEXT NOT NULL UNIQUE,
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),
    last_scanned_at TEXT
);

CREATE TABLE books (
    id            INTEGER PRIMARY KEY,
    folder_id     INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    path          TEXT NOT NULL UNIQUE,      -- absolute path
    filename      TEXT NOT NULL,
    format        TEXT NOT NULL,             -- 'pdf', 'epub', ...
    size_bytes    INTEGER NOT NULL,
    file_mtime    REAL NOT NULL,             -- for change detection

    title         TEXT,
    author        TEXT,
    publisher     TEXT,
    year          INTEGER,
    edition       TEXT,
    isbn          TEXT,
    pages         INTEGER,
    genre         TEXT,
    language      TEXT,

    cover_path    TEXT,                      -- relative to cache dir
    is_missing    INTEGER NOT NULL DEFAULT 0,
    date_added    TEXT NOT NULL DEFAULT (datetime('now')),

    -- reserved for later versions (unused in v1)
    status        TEXT,                      -- v2: want / reading / read
    rating        INTEGER,                   -- v2
    notes         TEXT,                      -- v2
    metadata_src  TEXT DEFAULT 'file',       -- v3: file / online / manual
    file_hash     TEXT,                      -- v3: duplicate detection
    source        TEXT NOT NULL DEFAULT 'local',  -- v4: local / drive
    drive_file_id TEXT                       -- v4
);

CREATE INDEX idx_books_title   ON books(title COLLATE NOCASE);
CREATE INDEX idx_books_author  ON books(author COLLATE NOCASE);
CREATE INDEX idx_books_folder  ON books(folder_id);
CREATE INDEX idx_books_missing ON books(is_missing);
```

**Notes**
- Use `PRAGMA user_version` to store the schema version. `database.py` applies numbered migrations on startup so v2 and later can change the schema safely.
- Store the database in the OS app-data folder (`platformdirs.user_data_dir("BookLib")`), together with `covers/` and `app.log`.
- All SQL lives in `repository.py`. The rest of the code calls methods like `upsert_book()`, `list_books()`, `mark_missing()`.
- Use **upsert** (`INSERT ... ON CONFLICT(path) DO UPDATE`) so rescans update rows instead of duplicating them.

---

## 5. Implementation Details

### 5.1 Metadata dataclass
```python
@dataclass
class BookMeta:
    title: str | None = None
    author: str | None = None
    publisher: str | None = None
    year: int | None = None
    isbn: str | None = None
    pages: int | None = None
    genre: str | None = None
    language: str | None = None
    cover_bytes: bytes | None = None   # raw image data if found
```
Each extractor takes a file path and returns a `BookMeta`. `extract.py` dispatches by extension, wraps the call in `try/except`, and fills gaps using `filename.py`.

### 5.2 EPUB extraction (`metadata/epub.py`)
1. Open the file with `zipfile.ZipFile`.
2. Read `META-INF/container.xml` and get the `full-path` of the OPF file.
3. Parse the OPF with `ElementTree`, using the Dublin Core namespace (`http://purl.org/dc/elements/1.1/`) for `title`, `creator`, `publisher`, `date`, `identifier`, `language` and `subject`.
4. **Cover lookup, in this order:**
   1. EPUB 3: manifest `item` with `properties="cover-image"`.
   2. EPUB 2: `<meta name="cover" content="ID">`, then the manifest item with that `id`.
   3. Fallback: a manifest image whose id or href contains `cover`.
5. Resolve the cover `href` relative to the OPF's folder, read the bytes from the zip.
6. ISBN: scan `dc:identifier` values, strip hyphens and the `urn:isbn:` prefix, and accept only 10 or 13 digit strings that pass the checksum.
7. Year: take the first four digits of `dc:date`; ignore values outside 1000 to the current year.

### 5.3 PDF extraction (`metadata/pdf.py`)
1. `doc = pymupdf.open(path)`; if it is encrypted and cannot be opened without a password, skip the metadata and use a placeholder cover.
2. `pages = doc.page_count`; `info = doc.metadata` (keys `title`, `author`, `creationDate`, ...).
3. Cover: render page 0 with a scale matrix so the width is about 300 px, then `pix.tobytes("jpeg")`.
4. Clean the title with `is_junk_title()` (empty, `untitled`, starts with `Microsoft Word`, ends in `.doc/.docx/.indd`, etc.).
5. Use the PDF creation year only as a weak fallback for `year`, and only if nothing else provides one.
6. Always close the document (`with` block) to avoid file handle leaks.

### 5.4 CBZ and other formats
- **CBZ:** open as zip, take the alphabetically first image file, use it as the cover.
- **MOBI / AZW3 / DJVU / TXT:** no embedded parsing in v1. Use filename parsing plus a placeholder cover.

### 5.5 Filename parsing (`metadata/filename.py`)
- Strip the extension, replace `_` with spaces, collapse repeated spaces.
- If the name matches `^(.+?)\s+-\s+(.+)$`, treat the left part as author and the right part as title, but only if the left part is short (under about 60 characters) and does not look like a number.
- Otherwise the whole cleaned name is the title.
- Strip common junk like `(z-lib.org)`, `[PDFDrive]`, `libgen`.

### 5.6 Cover cache (`covers/cache.py`)
- Cache folder: `<app data>/covers/`.
- File name: `<book_id>_<mtime_int>.jpg`, so a changed file gets a new cover automatically.
- Steps: load `cover_bytes` with Pillow, convert to RGB, resize to 300 px wide keeping the ratio, save as JPEG quality 85.
- Placeholder cover (`placeholder.py`): a 300×450 image with a color chosen by hashing the format name, and the format text (`PDF`, `MOBI`) drawn in the center. Use Pillow's `ImageDraw`.
- Store only the relative file name in `books.cover_path`.

### 5.7 Scanner (`scanner/`)
**walker.py**
- `os.walk` each folder; ignore hidden folders and files (names starting with `.`), plus anything not in the supported extension list.
- For each file get `size` and `mtime` from `os.stat`.
- Load existing rows for the folder into a dict keyed by path.
- Classify each file as **new**, **changed** (size or mtime differs), or **unchanged**. Paths in the database but not on disk are **missing**.

**pipeline.py** (per file)
```
meta  = extract_metadata(path, format)      # never raises
cover = save_cover(meta.cover_bytes or placeholder(format), book_id/mtime)
repo.upsert_book(...)
```

**worker.py**
- Run the scan in a `QThread` (or `QRunnable` on `QThreadPool`) so the UI stays responsive.
- Emit signals: `progress(done, total, current_file)`, `book_added(book_id)`, `finished(summary)`, `error(path, message)`.
- Check a `cancel_requested` flag between files.
- **Important:** SQLite connections must not be shared across threads. Give the worker its own connection, and use WAL mode (`PRAGMA journal_mode=WAL`) so the UI can read while the scan writes.
- Commit in batches (for example every 25 books) so the UI can show books as they appear and a cancel does not lose everything.
- Optional speed-up: extract metadata for several files in parallel with a small thread pool, but write to the database from one thread only. Do this only if scanning proves slow.

**Missing files:** after the walk, set `is_missing = 1` for database rows whose files were not found, and back to `0` if the file returns. The library view hides missing books by default; **Remove missing** deletes them.

### 5.8 Library model and view (`ui/`)
- `LibraryModel(QAbstractListModel)` holds a list of lightweight book records (id, title, author, cover path, and the sortable fields). It does **not** load full-size images itself.
- Roles: `DisplayRole` (title), `DecorationRole` (thumbnail), plus custom roles for author, year, size and so on.
- **Thumbnail loading:** keep an in-memory `QPixmapCache` keyed by cover path. Load pixmaps lazily when the delegate paints, so only visible items cost memory.
- `QListView` in `IconMode`, `setResizeMode(Adjust)`, `setUniformItemSizes(True)`, `setViewMode(IconMode)`, and a custom `QStyledItemDelegate` that paints the cover, then the title (elided to two lines), then the author.
- Sorting: do it in SQL (`ORDER BY` with `COLLATE NOCASE` and `NULLS LAST` handling via `col IS NULL, col`) and reload the model, or use a `QSortFilterProxyModel` with a custom `lessThan`. For v1, a proxy model is simpler and also makes v2 filtering easy. Implement `lessThan` so empty values sort last in both directions and text uses a natural-sort key.
- `dataChanged` / `beginInsertRows` are used when the scanner adds books, so the grid fills in live.

### 5.9 Details pane (`ui/details_pane.py`)
- Connected to the view's `selectionChanged` signal.
- Fetches the full record by id from the repository (so the model can stay small).
- Layout: cover on top (scaled to fit), then a `QFormLayout` of labeled fields; long paths and titles wrap; text is selectable for copying.
- Buttons: **Open** and **Show in folder**.
- When nothing is selected, show a friendly hint ("Select a book to see details").

### 5.10 Opening files and folders (`utils/fileops.py`)
```python
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

def open_file(path):                       # default app
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path))

def show_in_folder(path):
    # Windows: subprocess.run(["explorer", "/select,", path])
    # macOS:   subprocess.run(["open", "-R", path])
    # Linux:   open the parent directory with QDesktopServices
    ...
```
Check `os.path.exists` first; if the file is gone, show a message box and offer **Remove from library**.

### 5.11 Settings
Use `QSettings` to persist window geometry, splitter sizes, sort field and direction, and last-used folder for the picker.

### 5.12 Logging and errors
- Python `logging` to `app.log` in the app-data folder (rotating file handler).
- Per-file failures are logged with the path and traceback, and counted; the scan summary shows "Added 120, updated 3, skipped 2 with errors".
- No `except: pass`. Always log.

---

## 6. UI Layout

```
┌──────────────────────────────────────────────────────────────┐
│ [Add Folder] [Rescan] [Remove Missing] [Folders...]          │
│ Sort by: [Title ▼]  [↑/↓]                                    │
├───────────────────────────────────────┬──────────────────────┤
│                                       │   ┌──────────────┐   │
│  ┌────┐  ┌────┐  ┌────┐  ┌────┐       │   │    cover     │   │
│  │cvr │  │cvr │  │cvr │  │cvr │       │   └──────────────┘   │
│  └────┘  └────┘  └────┘  └────┘       │   Title              │
│  Title   Title   Title   Title        │   Author             │
│  Author  Author  Author  Author       │   Publisher          │
│                                       │   Year / Edition     │
│  ┌────┐  ┌────┐  ...                  │   ISBN / Pages       │
│                                       │   Genre / Language   │
│                                       │   Size / Format      │
│                                       │   Path               │
│                                       │   [Open] [Show]      │
├───────────────────────────────────────┴──────────────────────┤
│ 1,248 books        Scanning: 312 / 1,248  [██████░░░░] Cancel │
└──────────────────────────────────────────────────────────────┘
```
The grid and details pane sit in a `QSplitter` so the user can resize them.

---

## 7. Build Order (Milestones)

Complete and test each milestone before moving on.

| # | Milestone | What "done" looks like |
|---|---|---|
| 1 | **Project setup** | Repo, virtual environment, folder structure, a window that opens |
| 2 | **Database layer** | Schema created on first run; repository methods for folders and books; migration via `user_version` |
| 3 | **Walker** | Given a folder, returns new/changed/unchanged/missing lists (test with a temp folder) |
| 4 | **Filename parser** | Unit tests for junk-title detection and `Author - Title` splitting |
| 5 | **EPUB extractor** | Correct metadata and cover from several real EPUBs (EPUB 2 and 3) |
| 6 | **PDF extractor** | Page count, metadata and rendered cover from several PDFs, including a scanned one and a password-protected one |
| 7 | **Cover cache and placeholders** | Thumbnails saved and reused; placeholder for other formats |
| 8 | **Scan pipeline (no UI)** | A command-line script scans a folder and fills the database correctly; a second run does nothing (incremental) |
| 9 | **Basic UI: library grid** | Model, view and delegate showing books and covers from the database |
| 10 | **Background scanning in UI** | Add Folder runs the worker; progress bar and Cancel work; books appear live |
| 11 | **Details pane** | Selecting a book fills all fields; Open and Show in folder work |
| 12 | **Sorting** | All sort fields work in both directions; empty values last; sort remembered |
| 13 | **Rescan, missing files, folders dialog** | Removed files are marked missing; Remove Missing works; folders can be removed |
| 14 | **Polish and testing** | Settings persistence, error messages, logging, performance test with 5,000+ files, packaging notes |

---

## 8. Testing Plan

**Unit tests (`pytest`)**
- Filename parser: a table of names and expected `(author, title)`.
- Junk-title detector.
- ISBN validation (valid ISBN-10, valid ISBN-13, invalid checksum, with hyphens).
- Size formatter (`0 B`, `1.0 KB`, `4.2 MB`).
- Walker classification (new, changed, unchanged, missing) using a temporary directory.
- Repository upsert (running twice does not duplicate rows).

**Fixture-based tests**
- Keep a few tiny sample files in `tests/fixtures/`: an EPUB 2, an EPUB 3, a PDF with metadata, a PDF without metadata, a CBZ, and a corrupt file. Verify metadata and that the corrupt file is skipped without a crash.

**Manual test checklist**
- Scan a folder with mixed formats, nested subfolders and special characters or non-English names in file names.
- Rescan with no changes (should be fast, no new rows).
- Delete a file, rescan, confirm it is marked missing, then Remove Missing.
- Rename or replace a file, rescan, confirm the entry updates.
- Cancel a scan halfway; the app stays usable and the next scan continues correctly.
- Sort by every field in both directions.
- Restart the app; window layout and sort order are restored.
- Try a folder with 5,000+ files to check scan time and scrolling smoothness.

---

## 9. Known Pitfalls and How to Handle Them

| Problem | Handling |
|---|---|
| Wrong or junk PDF metadata | Junk-title detector and filename fallback; manual editing arrives in v2 |
| Very large PDFs slow down cover rendering | Render only page 1 at low scale; avoid loading the whole document into memory |
| Scanned or password-protected PDFs | Catch the error, use a placeholder cover, keep filename metadata |
| Corrupt or zero-byte files | Try/except per file, log, and continue |
| UI freezing during scan | Scan in a worker thread; batch commits; separate DB connection per thread |
| "Database is locked" errors | WAL mode, short transactions, one writer thread |
| Memory growth with thousands of covers | Lazy loading with `QPixmapCache`, fixed thumbnail size |
| Files on slow or disconnected drives | Treat unreadable paths as errors, not as deleted; only mark missing if the parent folder is reachable |
| Windows long paths and non-ASCII names | Use `pathlib`, always open files with full paths, test with Hindi/Unicode names |
| Same book in two folders | Stored as two rows in v1; duplicate detection arrives in v3 (`file_hash` column already exists) |

---

## 10. Definition of Done for v1

- [ ] Add one or more folders and scan them recursively without freezing the UI
- [ ] PDF, EPUB and CBZ files show real covers; other formats show a placeholder
- [ ] Details pane shows title, author, publisher, year, edition, ISBN, pages, genre, language, size, format, path and date added (empty values shown as a dash)
- [ ] Sorting works on all listed fields, ascending and descending
- [ ] Rescan is incremental; missing files are detected and can be removed
- [ ] Books open in the default app; Show in folder works
- [ ] One bad file never crashes a scan; errors are logged
- [ ] Settings persist between launches
- [ ] Handles at least 5,000 books with smooth scrolling
- [ ] Unit tests pass for parsing, ISBN validation, walker and repository

---

## 11. What Comes Next (Preview of v2)

The v1 design already prepares for v2: the `status`, `rating` and `notes` columns exist, the proxy model is ready for filters, and the details pane can host editable fields. Version 2 adds reading status, "open with" other readers, search and filters, list view, manual metadata editing, ratings, and dark mode.

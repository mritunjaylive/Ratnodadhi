# Book Library App: Version 6 Plan (Advanced Features)

**Goal of v6:** Turn the library into a place where you also *read*. Add a built-in reader with remembered positions, bookmarks, highlights and notes; search inside the text of your books; get suggestions for what to read next; browse and download your library from your phone over your home network; and, optionally, index books from OneDrive and Dropbox.

**Prerequisite:** v5 is complete and its definition of done is met (especially the action registry, `ensure_local`, the job manager lanes, backups, `reading_log`, statistics and `LibraryQuery`).

**Out of scope for v6:** DRM removal, OCR of scanned books (listed as a stretch idea), editing book files, internet-facing hosting of your library, cross-device sync of reading positions beyond what the web interface offers.

> **Facts checked while writing this plan (re-check when you build):**
> - **PyMuPDF/MuPDF** opens PDF, EPUB, MOBI, FB2, CBZ, XPS, SVG, TXT and image files, renders their pages, searches and extracts text. It is offered under the **AGPL** or a commercial licence from Artifex. That is fine for personal use, but if you ever distribute the app you must comply with the AGPL or buy a commercial licence (see section 5.1 and the last section).
> - **SQLite FTS5 contentless tables** are smaller but cannot return the original text, only the row id. So search snippets must be built from the source file on demand (section 5.10).
> - **FTS5's default `unicode61` tokenizer** does not split runs of CJK characters into words, so language coverage must be tested; I could not confirm how it treats Devanagari (Hindi), so section 5.10 includes a test and a fallback.
> - **OneDrive (Microsoft Graph):** `GET /me/drive/root/delta` gives incremental changes; the `Files.Read` delegated permission is available for personal Microsoft accounts; `quickXorHash` is the only file hash guaranteed for both personal and work accounts.
> - **Dropbox API v2:** access tokens are short-lived; apps that need long-lived access use refresh tokens (offline access); folders are listed with `list_folder` and continued with a cursor.

---

## 1. Feature List

### 1.1 Built-in reader
- **BookLib Reader** appears in the "Open with" menu (v2) and can be set as the default reader for a format.
- Formats: PDF, EPUB, MOBI, FB2, CBZ (comics), TXT. Anything the reader cannot open falls back to your external readers with a clear message.
- **PDF:** single page, continuous scroll and facing pages; zoom (fit width, fit page, custom), rotation, thumbnails panel, table of contents, clickable links, password prompt for encrypted files.
- **Reflowable books (EPUB, MOBI, FB2, TXT):** paginated or scrolled, adjustable font size, margins, line width and theme (light, sepia, dark, black).
- Night mode for PDFs, fullscreen, keyboard and mouse navigation, page slider, "time left in book" estimate.
- **Search in book** with next/previous and highlighted hits.
- Text selection and copy for books that have a text layer.
- Several books can be open at once in tabs.

### 1.2 Reading position, bookmarks and reading time
- The reader remembers where you stopped, per book, and resumes there (also from the Continue Reading shelf).
- Position survives font-size and layout changes (it is stored as a layout-independent locator, not a page number).
- Reader progress updates the library's progress bar, status (Want to Read to Reading) and the "Mark as Read?" prompt (v3 rules).
- **Bookmarks:** toggle on the current page, name them, list and jump.
- **Reading sessions:** active reading time is recorded (idle time is not counted). New statistics: time today, this week and year, average per day, **streaks**, a 12-month **heatmap**, and an estimated time left per book. Can be switched off.

### 1.3 Highlights and notes
- Select text, then highlight in one of several colors, add a note, or copy.
- Panel listing all highlights and notes of the book, filterable by color and searchable; click to jump.
- **Highlights & Notes view** in the library: all annotations across all books, with search and filters.
- **Non-destructive:** annotations live in the database; your PDF and EPUB files are never modified.
- Annotations follow the text when you change font size or layout; if they cannot be re-attached they are marked "orphaned" and kept.
- **Export** annotations per book or for the whole library as Markdown, HTML, CSV or JSON. For PDFs, **Export annotated copy** writes a copy of the PDF with real highlight annotations. Existing highlights already stored inside a PDF can be **imported**.

### 1.4 Full-text search inside books
- **Search inside books** mode (`Ctrl+Shift+F`): find words, phrases (`"exact phrase"`), exclusions (`-word`) and prefixes (`net*`) across the text of your books.
- Results grouped by book with the number of matches, page or chapter, and a highlighted snippet; click to open the reader at that spot with the search terms highlighted.
- Scope: whole library, current view or selection.
- Indexing is **opt-in per folder or collection**, runs quietly in the background at low priority, pauses on battery power, and can be paused or rebuilt at any time.
- Books without text (scanned PDFs) are detected and reported; OCR is not included.
- Progress and size of the index are visible in Settings.

### 1.5 Recommendations
- **What to read next:** a ranked shelf of books *you own but have not read*, based on the ratings, genres, authors, tags and series of books you have read, each with a plain-language reason ("Because you rated *Clean Code* 5 stars and read other Programming books").
- **Similar books** section in the details pane.
- **Not interested** and **Hide** feedback, which improves later results.
- **Surprise me** picks a random book from Want to Read (or from a genre you like).
- Everything is computed locally; nothing about your reading is sent anywhere.

### 1.6 Local web access and OPDS
- Optional small web server: browse, search, filter and sort the library from a phone or tablet on your home Wi-Fi, see covers and details, and **download books**.
- **OPDS catalog:** reading apps on the phone (any app that supports OPDS) can browse and download from your library directly.
- **Off by default.** Turning it on for other devices requires a password, shows a warning, can switch itself off after a set time, and lists paired devices you can revoke.
- Read-only by default; an extra switch allows changing status, rating and notes from the phone.
- Pair a phone by scanning a QR code shown in the app.
- Can also run **without the desktop window** (headless) on a home PC or Raspberry Pi.

### 1.7 Other cloud sources (optional)
- Index book folders from **OneDrive** and **Dropbox**, the same way as Google Drive in v4: browse, index, sync changes, download on demand, cache, badges.
- Built on a **provider abstraction** extracted from the v4 Drive code, so another provider needs only one new module.

### 1.8 Storage limits for the new data
- **Full-text index size limit** (default 2 GB): when it is reached, indexing pauses and the app tells you; nothing is deleted automatically. You can raise the limit, remove the index of books you have not opened for a chosen time, remove the index of selected folders, or **Compact** the index to give the space back to the disk.
- **Books you are reading stay available:** a cloud book open in the reader is protected from cleanup while its tab is open, and the keep-recent and Reading rules from v4 apply to books opened in the built-in reader.
- **Worker temp folders** used by background extraction are removed when a worker ends and swept at startup, even after a crash.
- **Daily budget for web downloads:** cloud books requested from a phone through the web interface count against a daily limit (default 2 GB) and pass the disk-space guard, so a phone cannot fill the drive.
- **Log rotation** for the web access log.
- The Storage page (v5) shows the new areas and the reader's memory cache.

---

## 2. Key Design Decisions

| Decision | Choice | Why |
|---|---|---|
| Reader engine | **PyMuPDF for every format**, behind a `DocumentBackend` interface | One engine gives rendering, text layer, search, links, contents and reflow for PDF, EPUB, MOBI, FB2, CBZ and TXT, with no browser engine to ship. Its EPUB styling support is simpler than a web browser's; a WebEngine-based EPUB mode can be added later behind the same interface |
| Licence risk | Keep PyMuPDF behind the interface and note the AGPL | Fine for personal use. To distribute later, comply with the AGPL, buy a commercial licence, or swap the backend (for example Qt's PDF module for PDFs) |
| Thread safety and crashes | Background extraction (metadata, covers, text for the index, deep index) runs in **worker processes**; the reader uses its own dedicated render thread | PyMuPDF's documentation says it does not support multi-threaded use, and a corrupt file can crash the native library. Worker processes keep the app alive when a bad file appears |
| Positions | Layout-independent **locator** (chapter, fraction, text quote) | Page numbers change with font size; a locator survives it |
| Annotations | Stored in the database, anchored by text quote and word sequence | Files stay untouched; anchors survive re-layout and can be re-attached |
| Full-text index | Separate `fulltext.db`, FTS5 **contentless** index, snippets built on demand | Keeps the main database small and fast to back up; the index can always be rebuilt; contentless saves a lot of space |
| Recommendations | Local content-based scoring with explanations | Works offline, private, easy to test and to explain |
| Web server | Qt-free package (`booklib_web`), Flask served by `waitress`, in-app thread or headless | Reuses the v1 rule that the data layer never imports the UI; easy to test; runs without the desktop window |
| Web security posture | Loopback only by default; LAN opt-in; password plus paired devices; read-only default; **never** meant for the open internet | A library server on a home network is fine; exposing it to the internet is a different risk level |
| Cloud providers | `CloudProvider` interface; Drive becomes provider number one | Avoids copy-pasting the v4 Drive code twice |

---

## 3. What Changes in the v1 to v5 Code

| Area | Change |
|---|---|
| Extractors, covers, deep index, ISBN scan | Move behind an **extractor process pool** (`extract_pool`, 2 worker processes, spawn start method on Windows, top-level functions returning plain data). The scanner, deep index and lookup jobs call `run_in_extractor(fn, path)` |
| Open flow (v2) | New reader entry `builtin` in the Open with list and in `format_defaults`; double-click uses it when it is the default; unsupported formats fall back automatically |
| Progress (v3) | The reader writes `progress_page` (PDF) or `progress_percent` (reflowable) and follows the v3 status rules; a manual edit in the details pane is respected until the next reading session |
| Job manager | New **index lane** (1 low-priority job) and a `ServiceManager` that starts and stops the web server and the index scheduler |
| Backup package (v5) | The snapshot excludes `fulltext.db` (rebuildable) and strips machine-specific web tables (`web_devices`); annotations, bookmarks, positions and sessions are included |
| Export/import (v5) | JSON export also carries annotations, bookmarks and positions; new "Export highlights" commands |
| Statistics (v5) | Reading-time cards, streaks, heatmap |
| `LibraryQuery` | New filters: `book_ids` (for "show these books" from search results), `has_annotations`, `fts_state`; a recommendation shelf is computed, not a saved query |
| Scanner and watchers | A changed file marks its index state `stale` and clears cached reader layouts |
| Action registry (v5) | New `reader` shortcut context; new actions for the reader, search inside books and web access |
| Sidebar | New entries: Highlights & Notes, Recommended; Sources gains OneDrive and Dropbox if built |
| Settings | New pages: Reader, Full-text index, Recommendations, Web access, Cloud accounts |
| Storage manager (v4, v5) | New areas: full-text index, extractor temp folders, web-triggered downloads, web log; the reader and web server renew leases on cached books |
| `fulltext.db` creation | Creates the file with incremental auto-vacuum so space can be reclaimed after deletions |
| Extractor process pool | Each worker gets its own temp folder and a per-file temp-space limit |
| Web server | Downloads of cloud books use the disk-space guard and a daily budget |

---

## 4. Database Changes (Migration 6)

Migration 6 is the core. **Migration 6b** (cloud providers) is separate and only applied when you start the optional cloud milestones. Take an automatic safety snapshot first (v5), and run each migration in one transaction.

```sql
-- migration 6 (core)

-- reading position (one per book)
CREATE TABLE reading_positions (
    book_id    INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    locator    TEXT NOT NULL,          -- JSON, see 5.5
    progress   REAL,                   -- 0..1 under the layout used when saved
    layout_key TEXT,                   -- font size, margins, page size the progress refers to
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE bookmarks (
    id         INTEGER PRIMARY KEY,
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    locator    TEXT NOT NULL,
    label      TEXT,
    snippet    TEXT,                   -- first words on the page, for the list
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_bookmarks_book ON bookmarks(book_id);

CREATE TABLE annotations (
    id         INTEGER PRIMARY KEY,
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL DEFAULT 'highlight',   -- 'highlight' | 'underline' | 'note'
    color      TEXT NOT NULL DEFAULT 'yellow',
    quote      TEXT NOT NULL,          -- the selected text
    prefix     TEXT,                   -- about 30 characters before
    suffix     TEXT,                   -- about 30 characters after
    locator    TEXT NOT NULL,          -- JSON, see 5.7
    note       TEXT,
    state      TEXT NOT NULL DEFAULT 'ok',          -- 'ok' | 'orphaned'
    origin     TEXT NOT NULL DEFAULT 'app',         -- 'app' | 'file' (imported from a PDF)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_annotations_book ON annotations(book_id);

CREATE VIRTUAL TABLE annotations_fts USING fts5(
    quote, note, content='annotations', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
-- three triggers (insert, delete, update of quote/note) as in migrations 2 and 3
-- then: INSERT INTO annotations_fts(annotations_fts) VALUES ('rebuild');

-- reading time
CREATE TABLE reading_sessions (
    id             INTEGER PRIMARY KEY,
    book_id        INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    started_at     TEXT NOT NULL,      -- local ISO datetime written from Python
    ended_at       TEXT,
    active_seconds INTEGER NOT NULL DEFAULT 0,
    start_progress REAL,
    end_progress   REAL
);
CREATE INDEX idx_sessions_started ON reading_sessions(started_at);
CREATE INDEX idx_sessions_book    ON reading_sessions(book_id);

-- recommendations
CREATE TABLE recommendation_feedback (
    book_id    INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    verdict    TEXT NOT NULL CHECK (verdict IN ('hide','not_interested')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- web access: paired devices (never restored from backups)
CREATE TABLE web_devices (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,  -- SHA-256 of the random device token; the token itself is never stored
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT,
    last_ip      TEXT,
    revoked_at   TEXT
);

-- full-text index bookkeeping (the index itself lives in fulltext.db)
ALTER TABLE books ADD COLUMN fts_state      TEXT;     -- NULL | 'queued' | 'indexing' | 'done' | 'no_text' | 'failed' | 'stale'
ALTER TABLE books ADD COLUMN fts_version    INTEGER;  -- extractor version used
ALTER TABLE books ADD COLUMN fts_indexed_at TEXT;
ALTER TABLE books ADD COLUMN text_chars     INTEGER;  -- total characters indexed

ALTER TABLE folders ADD COLUMN index_contents INTEGER NOT NULL DEFAULT 0;   -- opt-in per folder

PRAGMA user_version = 6;
```

**`fulltext.db` (separate database file, created on first use)**
```sql
-- must be the very first statement on a new, empty database file
PRAGMA auto_vacuum = INCREMENTAL;

CREATE TABLE chunks (
    id      INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL,
    unit    INTEGER NOT NULL,          -- page number (PDF) or chapter number (reflowable)
    part    INTEGER NOT NULL DEFAULT 0,-- chunk number inside a long chapter
    locator TEXT NOT NULL,             -- same JSON format as reading positions
    chars   INTEGER NOT NULL
);
CREATE INDEX idx_chunks_book ON chunks(book_id);

CREATE VIRTUAL TABLE chunk_fts USING fts5(
    text, content='', contentless_delete=1,
    tokenize='unicode61 remove_diacritics 2'
);
-- rowid of chunk_fts = chunks.id
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);   -- db id, extractor version, tokenizer name
```

**Notes**
- `PRAGMA auto_vacuum = INCREMENTAL` only takes effect when set **before** the first table is created. It lets the app return free pages to the disk with `PRAGMA incremental_vacuum(N)` after deleting a book's chunks, so the file shrinks without a full `VACUUM`.
- The **Compact** action runs `PRAGMA incremental_vacuum` in steps; a full `VACUUM` (which needs free space about the size of the file) is a fallback run in the maintenance lane after the disk-space guard check.
- If an existing `fulltext.db` was created without incremental auto-vacuum, Compact offers a one-time `VACUUM` to convert it.
- `contentless_delete=1` needs a recent SQLite (added in 3.43). Check `sqlite3.sqlite_version_info` at startup. If it is older, either install a newer SQLite through a wheel such as `pysqlite3-binary`, or fall back to a normal (contentful) table and accept a larger index; show the size in Settings either way.
- The `meta` table stores a random `db_id`. The main database remembers it in `app_meta`. After a restore, if `fulltext.db` is missing or the ids differ, reset all `fts_state` values to `NULL` so books are re-queued.
- `web_devices` rows are removed from the backup snapshot (sessions of an old computer must not carry over), as is any stored web password hash if you prefer to set it again after restoring.
- Timestamps in `reading_sessions` are **local** ISO datetimes written from Python (same rule as `reading_log` in v5), because streaks and heatmaps group by local day.

---

## 5. Implementation Details

### 5.1 Reader architecture (`reader/`)

```
reader/
├── backend.py        # DocumentBackend interface, Locator, TextWord, Hit
├── mupdf_backend.py  # implementation with PyMuPDF
├── render.py         # render thread, cache, prefetch
├── textlayer.py      # words, selection, hit-testing
├── layout.py         # reflow settings, themes
├── position.py       # locator save/restore, progress sync
├── sessions.py       # reading time tracking
├── annotations.py    # anchoring, re-anchoring, export
├── search.py         # in-book search
└── ui/
    ├── reader_window.py     # tabs, toolbar, panels
    ├── page_view.py         # scrolling canvas that paints pages and overlays
    ├── toc_panel.py, thumbs_panel.py, bookmarks_panel.py, notes_panel.py
    └── settings_popover.py  # font size, margins, theme
```

**Backend interface (`backend.py`)**
```python
class DocumentBackend(Protocol):
    is_reflowable: bool
    def open(self, path: str, password: str | None = None) -> None: ...
    def layout(self, width: int, height: int, font_size: float) -> None: ...   # no-op for fixed layout
    page_count: int
    def toc(self) -> list[TocEntry]: ...                 # (level, title, locator)
    def render(self, page: int, zoom: float, dpr: float, invert: bool) -> QImage: ...
    def words(self, page: int) -> list[TextWord]: ...    # (rect, text, block, line, word)
    def links(self, page: int) -> list[Link]: ...
    def search(self, text: str) -> list[Hit]: ...        # hits with page and rectangles
    def locator_for(self, page: int, y: float) -> Locator: ...
    def page_for(self, locator: Locator) -> tuple[int, float]: ...   # after re-layout
    def close(self) -> None: ...
```
`mupdf_backend.py` implements it with PyMuPDF. The reader code never imports PyMuPDF directly, so the backend can be swapped (for example if you later need a different licence).

**Formats:** support is decided at runtime by trying to open the file; the supported list shown in the UI comes from what the backend reports. AZW3 and DJVU are treated as unsupported (external reader fallback) unless your PyMuPDF version opens them.

**Process and thread model**
- The reader's PyMuPDF work happens on **one dedicated render/worker thread** that owns the `Document`. The UI thread never calls PyMuPDF directly; it sends requests (render page N at zoom Z, get words for page N, search text) and receives results by signal.
- Because PyMuPDF is documented as not supporting multi-threaded use, **background jobs must not use PyMuPDF in the app process while a reader is open**. That is why all background extraction goes to the extractor process pool (section 3). A crash in an extractor process is caught, the book is marked `failed`, and the app continues.
- Optional hardening later: run the reader's backend in its own process as well, so even a crash while viewing a malformed PDF cannot close the whole app. Because positions are saved every couple of seconds (5.5), a crash costs little either way.
- Extractor worker processes use per-worker temp folders that are removed on exit and swept at startup (section 5.15).

### 5.2 Rendering pipeline (`render.py`, `ui/page_view.py`)
- **Page layout:** the page view computes page sizes from the backend (cached), lays pages out vertically (continuous), singly, or as facing pairs (with a "cover alone" toggle), and paints only the visible pages.
- **Rendering:** `page.get_pixmap(matrix=Matrix(zoom, zoom), alpha=False)` produces pixels; convert to `QImage` (copy the buffer, because the pixmap memory is freed). Multiply zoom by the screen's `devicePixelRatio` for sharp text on high-DPI screens.
- **Cache:** an LRU keyed by `(page, zoom_step, dpr, theme_invert, layout_key)`. Quantize zoom to steps (for example 5%) so smooth zooming does not create hundreds of variants. Memory cap (default 256 MB).
- **Progressive rendering:** paint a quick low-resolution render first, then replace it with the full-resolution image. **Cancel stale requests** with a generation counter when the user scrolls or zooms quickly.
- **Prefetch** the pages next to the current one (two ahead in the reading direction, one behind).
- **Themes:** night mode for fixed layouts inverts the rendered image (`QImage.invertPixels()`); sepia multiplies with a warm color (`CompositionMode_Multiply`). Images are inverted too; a per-image exception is not attempted.
- **Overlays** (search hits, selection, highlights, bookmark ribbon) are drawn by the widget on top of the page image from stored geometry, never baked into the cached pixmap.
- **Large documents:** never render all pages; thumbnails are generated lazily at low resolution in the same worker.
- **Errors:** an unreadable page shows a placeholder with the error and continues; an unreadable file shows a full-view message with **Open in external reader**.
- The page cache is memory only (no disk spill); its cap is a setting and it can be cleared from the Storage page.

### 5.3 Text layer, selection, links and contents
- **Words:** `page.get_text("words")` returns each word with its rectangle and block, line and word numbers, in reading order. Cache per page (and per layout for reflowable books).
- **Hit-testing and selection:** map the mouse position from widget to page coordinates; the press point and the release point each pick the nearest word; the selection is the range of words between them in reading order. Double-click selects a word, triple-click a line. Draw the selection as merged line rectangles. Copy joins words with spaces and lines with line breaks, rejoining words split by a hyphen at a line end.
- **No text layer** (scanned PDFs, image-only pages): selection and search are unavailable; show a subtle note on the page ("No text on this page"). OCR is a stretch idea.
- **Links:** `page.get_links()` returns clickable regions. Internal links jump; external links ask for confirmation before opening the system browser (never open automatically).
- **Contents panel:** `doc.get_toc()` gives entries with levels; highlight the entry for the current position. If a book has no contents, show a message and use page thumbnails (PDF) or a page list (reflowable).
- **Thumbnails panel** (fixed-layout books): lazy, low-resolution, click to jump.

### 5.4 Reflowable layout and themes (`layout.py`)
- Reflow with `doc.layout(width, height, fontsize)` (PyMuPDF's reflowable-document API; check the current signature in its documentation). Font size, page size and margins come from the **layout settings**: font size (8 to 40 pt), margins (narrow, medium, wide), maximum line width, and mode (paginated or scrolled).
- Themes: light, sepia, dark, black. Background and text colors are applied by tinting or inverting the rendered image; if your PyMuPDF version lets you inject a user style sheet, use it for real font and color control (verify in the documentation).
- Line spacing and font family are limited by what the engine supports; keep them out of the first version rather than promising them.
- A **layout key** (`fontsize|width|height|margins`) identifies a layout; positions and cached word lists record which layout they belong to.
- Settings are saved globally and can be overridden per book (remember font size for a specific book).
- **Indic and other scripts:** test a Hindi EPUB early. The engine shapes complex scripts, but glyphs can appear as empty boxes when no suitable font is available; if so, the message offers **Open in external reader**.
- **Limits to be honest about:** complex EPUB styling, embedded fonts, fixed-layout EPUBs and interactive content may look plain or wrong. Provide **Open in external reader** in the reader's toolbar at all times.

### 5.5 Position memory, progress and sessions (`position.py`, `sessions.py`)

**Locator (JSON)**
```json
{"t": "pdf",  "page": 41, "y": 0.32}
{"t": "flow", "chapter": 5, "frac": 0.42, "quote": "the first fifty characters visible", "tok": 1180}
```
- PDF: page number (0-based) and vertical fraction of the top of the viewport.
- Reflowable: chapter, fraction inside the chapter, a short text quote from the top of the viewport, and an approximate word index. To restore after a layout change or a new session: go to the chapter and fraction, then refine by searching for the quote on nearby pages.
- Do not rely on any opaque bookmark integers from the engine surviving between sessions; the locator is your own, portable format.

**Saving**
- Save the locator when the position is stable for 2 seconds, when a tab closes, and when the app quits. The write is a small upsert into `reading_positions`, never blocking the UI.
- **Progress:** PDF: `page / page_count`. Reflowable: fraction of pages under the current layout, recomputed from the locator after a layout change (so changing font size does not make progress jump). Write to `books.progress_page` or `books.progress_percent`, apply the v3 rules (status becomes Reading, "Mark as Read?" at the end), and update `last_opened_at`.
- **Resume:** opening a book (from anywhere) restores the saved locator; a **Start from beginning** item is in the tab's menu.
- A stale locator (file replaced, page count changed) falls back to the saved `progress` fraction, then to the beginning, with a small notice.

**Reading sessions (`sessions.py`)**
- A session starts when a tab becomes active and the window has focus, and pauses after 120 seconds without input (mouse, keyboard, scroll) or when the window loses focus for more than 5 minutes.
- Store `started_at`, `ended_at`, `active_seconds`, and start and end progress. Flush every minute so a crash loses little.
- Sessions shorter than 10 seconds are discarded.
- Setting **Track reading time** (on by default); turning it off stops recording; **Delete all reading-time data** clears the table.

**Statistics additions (extends v5 `stats/`)**
- Cards: time today, this week, this year, average minutes per day, current and longest **streak** (consecutive local days with at least N minutes, default 10).
- **Heatmap** of the last 12 months (custom `QPainter` widget: one cell per day, five intensity levels from the palette).
- Per book: total reading time and an **estimated time left** = remaining progress divided by that book's average speed (progress per active hour); shown only after enough data (about 30 minutes).
- Clicking a day or a book shows the matching books in the library.

### 5.6 Bookmarks
- Toggle with `Ctrl+D` on the current page or position; a ribbon appears on the page. The panel lists bookmarks with label, snippet, chapter and date; rename, delete and jump.
- A bookmark stores a locator (same format) and the first words on the page as a snippet.
- For reflowable books the ribbon is drawn when the bookmarked position is on the current page under the current layout.

### 5.7 Highlights and notes (`annotations.py`)

**Creating**
- Select text, then a small popup offers five colors, **Add note**, **Copy**, **Search for selection** and **Look up** (later). Keyboard: `H` highlights with the last color, `N` adds a note to the selection.
- Store: `quote` (selected text), `prefix` and `suffix` (about 30 characters of context on each side), color, optional note, and a **locator**:
  - PDF: `{"t":"pdf","page":41,"rects":[[x0,y0,x1,y1], ...]}` with rectangles as **fractions of the page size**, so they are independent of zoom.
  - Reflowable: `{"t":"flow","chapter":5,"tok_start":1180,"tok_end":1211}`, the word range inside the chapter (a hint, not the truth).

**Anchoring and re-anchoring (pure functions, easy to unit test)**
```python
def anchor(words: list[str], quote: str, prefix: str, suffix: str,
           hint: tuple[int, int] | None) -> tuple[int, int] | None: ...
```
1. Normalize the quote and the chapter's words (NFKC, lowercase, remove punctuation and hyphen breaks) into tokens.
2. Look for the exact token sequence near the hinted range first, then in the whole chapter; if several matches, choose the one whose surrounding tokens best match `prefix` and `suffix`.
3. If there is no exact match, accept a fuzzy match (token-sequence similarity above about 0.85, for example with `difflib.SequenceMatcher`).
4. No acceptable match: set `state = 'orphaned'`; the annotation stays in the list with its quote and note, and a **Find manually** button lets the user search for the quote or delete it.
5. On success, convert the word range to per-line rectangles with the word rectangles of the current layout, and cache them per layout key.
- **Fixed-layout PDFs:** use the stored rectangles directly. If the text at those rectangles no longer equals the quote (the PDF was replaced), try `anchor()` on that page and the neighbors.
- Multi-page selections are split into one segment per page when drawn.

**Drawing:** the overlay paints translucent rectangles with a multiply blend (text stays readable), underlines, and a small note icon at the end of annotations that have a note. Hover shows the note; click opens the popup (edit, recolor, delete).

**Annotations panel (in the reader)** and **Highlights & Notes view (in the library):** list with color chips, quote, note, chapter or page, date; filters by color, kind, book, date; search box (uses `annotations_fts`); click jumps to the spot (opening the reader if needed).

**Export (`annotations.py`)**
- **Markdown** per book, for example:
  `## Clean Code (Robert C. Martin)`, then bullet items `> quote` with `— page 87, 12 March 2026`, and the note under it. Also HTML, CSV and JSON (v5 export extension).
- **Whole-library export** to a folder with one file per book.
- **PDF only: Export annotated copy** using PyMuPDF (`page.add_highlight_annot(...)` on the stored rectangles, then save to a new file). The original is never modified.
- **PDF only: Import highlights from file:** read existing highlight, underline and text annotations with `page.annots()` and create annotations with `origin='file'` (editable copies; the file itself is untouched).
- All annotation changes go through the undo stack (v2) where practical.

### 5.8 Reader UI and shortcuts

```
┌─ Reader ── Clean Code.pdf ✕ │ War and Peace.epub ✕ ──────────────────────────────┐
│ ☰ Contents  ⌕ Search   ▣ Layout(Aa)   ☾ Theme   ⤢ Fullscreen   ↗ External reader  │
├───────────────┬────────────────────────────────────────────────────┬───────────────┤
│ Contents      │                                                    │ Notes (4)     │
│ ▸ Preface     │        ┌──────────────────────────────┐            │ 🟨 "Clean code │
│ ▾ Chapter 1   │        │  Clean code is simple and    │  🔖        │    always…"    │
│    Meaningful │        │  direct. ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓    │            │  p. 12         │
│ ▸ Chapter 2   │        │  ▓▓▓▓ (highlight)           │            │ 🟩 "Names …"   │
│ Thumbnails    │        │  …                           │            │  note: check…  │
│ Bookmarks (2) │        └──────────────────────────────┘            │               │
├───────────────┴────────────────────────────────────────────────────┴───────────────┤
│  ◀  Page 87 of 464   ━━━━━━●━━━━━━━━━━━━━━━━   19%   · about 5 h 10 min left  ▶    │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Suggested reader shortcuts (context `reader`; editable in the v5 shortcuts page; the library's own shortcuts still apply in the library window):

| Action | Shortcut |
|---|---|
| Next / previous page | `Right`, `PageDown`, `Space` / `Left`, `PageUp`, `Shift+Space` |
| Scroll | `Up`, `Down`, mouse wheel |
| First / last page | `Home` / `End` |
| Zoom in / out / fit width / fit page | `Ctrl++` / `Ctrl+-` / `Ctrl+1` / `Ctrl+2` |
| Font bigger / smaller (reflowable) | `Ctrl+Shift++` / `Ctrl+Shift+-` |
| Go to page | `Ctrl+G` |
| Search in book / next / previous hit | `Ctrl+F` / `F3` / `Shift+F3` |
| Bookmark this page | `Ctrl+D` |
| Highlight selection / add note | `H` / `N` |
| Contents panel / notes panel | `T` / `Shift+N` |
| Night theme cycle | `Ctrl+Shift+N` |
| Fullscreen / leave | `F11` / `Esc` |
| Close tab / next tab | `Ctrl+W` / `Ctrl+Tab` |

All reader commands are actions in the v5 registry, so they also appear in the command palette while a reader window is active. The reader is fully usable by keyboard, and highlight colors are also distinguished by an icon shape (accessibility), not by color alone.

### 5.9 Opening flow and integration
- `reader_manager.open(book_id, locator=None, highlight_query=None)`:
  1. `ensure_local(book)` (v4; downloads cloud books first with the usual progress dialog).
  2. Try the backend; on password-protected files ask for the password (**never stored**); on failure offer the external reader.
  3. Restore layout settings and position; start a reading session; apply v2 open bookkeeping (`last_opened_at`, auto-mark Reading).
- **Open with** (v2): **BookLib Reader** appears first for supported formats; the default per format can be set to it; **Open with external reader** stays available.
- **Continue Reading** shelf items open at the saved position; the details pane shows **Resume at 42%**.
- Search-inside-books results and annotation lists call `open(..., locator=..., highlight_query=...)`.
- Closing the last reader tab closes the reader window; unsaved state is never lost because positions are written continuously.
- `ensure_local(book, lease=True)` renews a lease on the cached file while the tab is open and releases it on close (section 5.15). Books opened in the reader count as recently opened for the keep-recent rule.

### 5.10 Full-text search inside books (`fulltext/`)

```
fulltext/
├── extract.py      # extraction function run in the extractor process pool
├── normalize.py    # text cleanup shared by indexing and queries
├── chunker.py      # splits text into chunks
├── store.py        # fulltext.db access, insert/delete per book
├── scheduler.py    # queue, priorities, pause rules
├── query.py        # safe FTS5 query builder, ranking, grouping
└── snippets.py     # builds highlighted snippets on demand
```

**Extraction (`extract.py`, runs in a worker process)**
- Input: file path (or cache path for cloud books that are already downloaded) and `book_id`. Output: a list of `(unit, part, locator, text)` chunks plus the total character count, returned as plain data.
- PDF: text per page. Reflowable: text per chapter, split into chunks of about 1,500 to 2,500 characters at paragraph boundaries (so a hit maps to a place, not to a whole chapter).
- If a document yields very little text per page (for example under 20 characters on most pages), set `fts_state = 'no_text'` (scanned book) and store nothing.
- Enforce limits: maximum characters per book (for example 30 million), and a timeout per book.

**Normalization (`normalize.py`, applied to indexed text and to queries)**
- Unicode NFKC (fixes ligatures such as `ﬁ`), remove control characters, join words broken by a hyphen at a line end, collapse whitespace.
- Do **not** remove diacritics here; the tokenizer option `remove_diacritics 2` handles matching.
- Later improvement: drop lines that repeat at the same position on most pages (running headers and footers) so they do not create false hits.

**Tokenizer and languages**
- Default `unicode61 remove_diacritics 2` suits Latin scripts.
- **Test Hindi/Devanagari immediately** with a real Hindi book: search for a whole word and for a word containing vowel signs. If matches fail or fragment, try the tokenizer's `categories` option to keep combining marks inside words, or use the `trigram` tokenizer (substring matching, larger index, needs SQLite 3.34 or newer) for those books. If needed, allow a per-database choice in Settings and rebuild the index when it changes.
- CJK text has the run-together problem described earlier; trigram is the usual fallback.
- Stemming (`porter`) is off by default (English only); offer it as a setting if you mostly read English.

**Index state machine (`books.fts_state`)**
`NULL` (not indexed) → `queued` → `indexing` → `done` or `no_text` or `failed`.
A changed file (scanner or sync sets it) becomes `stale` and is re-queued. A `fts_version` lower than the current extractor version re-queues the book. On startup, `indexing` is reset to `queued` (crash recovery).

**Scheduling (`scheduler.py`, index lane)**
- Only books in folders with **Index contents** on (or in chosen collections), plus a manual **Index this book now** and **Index selected**.
- One book at a time, sent to the extractor pool; extractor processes run at below-normal priority (for example `psutil.Process().nice(...)`, `BELOW_NORMAL_PRIORITY_CLASS` on Windows).
- **Pause rules (all configurable):** on battery power, while a reader is rendering heavily, while another heavy job runs, and after 3 consecutive failures (with a notice).
- Cloud books are indexed only when they are already in the download cache (or when the user asks to download them); the index never triggers silent large downloads.
- A **Full-text index** settings page shows: books indexed, queued, no text, failed, index size, and buttons **Pause**, **Rebuild all**, **Delete index**.
- Index size guide: plain text of a typical book is around 0.5 to 1 MB, and the contentless index is smaller than the text, so 5,000 books need on the order of a gigabyte. Show the size and offer a limit.

**Storing (`store.py`)**
- For each book, in one transaction: delete old chunks (`DELETE FROM chunk_fts WHERE rowid IN (SELECT id FROM chunks WHERE book_id=?)`, then delete from `chunks`), insert new `chunks` rows and the matching `chunk_fts` rows with the same rowid. Update `fts_state = 'done'`, `text_chars`, `fts_indexed_at` in the main database afterwards.
- Writes to `fulltext.db` come from one thread only (the index lane).
- Before indexing a book, check the index size limit and free space (section 5.15); when either is exceeded, pause with reason `size_limit` or `low_space` and notify. After deleting a book's chunks, run an incremental vacuum step.

**Querying (`query.py`)**
- **Never pass raw text to `MATCH`.** Parse the user's query into: quoted phrases (`"exact phrase"`), excluded words (`-word`), `OR` between terms, prefix terms (`net*`), and plain terms (AND). Escape and quote every token, then build the FTS5 expression.
- Ranking: `ORDER BY bm25(chunk_fts)`; fetch the best few hundred chunks, then group by book (hit count, best rank).
- **Scope filter:** `ATTACH` the library database read-only and join, or filter the grouped results in Python by the current view's book ids.
- Limitation to state in the help text: a phrase that crosses a chunk boundary (page or chunk break) is not found.

**Snippets (`snippets.py`)**
- Because the index has no text, build snippets when results are shown: for the visible results, ask the extractor pool for the text of just that page or chunk (`extract_unit(path, locator)`), find the first query term, take about 80 characters on each side, escape HTML, and wrap matches. Cache snippets in memory for the session.
- If the book file is not available (cloud book not downloaded), show the location only and a **Download to see the snippet** action.

**UI (`ui/inbook_search.py`)**
```
🔍 Search inside books  [ "clean code" -refactoring       ]  Scope: [Current view ▾]
─────────────────────────────────────────────────────────────────────────────────
 [cover] Clean Code · Robert C. Martin                              12 matches ▾
          p. 87   …a name should reveal intent; **clean code** reads like…
          p. 141  …the boy scout rule keeps **clean code** clean…
 [cover] The Pragmatic Programmer                                    3 matches ▸
 ⓘ 214 of 1,248 books are indexed (18 have no text)     [Index more…]  [Settings]
```
- Click a hit: open the reader at that locator with the terms highlighted and the in-book search bar prefilled.
- **Show these books in the library** applies `LibraryQuery.book_ids` so you can sort, tag or add them to a collection.

### 5.11 Recommendations (`recommend/`)

```
recommend/
├── features.py    # turns a book into a weighted sparse feature vector
├── profile.py     # builds the taste profile from ratings and reading history
├── scoring.py     # scores candidates, applies bonuses, diversifies
├── explain.py     # produces the "because…" reasons
└── service.py     # caching, feedback, entry points for the UI
```

**Features (`features.py`)** per book, as a sparse dict `{feature: weight}`:

| Feature | Weight | Source |
|---|---|---|
| `author:<key>` | 3.0 | normalized first author |
| `genre:<g>` | 2.0 | each genre (v3 cleanup keeps them tidy) |
| `tag:<t>` | 2.0 | each tag |
| `series:<name>` | 1.0 | series (series continuation handled separately) |
| `lang:<code>` | 1.0 | language |
| `pub:<name>` | 0.5 | publisher |
| word tokens | 1.0 x TF-IDF | title and description, stop words removed |

Apply IDF weighting over the whole library so common features count less, and L2-normalize the vector.

**Taste profile (`profile.py`)**
- `profile = sum(w_i * vector_i)` over books you have read or rated, where `w_i = rating - 3` for rated books (1 to 5 stars become -2 to +2), `+0.5` for Read books without a rating, and a small `+0.3` for Want to Read books (interest signal).
- Books marked **Not interested** get a negative weight and are excluded from results.
- Fewer than 5 rated books: show "Rate a few books to improve suggestions" and fall back to the genres and authors of Read books.

**Scoring (`scoring.py`)**
```python
score = cosine(profile, candidate_vec)
score += 0.30 if is_next_in_series(candidate)            # previous book rated >= 4 or just finished
score += 0.10 * (author_avg_rating(candidate) - 3) / 2   # you liked this author
score -= 0.20 if in_disliked_genres(candidate)
```
- **Candidates:** books that are not Read, not hidden, not missing.
- **Diversify** with a maximal-marginal-relevance pass and a cap of 2 books per author or series in the top 20, so the list is not ten books by one author.
- Deterministic (ties broken by title), so tests are stable.

**Explanations (`explain.py`)**: for each suggestion take the features with the largest contribution to the dot product and the rated books that contributed most to them, then produce one line such as *"Because you rated Clean Code 5 stars and read other Programming books"* or *"Next in the Foundation series"*.

**Similar books:** the same cosine similarity between a chosen book and all others, top 5, shown in the details pane with a short reason.

**Service and performance:** vectors are cached in memory and updated for changed books after `library_changed` (debounced); IDF is recomputed only when the library changes a lot. With 20,000 books a full scoring pass takes a fraction of a second in plain Python; use NumPy only if you measure a problem.

**Feedback:** context menu **Not interested** or **Hide from suggestions** writes `recommendation_feedback`; **Undo** appears in the status bar; a **Reset feedback** button is in Settings.

**UI**
- Sidebar entry **Recommended** shows the grid with a reason line under each title.
- Details pane section **Similar books**.
- **Surprise me** button (and a command palette action): random pick from Want to Read, or, if empty, from unread books in your top genres.
- Setting: minimum number of ratings before showing suggestions; toggle to turn recommendations off.

### 5.12 Local web access and OPDS (`booklib_web/`)

```
booklib_web/
├── app.py          # Flask app factory: create_app(config, repository)
├── config.py       # bind address, port, options
├── security.py     # password hashing, sessions, pairing, rate limiting, headers
├── routes_ui.py    # pages: library, book, shelves, login, pairing
├── routes_api.py   # JSON API
├── routes_files.py # covers and downloads with Range support
├── opds.py         # OPDS catalog feeds
├── templates/      # Jinja2 (autoescaping on)
├── static/         # own CSS and JS only, no third-party scripts or CDNs
└── __main__.py     # headless mode: python -m booklib_web --db ... --port ...
```
- **Qt-free.** It imports the same `db.query.LibraryQuery` and repository as the desktop app (the v1 rule that the data layer never imports `ui`).
- **Server:** `waitress.create_server(app, host, port, threads=8)`, run in a background thread inside the desktop app (`ServiceManager` starts and stops it), or as a standalone process in headless mode.
- **Database access:** short-lived read connections per request (WAL mode allows this while the desktop app writes).

**Access modes (Settings, Web access)**

| Mode | What it means |
|---|---|
| **Off** (default) | No server running |
| **This computer only** | Binds to `127.0.0.1`; for testing and for a local browser tab |
| **Devices on my network** | Binds to one chosen private network address; password and paired devices required |

- The network-address list comes from the machine's interfaces (for example with `psutil.net_if_addrs()`), preselecting the main private IPv4 address (`192.168.x.x`, `10.x.x.x`, `172.16.x.x` to `172.31.x.x`). Binding to a public address is refused unless the user types a confirmation phrase. Avoid `0.0.0.0`, which also exposes virtual adapters (VPN, WSL, Hyper-V).
- **Auto-off timer** for network mode (default 4 hours; options: 1 h, 4 h, 24 h, until I turn it off). A status-bar indicator shows when web access is active.
- The first time network mode starts, **Windows Defender Firewall** shows its own prompt. The in-app help says to allow it for **private networks only**.
- **Never expose this server to the internet** (no router port forwarding). For remote access use a private network tool such as a VPN that you trust; the help page says so plainly.

**Authentication and pairing (`security.py`)**
- **Password:** set by the user (minimum length enforced), hashed with `hashlib.scrypt` (or argon2) and a per-password salt; never stored in plain text and never logged.
- **Pairing by QR code:** the desktop app shows a QR code (for example with the `qrcode` package) containing `http://<ip>:<port>/pair?code=<one-time code>`. The code is single-use and expires in 5 minutes. Opening it on the phone creates a **device token** (32 random bytes) stored in a cookie; the database stores only its SHA-256 (`web_devices.token_hash`). Devices have names ("Mritunjay's phone"), last-seen time and IP, and can be revoked.
- **Login page** with the password as the alternative to pairing.
- **Sessions:** cookies with `HttpOnly` and `SameSite=Lax` (`Secure` when HTTPS is on); expiry 30 days for paired devices, 12 hours for password sessions.
- **Brute-force protection:** rate limit login attempts per IP with growing delays and a temporary lockout after 5 failures; all failures are logged.
- **CSRF protection** on every write request (token in forms, and an `Origin`/`Host` check).
- **HTTPS (optional):** generate a self-signed certificate (for example with the `cryptography` package) valid for the chosen IP; show its fingerprint. Phones will warn about it, and many OPDS apps refuse self-signed certificates, so HTTPS is optional and HTTP on a trusted home network is the default with a visible warning ("People on your Wi-Fi can see this traffic; use only on a network you trust, not on guest or public Wi-Fi").
- **Security headers:** `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, and a `Content-Security-Policy` allowing only own scripts and styles.
- **Input safety:** only whitelisted query parameters map to `LibraryQuery`; templates autoescape (titles and notes can contain HTML); the server **never accepts file paths**, only book ids, so path traversal is impossible by design.
- **Access log** (IP, method, path, status, device name) written to `web_access.log`; **no tokens, passwords or cookies** are logged.

**Pages and endpoints**

| Route | Purpose | Auth |
|---|---|---|
| `GET /pair?code=` | Exchange a one-time code for a device cookie | Code |
| `GET/POST /login`, `POST /logout` | Password login | none / session |
| `GET /` | Library grid: search, filters (status, format, tag, collection, series), sort, paging (60 per page) | Session |
| `GET /shelf/<name>` | Continue Reading, Recently Added, Want to Read | Session |
| `GET /book/<id>` | Details page: cover, metadata, description, tags, series, buttons | Session |
| `GET /covers/<id>.jpg` | Cover image (cached headers) | Session |
| `GET /book/<id>/download` | File as attachment, **Range** supported, safe file name (`Content-Disposition` with UTF-8 `filename*`) | Session |
| `GET /book/<id>/view` | PDFs opened inline in the phone's browser (optional setting) | Session |
| `GET /api/books`, `GET /api/books/<id>` | JSON list and details, same filters as the page | Session |
| `POST /api/books/<id>/status`, `/rating`, `/notes` | Change status, rating, notes (only when **Allow changes** is on) | Session + CSRF |
| `GET /opds`, `/opds/...` | OPDS catalog feeds | HTTP Basic (see below) |

- **OPDS (`opds.py`):** OPDS 1.2 Atom feeds: root, Recently added, Continue reading, Want to read, By author, By series, By tag, By collection, and a search entry (OpenSearch description). Acquisition links point to the download route with correct MIME types; feeds are paginated. Many phone reading apps support OPDS.
- **OPDS authentication:** reading apps usually use HTTP Basic. Provide a separate **OPDS key** (random, shown once, revocable) with the username `booklib`; OPDS access is always read-only. Basic authentication over plain HTTP is visible on the network; this is another reason to use it only on a trusted home Wi-Fi.
- **Cloud books** (Drive and others): the server can trigger the normal download job (with a "Preparing your file…" page that refreshes) only if **Allow the server to download cloud books** is on; concurrency limit 1; otherwise the page shows "Not available offline on the server". Cloud downloads triggered from the web interface check the guard and the daily budget first, hold a lease while streaming, and do not count as opened (section 5.15).
- **Web interface:** responsive, large touch targets, dark mode via `prefers-color-scheme`, no external fonts or scripts. An installable web-app manifest is a stretch idea.
- **Drag-free phone flow:** open the book page, tap Download, and open it in your phone's reader app; or add the OPDS catalog once in a reading app and browse from there.

**Desktop UI: Settings, Web access**
```
┌───────────────────── Web access ─────────────────────────┐
│ Mode:  ( ) Off  ( ) This computer only  (•) Devices on my network │
│ Network address: [192.168.1.20 ▾]   Port: [8765]          │
│ Turn off automatically after: [4 hours ▾]                 │
│ Password: [Set…]      ☐ Allow changes (status, rating, notes) │
│ ☐ Allow the server to download cloud books   ☐ HTTPS (self-signed) │
│                                                           │
│   [ QR code ]   Scan with your phone to pair              │
│   http://192.168.1.20:8765                                │
│                                                           │
│ Paired devices:  Mritunjay's phone   last seen 2 min ago  [Revoke] │
│ OPDS key: ••••••••  [Show once] [Regenerate]              │
│ ⚠ Only use on a network you trust. Do not expose to the internet. │
│ [Check from this computer]   Troubleshooting…             │
└───────────────────────────────────────────────────────────┘
```
- **Troubleshooting page** shows the address, whether the port is listening, and a **Check from this computer** test; help text covers the firewall prompt, phone and PC being on the same network, and guest-network isolation.

### 5.13 Other cloud sources (optional; `cloud/`)

**Provider abstraction**
```python
class CloudProvider(Protocol):
    key: str                                   # 'gdrive' | 'onedrive' | 'dropbox'
    def authorize(self, ui_callbacks) -> Account: ...
    def list_children(self, acct, folder_id, page=None) -> Page[RemoteItem]: ...
    def initial_cursor(self, acct) -> str: ...
    def list_changes(self, acct, cursor) -> ChangePage: ...
    def open_download(self, acct, item, offset=0) -> Stream: ...
    def thumbnail(self, acct, item) -> bytes | None: ...

@dataclass
class RemoteItem:
    id: str; name: str; parent_id: str | None; is_folder: bool
    size: int | None; modified: str | None
    hash_kind: str | None; hash_value: str | None    # 'md5' | 'quickxor' | 'sha1' | 'dropbox'
    mime: str | None; web_url: str | None
```
- Move the v4 Drive code behind `GoogleDriveProvider`; the indexer, sync, download, cache and picker use only the interface. The v4 features (basic index, deep index, changes, cache, badges, offline) work for every provider.
- **Migration 6b:** `ALTER TABLE drive_accounts ADD COLUMN provider TEXT NOT NULL DEFAULT 'gdrive'`; `ALTER TABLE books ADD COLUMN remote_hash_kind TEXT; ADD COLUMN remote_hash TEXT` (fill from `md5` for existing Drive books with kind `md5`); `folders.kind` gains the values `'onedrive'` and `'dropbox'`. The columns named `drive_*` keep their names and simply hold the provider's item id (rename them in a later cleanup version). Virtual paths use the provider key: `onedrive://<account_id>/<item_id>`.
- **Duplicates across sources:** compare hashes only when the hash kinds are equal; otherwise compare size and name, and confirm with a SHA-256 after download.
- **Sign-in and secrets:** same rules as v4 (refresh secrets in the OS credential store, never in the database or logs, client credentials imported by the user, per-provider setup guides). Keep credential blobs small; if a library stores a large token cache, encrypt it with the OS (for example Microsoft's `msal-extensions`) instead of putting it into the credential store directly.

**OneDrive specifics**
- Register your own app in Microsoft's Entra (Azure) portal for personal accounts as a public client with a loopback redirect; delegated permissions `Files.Read` and `offline_access` (plus basic profile for the account email). No client secret; PKCE is used through the `msal` library (`acquire_token_interactive`).
- Browse: `GET /me/drive/root/children` and `/me/drive/items/<id>/children` with `@odata.nextLink` paging.
- Incremental sync: `GET /me/drive/root/delta`; keep the `@odata.deltaLink`; process items with a `deleted` facet as removals; when a folder is reported deleted, verify before marking its books missing (delta sometimes omits events for children).
- Download: use the item's short-lived pre-authenticated download URL (`@microsoft.graph.downloadUrl`) fetched fresh for each download, never stored, or the `/content` endpoint; `Range` resume works with either.
- Integrity: `quickXorHash` is the hash guaranteed for both personal and work accounts. Verify size always; verify the hash if you implement Microsoft's documented QuickXorHash algorithm, otherwise use `sha1Hash` when the account provides it.
- Personal and work/school accounts differ in details; start with personal.

**Dropbox specifics**
- Create your own app in Dropbox's App Console (scoped access; choose **Full Dropbox** to index existing books, or **App folder** for a sandboxed folder); scopes `files.metadata.read`, `files.content.read`, `account_info.read`.
- OAuth 2 authorization code flow with PKCE and offline access, which returns a short-lived access token and a long-lived refresh token; store the refresh token only.
- Browse and index: `files/list_folder` (it can list recursively in one paged sequence) then `files/list_folder/continue` with the cursor; the same cursor later returns only changes, which gives incremental sync. (`list_folder/longpoll` can push changes but is not needed.)
- Identity: use the file `id` (paths change on rename or move; Dropbox paths are case-insensitive).
- Download: `files/download`, or a temporary link; support `Range` resume.
- Integrity: Dropbox's `content_hash` is computed from 4 MB block hashes; it is documented and simple to compute locally (SHA-256 of each 4 MB block, then SHA-256 of the concatenated digests) to verify downloads and to compare with local files.
- Handle 429 with `Retry-After`, like all providers.

**Testing:** implement a `FakeProvider` for integration tests; keep recorded JSON fixtures per provider; test every provider with the same conformance suite (listing, paging, changes, deletes, renames, moves, download with resume, hash verification, expired token).
- Downloads from every provider go through the same cache table and the same storage policies as Google Drive.

### 5.14 Settings (new pages)
- **Reader:** default reader per format, default view (continuous/single/facing), zoom, theme, margins, font size, track reading time, idle timeout, streak minimum minutes, cache size.
- **Full-text index:** folders and collections to index, pause rules, size limit, tokenizer choice, rebuild and delete.
- **Recommendations:** on/off, minimum ratings, reset feedback.
- **Web access:** as in the sketch above, plus log location.
- **Cloud accounts** (if built): providers, import credentials, sign-in state.

### 5.15 Storage integration for v6 features

This section extends the storage manager from the v4 plan (section 6.15) and the Storage page from the v5 plan (section 4.9). Protection tiers, the planner and executor, the guard and the dry run work as described there.

**New storage areas**

| Area | Kind | Default policy |
|---|---|---|
| `fulltext_index` (`fulltext.db`) | Regenerable | Limit 2 GB. At the limit: pause indexing, notify, delete nothing. Optional trim and compact actions (below) |
| `extractor_tmp` (`<app data>/tmp/extract/`) | Regenerable | One folder per worker, removed when the worker ends; startup sweep removes folders older than one day or belonging to processes that no longer exist |
| `web_downloads` (cloud books fetched for the web server) | Regenerable | Stored in the normal download cache with a lease while streaming; daily budget 2 GB |
| `web_log` (`web_access.log`) | Regenerable | Rotating, 5 files of 5 MB |
| Reader page cache | Memory only | 256 MB cap (already in 5.2); shown on the Storage page as a memory readout with a **Clear memory cache** button. Nothing is written to disk |

**Full-text index limit (`fulltext/scheduler.py`)**
- Before indexing each book, check the size of `fulltext.db` against the limit and ask the guard for room (estimated growth is the average index bytes per indexed book, measured from previous books, times two). If either check fails, set the scheduler's pause reason to `size_limit` or `low_space` and show a notice with a link to the Storage page. Books stay `queued`.
- **Actions on the Storage page:**
  - **Raise limit.**
  - **Remove index for books not opened for [90] days:** deletes those books' chunks (needs `contentless_delete`), sets their `fts_state` to `NULL`, then compacts. Order is oldest `books.last_opened_at` first (never-opened books first). Optional automatic version of this rule, **off by default**.
  - **Remove index for selected folders.**
  - **Compact index** (incremental vacuum, with a full `VACUUM` fallback as described in the migration notes).
  - **Delete entire index** (confirmation; all `fts_state` values reset to `NULL`).
- Nothing in the index is ever removed automatically unless the user has turned the optional rule on.

**Extractor temp folders (`extract_pool`)**
- Each worker process creates its temp folder with `tempfile.TemporaryDirectory(dir=<app data>/tmp/extract/, prefix=f"{pid}-")` and cleans it in a `finally` block.
- **Per-file limit:** extraction results are returned as plain data, so temp use should be tiny; if a worker's temp folder grows past 500 MB, abort that file and mark it `failed`.
- **Startup sweep:** delete folders in `tmp/extract/` whose process id is not running or that are older than one day.

**Leases for the reader and the web server**
- `ensure_local(book, lease=True)` sets `drive_cache.in_use_until`. The built-in reader **renews the lease every 60 seconds** while a tab is open (lease length 5 minutes) and releases it (`in_use_until = now`) when the tab closes; a crash simply lets the lease expire within minutes.
- The web server sets a lease for the duration of a download response and extends it while bytes are being sent.
- Books opened in the built-in reader update `books.last_opened_at`, so they count as recently opened for the keep-recent rule. Books fetched by the **web server** do **not** count as opened (so a phone browsing does not push out the books you read).

**Web downloads and the daily budget (`booklib_web`)**
- A request that would trigger a cloud download first asks the guard for room and checks the **daily budget** (default 2 GB, stored per local calendar day in `app_meta` under `web.download_bytes.<date>`). Over budget or low space: respond with a friendly "Not available right now" page and log the reason.
- Concurrent web-triggered downloads stay limited to 1 (as in 5.12).

**Logs:** `web_access.log` uses a rotating handler (5 files of 5 MB). The Storage page lists it under Logs.

**Storage page additions (v5 section 4.9):** rows for Full-text index (with **Compact**, **Remove old index…** and **Delete index**), Extractor temp, Web access log, and the reader's memory cache readout.

**Settings keys (new):** `fulltext_limit_bytes` (2 GB), `fulltext_auto_trim_days` (0 = off), `web_download_budget_bytes` (2 GB per day), `reader_cache_bytes` (256 MB).

---

## 6. Build Order (Milestones)

Finish and test each milestone before starting the next. Milestones 2 to 8 make the reader; 9 to 11 add search and reading time; 14 to 16 add the web interface; 17 to 19 are optional.

| # | Milestone | What "done" looks like |
|---|---|---|
| 1 | **Migration 6, extractor process pool, lanes** | Migration passes on a copy of your library; background extraction runs in worker processes; a corrupt PDF fixture fails without crashing the app; index lane and `ServiceManager` exist |
| 2 | **Backend interface and PyMuPDF backend** | Open, page count, render, words, links, contents and search work for PDF, EPUB, MOBI, FB2, CBZ and TXT samples through a small test script |
| 3 | **Reader window for PDF** | Continuous, single and facing views; zoom and fit; contents and thumbnails; keyboard and mouse; cache and prefetch; night mode; password prompt |
| 4 | **Reflowable books** | Font size, margins, themes, paginated and scrolled modes; a Hindi EPUB tested and the limits documented |
| 5 | **Text layer, selection and in-book search** | Word selection and copy, hit highlighting with next/previous, links, "no text on this page" notice |
| 6 | **Positions, progress, sessions and open flow** | Resume works across restarts and font-size changes; library progress and status update; Open with and defaults; Continue Reading opens at the position; reading sessions recorded |
| 6b | **Leases for open books** | Built-in reader renews and releases leases on cached cloud books; the storage manager never evicts a book that is open in a tab; opens in the reader count as recent |
| 7 | **Bookmarks** | Toggle, list, rename, jump, ribbon |
| 8 | **Highlights and notes** | Create, edit, colors, re-anchoring after layout change, orphan handling, panel, library view, export (Markdown, HTML, CSV, JSON), annotated PDF copy, import from PDF |
| 9 | **Full-text index engine** | Extraction in worker processes, chunker, state machine, contentless store, scheduler with pause rules; tested on real books including a scanned one and a Hindi one |
| 9b | **Index limit, compaction and extractor temp cleanup** | Index size limit with pause and notice; trim by age or folder; compact and incremental vacuum; extractor temp folders removed on exit and swept at startup; Storage page rows added |
| 10 | **Search inside books UI** | Query syntax, grouped results, on-demand snippets, open at hit, "show these books in the library" |
| 11 | **Reading-time statistics** | Time cards, streaks, heatmap, per-book time left, drill-down |
| 12 | **Recommendation engine** | Features, profile, scoring, diversification, explanations, feedback; unit tests on a synthetic library |
| 13 | **Recommendation UI** | Recommended shelf with reasons, Similar books, Not interested, Surprise me, settings |
| 14 | **Web server core and security** | Loopback default; auth, pairing, sessions, CSRF, rate limits, headers, logging; authentication matrix tests pass |
| 15 | **Web UI, downloads and OPDS** | Library, filters, details, covers, downloads with Range, OPDS feeds tested with a real phone app |
| 15b | **Web download budget and guard** | Cloud downloads from the web interface respect the guard, the daily budget and leases; web log rotates |
| 16 | **Web extras and admin** | Optional write actions, device management, auto-off timer, HTTPS option, troubleshooting page, headless mode |
| 17 | **(Optional) Cloud provider abstraction** | Drive code behind `CloudProvider`; migration 6b; v4 tests still pass through the interface; `FakeProvider` conformance suite |
| 18 | **(Optional) OneDrive** | Sign-in, folder picker, index, delta sync, download, hash handling |
| 19 | **(Optional) Dropbox** | Sign-in, folder picker, index, cursor sync, download, content hash |
| 20 | **Polish and release readiness** | Performance tests, security review, accessibility pass, backup and restore test with the new data, README, licence review |

---

## 7. Testing Plan

**Unit tests (`pytest`)**
- **Migration 5 to 6:** existing data intact; new tables exist; `fts_state` defaults; running twice is safe.
- **Locators:** save and restore for PDF and reflowable; restore after font-size changes lands on the same text; stale locator fallbacks (file replaced, fewer pages).
- **Anchoring (pure functions):** exact match, repeated phrases resolved by prefix and suffix, hyphenation and ligature differences, fuzzy match above threshold, orphaned below threshold, multi-page selections, hint range used first.
- **Progress:** conversion from locator to percent under different layouts; v3 status rules triggered by the reader; "Mark as Read?" at the end.
- **Sessions:** idle pause, focus loss, sessions under 10 seconds discarded, flush on crash simulation, local-day grouping around midnight, streak calculation (gaps, minimum minutes, timezone-free), heatmap bins.
- **Bookmarks and annotations:** CRUD, undo, `annotations_fts` stays in sync, export formats (Markdown, HTML, CSV, JSON) against golden files, annotated PDF copy contains the highlights and the original is untouched, import of PDF annotations.
- **Text layer:** selection range between two points, double and triple click, copy text with hyphen rejoining, links.
- **Rendering cache:** LRU eviction, zoom quantization, stale request cancellation, memory cap.
- **Extractor pool:** corrupt, encrypted, huge and zero-byte files produce failures, not crashes; timeouts kill the worker and the pool recovers; results are plain data.
- **Full-text:** normalization (NFKC, hyphen joining), chunking boundaries, state machine transitions including `stale` and crash recovery, `no_text` detection, contentless insert/delete/re-index of a book, query builder (phrases, `-word`, `OR`, prefix, special characters, empty query, Hindi text), grouping and scope filter, snippet generation with escaping, fallback when the file is missing.
- **Tokenizer check:** a Devanagari sample searched by full word and by word with vowel signs, with each tokenizer choice; the test documents which setting works on your SQLite version.
- **SQLite capabilities:** startup check for `contentless_delete` and the fallback path.
- **Recommendations:** synthetic library with known preferences gives the expected top results; ties are deterministic; series continuation bonus; author bonus; diversification cap; feedback exclusion; cold start message; explanations mention real contributing books.
- **Web security (Flask test client plus a real socket test):**
  - a test lists **every registered route** and checks it returns 401 or a redirect to login without authentication (except `/pair`, `/login` and static files);
  - default bind is loopback only;
  - path traversal attempts on ids and file names fail; ids only;
  - CSRF token required for writes; write routes blocked when **Allow changes** is off;
  - login rate limiting and lockout; pairing code single-use and expires;
  - device revoke takes effect immediately; only token hashes are stored;
  - security headers present; templates escape HTML in titles and notes;
  - download supports `Range` (partial, suffix, invalid ranges), correct `Content-Disposition` for Unicode names;
  - logs contain no passwords, tokens or cookies;
  - auto-off timer stops the server.
- **OPDS:** feeds validate as well-formed Atom, links resolve, paging, search, and Basic authentication.
- **Cloud (optional):** the shared conformance suite against `FakeProvider` and against recorded fixtures for OneDrive and Dropbox; hash verification (quickXor or SHA-1 handling, Dropbox `content_hash`) with known test vectors.
- **Index limit:** reaching the limit pauses the scheduler with reason `size_limit`, books stay `queued`, nothing is deleted; raising the limit resumes; low free space pauses with reason `low_space`.
- **Index trimming:** removing the index for books not opened for N days deletes only those books' chunks and resets their `fts_state`; other books remain searchable; a never-opened book is trimmed first.
- **Compaction:** with incremental auto-vacuum, the file size drops after deleting chunks; a database created without it is detected and offered a one-time `VACUUM`; the compact action uses the guard.
- **Extractor temp folders:** removed on normal exit and after a simulated crash (sweep at startup); a worker that exceeds the 500 MB temp limit aborts the file and marks it `failed`.
- **Leases:** an open reader tab keeps renewing; closing releases immediately; a crash lets the lease expire; the storage manager skips a book with a valid lease even when the cap is exceeded.
- **Recency:** opening a book in the reader updates `last_opened_at`; fetching it through the web server does not.
- **Web budget:** downloads stop at the daily budget, the counter resets on the next local day, low space blocks a download with a friendly message, and only one web-triggered download runs at a time.
- **Log rotation:** the web access log rotates at the configured size and count.

**Manual test checklist**
- Open a 500-page PDF and a 300-page EPUB; scroll fast, zoom fast, and confirm the window stays responsive and memory stays under control.
- Close and reopen both; you land on the same text. Change the EPUB font size, close, reopen; the position still matches the text.
- Highlight three passages in the EPUB, change the font size and margins, and confirm the highlights follow the text; replace or edit a copy of the file and see orphaned handling.
- Add notes, export to Markdown, open it in a text editor; export an annotated PDF copy and open it in another PDF viewer.
- Try a Hindi EPUB and a scanned PDF; read the on-screen messages and the fallback to the external reader.
- Kill the app while a book is open; on restart the position is at most a few seconds old.
- Index 50 books with content indexing on, watch the background priority (the app stays smooth), unplug the charger on a laptop and confirm indexing pauses; search a phrase, exclude a word, click a hit and land on the right page with the term highlighted.
- Rebuild the index, delete it, and confirm books re-queue.
- Read for a few days with time tracking on; check the heatmap, streak and time-left estimate; turn tracking off and check nothing more is recorded.
- Rate 15 books, look at Recommended and the reasons; mark two suggestions Not interested; confirm they disappear and stay hidden.
- Turn on web access (this computer only), then network mode; pair a phone by QR; browse, search, download a book; try a wrong password five times; revoke the phone; confirm it loses access immediately.
- Add the OPDS catalog to a phone reading app; browse by author, download a book, and test with **Allow changes** off (writes must fail).
- Confirm that with web access off nothing listens on the port (check from another device).
- Run the headless server on another machine or a second copy of the app data.
- Backup, restore into a fresh app-data folder; annotations, bookmarks, positions and sessions return; the full-text index is empty and re-queues; web devices are gone.
- (Optional) Index a OneDrive and a Dropbox folder; add, rename, move and delete files there and run sync; download and read a book from each.

---

## 8. Known Pitfalls and How to Handle Them

| Problem | Handling |
|---|---|
| PyMuPDF licence (AGPL) | Fine for personal use; keep it behind `DocumentBackend`; before distributing, comply with the AGPL, buy a commercial licence, or replace the backend |
| PyMuPDF is not thread-safe; corrupt files can crash the native code | Dedicated render thread; all background extraction in worker processes; crash handling marks the book `failed`; positions saved continuously |
| Memory growth when scrolling through big PDFs | LRU cache with a byte cap, lazy thumbnails, render only visible pages, cancel stale renders |
| Blurry text on high-DPI screens | Multiply zoom by `devicePixelRatio`; test at 125% and 150% Windows scaling |
| Selection is wrong in multi-column, rotated or scanned pages | Reading-order words from the engine; accept limits; show "No text on this page" instead of failing silently; OCR is a stretch idea |
| EPUB looks plain or broken in the built-in reader | Honest limits, **Open in external reader** always available, WebEngine mode as a later backend |
| Hindi and other Indic scripts show empty boxes or fail to search | Test early; provide font fallback if possible; tokenizer options or trigram; external reader fallback |
| Position drifts after changing font size | Locator with chapter, fraction and text quote; re-locate by quote; tests |
| Highlights lose their place after re-layout | Token-sequence anchoring with prefix and suffix; fuzzy match; orphan state with a manual **Find** action; never delete automatically |
| Annotation data lost if the book file is replaced | Annotations are in the database (and in backups); orphan handling; JSON export |
| PDF password handling | Prompt each time, never store the password |
| DRM-protected EPUB or PDF cannot be opened | Clear message and external reader fallback; no DRM removal |
| Index grows too large | Opt-in per folder or collection, contentless FTS, size shown and limit available, delete or rebuild any time |
| `contentless_delete` missing in old SQLite | Startup check; newer SQLite wheel or contentful fallback |
| Scanned PDFs waste indexing time | `no_text` detection after sampling pages; failure and timeout limits |
| Line-end hyphenation, ligatures, running headers cause misses and false hits | NFKC normalization, hyphen joining, later header/footer removal |
| Phrase spanning two chunks not found | State the limitation in the help; keep chunks reasonably large |
| Snippets need the file | Build on demand; cloud books without a download show location only |
| Indexing slows the PC or drains the battery | Below-normal priority, single job, pause on battery, pause during heavy work |
| Recommendations feel wrong with few ratings or sparse metadata | Minimum-ratings rule, cold-start message, explanations, feedback, easy off switch |
| Filter bubble (same authors and genres) | Diversification cap; **Surprise me**; genre variety in tie-breaking |
| **Web server exposed too widely** | Default off; loopback default; single private interface; refuse public addresses without explicit confirmation; auto-off timer; clear "never expose to the internet" help |
| Weak or leaked password, brute force | Minimum length, scrypt hashing, rate limiting and lockout, device tokens that can be revoked |
| CSRF, XSS through book titles or notes, path traversal | CSRF tokens and origin checks, autoescaped templates and CSP, ids only (never paths) |
| Malicious book files served to other devices | Files are served as downloads (attachment) by default, `nosniff`, optional inline PDF only |
| Plain HTTP traffic on Wi-Fi can be read by others on the network | Visible warning, trusted network only, optional HTTPS with fingerprint, read-only OPDS |
| Windows Firewall blocks the phone | In-app instructions, "Check from this computer" and a troubleshooting page |
| Server left running forever | Auto-off timer and a persistent status-bar indicator |
| Secrets in logs | Log scan test; only hashes stored |
| Cloud provider quirks (OneDrive delta gaps, Dropbox case-insensitive paths, throttling) | Verify before marking missing, ids instead of paths, backoff with `Retry-After`, shared conformance tests |
| Different hash types across providers | Store hash kind; compare only equal kinds; confirm with SHA-256 after download |
| Provider rules or APIs change | Provider modules isolated behind the interface; setup guides say to re-check documentation |
| The full-text index keeps growing and eats the drive | Size limit that pauses indexing, opt-in per folder, trim by age or folder, compaction, size shown on the Storage page |
| The index file does not shrink after deleting books | Incremental auto-vacuum set at creation, incremental vacuum after deletions, one-time `VACUUM` for older files |
| Extractor workers leave temp folders after a crash | Per-worker temp folders, cleanup in `finally`, startup sweep by process id and age |
| A book is evicted while it is open in the reader | Lease renewed while the tab is open; locked files are skipped |
| A phone (or anyone with the password) fills the drive through cloud downloads | Guard check, daily budget, one download at a time, log entries |
| Web browsing pushes your own books out of the recent list | Web downloads do not count as opened |
| Logs grow without limit | Rotating handlers for app and web logs |

---

## 9. Definition of Done for v6

- [ ] Migration from v5 works on a copy of your real library, with an automatic safety snapshot first
- [ ] Background extraction runs in worker processes; a corrupt file never crashes the app
- [ ] The built-in reader opens PDF, EPUB, MOBI, FB2, CBZ and TXT with contents, search, links, selection, zoom and reflow settings, and falls back to external readers cleanly
- [ ] Reading position is remembered and survives layout changes; library progress and status follow the reader
- [ ] Bookmarks, highlights and notes work, follow the text after re-layout, and can be exported; PDFs can export an annotated copy and import existing highlights; files are never modified
- [ ] Reading time, streaks and the heatmap work and can be switched off
- [ ] Full-text indexing is opt-in, runs quietly, pauses on battery, shows its size, can be rebuilt, and search inside books opens the reader at the hit with terms highlighted
- [ ] Hindi (or your other languages) tested for full-text search with a documented working setting
- [ ] Recommendations show reasons, similar books and feedback options, and work fully offline
- [ ] Web access is off by default, secure when on (password, pairing, CSRF, rate limits, auto-off), browsable and downloadable from a phone, OPDS works with a real reading app, and all web tests pass, including "every route requires authentication"
- [ ] Backups include annotations, bookmarks, positions and sessions, and exclude the index and web devices
- [ ] (Optional) OneDrive and Dropbox index, sync, download and open like Google Drive, through the provider abstraction
- [ ] Runs smoothly with 20,000 books and a 1 GB full-text index
- [ ] Unit tests pass for locators, anchoring, sessions, annotations and export, text layer, extractor pool, full-text, recommendations, web security and OPDS
- [ ] The full-text index has a size limit that pauses indexing with a clear notice, can be trimmed, compacted and deleted, and never removes anything automatically unless the optional rule is on
- [ ] Extractor temp folders never accumulate, even after crashes
- [ ] Books open in the built-in reader are never evicted while open, and count as recently opened
- [ ] Web-triggered cloud downloads respect the disk-space guard and the daily budget, and do not affect the keep-recent list
- [ ] Logs rotate; the Storage page shows all v6 areas and the reader's memory cache
- [ ] Unit tests pass for index limits and trimming, compaction, extractor temp cleanup, leases, recency and the web budget

---

## 10. Stretch Ideas (After the Definition of Done)

- **OCR** for scanned books using Tesseract (PyMuPDF can use it when installed) so they become selectable and searchable.
- **WebEngine-based EPUB mode** for books whose styling the built-in engine renders poorly (sandboxed, no network, sanitized content).
- **Read aloud** with the system's text-to-speech (`QTextToSpeech`).
- **Dictionary lookup** on double-click using a local dictionary file.
- **Online discovery and wishlist:** suggestions from Open Library or Google Books for books you do not own, saved to a wishlist.
- **KOReader or other reading-progress sync** with your phone.
- **Web app manifest** so the phone can install the library page like an app; **mDNS** so the server is reachable as `booklib.local`.
- **Per-annotation tags and spaced-repetition review** of highlights.
- **Render process isolation** for the reader itself.

---

## 11. After v6: Packaging and Releasing

The roadmap's feature work ends here. Before sharing the app or trusting it with years of data:
- **Upgrade tests from every version:** keep a small database fixture from v1, v2, v3, v4, v5 and v6, and a test that migrates each one to the latest version and checks the data.
- **Packaging:** build a Windows folder distribution with PyInstaller (or a similar tool), test it on a clean machine, and put your app data under the user's application-data folder. An installer (for example Inno Setup) is optional.
- **Licences:** PySide6 is LGPL (dynamic linking is fine); PyMuPDF is AGPL or commercial (see the note at the top); Calibre is a separate program the user installs; check the licence of every other dependency (`pip-licenses` helps) and include a third-party notices file.
- **First-run wizard:** choose a library folder, choose your default reader, optionally connect cloud storage, optionally enable full-text indexing.
- **Diagnostics:** a "Copy diagnostics" button (versions, schema version, settings without secrets, recent log lines) so problems can be reported without exposing private data.
- **Versioning and changelog:** semantic version numbers, a changelog, and a documented migration policy (always back up, never edit past migrations).
- **Security review:** re-read the web server and credential storage code with the checklist in section 8, and run dependency vulnerability scans.

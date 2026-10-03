# Book Library App: Version 3 Plan (Metadata Enrichment and Organization)

**Goal of v3:** Complete the details pane automatically and give you real tools to organize a large collection: fetch missing metadata online, group books with tags, collections and series, find duplicates, keep the library in sync with your folders, track reading progress, and replace covers.

**Prerequisite:** v2 is complete and its definition of done is met (especially `edited_fields`, `LibraryQuery`, the undo stack and the table model).

**Out of scope for v3** (planned for later versions): Google Drive, auto-rename and organize files, format conversion, import/export, reading statistics and goals, built-in reader.

> **Note on online services.** Open Library and Google Books are free but their limits, fields and terms change over time. The endpoints and numbers below are sensible starting points. Check each service's current documentation before you build, and keep all network code behind the provider interface in section 4.1 so a change only touches one file.

---

## 1. Feature List

### 1.1 Online metadata lookup (single book)
- **Fetch online metadata** button in the details pane and right-click menu.
- Looks up by ISBN when the book has a valid one; otherwise searches by title and author.
- Two providers, **Open Library** and **Google Books**, results merged field by field.
- Fills: title, author, publisher, year, edition (when available), ISBN, pages, genre, language, description (synopsis) and cover.
- A **candidate chooser** shows the best matches side by side with your current values; you tick which fields to apply.
- **Safe by default:** it fills empty fields only. Fields you edited by hand are never overwritten. Replacing file-derived values is an explicit choice.
- Each field remembers where it came from (file, manual, or online source) and shows a small source icon.
- Works offline gracefully: a clear message, no crash, and results already fetched are cached.

### 1.2 Bulk fetch and review queue
- Run the lookup on a selection, on a whole shelf, or on **all books with incomplete metadata**.
- Progress bar, pause and cancel; safe to stop and resume later.
- **High-confidence matches are applied automatically; uncertain ones go to a review queue**; unmatched books are marked "not found".
- **Review queue** dialog to go through uncertain books one by one (choose a candidate, search manually, skip, or "don't ask again").
- **Batch undo:** every bulk run can be undone afterwards, even after restarting the app.
- ISBN detection from PDF text (front and back pages), so PDFs without embedded metadata can still be matched.

### 1.3 Tags
- Free-form tags (many per book), with optional color.
- Tag editor in the details pane (chips with autocomplete), and bulk add/remove for a selection.
- Sidebar Tags section with counts; filter by tags with **Any / All** matching.
- Tags are included in search. Rename and merge tags; deleting a tag never deletes books.

### 1.4 Collections (shelves)
- **Manual collections:** create, rename, delete; add books by right-click menu or **drag and drop** onto the sidebar.
- **Smart collections:** a saved combination of search, filters and sort that updates itself (for example "Unread PDFs about Python rated 4+").
- A book can be in any number of collections; removing it from a collection never touches the file.

### 1.5 Series
- Assign a book to a series with an index (supports `1`, `2`, `2.5`).
- Series read automatically from EPUB metadata (Calibre and EPUB 3 formats) when present; editable by hand.
- Sidebar Series list; inside a series books are ordered by index. The details pane shows "Book 3 of *Series*" with previous/next navigation.
- Sort and filter by series; series column in the list view.

### 1.6 Duplicate detection
- **Find duplicates** tool with three levels of confidence:
  1. **Exact duplicates:** identical file content (different names or folders).
  2. **Same ISBN:** for example the same book as PDF and EPUB, or two scans.
  3. **Similar title and author:** possible duplicates for you to judge.
- Side-by-side comparison of each group (format, size, pages, folder, status, rating, date added).
- Actions: keep both, **remove from library only**, or **send to Recycle Bin**, always with confirmation.
- **Merge user data** into the book you keep (status, rating, notes, tags, collections, dates, progress).
- "Not a duplicate" remembers your decision.
- Nothing is ever deleted automatically.

### 1.7 Watch folders and smarter rescan
- Per-folder **Watch for changes** option: new books appear automatically while the app runs.
- Waits until a file has finished copying before importing it.
- Removed files are marked missing; changed files are re-read.
- **Moved or renamed files keep their data:** the scanner relinks them to the existing entry (status, rating, tags and notes survive) instead of creating a new one.
- Quick rescan of watched folders at startup to catch changes made while the app was closed.
- Optional: automatically fetch online metadata for newly imported books.

### 1.8 Reading progress and dates
- Progress as **page X of Y** (when the page count is known) or a **percentage**.
- A thin progress bar on the cover in the grid, a progress column in the list view, and sorting by progress.
- **Start and finish dates**, filled automatically when status changes and editable.
- **Reading history:** a book can be read more than once ("Read again"); each reading keeps its own dates. This also prepares v5 statistics.
- Optional prompt "Mark as Read?" when progress reaches 100%.

### 1.9 Custom covers
- Replace a cover from: an image file, the clipboard, drag and drop, an online cover candidate, or a chosen **PDF page** (useful when page 1 is blank).
- **Restore original** brings back the generated cover.
- Custom and online covers are protected from rescans and from cache cleaning.

---

## 2. What Changes in the v1 and v2 Code

| Area | Change |
|---|---|
| Database | Migration 3: new columns and tables (section 3); `user_version` becomes 3 |
| Field protection | v2's `edited_fields` is replaced by `field_sources` (records **where each field came from**: file, manual, online). Rescans and online lookups both respect it |
| Background work | New **job manager** so scan, lookup, hashing and folder watching never fight over the database or the UI |
| Scanner | Computes a quick hash for each file, relinks moved/renamed files, and skips covers whose `cover_source` is custom/online |
| EPUB extractor | Also reads series information |
| `LibraryQuery` | New filters: tags, collection, series, lookup status, incomplete metadata; new sort fields: series, progress |
| Sidebar | New sections: Collections, Series, Tags, Tools |
| Details pane | Becomes a scrollable stack of collapsible sections (Overview, Details, Organize, Progress, Notes, File) |
| Status changes | v2's status command also updates the reading history |
| FTS index | Rebuilt to include tags |
| Settings | Online lookup, watch and duplicate options |

---

## 3. Database Changes (Migration 3)

Take a **backup copy of the database file** before migrating, and run all steps in one transaction.

```sql
-- migration 3: books table additions
ALTER TABLE books ADD COLUMN field_sources    TEXT;     -- JSON: {"title":"manual","publisher":"online:openlibrary"}
ALTER TABLE books ADD COLUMN description      TEXT;
ALTER TABLE books ADD COLUMN online_source    TEXT;     -- 'openlibrary' | 'googlebooks'
ALTER TABLE books ADD COLUMN online_id        TEXT;
ALTER TABLE books ADD COLUMN lookup_status    TEXT;     -- NULL | 'applied' | 'review' | 'not_found' | 'skipped'
ALTER TABLE books ADD COLUMN lookup_at        TEXT;
ALTER TABLE books ADD COLUMN cover_source     TEXT NOT NULL DEFAULT 'file';  -- 'file'|'placeholder'|'online'|'custom'
ALTER TABLE books ADD COLUMN quick_hash       TEXT;     -- first+last 64 KB + size
ALTER TABLE books ADD COLUMN series_id        INTEGER REFERENCES series(id) ON DELETE SET NULL;
ALTER TABLE books ADD COLUMN series_index     REAL;
ALTER TABLE books ADD COLUMN progress_page    INTEGER;
ALTER TABLE books ADD COLUMN progress_percent REAL;
ALTER TABLE books ADD COLUMN tags_text        TEXT;     -- denormalized, for search only

ALTER TABLE folders ADD COLUMN watch       INTEGER NOT NULL DEFAULT 0;
ALTER TABLE folders ADD COLUMN auto_lookup INTEGER NOT NULL DEFAULT 0;

CREATE INDEX idx_books_size        ON books(size_bytes);
CREATE INDEX idx_books_quick_hash  ON books(quick_hash);
CREATE INDEX idx_books_file_hash   ON books(file_hash);
CREATE INDEX idx_books_isbn        ON books(isbn);
CREATE INDEX idx_books_series      ON books(series_id, series_index);
CREATE INDEX idx_books_lookup      ON books(lookup_status);

-- organization
CREATE TABLE series (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE tags (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color TEXT
);
CREATE TABLE book_tags (
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (book_id, tag_id)
);
CREATE INDEX idx_book_tags_tag ON book_tags(tag_id);

CREATE TABLE collections (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind        TEXT NOT NULL DEFAULT 'manual',     -- 'manual' | 'smart'
    smart_query TEXT,                               -- JSON of a LibraryQuery (smart only)
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE collection_books (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    book_id       INTEGER NOT NULL REFERENCES books(id)       ON DELETE CASCADE,
    added_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (collection_id, book_id)
);

-- reading history (one row per reading of a book)
CREATE TABLE reading_log (
    id          INTEGER PRIMARY KEY,
    book_id     INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    started_on  TEXT,            -- ISO date, may be NULL
    finished_on TEXT,            -- ISO date, NULL while still reading
    note        TEXT
);
CREATE INDEX idx_reading_log_book ON reading_log(book_id);

-- online lookups
CREATE TABLE online_cache (
    cache_key  TEXT PRIMARY KEY,     -- 'openlibrary:isbn:978...' , 'cand:<book_id>' ...
    provider   TEXT NOT NULL,
    response   TEXT NOT NULL,        -- JSON
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- change history for safe batch undo
CREATE TABLE metadata_history (
    id         INTEGER PRIMARY KEY,
    batch_id   TEXT NOT NULL,        -- one id per bulk run or single apply
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    source     TEXT NOT NULL,        -- 'online:openlibrary' ...
    before_json TEXT NOT NULL,       -- values of the changed fields before
    after_json  TEXT NOT NULL,       -- values applied
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_meta_history_batch ON metadata_history(batch_id);

-- duplicates the user has dismissed
CREATE TABLE duplicate_ignores (
    group_key  TEXT PRIMARY KEY,     -- '<level>:<sorted book ids>'
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**Data conversion steps (do these in Python inside the same transaction)**
1. **Field provenance:** for every row with `edited_fields = '["title","author"]'`, write `field_sources = '{"title":"manual","author":"manual"}'`. Keep the old column but stop using it (remove it in a later cleanup version).
2. **Reading history:** for `status = 'reading'` create a `reading_log` row with `started_on = date(status_changed_at)`; for `status = 'read'` create a row with `finished_on = date(status_changed_at)` and no start date.
3. **Cover source:** set `cover_source = 'placeholder'` for formats that never have real covers (`mobi`, `azw3`, `djvu`, `txt`); everything else stays `'file'`. Offer a one-time **Refresh covers** action for PDFs that fell back to placeholders in v1.
4. **FTS rebuild for tags:** drop `books_fts` and its three triggers, recreate them exactly as in migration 2 but with `tags_text` added to the column lists, then run `INSERT INTO books_fts(books_fts) VALUES('rebuild')`.
5. **Quick hash backfill:** not in the migration; a background job computes `quick_hash` for existing books on first launch ("Preparing library, 320 of 1,248").

**Important**
- `PRAGMA foreign_keys = ON` and `PRAGMA busy_timeout = 5000` must be set on **every** connection (main thread and each worker), not just once. Put both in `database.connect()`.
- `ON DELETE CASCADE` on `book_tags`, `collection_books` and `reading_log` means "Remove missing" cleans up related rows automatically, but only when foreign keys are on.

---

## 4. Implementation Details

### 4.1 Online providers (`metadata/online/`)

```
metadata/online/
├── models.py        # Candidate dataclass
├── base.py          # Provider interface
├── openlibrary.py   # Open Library provider
├── googlebooks.py   # Google Books provider
├── http.py          # shared session: User-Agent, timeout, retry, rate limiter
├── scoring.py       # match scoring, thresholds
├── merge.py         # per-field merge rules, genre/author cleanup
└── service.py       # orchestration: lookup(book) -> ranked candidates
```

```python
@dataclass
class Candidate:
    provider: str                  # 'openlibrary' | 'googlebooks'
    provider_id: str               # work/edition key or volume id
    title: str | None
    authors: list[str]
    publisher: str | None
    year: int | None
    isbn: str | None               # ISBN-13 preferred
    pages: int | None
    genres: list[str]
    language: str | None
    description: str | None
    edition: str | None
    cover_url: str | None
    matched_by: str                # 'isbn' | 'title_author'
    score: float = 0.0             # filled by scoring.py

class Provider(Protocol):
    name: str
    def lookup_isbn(self, isbn: str) -> list[Candidate]: ...
    def search(self, title: str, author: str | None) -> list[Candidate]: ...
```

**Endpoints to start with**

| Provider | By ISBN | By title/author | Cover |
|---|---|---|---|
| Open Library | `https://openlibrary.org/api/books?bibkeys=ISBN:<isbn>&format=json&jscmd=data` | `https://openlibrary.org/search.json?title=...&author=...&limit=5&fields=...` | `https://covers.openlibrary.org/b/isbn/<isbn>-L.jpg?default=false` (the `default=false` makes a missing cover return 404 instead of a blank image) |
| Google Books | `https://www.googleapis.com/books/v1/volumes?q=isbn:<isbn>` | `...volumes?q=intitle:<t>+inauthor:<a>&maxResults=5` | `volumeInfo.imageLinks` (switch `http` to `https`) |

- Parse **defensively**: every field access uses `.get()` with defaults; a missing or renamed field must produce `None`, never an exception.
- Google Books works without a key at low volume. Let the user paste an optional API key in Settings (keep it out of the code and out of logs).
- Open Library asks applications to identify themselves. Send a descriptive `User-Agent` such as `BookLib/3.0 (contact: your-email)`. If you publish the app, put a real contact address there.

**HTTP layer (`http.py`)**
- One `requests.Session` per provider with `timeout=(5, 15)`.
- Retry with exponential backoff on connection errors, 429 and 5xx (max 3 tries); respect a `Retry-After` header.
- **Rate limiter:** a simple minimum interval between requests per provider (start with 1 request per second per provider; raise it only after checking the current documentation).
- Cache every successful response in `online_cache` (key = provider + request type + normalized query) with a 30-day expiry; also cache "no result" for 7 days so a bulk run does not re-ask.
- Detect offline state (connection errors on three consecutive requests) and stop the job with a clear message instead of marking books "not found".

**Privacy**
- Lookups send ISBNs, titles and authors of your books to third-party services. Show a one-time notice on first use and a master switch **Enable online lookup** in Settings (default off until the user accepts).

### 4.2 ISBN detection from PDF text (`metadata/isbn_scan.py`)
Most PDFs carry no ISBN metadata, but the printed copyright page usually does.

1. Extract text from the first 12 pages and the last 4 pages with PyMuPDF (`page.get_text()`); stop early as soon as a valid ISBN is found.
2. Search with a tolerant regex for the words `ISBN`, `ISBN-10` or `ISBN-13` followed by 10 to 17 characters of digits, hyphens, spaces and a possible final `X`.
3. Normalize (remove hyphens/spaces) and **validate the checksum** (ISBN-10 and ISBN-13). Discard anything that fails.
4. If several ISBNs are found (print, ebook, hardcover), prefer the ISBN-13 that appears closest to the words "ebook" or "PDF" when present; otherwise take the first valid one.
5. Store it in `isbn` with `field_sources["isbn"] = "file:pdftext"`.
6. It runs on demand and inside the bulk job, not during the normal scan (text extraction is slower than metadata reading). Skip encrypted PDFs and scanned PDFs with no text layer.

### 4.3 Matching, scoring and merging

**Query preparation**
- Clean the local title: remove edition markers like `(2nd Edition)`, tags like `[PDF]`, `z-lib` noise, underscores and extra spaces (reuse the v1 filename cleaner).
- If the title contains a subtitle (`Title: Subtitle`), try the full title first, then the part before the colon.
- Use the first author's surname when searching by author.

**Scoring (`scoring.py`)**
Score each candidate from 0 to 1:

| Signal | Weight |
|---|---|
| Title similarity (normalized, lowercase, punctuation removed; compare with `difflib.SequenceMatcher` or `rapidfuzz`) | 0.60 |
| Author match (any surname overlap after normalizing `Last, First` / `First Last`) | 0.25 |
| Year within ±2 (only if the book has a year) | 0.10 |
| Page count within ±15% (only if known) | 0.05 |

When a signal is unknown on your side, drop it and rescale the remaining weights to sum to 1. An **exact ISBN match** scores 1.0 regardless of the other signals.

**Decision rules (starting values; tune on your own books)**

| Situation | Result |
|---|---|
| ISBN match | Apply automatically |
| Score ≥ 0.90 and at least 0.10 ahead of the second candidate | Apply automatically |
| Score between 0.60 and 0.90, or too close to the second | Status `review`, keep the top 5 candidates |
| Below 0.60 or no results | Status `not_found` |

Create a small labelled test set (about 50 of your own books with the correct answers) and adjust the thresholds until automatic matches are almost never wrong. A wrong automatic match is worse than sending the book to review.

**Merging fields from two providers**

| Field | Preferred source | Notes |
|---|---|---|
| Title, authors | Best-scoring candidate | Store authors as `First Last`, separated by `; ` |
| Publisher | Open Library, then Google | |
| Year | Edition publish date when matched by ISBN; otherwise Open Library `first_publish_year` | The edition year and the original publication year can differ; you can edit it |
| ISBN | The ISBN used for the match, ISBN-13 preferred | |
| Pages | Google Books, then Open Library | Ignore 0 |
| Genre | Google Books `categories`, then Open Library `subjects` | See cleanup below |
| Language | Whichever provider has it, converted to a two-letter code | |
| Description | Google Books, then Open Library | Plain text only, strip HTML |
| Edition | Open Library edition name when present | Rarely available; usually manual |
| Cover | Open Library by ISBN, then Google | Only offered when the book's cover is a placeholder or you ask for it |

**Genre cleanup:** Open Library subjects contain library noise (`Accessible book`, `Protected DAISY`, `In library`, `Large type books`, `Lending library`, entries starting with `nyt:` or `overdrive`). Keep a blocklist, drop matches, and store at most 3 short genres, title-cased, comma-separated. For Google `categories` such as `Fiction / Science Fiction / General`, split on `/`, drop `General`, and keep the first two levels.

**Applying results (`merge.py`, single function used by both single and bulk lookups)**
```
for each field in candidate:
    if field is protected (source is 'manual', or mode is fill-only and value exists): skip
    if value is empty: skip
    set the field, record field_sources[field] = f"online:{provider}"
write one metadata_history row (before/after values of changed fields)
set online_source, online_id, lookup_status='applied', lookup_at=now
```
Modes: **Fill missing only** (default) and **Replace file-derived values** (still never touches `manual` fields). In the candidate chooser the user can override per field.

### 4.4 Job manager and background work (`jobs/manager.py`)
v3 has several long-running tasks: scan, quick-hash backfill, lookup, duplicate hashing and the folder watcher. Without coordination they will collide.

- `JobManager` owns a queue and a status-bar area showing the current job, its progress and a Cancel button.
- **Rules:** at most one *heavy* job (scan, lookup, hashing) at a time; the rest wait in a queue (for example a scan requested by the watcher while a lookup is running). The UI thread is never blocked.
- Every job runs in its own `QThread`/`QRunnable` with **its own database connection** (from `database.connect()`), short transactions (commit every 20 to 25 rows), and WAL mode.
- Every job supports `cancel()` and reports `progress(done, total, message)`, `finished(summary)`, and `error(message)`.
- Jobs that change data emit a `library_changed` signal (debounced, 300 ms); the model reloads once, not once per book.
- Undo stack rule from v2 still applies: clear it when a job changes the database in bulk.

### 4.5 Lookup worker and review queue

**Single book:** run in a small job, then open the candidate chooser (4.5.1). **Bulk job flow, per book:**
1. If there is no ISBN and the book is a PDF and the option "Scan PDFs for ISBN" is on, run the ISBN scan.
2. Query providers (ISBN first, then title/author if the ISBN gave nothing).
3. Score, decide (table in 4.3), apply or store candidates under `online_cache` key `cand:<book_id>` and set `lookup_status = 'review'`.
4. Update progress; respect pause and cancel between books.
5. At the end show a summary: applied N, review M, not found K, errors E, with buttons **Open review queue** and **Undo this run**.

**Which books a bulk run includes:** the selection, the current view, or "incomplete metadata" (books missing any of the fields you marked as required in Settings, or with a placeholder cover). Books with `lookup_status` of `applied` or `skipped` are skipped unless the user chooses **Include already checked**.

**Batch undo:** `undo_batch(batch_id)` restores each field from `before_json` **only if the current value still equals `after_json`** (so later manual edits are kept), updates `field_sources`, and resets `lookup_status`. Keep history rows for 30 days, then purge them at startup.

#### 4.5.1 Candidate chooser and review dialog (`ui/lookup_review.py`)
- **Left:** list of books to review (all with `lookup_status = 'review'`, or just the one book for a single lookup).
- **Middle:** up to five candidate cards (cover thumbnail loaded lazily, title, authors, publisher, year, ISBN, match score and how it matched).
- **Right/bottom:** comparison table `Field | Current | Candidate | ☑ Apply`, defaults follow the current mode; a source icon shows where the current value came from.
- **Buttons:** Apply, Skip (stays in queue), **Not this book** (marks `skipped`, never asked again), **Search manually** (edit title, author and ISBN, run again), and **Use cover** (separate checkbox).
- `Ctrl+Enter` applies and moves to the next book, so a queue of 100 can be cleared quickly.
- All applies go through the same `merge.apply` function and history table.

### 4.6 Tags
- Repository: `create_tag`, `rename_tag`, `merge_tags(source, target)`, `delete_tag`, `set_book_tags(book_ids, add, remove)`.
- Every tag change updates `books.tags_text` (space-separated tag names) **in the same transaction**, so the FTS triggers keep search in sync.
- Details pane: chip editor with autocomplete from existing tags; Enter or comma creates a chip; typing a new name creates the tag.
- Bulk: right-click **Tags ▸ Add…/Remove…** on a selection.
- Sidebar Tags section: list with counts; clicking sets `LibraryQuery.tag_ids`; ctrl-click selects several; an **Any / All** toggle changes the match mode.
- SQL for **All** mode:
  `id IN (SELECT book_id FROM book_tags WHERE tag_id IN (...) GROUP BY book_id HAVING COUNT(DISTINCT tag_id) = :n)`
- Tag names are trimmed, case-insensitive unique (`COLLATE NOCASE`); limit length to 40 characters.
- Undo/redo through `QUndoStack` commands.

### 4.7 Collections
- **Manual:** repository methods `create_collection`, `rename`, `delete`, `add_books`, `remove_books`. Query: `id IN (SELECT book_id FROM collection_books WHERE collection_id = ?)`.
- **Drag and drop:** the view starts a drag with a custom MIME type (`application/x-booklib-ids`, a JSON list of book ids); the sidebar collection items accept drops and call `add_books`. Highlight the target while hovering and show a status bar message afterwards.
- **Smart collections:** serialize the current `LibraryQuery` to JSON (sets become sorted lists) with a `"v": 1` field for forward compatibility. Loading a smart collection deserializes it into a `LibraryQuery` and ignores unknown keys. A **Save current view as smart collection…** action sits next to the filter chips.
- A collection view shows books normally, with search, filters and sort applied on top.
- Sidebar: collections are reorderable (updates `sort_order`); smart ones get a different icon.

### 4.8 Series
- **EPUB extractor additions:**
  - Calibre style: `<meta name="calibre:series" content="..."/>` and `calibre:series_index`.
  - EPUB 3 style: `<meta property="belongs-to-collection">` with `collection-type` = `series` and `group-position`.
- Repository: `get_or_create_series(name)`, `set_series(book_ids, name, index)`; empty series names clear the link. Series with no books are removed by a cleanup step at startup.
- Details pane: Series field (autocomplete) and Index field (decimal). When a series is set, show "Book N of *Series*" with **◀ ▶** buttons that select the neighboring books in that series.
- **Bulk assign:** select several books, choose **Set series…**, tick "number them in the current sort order" to fill indexes 1, 2, 3, … automatically (editable afterwards).
- **Sorting:** `ORDER BY series.name COLLATE NATURAL, series_index, title`; books without a series go last.
- Sidebar Series section with counts; clicking sets `LibraryQuery.series_id` and switches the sort to series order.

### 4.9 Duplicate detection (`duplicates/`)

```
duplicates/
├── hashing.py     # quick_hash, full_hash
├── finder.py      # builds duplicate groups
├── merge.py       # merges user data into the kept book
└── actions.py     # remove from library / recycle bin
```

**Hashing**
- `quick_hash` = SHA-256 of (file size + first 64 KB + last 64 KB). Computed during scans (the file is already open) and by the backfill job.
- `file_hash` = full SHA-256 with `hashlib.file_digest` (Python 3.11+), read in large chunks. Computed **only** for files that share `size_bytes` and `quick_hash` with another file, and stored so it is never recomputed unless size or mtime changes (the scanner sets both hashes to `NULL` on change).
- Runs as a cancellable job with progress; unreadable files are skipped and reported.

**Finding groups (`finder.py`)**
1. **Exact:** rows sharing the same `file_hash`.
2. **Same ISBN:** rows sharing a valid `isbn` but different hashes and not already in an exact group.
3. **Similar:** rows sharing a `title_key` + `author_key`, not already grouped.
   - `title_key`: lowercase, accents removed, punctuation removed, leading articles (`the`, `a`, `an`) and words like `edition`, `ed`, `revised`, `pdf` removed, whitespace collapsed.
   - `author_key`: surname of the first author, lowercased.
   - Optional later improvement: fuzzy matching, but only inside blocks (same `author_key` or same first three letters of `title_key`); comparing every book with every other is too slow.
- Each group gets a `group_key` = `<level>:<sorted book ids>`; groups present in `duplicate_ignores` are hidden.

**Duplicates dialog (`ui/duplicates_dialog.py`)**
- Left: list of groups with level, count and reclaimable size. Right: comparison table with one column per book.
- Row highlights show differences; a **Suggested keeper** is marked (prefer more complete metadata, then larger page count, then the format the user set as default for that type, then oldest).
- Actions per group:
  - **Keep both / Not a duplicate** (writes to `duplicate_ignores`).
  - **Remove selected from library** (database only, files stay).
  - **Send selected to Recycle Bin** (uses `send2trash`, so it is recoverable), only after a confirmation dialog that lists file paths and total size.
- **Merge user data** checkbox (on by default) applies these rules to the kept book:
  - Status: the most advanced (`read` > `reading` > `want` > none).
  - Rating: keeper's if set, otherwise the other's.
  - Notes: keep both, separated by a line if they differ.
  - Tags and collections: union.
  - Reading log: union of entries; progress: the larger.
- **Never automatic.** Nothing is removed or deleted without a click and a confirmation. Log every removal (path, hash, time) to `app.log`.

### 4.10 Watch folders and smarter rescan

**Watching (`watcher/folder_watcher.py`)**
- Use the `watchdog` library (recursive, uses the native Windows directory-change API). `QFileSystemWatcher` does not watch subfolders recursively and is limited on some systems.
- Watchdog runs in its own thread; it only **pushes events into a thread-safe queue** (never touches the database or UI). A `QTimer` in the UI thread drains the queue after **3 seconds of quiet** and hands the batch to the job manager.
- **Ignore:** hidden files, unsupported extensions, and temporary extensions (`.part`, `.crdownload`, `.tmp`, `.download`, names ending with `~`).
- **Wait for completion:** a new file is imported only when its size has not changed for 2 seconds **and** it can be opened for reading. Otherwise re-check later (up to a limit), so half-copied files are not read.
- Handle: created (import), modified (re-extract), deleted (mark missing), moved/renamed (see relinking).
- Fallback for folders where events are unreliable (network shares, some USB drives): a **periodic quick rescan** (setting, default every 15 minutes) instead of live watching.
- Show progress and results in the status bar ("3 new books added"). A watched folder that becomes unreachable is shown with a warning icon and its books are **not** marked missing.
- On startup, quick-rescan every watched folder to catch changes made while the app was closed.
- Optional per-folder setting **Fetch online metadata for new books** (`auto_lookup`), off by default and honoring the online-lookup master switch.

**Relinking moved or renamed files (scanner change, also used by the watcher)**
1. After the walk, take the list of **new** files and the list of **missing** rows.
2. For each new file, look for missing rows with the **same `size_bytes`**; compute the new file's `quick_hash` and compare with the row's `quick_hash`.
3. Exactly one match: **relink**, meaning update `path`, `filename`, `folder_id`, `file_mtime`, set `is_missing = 0`, and keep everything else (status, rating, notes, tags, collections, series, progress, covers).
4. Several matches (the same file existed twice): prefer the row with the same filename; otherwise treat the file as new.
5. No match: import as a new book.
This makes reorganizing your folders safe: your reading data follows the file.

### 4.11 Reading progress, dates and history

**Progress**
- Store `progress_page` (when `pages` is known) or `progress_percent`. The UI shows one control: a spin box `Page [ ] of Y` plus a slider, or a percent box when there is no page count. The other value is derived, never stored twice.
- Grid: a 3 px bar along the bottom edge of the cover (accent color) for books with progress. List view: a progress column (`42%` or `112 / 320`). Sorting by progress is available.
- When progress becomes greater than 0 and the status is unset or `want`, set status to `reading` (setting, on by default). When progress reaches 100%, ask "Mark as Read?" (never silent).

**Reading log state machine (`repository.set_status` extended)**

| New status | Log effect |
|---|---|
| Reading | If there is no open entry (`finished_on IS NULL`), insert one with `started_on = today` |
| Read | If there is an open entry, set `finished_on = today`; otherwise insert an entry with only `finished_on = today`. Clear progress |
| Want / unset | Leave the log unchanged (history is never deleted automatically) |

- **Read again** action (context menu and details pane): sets status to Reading, resets progress, and starts a new log entry while keeping the old ones.
- The details pane shows **Started** and **Finished** dates for the latest reading, plus a **History** list of all readings. Each row can be edited with two date pickers or deleted (with confirmation).
- All of this runs inside the same transaction and the same `QUndoCommand` as the status change, so **undo restores the log too**.
- A "did not finish" status is intentionally not added here; it can come with v5 statistics.

### 4.12 Custom covers (`covers/custom.py`)
- Entry points in the details pane cover menu and the context menu: **Replace cover ▸ From file… / From clipboard / From online… / From PDF page… / Restore original**, plus drag and drop of an image file onto the cover.
- **Processing:** validate it is a readable image (Pillow), reject files over 20 MB, warn if the width is under 150 px, convert to RGB, resize to 300 px wide keeping the ratio, save as JPEG (quality 85).
- **Storage:** custom covers go to `<app data>/covers/custom/<book_id>_<n>.jpg`, separate from the regenerable cache, so clearing the cache never deletes them. Increment `<n>` on every change so the pixmap cache key changes and the grid refreshes instantly.
- `cover_source` becomes `'custom'` (or `'online'` when chosen from a provider). The scanner and lookup only replace a cover when `cover_source` is `'file'` or `'placeholder'`.
- **From PDF page:** small dialog with a page spin box and a live preview (render at low scale); on OK render that page at full cover size.
- **Restore original:** set `cover_source = 'file'` (or `'placeholder'`), regenerate through the v1 pipeline, delete the custom file.
- No cropping tool in v3 (image is scaled to fit); a crop tool can be a later polish item.

### 4.13 Query, sidebar, details pane and settings

**`LibraryQuery` additions**
```python
tag_ids: set[int]          # plus tag_mode: 'any' | 'all'
collection_id: int | None
series_id: int | None
lookup_status: str | None  # 'review' powers the "Needs review" shelf
incomplete: bool = False   # missing any required field, or placeholder cover
```
New sort fields: `series` and `progress`. All values remain SQL parameters; column names come from a whitelist.

**Sidebar sections (top to bottom):** Library (All Books, Continue Reading, Recently Added) · Status · **Collections** (with a `+` button) · **Series** · **Tags** · **Tools** (Needs review, Incomplete metadata, Find duplicates). Long lists (series, tags) collapse to the top 20 with a filter box.

**Details pane:** a scrollable column of collapsible sections, whose open/closed state is remembered:
1. Overview: cover (with cover menu), title, author, status buttons, rating
2. Details: metadata fields with source icons, **Fetch online metadata**, Edit, description
3. Organize: tags, series, collections
4. Progress: progress control, dates, history
5. Notes
6. File: path, size, format, added, hashes (read-only), Show in folder, Open with

**Settings (new)**
- Online: master switch, provider on/off, optional Google Books API key, fill mode, auto-apply threshold, "Scan PDFs for ISBN".
- Required fields for "Incomplete metadata" (checkboxes).
- Watch: default debounce, polling interval, auto-lookup default.
- Progress: auto-mark Reading, ask to mark Read at 100%.
- Duplicates: show level 3 (similar), default action.

---

## 5. UI Layout (v3)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ [Add Folder][Rescan][Fetch Metadata ▾] 🔍 Search…   Sort:[Series▼][↑/↓] [▦|☰] [⚙] │
├──────────────┬───────────────────────────────────────────┬───────────────────────┤
│ LIBRARY      │ Filters: [#python ✕] [PDF ✕]  Clear  [Save as smart collection]     │
│ All Books    │───────────────────────────────────────────┤ ▾ Overview            │
│ Continue   3 │ ┌────┐ ┌────┐ ┌────┐ ┌────┐               │  ┌───────────┐        │
│ Recent    12 │ │cvr │ │cvr │ │cvr │ │cvr │  ▁▁▁ = progress│  │  cover ▾  │        │
│ STATUS       │ │    │ │    │ │    │ │    │     bar        │  └───────────┘        │
│ Want/Read/.. │ └▁▁▁─┘ └────┘ └────┘ └▁───┘               │  Title / Author       │
│ COLLECTIONS +│ Title  Title  Title  Title                 │  [Want|Reading|Read]  │
│ 📚 Exam prep │                                            │  ★★★★☆                │
│ ⚙ Unread PDF │                                            │ ▾ Details       🌐 ✎ 📄│
│ SERIES       │                                            │  Publisher · Year     │
│ Foundation 7 │                                            │  ISBN · Pages · Genre │
│ TAGS         │                                            │  [Fetch online] [Edit]│
│ #python   14 │                                            │ ▾ Organize            │
│ #networks  9 │                                            │  [#python][#dsa] +    │
│ TOOLS        │                                            │  Book 3 of Foundation │
│ Needs review │                                            │ ▸ Progress            │
│ Incomplete   │                                            │ ▸ Notes  ▸ File       │
│ Duplicates   │                                            │                       │
├──────────────┴───────────────────────────────────────────┴───────────────────────┤
│ 37 of 1,248 books        Lookup: 120 / 400  [██████░░░░]  Pause  Cancel           │
└──────────────────────────────────────────────────────────────────────────────────┘
```
Icons beside details fields: 🌐 online, ✎ edited by you, 📄 from the file.

---

## 6. Build Order (Milestones)

Finish and test each milestone before starting the next. Milestones 3 to 7 need no internet, so they give early wins and keep the risky online work for later.

| # | Milestone | What "done" looks like |
|---|---|---|
| 1 | **Migration 3** | Backup created; schema and conversions done; v2 data intact; tests pass on a copy of your real library |
| 2 | **Job manager and connection setup** | FK pragma and busy timeout on every connection; one-heavy-job rule; status bar shows job progress with cancel; quick-hash backfill runs |
| 3 | **Tags** | Create/edit/bulk tags, sidebar filter (any/all), included in search, undo works |
| 4 | **Series** | EPUB series import, manual assign, bulk numbering, series sorting and navigation |
| 5 | **Collections** | Manual collections with drag and drop; smart collections saved and reloaded |
| 6 | **Progress, dates and reading log** | Progress control and bars; status changes update the log; Read again; undo restores the log |
| 7 | **Custom covers** | All replacement sources work; original restorable; rescans keep custom covers; grid updates instantly |
| 8 | **Online providers** | Both providers parse recorded JSON fixtures; HTTP layer with retry, rate limit, cache; offline detection |
| 9 | **PDF ISBN scan and scoring** | ISBN found on real PDFs; scoring picks the right candidate on your labelled sample of about 50 books |
| 10 | **Single-book lookup UI** | Fetch button, candidate chooser, per-field apply, provenance icons, history rows written |
| 11 | **Bulk fetch and review queue** | Bulk job with pause/cancel/resume, auto-apply vs review vs not-found, review dialog, batch undo works after restart |
| 12 | **Duplicate engine** | Hash job and finder produce correct exact/ISBN/similar groups on a test folder |
| 13 | **Duplicates UI and actions** | Comparison view, merge user data, remove from library, recycle bin with confirmation, "Not a duplicate" |
| 14 | **Relinking in the scanner** | Rename or move files, rescan, all user data preserved |
| 15 | **Watch folders** | New files imported once fully copied; deletes and renames handled; polling fallback; startup quick rescan |
| 16 | **Sidebar, details pane and shelves** | Collapsible sections, Needs review and Incomplete shelves, settings pages complete |
| 17 | **Polish and testing** | Performance test with 20,000 books, error messages, logging, updated README |

---

## 7. Testing Plan

**Unit tests (`pytest`), no real network calls**
- **Migration 2 to 3:** `edited_fields` becomes `field_sources`; `status` becomes reading-log rows with dates; FTS includes tags; running twice is safe.
- **Provider parsers:** saved real JSON responses (including ones with missing fields, empty results and unexpected types) parse into `Candidate` objects without exceptions.
- **HTTP layer:** with a fake session, verify retries on 429/5xx, `Retry-After`, the rate limiter interval, cache hits, and the offline-detection stop.
- **ISBN:** regex and checksum on valid ISBN-10/13, invalid checksums, hyphens and spaces, multiple ISBNs on one page.
- **Scoring:** table of (local book, candidates, expected decision); the labelled sample must reach your target (automatic matches wrong at most rarely).
- **Merge rules:** manual fields are never overwritten; fill-only vs replace modes; genre cleanup blocklist; author normalization; provenance written correctly.
- **History undo:** batch undo restores fields, but leaves a field alone if the user edited it afterwards.
- **Tags:** CRUD, rename, merge, case-insensitive uniqueness, `tags_text` and FTS stay in sync, any/all SQL.
- **Collections:** membership, smart query round trip (including unknown keys ignored).
- **Series:** EPUB parsing (Calibre and EPUB 3 samples), indexes like `2.5`, sort order, bulk numbering.
- **Hashing and duplicates:** temp files with identical content under different names, same size but different content, same ISBN in PDF and EPUB, similar titles; groups and ignores are correct.
- **Merge user data:** status, rating, notes, tags, collections, log and progress rules.
- **Relinking:** rename and move files, rescan; status, rating, tags and covers preserved; ambiguous cases fall back to "new".
- **Watcher:** in a temp folder, create a file that keeps growing; it is imported only after it stabilizes; temporary extensions are ignored; a burst of 200 files produces one batch.
- **Reading log state machine:** every status transition, Read again, undo.
- **Covers:** each source produces a correct 300 px JPEG; custom covers survive a rescan and a cache clear; invalid images are rejected with a message.

**Manual test checklist**
- Run a lookup on 20 books with valid ISBNs, then on 20 PDFs with no metadata; inspect the results and the review queue.
- Turn Wi-Fi off during a bulk run; the job should stop with a clear message and no books marked "not found".
- Edit a title by hand, run a bulk lookup in replace mode; the edited title stays.
- Undo a bulk run, restart the app, undo another one.
- Tag 30 books, filter by two tags with Any and then All, search by a tag name.
- Drag books onto a collection; create a smart collection, close and reopen the app, check it still works.
- Assign a series, number books automatically, use previous/next navigation.
- Rename a folder of books and rescan; confirm status, rating and tags survived.
- Copy a large PDF into a watched folder; it should appear only after the copy completes.
- Run duplicate detection on a library where you know a few duplicates; verify each level; remove one to the Recycle Bin and restore it from there.
- Mark a book Read, then Read again; check the history list and dates; undo each step.
- Replace a cover from the clipboard and from a PDF page; rescan; the cover stays.
- Performance with 20,000 books: sidebar sections load quickly, filters and searches stay fast, bulk jobs do not freeze the window.

---

## 8. Known Pitfalls and How to Handle Them

| Problem | Handling |
|---|---|
| Wrong automatic matches corrupt your metadata | Conservative thresholds, review queue for uncertain cases, provenance icons, and batch undo based on `metadata_history` |
| API rate limits (429), outages, or timeouts | Per-provider rate limiter, backoff with `Retry-After`, caching (including "not found"), pause/resume, stop after repeated failures |
| Provider response format changes | Defensive parsing, fixture-based tests, all network code isolated behind `Provider` |
| Coverage is weaker for non-English or very old or niche books | Expect more `not_found`; manual edit and manual search remain available; do not treat "not found" as an error |
| Edition year vs original year confusion | Follow the rule in 4.3 and let the user edit; show the source icon |
| Privacy of lookups | Master switch, first-use notice, no cover or file content is uploaded (only ISBN/title/author queries) |
| Several workers writing to SQLite | Job manager, WAL, `busy_timeout`, one connection per thread, short transactions, batched `library_changed` signal |
| Foreign keys silently off, so cascades do not run | Set `PRAGMA foreign_keys = ON` in `database.connect()` and test it |
| Hashing a large library takes long | Group by size first, quick hash next, full hash only for collisions; cancellable job; results cached in the database |
| False duplicate positives (for example two different books with the same short title) | Three confidence levels, side-by-side comparison, "Not a duplicate", never automatic deletion, Recycle Bin instead of permanent delete |
| Deleting files by mistake | Confirmation listing paths and sizes, `send2trash`, logging |
| Watcher fires on half-copied files | Quiet period plus size-stable plus readable checks, temp-extension ignore list |
| Watching network or USB drives is unreliable | Polling fallback; unreachable folders show a warning and never mark books missing |
| Event bursts (copying 1,000 files) | Queue and batch after quiet period, one job per batch |
| Relink guesses wrong when the same file existed twice | Prefer same filename, otherwise import as new; never merge two live rows automatically |
| Series parsing misses or misreads metadata | Only trust explicit metadata fields; manual assignment and bulk numbering as fallback |
| Tag clutter (`Python`, `python`, `py`) | Case-insensitive names, rename and merge tools, autocomplete while typing |
| Custom cover images too large or broken | Size cap, Pillow validation, resize, clear error message |
| Stale grid thumbnails after cover changes | Versioned file names (`<id>_<n>.jpg`) so the pixmap cache key changes |
| Smart collections break when `LibraryQuery` gains fields later | Versioned JSON, ignore unknown keys, defaults for missing keys |
| Undo restores data that a job changed meanwhile | Clear the undo stack after bulk jobs; history-based batch undo compares current values first |

---

## 9. Definition of Done for v3

- [ ] Migration from v2 works on a copy of your real library with no data loss; a backup is created
- [ ] Single-book online lookup works by ISBN and by title/author, with a candidate chooser and per-field apply
- [ ] Bulk fetch runs with pause/cancel/resume, applies only high-confidence matches automatically, and sends the rest to a review queue
- [ ] Manually edited fields are never overwritten by lookups or rescans; every field shows its source
- [ ] Any bulk run can be undone, including after restarting the app
- [ ] PDFs without metadata can be matched through ISBN found in their text
- [ ] Tags: create, bulk edit, filter (any/all), search, rename and merge
- [ ] Collections: manual (with drag and drop) and smart collections work and persist
- [ ] Series: imported from EPUB where available, editable, sortable, with navigation and bulk numbering
- [ ] Duplicate finder reports exact, same-ISBN and similar groups; merging user data and removing (library only or Recycle Bin) works with confirmation; nothing is deleted automatically
- [ ] Renamed or moved files are relinked and keep status, rating, tags, notes and collections
- [ ] Watched folders import new books after they finish copying, and handle deletes and renames; polling fallback works
- [ ] Progress (pages or percent), start/finish dates and reading history work, with undo
- [ ] Covers can be replaced from file, clipboard, online, PDF page, and restored; rescans keep them
- [ ] Jobs never freeze the UI or cause "database is locked" errors; only one heavy job runs at a time
- [ ] Runs smoothly with 20,000 books
- [ ] Unit tests pass for migration, providers, scoring, merge, tags, collections, series, hashing, duplicates, relinking, watcher and reading log

---

## 10. What Comes Next (Preview of v4)

v3 prepares for Google Drive in several ways: the `source` and `drive_file_id` columns already exist, the job manager can run download and indexing jobs alongside everything else, `cover_source` and versioned cover files handle covers that come from Drive files, and the relink and duplicate logic can compare Drive and local copies of the same book (Google Drive reports an MD5 checksum for files, so consider adding an `md5` column at that point). Version 4 adds Google sign-in, Drive folder browsing and indexing, download-on-demand with a local cache, Drive/Local indicators, and optional database backup to Drive.

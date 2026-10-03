# Book Library App: Version 5 Plan (Library Maintenance and Convenience)

**Goal of v5:** Make the library easy to live with over years: keep file names tidy, convert books between formats, move data in and out, protect the library with backups, see how much you read and work toward yearly goals, and drive the app quickly with the keyboard and drag and drop.

**Prerequisite:** v4 is complete and its definition of done is met (especially `ensure_local`, the job manager lanes, the Drive backup code, `field_sources`, `reading_log`, and the duplicate finder).

**Out of scope for v5:**
- Removing DRM or converting DRM-protected books (the app will not attempt this)
- OCR for scanned books
- Renaming, moving or deleting Google Drive files (the app stays read-only towards Drive)
- Built-in reader, full-text search inside books, annotations, recommendations, phone/web access (v6)

---

## 1. Feature List

### 1.1 Rename and organize files (local books only)
- **Rename files** using a pattern built from metadata, default `{author} - {title}[ ({year})]`, for example `Leo Tolstoy - War and Peace (1869).epub`.
- Optional **folder pattern** to organize into subfolders, for example `{author:sort}/{series}` giving `Tolstoy, Leo/War and Peace Series/`. Files never leave their library folder.
- Works on a selection, the current view or the whole library.
- **Always preview first:** a table shows old name, new name and a status for every book (OK, unchanged, conflict, missing value, too long, skipped). Nothing changes until you press Apply.
- **Safe by design:** never overwrites an existing file, handles Windows-illegal characters and reserved names, stays inside the library folder, and skips files that are open in a reader.
- **Full undo:** every batch is journaled and can be undone later, even after restarting the app.
- Quick **Rename this file…** (`F2`) for a single book with an editable proposed name.
- Books whose title and author were only guessed from the file name are flagged, because renaming from a guess rarely helps.

### 1.2 Convert formats with Calibre
- **Convert to…** on a selection, using Calibre's `ebook-convert` tool (free, installed separately).
- Targets: EPUB, AZW3, MOBI (legacy), PDF, TXT, DOCX. Available conversions depend on the source format and your Calibre version.
- Title, author, publisher, ISBN, language, series, tags and cover are passed to Calibre so the new file carries correct metadata.
- The converted file is added to the library as its own book, **linked to the original** ("Converted from …"). Choose what carries over: tags, collections, series, rating. Status, progress and notes do not.
- Progress per book, Cancel, timeouts, and clear error messages (including "this book is DRM-protected").
- Drive books are downloaded first (v4 `ensure_local`); the result is saved to a local folder you choose.
- Honest quality warnings in the dialog: PDF to EPUB is a reflow of fixed pages and often needs checking; scanned PDFs cannot be converted usefully.

### 1.3 Export and import
- **Export** the whole library, the current view or a selection to **CSV** (opens in Excel/Sheets, Unicode-safe) or **JSON** (complete, including tags, collections, series, reading history, ratings and notes).
- Field picker with presets (Basic, All), and an option to include or leave out file paths.
- **Import** from BookLib JSON or CSV, or from any CSV through a column-mapping step, with a built-in **Goodreads** preset (read status, ratings, dates, shelves as tags, review as notes).
- Import **updates books already in your library**; it does not create books without files. Rows that do not match are listed in a report.
- **Preview before apply:** how each row matched, and exactly which fields will change. Fill-empty-only or overwrite. Every import can be undone.

### 1.4 Backup, restore and safety snapshots
- **Local backup** to a folder you choose (external drive, synced folder): database snapshot, custom covers, non-secret settings, and a manifest with checksums.
- The same backup package is used for the v4 Drive backup; both are pluggable destinations.
- Automatic backups (daily/weekly), keep the newest N, restore with verification and a safety copy of the current library.
- **Safety snapshots:** small automatic database snapshots taken before risky operations (bulk rename, import, bulk online metadata, restore, migration), so a mistake can always be rolled back.

### 1.5 Library health and maintenance
- **Library health** tool that checks and offers fixes for: database integrity, search index consistency, missing files, books whose cover file is missing, orphan cover and cache files, unused tags/series/empty collections, expired caches and old history, database size (with compact/optimize).
- Report can be saved as a text file.

### 1.6 Reading statistics and yearly goals
- **Statistics view** with:
  - Books finished per year and per month, pages read per year
  - Average rating, rating distribution, average days to finish, longest and shortest book
  - Top authors, genres, formats and tags
  - Library overview: total books, size, by source, share read, size of the want-to-read queue, books added per month
- Filter by year; **click a bar or item to show those books in the library**.
- **Yearly goals:** set a target in books, pages or both; progress bar, pace ("2 books ahead of schedule"), projected total, and a small progress indicator in the sidebar.
- **Fix dates** helper for books marked Read without a finish date, so old data is not lost from the statistics.
- Copy any chart as an image; export the statistics tables to CSV.

### 1.7 Keyboard shortcuts and command palette
- Every command is an action in one registry with a default shortcut.
- **Shortcuts settings page** to view, change, reset and detect conflicts.
- **Cheat sheet** (`Ctrl+/`) and a **command palette** (`Ctrl+K`): type to find and run any command.
- Full keyboard navigation through the grid, list, sidebar and dialogs.

### 1.8 Drag and drop and Add files
- Drop **files or folders** anywhere on the window to add them.
  - A folder: add as a library folder (with optional watching).
  - Files already inside a library folder: import them right away.
  - Files from elsewhere: **copied** into a chosen library folder (your default import folder), optionally renamed with your pattern, then added. The original stays where it is.
- **Add files…** (`Ctrl+O`) uses the same flow.
- Checks for books already in the library before copying (by size and quick hash) and asks what to do.
- Drag books **out** of the app to Explorer, e-mail or a chat window (local files and downloaded Drive files) to copy them.
- Extend v3 drag and drop: drop books onto a tag or a status in the sidebar to apply it.

### 1.9 Storage page and disk-space protection
- **Settings, Storage page:** one place that shows every area the app stores data in (downloaded books, covers, indexes, snapshots, backups, logs), its size, its limit and its policy, with **Preview cleanup**, **Clean now**, **Open folder**, and per-area controls.
- **Largest cached books** list with **Remove** and **Keep offline** buttons.
- **Temporary-file registry:** any temporary file the app creates outside its own folders (conversion output, rename temp names, copy temp names, export files being written, backup uploads) is recorded first and removed when the job ends. Leftovers from crashes are swept at startup.
- **Disk-space guard for v5 operations:** conversion, Add files, backup, restore, compact and export check free space before starting and refuse with a clear message instead of failing half-way.
- **Library health** gains storage checks (areas over their limit, leftover temp files, low free space, missing cache marker).
- **Retention** for v5 data: safety snapshots (newest 5 or 14 days), conversion log entries (180 days), backups (keep newest N).
- Command palette actions: **Clean up storage now**, **Open Storage settings**.

---

## 2. What Changes in the v1 to v4 Code

| Area | Change |
|---|---|
| Database | Migration 5 (section 3); `user_version` becomes 5 |
| Protected fields | `field_sources` gains a source kind `import:*`; it is protected from rescans and lookups exactly like `manual` |
| Job manager | New **convert lane** (default 1 concurrent Calibre process, configurable) and a **maintenance lane** (runs alone) |
| Undo | Rename batches and import batches have persistent undo (journal and history tables). The in-memory undo stack is cleared when they run, as for other bulk jobs |
| Duplicate finder | Ignores pairs linked by `converted_from` (they are intentional) and shows them as "related formats" |
| Backup code | Refactored into a `backup` package with pluggable destinations; the v4 Drive backup becomes one destination |
| Watch folders (v3) | Must ignore changes the app makes itself (renames, copies during import), using a short-lived "own changes" set |
| Actions | All actions move into one registry (`actions.py`); menus, toolbar, context menus and the command palette are built from it |
| Main window | New menu bar (File, Edit, View, Library, Tools, Help) and a second main view for Statistics |
| `LibraryQuery` | New filters: finished date range, `undated_read`, `has_conversions`; used by statistics drill-down |
| Settings | New pages: Shortcuts, Backup, Conversion, Import/Export defaults, Goals |
| Storage manager (v4) | Extended with v5 areas (safety snapshots, backups, temp registry) and a Storage page that shows all areas |
| Conversion, rename, Add files, export, backup code | Register temporary files, call the disk-space guard first, release temp registrations when done |
| Library health | New storage checks (section 4.9) |
| Job manager | Cleanup jobs must not run while a maintenance-lane job (rename apply, restore, compact, import) is active |

---

## 3. Database Changes (Migration 5)

Take a backup copy of the database file first (this is the last time you will do it by hand; from now on the safety snapshot in 4.4 does it automatically). Run everything in one transaction.

```sql
-- conversion link
ALTER TABLE books ADD COLUMN converted_from INTEGER REFERENCES books(id) ON DELETE SET NULL;
CREATE INDEX idx_books_converted_from ON books(converted_from);

CREATE TABLE conversion_log (
    id             INTEGER PRIMARY KEY,
    source_book_id INTEGER REFERENCES books(id) ON DELETE SET NULL,
    output_book_id INTEGER REFERENCES books(id) ON DELETE SET NULL,
    from_format    TEXT NOT NULL,
    to_format      TEXT NOT NULL,
    started_at     TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at    TEXT,
    status         TEXT NOT NULL,          -- 'running' | 'done' | 'failed' | 'cancelled'
    error_tail     TEXT                    -- last lines of Calibre output on failure
);

-- rename journal (write-ahead, enables crash recovery and undo)
CREATE TABLE rename_batches (
    id         TEXT PRIMARY KEY,           -- uuid
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    folder_pattern TEXT,
    file_pattern   TEXT NOT NULL,
    undone_at  TEXT
);
CREATE TABLE rename_log (
    id           INTEGER PRIMARY KEY,
    batch_id     TEXT NOT NULL REFERENCES rename_batches(id) ON DELETE CASCADE,
    book_id      INTEGER REFERENCES books(id) ON DELETE SET NULL,
    old_path     TEXT NOT NULL,
    new_path     TEXT NOT NULL,
    created_dirs TEXT,                     -- JSON list of directories this step created
    status       TEXT NOT NULL,            -- 'pending' | 'done' | 'failed' | 'undone'
    error        TEXT
);
CREATE INDEX idx_rename_log_batch ON rename_log(batch_id);

-- yearly goals
CREATE TABLE goals (
    id         INTEGER PRIMARY KEY,
    year       INTEGER NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('books','pages')),
    target     INTEGER NOT NULL CHECK (target > 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (year, kind)
);

-- statistics queries
CREATE INDEX idx_reading_log_finished ON reading_log(finished_on);
CREATE INDEX idx_reading_log_started  ON reading_log(started_on);

-- registry of temporary files created outside the app's own folders
CREATE TABLE temp_files (
    id         INTEGER PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,
    purpose    TEXT NOT NULL,          -- 'convert' | 'rename' | 'copy' | 'export' | 'backup'
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_temp_files_created ON temp_files(created_at);

PRAGMA user_version = 5;
```

**Notes**
- **Import undo** reuses the v3 `metadata_history` table. Its `before_json` / `after_json` columns are free-form, so extend the vocabulary they may contain beyond metadata fields: `status`, `rating`, `notes`, `tags` (list of names), and `reading_log` (list of entries added or changed). The undo code handles each key. Use `source = 'import:goodreads'`, `'import:booklib'` or `'import:csv'`.
- **Dates** in `reading_log` are stored as local ISO dates (`YYYY-MM-DD`) written from Python (`date.today()`). SQLite's `datetime('now')` is UTC, so never derive a reading date from it; near midnight it can be a day off.
- No existing rows change.

---

## 4. Implementation Details

### 4.1 Rename and organize (`organize/`)

```
organize/
├── template.py     # parses and renders patterns
├── sanitize.py     # file-system-safe names, length limits
├── planner.py      # builds the preview (old path, new path, status)
├── executor.py     # journaled apply, crash recovery
└── undo.py         # undo a batch
```

**Pattern language (`template.py`)**

| Syntax | Meaning | Example |
|---|---|---|
| `{title}`, `{author}`, `{year}`, `{series}`, `{series_index}`, `{isbn}`, `{publisher}`, `{genre}`, `{language}`, `{format}` | Insert a field | `{title}` |
| `{author:first}` | First author only | `Leo Tolstoy` |
| `{author:last}` | Surname of the first author | `Tolstoy` |
| `{author:sort}` | `Surname, First` form | `Tolstoy, Leo` |
| `{title:main}` | Title before the subtitle colon | `Clean Code` |
| `{title:60}` | Shorten to 60 characters at a word boundary | |
| `{series_index:02}` | Zero-padded number | `03` |
| `{genre:first}` | First genre | |
| `{field\|fallback}` | Use `fallback` text if the field is empty | `{author\|Unknown Author}` |
| `[ ... ]` | Optional group: the text inside appears only if **every** field inside is non-empty | `[ ({year})]` |
| `\[` `\{` | Literal bracket | |

- Folder pattern and file-name pattern are **separate fields**; only the folder pattern may contain `/`. A `/` inside a metadata value is replaced (with `-`), so metadata can never create folders by accident.
- A field that is empty and has no fallback and is not inside an optional group makes the row **Missing value**; such rows are skipped by default.
- Author formatting options (Settings): multiple authors joined with `, ` up to 2 then `et al.`, or first author only. Text case: keep as is (default) or Title Case (off by default; automatic case changes damage titles like `iOS`).
- Extension: kept from the original, normalized to lowercase.
- Provide presets: `{author} - {title}[ ({year})]`, `{title}[ - {author}]`, `{series}/{series_index:02} - {title}`, and let users save their own.

**Sanitizing (`sanitize.py`)**
- Replace `< > : " / \ | ? *` and control characters; strip leading/trailing spaces and trailing dots; collapse repeated spaces; normalize Unicode to NFC.
- Avoid Windows reserved names (`CON`, `PRN`, `AUX`, `NUL`, `COM1` to `COM9`, `LPT1` to `LPT9`), with or without an extension, by appending an underscore.
- Length: each component at most about 120 characters; whole path at most about 240 characters (configurable). If too long, shorten `title` first (at a word boundary), then `author`; if still too long the row is flagged **Too long**.

**Planner (`planner.py`)** builds one row per selected local book:
1. Skip non-local books (`source != 'local'`), missing books and books in unreachable folders, with a clear reason.
2. Flag books whose `title` and `author` both have `field_sources = file:filename` (guessed); they are unchecked by default with a warning.
3. Render the patterns and sanitize.
4. Resolve the target directory inside the book's library folder and **verify containment**: after resolving `..` and symlinks the target must still be inside the library root, otherwise the row is **Blocked**.
5. Detect conflicts:
   - target already exists and is another file: **Conflict**; policy option: skip (default) or append ` (2)`, ` (3)`.
   - two books in the same batch map to the same target: disambiguate the later ones with ` (2)`, or ISBN/format if the setting allows.
   - unchanged name: **Unchanged**.
   - case-only change on Windows (`book.pdf` to `Book.pdf`): allowed but executed in two steps (below).
6. Record the file's size and modified time in the row so the executor can detect changes made after the preview.

**Preview dialog (`ui/rename_preview.py`)**
```
┌──────────────────── Rename files ─────────────────────────────────┐
│ Folder pattern: [{author:sort}          ▾]  File: [{author} - {title}[ ({year})] ▾] │
│ [ ] Also organize into folders   [ ] Remove empty folders left behind │
├────┬──────────────────────────────┬──────────────────────────┬─────────┤
│ ☑  │ Current                      │ New                      │ Status  │
├────┼──────────────────────────────┼──────────────────────────┼─────────┤
│ ☑  │ war_and_peace_final.epub     │ Leo Tolstoy - War and…   │ OK      │
│ ☐  │ dsa.pdf                      │ (guessed title)          │ ⚠ guess │
│ ☐  │ book1.pdf                    │ —                        │ Missing │
│ ☑  │ Clean Code.pdf               │ Robert Martin - Clean…   │ OK      │
├────┴──────────────────────────────┴──────────────────────────┴─────────┤
│ 412 selected · 3 conflicts · 9 skipped     [Select only OK] [Cancel] [Apply] │
└────────────────────────────────────────────────────────────────────────┘
```
- Filter by status, sort by any column, edit a proposed name by double-clicking a cell (validated live).
- The preview is regenerated when the pattern changes (debounced); large batches build in a background job.

**Executor (`executor.py`)**: runs as a **maintenance-lane job**.
1. Take a **safety snapshot** of the database (4.4) if the batch has more than 50 books.
2. Create the `rename_batches` row and one `rename_log` row per book with `status='pending'`, committed **before** touching any file (write-ahead journal).
3. For each row, in order:
   - Re-check that the source still exists and its size and modified time still match the preview; otherwise mark `failed: changed since preview`.
   - Create missing directories with `mkdir(parents=True, exist_ok=True)`, recording each directory that did not exist before in `created_dirs`.
   - **Never overwrite**: if the target now exists, mark `failed: target exists`. Use `os.rename` (not `os.replace`), which fails on an existing target on Windows; on other systems check existence first.
   - Case-only rename: rename to a temporary name (`.<uuid>.tmp`) then to the final name.
   - On `PermissionError` (file open in a reader): mark `failed: in use`, continue with the next book.
   - After a successful rename, update the book row (`path`, `filename`) in a short transaction and mark the log row `done`. If the database update fails, rename the file back and mark `failed`.
4. Register both old and new paths in the **own-changes set** (30-second TTL) so the v3 watcher ignores these events.
5. Optionally remove now-empty folders left behind: only folders emptied by this batch, only inside the library root, using `os.rmdir` (which refuses non-empty folders), never the root itself.
6. Emit progress and a summary (renamed, failed with reasons, skipped) with buttons **Undo this batch** and **Save report**.
- Register the temporary name used for case-only renames with `register_temp`, and release it after the final rename. Before creating the safety snapshot for large batches, call the disk-space guard (section 4.9).

**Crash recovery:** at startup, look for `rename_log` rows still `pending`. If the new path exists and the old one does not, finish the database update and mark `done`; if the old path exists, mark `failed`. Show a notice if anything was recovered.

**Undo (`undo.py`)**: for a batch, process `done` rows in reverse order: if the file at `new_path` exists and the `old_path` is free, rename it back and update the book row; otherwise skip and report. Then remove directories listed in `created_dirs` if they are now empty. Mark rows `undone` and set `undone_at`. Keep batches for 90 days, then purge at startup.

### 4.2 Conversion with Calibre (`convert/`)

```
convert/
├── calibre.py     # detection, version check
├── planner.py     # which conversions are offered, warnings
├── runner.py      # builds the command, runs it, parses progress
└── job.py         # per-book flow, adding the result to the library
```

**Detection (`calibre.py`)**
- Search order: path set in Settings, `shutil.which("ebook-convert")`, standard install locations (for example `C:\Program Files\Calibre2\ebook-convert.exe`, and the macOS app bundle path).
- Verify by running `ebook-convert --version` (short timeout) and display the version in Settings with a **Test** button.
- If not found, the Convert action opens a helper dialog: what Calibre is, a link to its website, and a field to set the path manually. Calibre is a separate program under its own licence; the app only runs its command-line tool.

**What is offered (`planner.py`)**

| From | To | Expectation shown in the dialog |
|---|---|---|
| EPUB | AZW3, MOBI, PDF, TXT, DOCX | Good; PDF layout depends on Calibre's page options |
| MOBI, AZW3 | EPUB and others | Good for books without DRM |
| DOCX, TXT | EPUB, PDF | Good |
| PDF | EPUB, AZW3, TXT, DOCX | **Varies:** columns, tables, code, maths and scanned pages often come out badly |
| Any | PDF | Fixed layout output, not reflowable |
| Scanned PDF (no text layer) | Any | Not useful; the app warns and skips by default |

- The available list depends on your Calibre version; allow any extension in an "Advanced" field and let Calibre report failure.
- Show a **DRM note**: DRM-protected books will fail, and the app does not remove DRM.
- Warn about EPUB/MOBI legacy differences only in one short line; do not lecture.

**Convert dialog options**
- Target format (with presets: "EPUB for most e-readers", "AZW3 for Kindle", "PDF for fixed layout").
- **Destination:** next to the original (default for local books), a `Converted` subfolder, or a chosen folder. Drive books must use a chosen local folder (remembered; if it is not a library folder, offer to add it).
- **File name:** same base name as the original, or the rename pattern from 4.1.
- If the output already exists: skip (default) or append ` (2)`.
- **Add to library** (default on) and what to carry over: tags, collections, series, rating (status, progress and notes never).
- **Advanced:** extra Calibre options as text, split with `shlex.split` and passed as list items (never through a shell).

**Command (`runner.py`)**
```python
cmd = [ebook_convert, src_path, tmp_out_path,
       "--title", title, "--authors", authors,           # only the fields that have values
       "--publisher", publisher, "--isbn", isbn, "--language", lang,
       "--series", series, "--series-index", idx, "--tags", tags,
       "--cover", cover_file] + extra_args
```
- Only add a flag when the field is non-empty. `--cover` uses the book's current cover image file when it is a real cover (not a placeholder).
- The temporary output name must end with the real extension because Calibre picks the format from it, for example `Name.tmp-<uuid>.epub`. After success rename atomically to the final name; on failure delete it.
- Run with `subprocess.Popen(..., stdout=PIPE, stderr=STDOUT)`, read lines, and parse progress with `r"(\d{1,3})%"`. Keep the last 40 lines for `conversion_log.error_tail`.
- **Cancel:** terminate the process and its child processes (on Windows use a new process group and `taskkill /T /F`, or `psutil` to kill children); remove the temp file.
- **Timeout** per book (default 10 minutes, configurable).
- Map failures to friendly messages: output containing `DRM` becomes "This book is DRM-protected"; unsupported input format; input file unreadable; disk full; timeout.

**Job flow (`job.py`, convert lane, default 1 at a time)**
1. `ensure_local(book)` (downloads Drive books).
2. Insert `conversion_log` row (`running`).
3. Run Calibre; on success rename the output and import it: create a `books` row through the normal scan pipeline for that single file, set `converted_from = source_book_id`, copy the selected user data (tags, collections, series, rating), keep the source's metadata provenance as `file` since Calibre embedded it.
4. Update the log (`done` or `failed` with the error tail).
5. Summary dialog: converted, failed (with reasons and **Show details**), skipped; buttons to open a result or show it in the library.

**Integration**
- Details pane shows **Converted from "…"** with a link, and **Converted versions: EPUB, AZW3** with links.
- v3 duplicate finder: exclude pairs where either book's `converted_from` points to the other or both point to the same source; list them separately as "Related formats (kept on purpose)".
- Deleting or missing source books never removes converted ones (`ON DELETE SET NULL`).
- Register the temporary output name with `register_temp` before starting Calibre and release it after the atomic rename or on failure or cancel. Call the disk-space guard (source size x 2, destination drive) before starting each conversion. If the guard refuses, report it as a skipped conversion with the reason.

### 4.3 Export and import (`porting/`)

```
porting/
├── export_csv.py
├── export_json.py
├── import_reader.py    # detect type, decode, parse
├── mapping.py          # column mapping and presets (Goodreads, BookLib)
├── matcher.py          # matches rows to books
└── apply.py            # applies changes, writes history for undo
```

**Export options:** scope (all / current view / selection), fields (presets Basic, All, or custom), include file paths (default on for JSON backups, off for CSV meant for sharing), CSV protection for spreadsheets (default on).

**CSV rules**
- UTF-8 **with BOM** so Excel on Windows reads Hindi and other Unicode text correctly; comma delimiter; RFC 4180 quoting (notes containing commas, quotes and newlines are quoted).
- Multi-value fields (tags, collections, genres, authors) joined with `; `.
- Dates as ISO `YYYY-MM-DD`; booleans as `0`/`1`; numbers without thousands separators.
- **Spreadsheet formula protection:** a text cell starting with `=`, `+`, `-`, `@`, tab or carriage return is prefixed with a single quote when the option is on, because spreadsheets can execute such cells as formulas. The importer removes that prefix again for BookLib CSV files.
- Columns for CSV (Basic): title, author, publisher, year, edition, isbn, pages, genre, language, format, size_bytes, status, rating, tags, series, series_index, date_added. All adds: notes, collections, started/finished dates, progress, source, drive_path, md5, description, file_path, lookup status.

**JSON format (`export_json.py`)**
```json
{
  "format": "booklib-export", "version": 1,
  "exported_at": "2026-10-04T18:20:00", "app_version": "5.0", "schema_version": 5,
  "books": [{
    "key": {"isbn": "9780132350884", "md5": "…", "drive_file_id": null,
            "path": "D:/Books/Clean Code.pdf", "size_bytes": 4412345},
    "title": "…", "author": "…", "publisher": "…", "year": 2008, "pages": 464,
    "status": "read", "rating": 5, "notes": "…", "tags": ["dsa","python"],
    "series": {"name": null, "index": null},
    "collections": ["Exam prep"],
    "reading_log": [{"started_on": "2026-03-01", "finished_on": "2026-04-12"}],
    "field_sources": {"title": "manual"}
  }],
  "collections": [{"name": "Exam prep", "kind": "manual"},
                  {"name": "Unread PDFs", "kind": "smart", "smart_query": {"v": 1}}]
}
```
- Written with a streaming writer for large libraries. Never includes tokens, credentials or the Google client file.
- Include a `version` so future importers can read older files.
- Write exports to a registered temporary name and rename on success. Check free space on the destination first.

**Import flow (`ui/import_wizard.py`)**
1. **Choose file.** Detect type from the extension and content (BookLib JSON, BookLib CSV, Goodreads CSV by its header signature, otherwise generic CSV). Reject files over about 50 MB with a clear message.
2. **Decode and parse.** Try UTF-8 with BOM, UTF-8, UTF-16, then Windows-1252 as a last resort; report the row number for parse errors. Treat every cell as data, never as a formula.
3. **Map columns** (generic CSV only): pick which column is title, author, ISBN, status, rating, tags, notes, and so on; mapping presets can be saved. The Goodreads preset maps:

| Goodreads column | Becomes |
|---|---|
| Title, Author, Publisher, Number of Pages, Year Published | Metadata fields (fill empty) |
| ISBN, ISBN13 | ISBN (strip the `="…"` wrapper Goodreads uses; validate the checksum) |
| Exclusive Shelf: `to-read` / `currently-reading` / `read` | Status: Want / Reading / Read |
| My Rating (0 means unrated) | Rating |
| Date Read | `reading_log.finished_on` |
| Bookshelves | Tags (optional checkbox) |
| My Review | Notes (appended with a `Goodreads review:` prefix, optional checkbox) |

4. **Match and preview (`matcher.py`)**, each row is matched to existing books in this order:
   - `drive_file_id`, then `md5` or `file_hash`, then a valid unique `isbn`, then `title_key` + `author_key` (the v3 normalizers), then relative file path.
   - Several books with the same ISBN (for example PDF and EPUB): apply to all of them (option, default on), because ratings and status belong to the work.
   - Ambiguous title/author matches are **skipped by default** and listed; a **Pick book…** button lets you choose one manually.
   - Rows with no match are listed in a report (**Save unmatched rows as CSV**). No new books are created.
5. **Options:** which fields to import (checkboxes), **Fill empty only** (default) or **Overwrite**, treatment of status/rating/dates.
6. **Apply (maintenance lane):**
   - Safety snapshot first.
   - For each matched book, write only changed fields; set `field_sources[field] = "import:<kind>"` (protected like `manual`).
   - Save a `metadata_history` row with before/after values, including the extended keys (status, rating, notes, tags, reading log entries).
   - Reading status uses the v3 state machine so the log stays consistent; imported dates are written directly.
7. **Summary and undo:** rows matched, books changed, fields changed, unmatched, errors; **Undo this import** restores the recorded values, and only fields whose current value still equals the imported value (later edits are kept).

**Moving a library to a new computer** is done with backup and restore (4.4), not with JSON import, because import only updates books that are already present.

### 4.4 Backup, restore and safety snapshots (`backup/`)

```
backup/
├── snapshot.py       # consistent database snapshot + integrity check
├── package.py        # build and verify the backup zip
├── destinations.py   # LocalFolder, GoogleDrive (from v4)
├── scheduler.py      # automatic backups, retention
├── safety.py         # pre-operation snapshots
└── restore.py        # verification, safety copy, staged swap
```

**Destination interface**
```python
class BackupDestination(Protocol):
    name: str
    def upload(self, zip_path: Path, on_progress) -> str: ...      # returns an id
    def list(self) -> list[BackupInfo]: ...
    def download(self, backup_id: str, target: Path, on_progress) -> None: ...
    def delete(self, backup_id: str) -> None: ...                 # for pruning
```
Move the v4 Drive backup code behind `GoogleDriveDestination` and add `LocalFolderDestination` (a plain folder; files named `booklib-backup-YYYYMMDD-HHMMSS-<computer>.zip`).

**Package contents (`package.py`)**
- `library.db`: snapshot taken with SQLite's online backup API (`Connection.backup()`), **never** by copying the live file (a WAL-mode file copy can be inconsistent), then `PRAGMA integrity_check`.
- `covers/custom/`: custom covers only (generated covers can be rebuilt).
- `settings.json`: non-secret settings (theme, shortcuts, view options, patterns). **No tokens, no Google client file.**
- `manifest.json`: app version, schema version, timestamp, computer name, book count, and the **SHA-256 of every entry**.
- Excluded: caches (covers cache, Drive cache, online cache), logs, temporary files.

**Automatic backups (`scheduler.py`)**
- Settings: destination, frequency (daily / weekly / off), keep newest N (default 10).
- Runs shortly after startup (not at exit, so quitting is never delayed), only if data changed since the last backup (`dirty` flag) and the interval has passed. Progress in the status bar; failures produce a quiet notification, never a modal.
- Retention: after a successful upload delete the oldest beyond N (never delete the only backup, and never delete if the upload failed).

**Safety snapshots (`safety.py`)**
- Small database-only snapshots in `<app data>/safety/`, taken automatically before: schema migrations, rename batches over 50 books, imports, bulk online metadata runs, and restores.
- Keep the newest 5 (or 14 days). **Tools, Library health, Restore a safety snapshot** lists them.

**Restore (`restore.py`)** (shared by all destinations)
1. Choose a backup (list shows date, computer name, book count from the manifest).
2. Download and verify: zip integrity, manifest present, every entry's SHA-256, `PRAGMA integrity_check` on the database, and **schema version not newer than this app** (older ones are migrated forward after restore).
3. Create a safety snapshot of the current library and show where it is.
4. Stage the restored files, ask to restart, and swap the files in on the next start before the database opens.
5. After restore: unreachable local folders show a warning (books are not marked missing) and the **Relocate folder…** tool from v4 is offered; Drive folders work after **Sync now**.
6. Restore replaces the library; it is not a merge.
- Safety snapshots and backups follow the retention table in section 4.9. Call the guard before a snapshot, a backup or a restore. Register the temporary upload name for local-folder backups.

### 4.5 Library health and maintenance (`maintenance/`)
Runs as a **maintenance-lane job** (alone; no other heavy job while it runs). Each check reports a count and offers a fix button:

| Check | How | Fix |
|---|---|---|
| Database integrity | `PRAGMA integrity_check`, `PRAGMA foreign_key_check` | Offer restore from a backup or safety snapshot (never auto-repair) |
| Search index | FTS5 `integrity-check` command and row-count comparison | Rebuild the index |
| Missing local files | `is_missing = 1` count | Remove missing, or Relocate folder |
| Missing cover files | Cover path set but file absent | Regenerate covers |
| Orphan cover / cache files | Files with no row | Delete orphans |
| Drive cache consistency | v4 consistency routine | Run it |
| Unused tags, empty series, empty collections | Rows with zero books | Review list, then delete selected |
| Old history and caches | `metadata_history` over 30 days, expired `online_cache`, old rename batches | Purge |
| Database size | File size, free pages | **Compact** (`VACUUM`, needs free disk space of about the database size), `wal_checkpoint(TRUNCATE)`, `PRAGMA optimize` |

Results can be saved as a text report. Nothing is deleted without a confirmation listing what will go.
- Add the four storage checks from section 4.9. Compact (`VACUUM`) calls the guard first.

### 4.6 Statistics and goals (`stats/`)

```
stats/
├── queries.py     # pure SQL functions returning small dataclasses
├── goals.py       # goal progress, pace and projection
└── ui/
    ├── stats_view.py
    ├── charts.py    # BarChart / HBarList widgets
    └── fix_dates_dialog.py
```

**Definitions**
- A book is **finished in year Y** when a `reading_log` row has `finished_on` in year Y. With the "count re-reads" setting on (default), each reading counts.
- **Pages read in Y**: sum of `books.pages` of those readings. Books with no page count are excluded from page totals and the view says how many ("12 finished books have no page count").
- **Days to finish**: `julianday(finished_on) - julianday(started_on)` for readings with both dates and a non-negative result.
- **Undated reads**: books with status `read` and no dated log entry. They are excluded from time-based charts and counted in a note with a **Fix dates…** link.

**Example queries**
```sql
-- books and pages finished per year
SELECT substr(r.finished_on,1,4) AS year, COUNT(*) AS books, SUM(b.pages) AS pages
FROM reading_log r JOIN books b ON b.id = r.book_id
WHERE r.finished_on IS NOT NULL
GROUP BY year ORDER BY year;

-- per month in a given year
SELECT substr(r.finished_on,6,2) AS month, COUNT(*) AS books
FROM reading_log r
WHERE substr(r.finished_on,1,4) = :year
GROUP BY month ORDER BY month;

-- average days to finish
SELECT AVG(julianday(finished_on) - julianday(started_on))
FROM reading_log
WHERE started_on IS NOT NULL AND finished_on IS NOT NULL
  AND julianday(finished_on) >= julianday(started_on);
```
Genres are stored comma-separated, so split them in Python for the genre chart.

**Statistics view (`ui/stats_view.py`)**: a second main-window mode next to the library (`F6` toggles).
```
┌──────────────────────── Statistics ─────────────────────────────────────┐
│ Year: [2026 ▾] [All time]           Goal 2026: ▓▓▓▓▓▓░░░░ 14 / 24 books │
│                                     2 books ahead of pace · on track for 27│
├───────────────┬───────────────┬───────────────┬─────────────────────────┤
│ Finished  14  │ Pages 4,120   │ Avg ★ 4.1     │ Avg 19 days to finish   │
├───────────────┴───────────────┴───────────────┴─────────────────────────┤
│ Books finished per month        ▂ ▅ ▃ ▇ ▂ ▁ ▅ ▃ ▁ . . .                  │
│                                 J F M A M J J A S O N D                  │
├──────────────────────────────────┬──────────────────────────────────────┤
│ Top authors     ▇▇▇▇▇▇ Martin 4  │ Genres   ▇▇▇▇▇▇ Programming 9        │
│                 ▇▇▇▇ Tolstoy 3   │          ▇▇▇▇ Fiction 5              │
├──────────────────────────────────┴──────────────────────────────────────┤
│ Library: 1,248 books · 6.2 GB · 19% read · 24 want to read              │
│ ⓘ 3 books marked Read have no finish date [Fix dates…]                  │
└─────────────────────────────────────────────────────────────────────────┘
```
- Click a bar, an author or a genre: switch to the library view with the matching `LibraryQuery` (new finished-date range and existing filters).
- **Charts:** draw simple bar and horizontal-bar charts yourself with `QPainter` in a small `BarChart` widget (palette-aware so it works in dark mode, hover tooltips, click signal). Qt Charts (`PySide6.QtCharts`) is an option, but it has different licence terms from the core PySide6 modules, so check them if you ever plan to distribute the app.
- **Copy as image:** `widget.grab()` to the clipboard or a PNG file. **Export tables to CSV.**
- Compute on demand with SQL (fast at 20,000 books); no cache table needed.

**Goals (`goals.py`)**
- Set a goal for a year in books, pages or both; edit or delete; allow current, next and past years.
- Progress = count (or pages) finished in that year.
- **Pace:** `expected = target * day_of_year / days_in_year`; `difference = done - expected` (rounded, shown as "ahead" or "behind" by N books, or "on pace"); **projection** = `done / day_of_year * days_in_year`. Use the real number of days in the year (leap years) and the local date.
- When a goal is reached show a quiet message in the status bar.
- Sidebar mini progress line ("2026: 14 / 24 books") under the Status section, optional in Settings.
- **Fix dates dialog:** lists Read books without a finish date, with editable date cells and bulk actions: set all to a chosen date, use `date_added`, use the date of the last status change (`status_changed_at`), or leave undated.

### 4.7 Shortcuts and command palette (`actions.py`, `ui/shortcuts_page.py`, `ui/command_palette.py`)

**Action registry**
```python
@dataclass
class ActionDef:
    id: str                 # 'library.rescan'
    text: str               # 'Rescan folders'
    default_shortcut: str   # 'F5'
    handler: Callable
    enabled_when: Callable | None
    menu: str               # 'Library'
    icon: str | None
    context: str            # 'window' | 'library_view' | 'details'
```
Build `QAction`s from the registry once; menus, toolbar, context menus and the palette all use those same actions, so a shortcut change applies everywhere.

**Suggested defaults** (adjust to taste; they are stored in `QSettings` as JSON and editable in Settings):

| Action | Shortcut |
|---|---|
| Add files… | `Ctrl+O` |
| Add folder… | `Ctrl+Shift+O` |
| Rescan | `F5` |
| Sync Google Drive | `Ctrl+F5` |
| Focus search | `Ctrl+F` |
| Clear search and filters | `Esc` (in search box) |
| Open book | `Enter` |
| Open with menu | `Shift+Enter` |
| Edit metadata | `Ctrl+E` |
| Fetch online metadata | `Ctrl+I` |
| Rename file | `F2` |
| Status: Want / Reading / Read / clear | `Ctrl+1` / `Ctrl+2` / `Ctrl+3` / `Ctrl+0` |
| Rating 1 to 5 / clear | `Alt+1` to `Alt+5` / `Alt+0` |
| Add tag | `Ctrl+T` |
| Grid / list view | `Ctrl+G` |
| Toggle sidebar / details pane | `Ctrl+B` / `F4` |
| Statistics view | `F6` |
| Select all | `Ctrl+A` |
| Undo / redo | `Ctrl+Z` / `Ctrl+Y` |
| Command palette | `Ctrl+K` |
| Shortcut cheat sheet | `Ctrl+/` |
| Settings | `Ctrl+,` |

**Rules**
- **Text fields keep their own shortcuts:** when a text editor (notes, search box, edit dialog) has focus, `Ctrl+Z`, `Ctrl+A` and `Ctrl+C` must act on the text, not on the library. Use widget-scoped or application-scoped shortcuts deliberately and test it.
- **Shortcuts page:** table of actions with a `QKeySequenceEdit`; conflict detection (warn and offer to swap); **Reset to default** per action and for all.
- **Cheat sheet:** read-only list generated from the registry, grouped by menu, with a search box.
- **Command palette:** a small frameless dialog with a search box; fuzzy-match on action text (and menu name); Enter runs the selected action; shows each action's shortcut; disabled actions are hidden. Remember the most recently used actions and show them first.
- **Keyboard navigation:** arrow keys, `Home`/`End`, `PageUp`/`PageDown` in the grid and list; `Tab` order through sidebar, search, view, details pane; every dialog operable without a mouse; visible focus indicators.
- **Accessibility basics:** accessible names on custom widgets (star rating, chips, badges), badge colors with sufficient contrast in both themes, status not conveyed by color alone (badges also have an icon or text in tooltips).

### 4.8 Drag and drop and Add files (`ui/dnd.py`, `importing/add_files.py`)

**Accepting drops** on the main window: `dragEnterEvent` accepts URLs that are local files or folders; `dropEvent` collects paths.
- **Filter:** supported extensions only; ignore hidden and system files; warn if more than 500 files are dropped.
- **Folder dropped:** dialog "Add this folder to the library?" with options include subfolders, watch for changes; then the normal v1 scan.
- **File dropped that is inside an existing library folder:** import just those files (targeted scan) and select them.
- **File dropped from elsewhere:** the **Add files** flow below.
- Dropping Drive URLs or web links is not supported; the drop overlay says so clearly.

**Add files flow (also used by `Ctrl+O`)**
1. Choose the **destination library folder**: default from Settings (**Default import folder**), or pick another; if there are no library folders yet, offer to create one.
2. **Duplicate check before copying:** compare size and quick hash (v3) with existing books; for each hit ask **Skip / Add anyway / Replace metadata only**, with an "apply to all" checkbox.
3. **Naming:** keep original names, or apply the rename pattern from 4.1 (uses the file's own metadata after extraction; if metadata is missing, keep the original name). Optional folder pattern.
4. **Copy** (not move) with progress in the I/O lane: copy to a temporary name then rename; never overwrite (append ` (2)` on conflict); verify size after copy.
5. Register the new paths in the own-changes set so the watcher does not import them twice, then import through the normal scan pipeline (metadata, cover), optionally start an online lookup if the folder's auto-lookup setting is on.
6. Summary: added, skipped as duplicates, failed.

**Dragging out:** the grid and list start a `QDrag` with `QMimeData.setUrls([...])` for the selected local books and for downloaded Drive books; Drive books not yet downloaded are skipped with a message (download first). Copying happens in the target application.

**Extra drop targets in the sidebar:** tags (apply the tag), status entries (set the status), collections (v3). Highlight the target under the cursor, apply as one undoable command.
- Register the temporary copy name with `register_temp`; call the guard for the total size of the files before copying; if there is not enough space, tell the user how much is needed.

### 4.9 Storage page, temp-file registry and disk-space protection

This section extends the storage manager from the v4 plan (section 6.15). Areas, protection rules, the planner and executor, and the guard are reused unchanged.

**Temp-file registry (`storage/tempfiles.py`)**
- `register_temp(path, purpose)` inserts a row **before** the file is created. `release_temp(path)` removes the row after the file has been renamed to its final name or deleted.
- Use it for every temporary file that lives **outside** the app's own folders:
  - conversion output (`Name.tmp-<uuid>.epub`),
  - the temporary name in a case-only rename (`.<uuid>.tmp`),
  - the temporary name while copying files in (Add files),
  - export files being written,
  - the temporary name of a local backup upload.
- Files inside the app's data folder (cache `.part` files, staging for restore) are covered by the area sweeps instead.
- **Sweeping:** at startup nothing is running, so **every** registered path that still exists is deleted (after the `safe_delete` checks below) and its row removed. While the app runs, entries older than one day are removed by the daily cleanup.
- Safety: a path is deleted only if it is in the registry **and** its file name matches the temporary naming pattern of its purpose. Registry rows alone never authorize deleting a normal file.

**Disk-space guard integration**

| Operation | Space required (estimate) | Drive checked |
|---|---|---|
| Convert a book | source size x 2 (temporary plus final file) | Destination folder's drive |
| Add files (copy in) | Sum of the file sizes | Destination library folder's drive |
| Local backup | Snapshot plus custom covers, times 1.2 for the zip | Temporary folder's drive and the destination |
| Restore | 2 x backup size | App data drive |
| Compact database (`VACUUM`) | Database size plus 10% | Database drive |
| Safety snapshot | Database size | App data drive |
| Export | Estimated from the row count (about 1 KB per book) | Destination drive |

If free space would fall below the minimum, the guard runs the emergency cleanup (v4 6.15) on regenerable areas first, then refuses with a message that says how much is needed and how much is free. Backup, conversion and copy jobs release their temp registrations when they stop.

**Retention for v5 areas**

| Area | Kind | Policy |
|---|---|---|
| Safety snapshots (`safety/`) | Regenerable | Newest 5 or 14 days, whichever keeps more; never the snapshot taken for an operation still running |
| Local backups (destination folder) | User data | Only the backup retention rule (keep newest N, never delete the last good backup, never delete after a failed upload) |
| Drive backups | User data | Same retention rule |
| `conversion_log` rows | Regenerable | Purge after 180 days |
| `rename_batches`, `rename_log` | Protected until purged | Purge after 90 days (as in 4.1) |
| Import and lookup history (`metadata_history`) | Protected until purged | Purge after 30 days (as in v3) |
| Converted books, exports, custom covers | User data | Never touched by cleanup |

**Storage page (`ui/storage_page.py`)**
```
┌─────────────────────────── Settings: Storage ────────────────────────────────┐
│ Free space on C:  48.2 GB          App data total: 7.9 GB    [Open data folder] │
│ ⚠ (shown only when below the minimum)  Low disk space   [Clean up]           │
├──────────────────────────┬──────────┬──────────┬────────────────┬────────────┤
│ Area                     │ Used     │ Limit    │ Policy         │            │
├──────────────────────────┼──────────┼──────────┼────────────────┼────────────┤
│ Downloaded cloud books   │ 3.9 GB   │ 5 GB     │ last 10 + Reading, 30 days │ [Open][Clean] │
│ Cover files              │ 0.6 GB   │ -        │ orphans swept  │ [Open][Clean] │
│ Full-text index (v6)     │ 1.1 GB   │ 2 GB     │ stop at limit  │ [Open][Compact] │
│ Safety snapshots         │ 0.2 GB   │ -        │ newest 5       │ [Open][Clean] │
│ Online lookup cache      │ 12 MB    │ 100 MB   │ 30 days        │ [Clean]    │
│ Logs                     │ 8 MB     │ 25 MB    │ rotating       │ [Open]     │
│ Backups (local)          │ 1.4 GB   │ keep 10  │ retention      │ [Open]     │
├──────────────────────────┴──────────┴──────────┴────────────────┴────────────┤
│ Keep last [10] opened books  ☑ Keep books marked Reading                      │
│ Cache limit [5 GB]  Remove downloads not opened for [30] days                 │
│ Minimum free disk space [2 GB]                                                │
│ [Preview cleanup]  [Clean now]  [Clear regenerable data…]                     │
│ Last cleanup: removed 6 files, 1.4 GB, 3 hours ago                            │
├───────────────────────────────────────────────────────────────────────────────┤
│ Largest cached books:  DSA Notes.pdf 220 MB [Keep offline] [Remove]  …        │
└───────────────────────────────────────────────────────────────────────────────┘
```
- **Preview cleanup** opens a dialog listing each action (area, file, size, reason, protected books skipped) and the total to be freed; **Clean now** runs the same plan.
- **Clear regenerable data…** lists exactly what will go (everything regenerable except pinned and open books) and asks for confirmation. Custom covers, converted books, backups, annotations and the database are not offered.
- Sizes are measured in a background thread when the page opens, and update as jobs run.
- Rows for v6 areas appear only when those features exist.
- The low-space banner from v4 (6.15) also links here.

**Library health additions (rows for the table in 4.5)**

| Check | How | Fix |
|---|---|---|
| Storage area over its limit | Usage versus limit | Preview and run cleanup |
| Registered temp files left behind | Rows in `temp_files` | Delete (with the safety checks) |
| Low free disk space | `shutil.disk_usage` | Open the Storage page |
| Cache folder without its marker file | Marker check | Recreate the marker if the folder is empty, or choose a new folder |

**Command palette and actions:** register `storage.clean_now` ("Clean up storage now") and `storage.open_settings` ("Open Storage settings") in the action registry (4.7).

**Settings keys (new):** the v4 storage settings (`keep_recent_books`, `keep_reading_books`, `cache_limit_bytes`, `max_age_days`, `min_free_bytes`, `lease_minutes`) move into the Storage page and stay in `QSettings`.

---

## 5. Build Order (Milestones)

Finish and test each milestone before starting the next. Milestones 2 to 3 improve everyday use immediately; 4 to 5 and 8 to 9 protect your data, so do backup before you try the risky features on your real library.

| # | Milestone | What "done" looks like |
|---|---|---|
| 1 | **Migration 5, safety snapshots, job lanes** | Migration passes on a copy of your library; automatic safety snapshots work; convert and maintenance lanes exist |
| 1b | **Temp-file registry and guard hooks** | `temp_files` table and `register_temp`/`release_temp`; startup sweep; guard estimates for v5 operations; a fake failing job leaves no temp file behind |
| 2 | **Action registry, shortcuts, command palette** | All existing commands are registry actions; shortcuts page, cheat sheet and palette work; text fields keep their own shortcuts |
| 3 | **Drag and drop and Add files** | Folder and file drops, duplicate check, copy into the import folder, drag out, extra sidebar drop targets |
| 4 | **Local backup and destinations refactor** | Backup package with checksums; local folder destination; Drive destination moved behind the same interface; retention |
| 5 | **Restore and scheduler** | Verified restore with safety copy and restart swap tested on a fresh app-data folder; automatic backups |
| 6 | **Rename engine (no UI)** | Template parser, sanitizer, planner and executor pass all unit tests on temporary folders, including crash recovery and undo |
| 7 | **Rename preview UI** | Preview table, editing, filters, apply, summary, undo, F2 single rename, watcher ignores own changes |
| 8 | **Export** | CSV (BOM, formula protection) and JSON exports with field picker and scopes |
| 9 | **Import** | BookLib and Goodreads presets, generic mapping, matching, preview, apply, undo |
| 10 | **Library health tool** | All checks and fixes work; report can be saved |
| 10b | **Storage page and health integration** | Storage page with all areas, preview and run cleanup, Clear regenerable data, largest cached books, low-space banner, four new health checks, command palette actions |
| 11 | **Calibre detection and conversion planner** | Detection and test button; conversion matrix and warnings; DRM note |
| 12 | **Conversion job** | Progress parsing, cancel, timeout, temp file plus atomic rename, `converted_from` link, duplicate-finder integration, Drive source support |
| 13 | **Statistics queries and Fix dates** | Correct numbers on a seeded test database including year boundaries, re-reads, undated reads |
| 14 | **Statistics view and goals** | Charts with drill-down, goals with pace and projection, sidebar mini progress |
| 15 | **Polish and regression** | Menu bar, accessibility pass, performance test with 20,000 books, README, full regression of v1 to v4 features |

---

## 6. Testing Plan

**Unit tests (`pytest`)**
- **Migration 4 to 5:** existing data intact; new tables exist; running twice is safe.
- **Template parser:** all tokens and modifiers, optional groups (included only when all fields are non-empty), fallbacks, escaped brackets, unknown tokens (clear error), nested and unbalanced brackets, Unicode text (including Hindi).
- **Sanitizer:** illegal characters, reserved Windows names with and without extensions, trailing dots and spaces, very long names, path-length shortening order, `/` inside a metadata value.
- **Planner:** unchanged names, conflicts with existing files, two books mapping to the same target, case-only renames, path traversal attempts (`..` in metadata), symlink escape, non-local and missing books skipped, guessed-metadata flag.
- **Executor (temp directories):** normal rename, folder creation and `created_dirs`, target appears after the preview (fails, no overwrite), source changed after preview, `PermissionError` simulation, partial failure continues, database update failure rolls the rename back, crash recovery from `pending` rows.
- **Undo:** reverse order, skips changed files, removes only directories created by the batch and only when empty, works after a restart.
- **Own-changes set:** renamed and copied paths are ignored by the watcher exactly once within the TTL.
- **CSV export/import round trip:** commas, quotes, newlines in notes, Unicode, empty values, multi-value fields; formula-like titles get protected on export and restored on import.
- **Import:** encoding detection (UTF-8, BOM, UTF-16, Windows-1252), Goodreads fixture (including `="…"` ISBNs, rating 0, shelves), column mapping presets, matching order and ambiguity handling, apply with fill-empty vs overwrite, protected sources honored, undo restores only unchanged values.
- **JSON:** export then import into a copy of the library reproduces status, ratings, tags, dates, and notes; older `version` files still import.
- **Backup:** snapshot taken while another connection writes is consistent; manifest checksums; corrupted zip and tampered entry are detected; retention keeps the newest N and never deletes the last good backup; no tokens or credentials in the package (scan test).
- **Restore:** newer schema refused, older schema migrated, integrity failure refused, safety snapshot created, staged swap on restart (simulate with a temporary app-data folder).
- **Destinations:** the same test suite runs against `LocalFolderDestination` and a fake Drive destination.
- **Health checks:** a deliberately broken fixture database (orphan rows, missing FTS rows, orphan files) is detected and fixed.
- **Conversion (with a fake `ebook-convert` script):** progress parsing from `NN%` lines, cancel kills the child process, timeout, exit code mapping, "DRM" message mapping, temp file name ends with the right extension, no overwrite, output imported with `converted_from`, Drive source goes through `ensure_local`, duplicate finder ignores linked pairs.
- **Statistics:** seeded logs covering year boundaries, leap years, re-reads on and off, missing page counts, undated reads, negative durations ignored.
- **Goals:** pace and projection for parametrized dates (day 1, mid-year, last day, leap day), goals in books and in pages.
- **Shortcuts:** conflict detection, persistence, reset, actions built from the registry exist in menus and palette; text-field focus keeps text shortcuts.
- **Drag and drop:** MIME/URL parsing, unsupported files ignored, more than 500 files warning, duplicate check, copy naming conflicts, verify-after-copy failure handling.
- **Temp-file registry:** register then release leaves no row; a job that fails or is cancelled at every step leaves no temporary file; startup sweep removes registered leftovers; a registered path whose name does not match the temp pattern is **not** deleted.
- **Guard estimates:** each operation in the estimate table calls the guard with the right size and drive; a simulated low-space condition stops conversion, Add files, backup, restore and compact cleanly with a clear message and no partial output.
- **Retention:** safety snapshots (newest 5 or 14 days, never the one in use), backup retention (never deletes the last good backup or anything after a failed upload), log-row purges.
- **Storage page logic:** usage measurement, preview lists the same actions as the real run, **Clear regenerable data** never includes user data or protected data, pinned and open books are skipped.
- **Health checks:** the four storage checks detect a crafted bad state (over limit, leftover temp file, missing marker) and their fixes work.
- **Interaction with maintenance jobs:** cleanup does not start while a rename apply, restore, compact or import is running.

**Manual test checklist**
- Take a backup, then restore it into a fresh app-data folder and confirm everything (tags, ratings, custom covers, goals) is back.
- Rename a batch of 30 books with the default pattern; check the preview statuses, apply, verify files and statuses, undo, restart the app, undo another batch.
- Try awkward names: very long titles, `Con.pdf`, titles with `:` and `?`, Hindi titles, two books that map to the same name.
- Open a book in a reader, then rename it in a batch; that row fails with "in use" and the others succeed.
- Rename with folder organization, undo, and confirm the created folders disappear and nothing else is removed.
- Export CSV and open it in Excel; check Unicode, and a title starting with `=`; export JSON; import the JSON into a copy of the library.
- Import a real Goodreads export; check matches, unmatched report, statuses, ratings, dates; undo it.
- Convert an EPUB to AZW3 and a PDF to EPUB; check the metadata and cover of the results, the "Converted from" link, and that the duplicate finder leaves the pair alone; cancel a conversion halfway; try a DRM-protected file.
- Convert a Drive book; confirm it downloads, converts and appears as a local book.
- Run Library health on a real library; review each finding before fixing.
- Fill in finish dates, set a 2026 goal, check pace text, click chart bars to jump to the books.
- Change several shortcuts, restart, verify they persist; use `Ctrl+K` for five different commands; use the app for ten minutes without the mouse.
- Drag a folder, a few files from Downloads (copy into the import folder), a duplicate file, and a mix of PDFs and unsupported files onto the window; drag books out into Explorer and e-mail.
- Performance with 20,000 books: statistics open in about a second, palette and shortcuts respond instantly, exports of the whole library finish quickly, rename preview for 5,000 books stays responsive.

---

## 7. Known Pitfalls and How to Handle Them

| Problem | Handling |
|---|---|
| Bulk rename ruins many file names | Mandatory preview, guessed-metadata warning, never overwrite, write-ahead journal, persistent undo, safety snapshot |
| Crash in the middle of a rename batch | Journal rows are written first; recovery routine at startup resolves `pending` rows |
| File open in a reader cannot be renamed on Windows | Catch `PermissionError`, mark failed, continue |
| Windows is case-insensitive | Two-step rename for case-only changes; conflict checks use case-insensitive comparison on Windows |
| Metadata value contains `/`, `..` or reserved names | Sanitizer plus a containment check after resolving the final path |
| Very long paths | Length limits and shortening order; flag rows that still do not fit |
| The watcher re-imports or relinks files the app just renamed or copied | Own-changes set with a short TTL |
| Renaming files that Drive-synced folders also watch | Only local library folders are processed; warn if the folder is inside a folder synced by another tool |
| Calibre not installed or moved | Detection, manual path, Test button, friendly help dialog |
| Poor PDF conversions | Honest warnings; scanned PDFs skipped by default; output is a separate linked book, the original is never touched |
| DRM-protected books | Report clearly; the app does not remove DRM |
| Long-running or stuck conversions | Timeout, Cancel that kills child processes, one conversion at a time by default |
| Wrong extension on temporary output confuses Calibre | Temporary name always ends with the target extension |
| Converted books flagged as duplicates | `converted_from` link; duplicate finder lists them as related formats |
| Spreadsheet formula injection from exported cells | Prefix protection on export (default on), removed again on import |
| Excel shows garbled Hindi text | UTF-8 with BOM for CSV |
| Imports overwrite good data | Fill-empty default, preview of exact changes, `import:*` provenance, undo via history |
| Goodreads rows match the wrong book | Match order by strongest key, ambiguous rows skipped, manual pick, unmatched report |
| Import cannot restore a library on a new computer | Documented: use backup and restore; import only updates existing books |
| Backup copied from a live WAL database is corrupt | Always the SQLite backup API plus `integrity_check` |
| Backup contains secrets | Explicit include list, scan test for tokens and credentials |
| Restore overwrites newer data | Verification, safety snapshot, explicit confirmation, shown dates and computer names |
| Automatic backup slows startup or fills a drive | Delayed and background, retention limit, failures notify quietly |
| `VACUUM` needs free disk space and no other writers | Maintenance lane runs alone; check free space first |
| Statistics off by a day near midnight | Reading dates are local dates from Python, never from SQLite's UTC `now` |
| Books finished without dates disappear from charts | Undated count with a Fix dates helper |
| Pages missing for many books (Drive basic index) | Excluded from page totals with a visible count and a hint to deep-index or look up |
| Goal pace wrong in leap years | Use the actual days in the year |
| Shortcuts hijack text editing | Deliberate shortcut contexts and a test with focus in text fields |
| Shortcut conflicts with system or reader shortcuts | Conflict detection and easy reset; defaults avoid common global shortcuts |
| Huge drops (thousands of files) freeze the UI | Warning above 500, copy and import as background jobs with progress and cancel |
| Copying from a slow or disconnected source fails midway | Temporary name then atomic rename, verify size, clear error, no partial files left |
| A crashed conversion or copy leaves a temporary file inside a library folder | Register temp files first; sweep them at startup; only delete registered paths whose names match the temp pattern |
| Cleanup deletes something in a library folder | Cleanup only touches marked app folders and registered temp files; user data such as converted books and exports is never an area for generic cleanup |
| A conversion or backup fills the drive halfway | Disk-space guard with per-operation estimates; the job refuses to start rather than failing midway |
| Cleanup runs during a rename batch, restore or import | Mutual exclusion with the maintenance lane |
| Regenerable data is cleared but the user expected it kept | **Preview cleanup**, a confirmation listing exactly what will go, and a default that keeps recent, Reading, pinned and open books |
| `VACUUM` fails for lack of space | The guard checks database size plus 10% first |

---

## 8. Definition of Done for v5

- [ ] Migration from v4 works on a copy of your real library, with an automatic safety snapshot taken first
- [ ] Rename with patterns works with preview, conflict handling, folder organization, journal, crash recovery and persistent undo; Drive books are never touched
- [ ] Format conversion works through Calibre with metadata and cover carried over, progress, cancel and timeout; results are linked to their originals and not flagged as duplicates
- [ ] CSV and JSON export work with field selection and scopes; imports (BookLib, Goodreads, generic CSV) match, preview, apply and can be undone
- [ ] Local and Drive backups use one package format with checksums; automatic backups and retention work; restore is verified, keeps a safety copy, and works on a fresh installation
- [ ] Library health finds and fixes the listed problems without deleting anything unconfirmed
- [ ] Statistics show correct yearly and monthly figures, distributions and library overview, with drill-down into the library; Fix dates works
- [ ] Yearly goals show progress, pace and projection
- [ ] All commands are actions with editable shortcuts, a cheat sheet and a command palette; the app is fully usable by keyboard; text fields keep their shortcuts
- [ ] Dropping files and folders works with duplicate checks and copy-into-library; dragging books out works; sidebar drop targets apply tags and statuses
- [ ] The watcher never re-imports files the app itself renamed or copied
- [ ] No secrets in exports, backups or logs
- [ ] Runs smoothly with 20,000 books
- [ ] Unit tests pass for templates, sanitizing, planner, executor, undo, export, import, backup, restore, health checks, conversion, statistics, goals, shortcuts and drag and drop
- [ ] The Storage page shows every storage area with size, limit and policy, and **Preview cleanup** matches **Clean now**
- [ ] Temporary files created by conversion, rename, copy, export and backup are registered and never left behind after failures, cancels or crashes
- [ ] Conversion, Add files, backup, restore and compact check free disk space first and stop cleanly with a clear message when it is short
- [ ] Safety snapshots and backups follow their retention rules and never delete the last good backup
- [ ] Library health includes the four storage checks with working fixes
- [ ] Unit tests pass for the temp-file registry, guard integration, retention and the Storage page logic

---

## 9. Stretch Ideas (Only After the Definition of Done Is Met)

- **Embed metadata into files** (write your corrected title, author and cover into EPUB and PDF files). Off by default, with a backup copy of each original first; it modifies your files, so treat it with the same care as renaming.
- **Auto-rename new imports** with your pattern once online metadata has been applied.
- **Did not finish** status and reading sessions with a simple timer.
- **Exclude or remove single books** from the library (with the path excluded from later scans).
- **Export to BibTeX or Markdown reading lists** for study notes.
- **Statistics extras:** reading heatmap by month, time-to-finish by genre, yearly summary image to share.

---

## 10. What Comes Next (Preview of v6)

v5 prepares v6 (Advanced Features) in several ways: the action registry and command palette make new commands (reader controls, highlights) easy to add; conversion gives the built-in reader clean EPUBs to work with and a local copy for Drive books; the backup package format can include annotations later; the statistics and goals can use real reading progress from the reader; and `ensure_local` and the cache already provide local files for text extraction. Version 6 adds a built-in PDF/EPUB reader with bookmarks and remembered position, full-text search inside books, highlights and annotations, recommendations from your ratings, local web access from your phone (with authentication), and optional other cloud sources.

# Book Library App: Version 2 Plan (Reading Tracking and Better Browsing)

**Goal of v2:** Turn the v1 scanner and viewer into a real library you use every day: mark what you are reading, find books quickly, fix wrong metadata, rate and annotate books, and open them in the reader of your choice.

**Prerequisite:** v1 is complete and its definition of done is met. v2 builds directly on the v1 schema, scanner, model/view and details pane.

**Out of scope for v2** (planned for later versions): online metadata lookup, tags and collections, series, duplicate detection, watch folders, reading progress (page X of Y), start/finish dates, custom cover replacement, Google Drive.

---

## 1. Feature List

### 1.1 Reading status
- Three statuses: **Want to Read**, **Reading**, **Read**. A book with no status is "Unset".
- Set the status from: the details pane (segmented buttons), the right-click menu, and keyboard shortcuts.
- Works on multiple selected books at once (bulk set).
- A small colored badge on each cover in the grid, and a status column in the list view.
- Sidebar shortcuts to view each status with a live count.
- Optional setting (on by default): **opening a book that is Unset or Want to Read automatically marks it Reading**.
- The time of each status change is stored for later features (v3 finish dates, v5 stats).

### 1.2 Open with other readers
- Right-click menu and details pane: **Open** (default app) and **Open with ▸** a submenu of readers that can handle that format.
- The list is detected from the system (registry on Windows, `.desktop`/MIME data on Linux, application lookup on macOS) and merged with a list of well-known readers found in standard install locations.
- **Custom readers:** add any executable manually, with a display name and the formats it handles.
- **Default reader per format:** for example "always open EPUB in Calibre Viewer and PDF in SumatraPDF". The plain **Open** action respects this.
- Fallback item **Choose another app…** that opens the operating system's own "Open with" dialog.
- Every open is recorded (`last_opened_at`, `open_count`) to power "Continue reading".

### 1.3 Search
- Search bar at the top of the library (`Ctrl+F` to focus).
- Searches title, author, publisher, genre, ISBN, filename and notes.
- Results update as you type (250 ms debounce), with prefix matching (`tolstoy` finds "Tolstoy, Leo").
- Case-insensitive and accent-insensitive; multiple words are all required (AND).
- Works with non-English text such as Hindi.

### 1.4 Filters
- Filter panel (collapsible sidebar section) with: status, format, author, genre, language, minimum rating.
- Each option shows a count of matching books.
- Multiple selections inside one filter mean OR (PDF or EPUB); different filters combine with AND.
- Active filters appear as removable chips above the library, with a **Clear all** button.
- Filters combine with search and with the current sort.

### 1.5 Grid and list views
- Toggle between the **grid** (covers) and a **list/table** view.
- List view columns: cover (small), title, author, publisher, year, edition, ISBN, pages, genre, language, size, format, status, rating, date added, last opened.
- Show/hide and reorder columns; click a header to sort; column layout is remembered.
- Grid thumbnail size slider (small to large).
- The selection is kept when switching views.

### 1.6 Manual metadata editing
- **Edit** dialog (`Ctrl+E`) for all metadata fields with validation: year is a number in a sane range, pages is a positive integer, ISBN gets a checksum check (warn, do not block).
- **Bulk edit** for several selected books: change author, publisher, genre, language, year or edition; fields left as "keep existing" are not touched.
- Edited fields are remembered per book so a **rescan never overwrites your edits**.
- **Revert to file metadata** per book (re-reads the file and clears the edit marks).
- **Undo/redo** (`Ctrl+Z` / `Ctrl+Y`) for edits, status changes and ratings.

### 1.7 Ratings and notes
- 1 to 5 star rating in the details pane and in the list view; click the current star again to clear.
- Free-text notes per book, autosaved, searchable.

### 1.8 Dark mode
- Theme setting: **System / Light / Dark**, applied instantly without restart.
- All custom painting (grid delegate, badges, star widget) uses palette colors so it looks right in both themes.

### 1.9 Home shelves in the sidebar
- **All Books**
- **Continue Reading:** books with status Reading, most recently opened first.
- **Recently Added:** books added in the last 30 days (configurable), newest first.
- **Want to Read**, **Reading**, **Read**, **Unset**.
- Each shelf is just a saved query, so it also works with search, filters and sort.

---

## 2. What Changes in the v1 Code

| Area | Change |
|---|---|
| Database | Migration 2 (new columns, FTS index, reader tables); `user_version` becomes 2 |
| Model | Replace the v1 `QAbstractListModel` with one `QAbstractTableModel`. The grid (`QListView`, `setModelColumn(0)`) and the list (`QTableView`) both use it |
| Sorting and filtering | Move to SQL through a `LibraryQuery` object (needed for full-text search and counts). The v1 proxy model is retired |
| Rescan pipeline | When a file changed, only overwrite metadata fields that are not in the book's `edited_fields` |
| Details pane | Becomes interactive: status buttons, stars, notes editor, Edit button, Open-with menu |
| Settings | New keys for theme, view mode, thumbnail size, column layout, reader preferences |
| Delegate/painting | Read colors from the palette, never hard-coded values |

---

## 3. Database Changes (Migration 2)

v1 already created `status`, `rating` and `notes` in `books`. Migration 2 adds the rest:

```sql
-- migration 2
ALTER TABLE books ADD COLUMN status_changed_at TEXT;
ALTER TABLE books ADD COLUMN last_opened_at    TEXT;
ALTER TABLE books ADD COLUMN open_count        INTEGER NOT NULL DEFAULT 0;
ALTER TABLE books ADD COLUMN edited_fields     TEXT;   -- JSON array, e.g. '["title","author"]'

CREATE INDEX idx_books_status      ON books(status);
CREATE INDEX idx_books_rating      ON books(rating);
CREATE INDEX idx_books_format      ON books(format);
CREATE INDEX idx_books_date_added  ON books(date_added);
CREATE INDEX idx_books_last_opened ON books(last_opened_at);

-- reader preferences
CREATE TABLE custom_readers (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    exe_path      TEXT NOT NULL,
    args_template TEXT NOT NULL DEFAULT '{file}',
    formats       TEXT NOT NULL DEFAULT '*'      -- comma-separated extensions or '*'
);

CREATE TABLE format_defaults (
    format     TEXT PRIMARY KEY,                 -- 'pdf', 'epub', ...
    reader_key TEXT NOT NULL                     -- 'system' | 'custom:<id>' | 'detected:<exe path>'
);

-- full-text search (external-content table, kept in sync by triggers)
CREATE VIRTUAL TABLE books_fts USING fts5(
    title, author, publisher, genre, isbn, notes, filename,
    content='books', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER books_ai AFTER INSERT ON books BEGIN
  INSERT INTO books_fts(rowid,title,author,publisher,genre,isbn,notes,filename)
  VALUES (new.id,new.title,new.author,new.publisher,new.genre,new.isbn,new.notes,new.filename);
END;

CREATE TRIGGER books_ad AFTER DELETE ON books BEGIN
  INSERT INTO books_fts(books_fts,rowid,title,author,publisher,genre,isbn,notes,filename)
  VALUES ('delete',old.id,old.title,old.author,old.publisher,old.genre,old.isbn,old.notes,old.filename);
END;

CREATE TRIGGER books_au AFTER UPDATE OF title,author,publisher,genre,isbn,notes,filename ON books BEGIN
  INSERT INTO books_fts(books_fts,rowid,title,author,publisher,genre,isbn,notes,filename)
  VALUES ('delete',old.id,old.title,old.author,old.publisher,old.genre,old.isbn,old.notes,old.filename);
  INSERT INTO books_fts(rowid,title,author,publisher,genre,isbn,notes,filename)
  VALUES (new.id,new.title,new.author,new.publisher,new.genre,new.isbn,new.notes,new.filename);
END;

INSERT INTO books_fts(books_fts) VALUES ('rebuild');   -- index existing v1 books
PRAGMA user_version = 2;
```

**Notes**
- Run the migration inside one transaction, and **copy the database file to a backup** (`library.db.bak-v1`) before migrating.
- `status` accepts only `want`, `reading`, `read` or `NULL`. SQLite cannot add a `CHECK` afterwards without rebuilding the table, so validate in `repository.py`.
- The update trigger is limited to the searchable columns so changing `last_opened_at` or `status` does not rewrite the search index.
- Check FTS5 support at startup (`sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")`). It is available in almost all Python builds. If it is missing, fall back to `LIKE '%term%'` search on the main columns.

---

## 4. Implementation Details

### 4.1 Query layer (`db/query.py`)
All browsing goes through one object:

```python
@dataclass
class LibraryQuery:
    search: str = ""
    statuses: set[str] = field(default_factory=set)    # {'want','reading','read','none'}
    formats: set[str] = field(default_factory=set)
    authors: set[str] = field(default_factory=set)
    genres: set[str] = field(default_factory=set)
    languages: set[str] = field(default_factory=set)
    min_rating: int | None = None
    shelf: str | None = None        # None | 'continue' | 'recent'
    sort_field: str = "title"
    sort_desc: bool = False
    include_missing: bool = False
```

`repository.query_books(q)` builds one SQL statement from it and returns lightweight rows (id, title, author, cover_path, format, status, rating, year, size, pages, date_added, last_opened_at, plus the other list columns). Use parameters for every value; only column names for `ORDER BY` come from a fixed whitelist.

- **Search:** `id IN (SELECT rowid FROM books_fts WHERE books_fts MATCH ?)`.
- **Status "Unset":** `status IS NULL` (translated from the `'none'` value).
- **Shelves:**
  - `continue`: `status = 'reading' ORDER BY last_opened_at DESC`
  - `recent`: `date_added >= datetime('now', '-30 days') ORDER BY date_added DESC`
- **Sorting with empty values last:** `ORDER BY col IS NULL, col COLLATE NATURAL ASC/DESC`, then `title` as a tie-breaker.
- **Natural sort:** register a Python collation on every connection: `conn.create_collation("NATURAL", natural_compare)` (case-insensitive, numbers compared as numbers, `Book 2` before `Book 10`).
- **Facet counts:** `facet_counts(field, q)` runs a `GROUP BY` for the filter panel. Start with counts over the whole library; refine later so each facet ignores its own filter but respects the others.

### 4.2 Building the FTS search string
Never pass raw user text to `MATCH`; quotes, `-`, `*` and `:` are operators and can raise errors.

```python
def build_fts_query(text: str) -> str | None:
    tokens = re.findall(r"\w+", text, flags=re.UNICODE)   # letters/digits, any script
    if not tokens:
        return None
    return " ".join(f'"{t}"*' for t in tokens)            # prefix match, all tokens required
```

- Empty result means "no search", return all books.
- Debounce with a `QTimer` (250 ms, single-shot) restarted on each keystroke.
- Run the query in the UI thread; with tens of thousands of rows it is fast. If it ever lags, move it to a worker and discard stale results using a request counter.

### 4.3 Library model (`ui/library_model.py`)
- One `QAbstractTableModel` subclass. Columns are defined in a single list (`COLUMNS = [Column("title", ...), ...]`) that also drives the list view header and the column chooser.
- `reload(query)` calls `repository.query_books`, then `beginResetModel/endResetModel`. Remember the selected book ids before reset and restore them after.
- Targeted updates: after a status/rating/edit change, update the one row and emit `dataChanged` instead of reloading (avoids the grid jumping). If the change makes the book leave the current filter (for example marking Read while viewing Reading), remove the row with `beginRemoveRows`.
- Roles: `DisplayRole`, `DecorationRole` (thumbnail), `UserRole` (book id), plus custom roles for status, rating, sort key.
- **Grid view:** `QListView` in `IconMode` with `setModelColumn(0)`; the delegate paints cover, title, author, status badge and (optionally) stars. **List view:** `QTableView` with the same model, sortable header, `setSelectionBehavior(SelectRows)`, `setAlternatingRowColors(True)`.
- Both views share one `QItemSelectionModel` so the selection carries over when toggling.
- Thumbnail size slider: `view.setIconSize(...)` plus `setGridSize(...)`, and rescale pixmaps from the 300 px cache (do not regenerate covers).

### 4.4 Sidebar (`ui/sidebar.py`)
- A `QTreeWidget` (or `QListWidget` with headers) with two sections: **Library** (All Books, Continue Reading, Recently Added) and **Status** (Want to Read, Reading, Read, Unset), each with a count.
- Choosing an item sets `LibraryQuery.shelf` / `statuses` and reloads the model.
- Below it, the collapsible **Filters** panel: checkable lists for format, author, genre, language and a minimum-rating selector. Long lists (authors, genres) show the top 20 plus a "Show more…" search box.
- Counts refresh after scans and after status/metadata changes (debounced, so bulk changes do not trigger many refreshes).
- Filter chips (`ui/filter_chips.py`): a horizontal row of small buttons, one per active filter or search term, each with an ✕, plus **Clear all**.

### 4.5 Status handling
- `repository.set_status(ids, status)` updates `status` and `status_changed_at` in one transaction for all selected ids.
- UI entry points:
  - Details pane: segmented buttons `Want | Reading | Read`, click the active one again to clear.
  - Context menu: **Mark as ▸ Want to Read / Reading / Read / Clear status**.
  - Shortcuts: `Ctrl+1` Want, `Ctrl+2` Reading, `Ctrl+3` Read, `Ctrl+0` clear.
- Badge colors (light/dark variants defined in `theme.py`): Want = blue, Reading = amber, Read = green.
- Auto-mark on open: in `open_book()`, after a successful launch, if the setting is on and status is `NULL` or `want`, set it to `reading`. Show a short status bar message ("Marked as Reading, undo?") so it is never surprising.

### 4.6 Ratings and notes
- `StarRating` widget (`ui/star_rating.py`): paints 5 stars from the palette, hover preview, click sets rating, click on the current rating clears it. Emits `ratingChanged(int | None)`.
- Notes: `QPlainTextEdit` in the details pane. Save on focus-out and after 800 ms of no typing (debounced). Switching books saves any pending note first, so nothing is lost.
- Both go through the undo stack (rating changes) or the debounced save (notes).

### 4.7 Metadata editing
**Edit dialog (`ui/edit_dialog.py`)**
- Fields: title, author, publisher, year, edition, ISBN, pages, genre, language.
- Validation on save: year 1000 to current year (or empty), pages positive integer (or empty), ISBN checksum (show a warning with "Save anyway"), title must not be empty.
- On save, compare with the old values; for each changed field add its name to `edited_fields` (JSON), and set `metadata_src = 'manual'`.

**Bulk edit**
- Same dialog with a "Keep existing" checkbox per field. Only fields with the checkbox cleared are applied. Title is disabled in bulk mode (setting the same title on many books is almost always a mistake).
- Apply everything in one transaction and one undo command.

**Rescan protection (change in `scanner/pipeline.py`)**
```python
edited = set(json.loads(row.edited_fields or "[]"))
new = extract_metadata(path, fmt)
for name in METADATA_FIELDS:
    if name not in edited:
        setattr(book, name, getattr(new, name))
```
File-derived values such as size, mtime, format and pages-from-PDF still update; only the fields the user edited are protected.

**Revert to file metadata:** re-run the extractor, overwrite all metadata fields, clear `edited_fields`, and set `metadata_src = 'file'`. Ask for confirmation.

**Undo/redo**
- Use `QUndoStack` (in `PySide6.QtGui`). Commands: `EditMetadataCommand`, `SetStatusCommand`, `SetRatingCommand`. Each stores the ids plus a before and after snapshot of the affected fields, so multi-book operations undo as one step.
- Clear the stack when a scan changes the database under it, to avoid undoing onto stale data.
- Bind `Ctrl+Z` / `Ctrl+Y` and the Edit menu actions using `undoStack.createUndoAction()`.

### 4.8 Reader detection and "Open with" (`readers/`)

```
readers/
├── models.py          # Reader dataclass (key, name, exe, formats, args_template)
├── known.py           # table of well-known readers and their install paths
├── detect_windows.py  # registry-based detection
├── detect_linux.py    # .desktop / MIME based detection
├── detect_macos.py    # NSWorkspace or 'open -a'
├── custom.py          # user-defined readers (DB table custom_readers)
├── registry.py        # merges everything, caches per extension
└── launcher.py        # safely starts a reader with a file
```

**Reader model**
```python
@dataclass(frozen=True)
class Reader:
    key: str            # 'detected:C:\\...\\SumatraPDF.exe' or 'custom:3'
    name: str           # 'SumatraPDF'
    exe: str
    formats: frozenset[str]     # {'pdf','epub'} or {'*'}
    args_template: str = "{file}"
```

**Windows detection (`detect_windows.py`), the most important target**
1. For the extension (for example `.pdf`), read these registry locations (with `winreg`):
   - `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\<ext>\OpenWithList` (values are executable names) and `...\OpenWithProgids`
   - `HKCR\<ext>\OpenWithList` (subkeys are executable names) and `HKCR\<ext>\OpenWithProgids`
2. Resolve each **executable name** through `HKCR\Applications\<exe>\shell\open\command`; resolve each **ProgID** through `HKCR\<progid>\shell\open\command`.
3. Extract the executable path from the command string: if it starts with a quote, take everything up to the closing quote; otherwise up to the first `.exe`. Keep only entries where the file exists.
4. Skip system launchers that are not readers (`rundll32`, `explorer`, `cmd`, `powershell`, entries using `DelegateExecute`, which are Microsoft Store apps and cannot be launched by path).
5. Display name: `FriendlyAppName` value if present, otherwise the executable's file description (Windows version resource via `ctypes`, optional), otherwise the executable name without `.exe`.
6. Remove duplicates by executable path (case-insensitive).

**Well-known readers (`known.py`)**
Some installed readers are missing from the registry lists, so also check standard install paths, and only show those that exist:

| Reader | Typical formats |
|---|---|
| SumatraPDF | pdf, epub, mobi, djvu, cbz |
| Adobe Acrobat / Acrobat Reader | pdf |
| Foxit Reader | pdf |
| Calibre E-book Viewer (`ebook-viewer.exe`) | epub, mobi, azw3, pdf, cbz, txt |
| Thorium Reader | epub |
| Kindle for PC | mobi, azw3 |
| Okular / Evince / Foliate / Sioyek (Linux) | pdf, epub, djvu |

Look in `%ProgramFiles%`, `%ProgramFiles(x86)%` and `%LocalAppData%\Programs`, and also check `shutil.which(...)` for the executable name.

**Linux and macOS (optional, if you use them)**
- Linux: get the MIME type (`mimetypes` or `gio info`), list handlers with `gio mime <mime>`, and read each `.desktop` file for `Name=` and `Exec=`. Launch with `gio launch <desktop file> <path>` so `%f/%U` codes are handled for you.
- macOS: `NSWorkspace.URLsForApplicationsToOpenURL_` through `pyobjc`, or the known-reader list with `open -a "<App>" <path>`.

**Registry and caching (`registry.py`)**
- `readers_for(ext) -> list[Reader]` merges detected + known + custom readers, filters by format, and sorts: default reader first, then alphabetically.
- Cache per extension for the session; a **Refresh reader list** menu item clears the cache (useful right after installing a new app).
- Detection runs lazily the first time the menu is opened for a format, not at startup.

**Launching (`launcher.py`)**
```python
def launch(reader: Reader, book_path: str) -> None:
    args = [reader.exe] + [a.replace("{file}", book_path)
                           for a in shlex.split(reader.args_template, posix=False)]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, close_fds=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
```
- **Never use `shell=True`**, and always pass the path as a list item so spaces and special characters in file names are safe.
- Wrap in `try/except OSError` and show a clear message ("Could not start SumatraPDF; the program may have been moved") with a **Refresh reader list** button.
- Fallback "Choose another app…" on Windows: `subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", book_path])` opens the OS's own chooser.

**Default reader per format**
- **Open** (double-click, Enter): looks up `format_defaults` for the book's format; `system` means `QDesktopServices.openUrl` (v1 behavior), anything else launches that reader; if the saved reader no longer exists, fall back to `system`.
- In the Open-with submenu: a checkable action **Always use this for .epub files** that writes to `format_defaults`.
- A **Readers** page in Settings lists detected and custom readers, lets you add/edit/remove custom ones (name, executable, formats, argument template with `{file}`), and choose the default per format.

**Recording opens**
`repository.record_open(book_id)`: `last_opened_at = datetime('now')`, `open_count = open_count + 1`. Call it only after a successful launch.

### 4.9 Themes (`ui/theme.py`)
- Setting `theme` = `system` | `light` | `dark` in `QSettings`.
- Use the **Fusion** style, which follows a custom `QPalette` on every platform. Build two palettes (window, base, text, highlight, button, link, disabled colors).
- **System mode:** read `app.styleHints().colorScheme()` (Qt 6.5 and later) and react to `colorSchemeChanged`. If it is unavailable in your Qt version, default to Light.
- Status badge and other accent colors live in a `THEME_COLORS` dict with light and dark variants.
- Rules for painting code: always use `option.palette` / `QPalette` roles; never hard-code `#ffffff` or `#000000`. Placeholder covers are images, so keep them mid-tone so they work in both themes.
- Use single-color SVG icons and tint them with the palette's `ButtonText` color, so the toolbar looks right in both themes.
- Apply with `app.setPalette(...)`; the views repaint immediately. Add a small manual test screen or checklist for each custom widget in both themes.

### 4.10 Settings and persistence (`QSettings`)
New keys: `theme`, `view_mode` (grid/list), `thumb_size`, `list/header_state` (`QHeaderView.saveState()`), `sidebar/visible`, `auto_mark_reading`, `recent_days`, `sort_field`, `sort_desc`, and the last selected sidebar shelf. Reader preferences live in the database tables from section 3. Filters and search text are **not** persisted; the app starts clean.

---

## 5. UI Layout (v2)

```
┌────────────────────────────────────────────────────────────────────────────┐
│ [Add Folder][Rescan] │ 🔍 Search books…      │ Sort:[Title▼][↑/↓] [▦|☰] [⚙] │
├─────────────┬──────────────────────────────────────────┬───────────────────┤
│ LIBRARY     │ Filters: [PDF ✕] [Reading ✕] [★≥4 ✕]  Clear all               │
│ All Books   │──────────────────────────────────────────┤  ┌─────────────┐  │
│ Continue  3 │  ┌────┐ ┌────┐ ┌────┐ ┌────┐             │  │    cover    │  │
│ Recent   12 │  │cvr │ │cvr │ │cvr │ │cvr │             │  └─────────────┘  │
│             │  │ ●  │ │ ●  │ │    │ │ ●  │  ● = status │  Title            │
│ STATUS      │  └────┘ └────┘ └────┘ └────┘    badge    │  Author           │
│ Want     24 │  Title  Title  Title  Title             │  [Want|Reading|Read]
│ Reading   3 │                                          │  ★★★★☆            │
│ Read     58 │                                          │  Publisher · Year │
│ Unset  1,163│                                          │  ISBN · Pages     │
│             │                                          │  Genre · Language │
│ FILTERS  ▾  │                                          │  Size · Format    │
│ Format      │                                          │  Notes ─────────  │
│ ☐ PDF  1,102│                                          │  │              │ │
│ ☐ EPUB  146 │                                          │  └──────────────┘ │
│ Author  ▸   │                                          │  [Open ▾][Edit]   │
│ Genre   ▸   │                                          │  [Show in folder] │
│ Rating  ▸   │                                          │                   │
├─────────────┴──────────────────────────────────────────┴───────────────────┤
│ 37 of 1,248 books                                             Scan idle     │
└────────────────────────────────────────────────────────────────────────────┘
```
`[Open ▾]` is a split button: the main part opens with the default reader, the arrow shows the Open-with menu.

---

## 6. Build Order (Milestones)

Finish and test each milestone before starting the next.

| # | Milestone | What "done" looks like |
|---|---|---|
| 1 | **Migration 2** | Backup made, new columns/tables/FTS created, existing v1 data intact and indexed; migration test passes |
| 2 | **Query layer** | `LibraryQuery` + `query_books` return correct rows for search, status, formats, shelves, sorting (natural, empty last); unit tests pass |
| 3 | **Model refactor** | Single table model drives the existing grid; v1 features still work; reload keeps the selection |
| 4 | **Sidebar and shelves** | All Books, Continue Reading, Recently Added, and status shelves with counts |
| 5 | **Status marking** | Details buttons, context menu, shortcuts, bulk set, badges, status changes reflected live |
| 6 | **Search** | Search bar with debounce and FTS; special characters and Hindi text do not crash or return nothing |
| 7 | **Filters and chips** | Filter panel with counts, combine with search, chips, Clear all |
| 8 | **List view** | Table view, view toggle, column chooser, header sorting, saved layout, shared selection |
| 9 | **Ratings and notes** | Star widget and autosaved notes, both searchable/visible in list where relevant |
| 10 | **Edit dialog and rescan protection** | Single-book edit with validation; edited fields survive a rescan; revert works |
| 11 | **Bulk edit and undo/redo** | Multi-book edit in one step; `Ctrl+Z`/`Ctrl+Y` for edits, status, rating |
| 12 | **Reader detection and launcher** | Open-with menu lists installed readers for each format and launches correctly, including paths with spaces |
| 13 | **Custom readers and defaults** | Add a custom reader, set per-format defaults, "Choose another app…" fallback, refresh list |
| 14 | **Dark mode** | System/Light/Dark switch works live; every custom widget checked in both themes |
| 15 | **Polish and testing** | Settings persistence, error messages, performance test with 20,000 books, updated README |

---

## 7. Testing Plan

**Unit tests (`pytest`)**
- **Migration:** build a v1 database with sample rows, run migration 2, assert data preserved, `user_version == 2`, FTS returns those rows, and running the migration twice is safe.
- **FTS query builder:** inputs such as `tolstoy`, `war and peace`, `"quoted"`, `c++`, `a-b`, `*`, an empty string, and Hindi text; none may raise an SQL error.
- **`LibraryQuery` to SQL:** seed a temporary database and assert results for each filter, filter combinations (OR inside a filter, AND across filters), each shelf, and each sort field in both directions with `NULL`s last.
- **Natural collation:** `Book 2 < Book 10`, case-insensitive, accents handled.
- **Status:** transitions, bulk update, `status_changed_at` set, invalid values rejected.
- **Rescan protection:** edit a title, change the file, rescan; the edited title stays, other fields update; after revert the file title returns.
- **Edit validation:** year, pages and ISBN edge cases.
- **Reader command parsing:** sample registry strings (quoted paths, paths with spaces, `"%1"`, extra arguments) yield the correct executable; system launchers are filtered out.
- **Launcher:** argument list is correct for a file name with spaces, brackets and Unicode; no shell is used.
- **Undo commands:** apply then undo restores the exact previous values for single and bulk edits.

**Manual test checklist**
- Mark books Want / Reading / Read using every entry point; verify badges, sidebar counts and the Reading shelf update immediately.
- Open a Want to Read book with auto-mark on, see it become Reading, then undo.
- Search while filters are active, then clear one filter at a time.
- Toggle between grid and list with a multi-book selection; the selection stays.
- Edit a book, run Rescan, confirm the edit remains; revert to file metadata.
- Bulk edit the genre of 10 books, undo, redo.
- Install a new reader (for example SumatraPDF), press Refresh reader list, confirm it appears and opens the book.
- Set a default reader for EPUB, double-click an EPUB, confirm it uses it; uninstall or rename the reader and confirm a graceful fallback.
- Switch System/Light/Dark with the app open; check grid, list, badges, stars, sidebar and dialogs.
- Restart the app and confirm theme, view mode, column layout, thumbnail size and sort are restored.
- Performance: 20,000 books, typing in the search box feels instant, shelf switching under a second, scrolling stays smooth.

---

## 8. Known Pitfalls and How to Handle Them

| Problem | Handling |
|---|---|
| FTS `MATCH` errors from special characters | Build the query with `build_fts_query` only; never concatenate raw text |
| FTS index out of sync | Triggers keep it updated; add a hidden **Rebuild search index** action (`INSERT INTO books_fts(books_fts) VALUES('rebuild')`) |
| Migration damages the v1 database | Backup before migrating, run in one transaction, test with a copy of your real library |
| Grid jumps or loses selection after edits | Update single rows with `dataChanged`; only reset the model when the query itself changes; restore selection after resets |
| Books disappear when their status changes inside a filtered view | Remove the row with `beginRemoveRows` and show the status bar message; this is expected behavior |
| Registry detection misses or mislabels some apps | Merge with the known-readers list, let users add custom readers, provide the OS "Open with" fallback |
| Microsoft Store apps and Edge cannot be launched by path | Skip entries using `DelegateExecute`; those still work through the system default (**Open**) |
| Paths with spaces or special characters break launching | Argument lists, never shell strings; test with awkward names |
| User edits overwritten by rescans | `edited_fields` check in the pipeline, covered by a test |
| Undo after a rescan restores stale data | Clear the undo stack when a scan writes to the database |
| Dark mode leaves unreadable text in custom-painted widgets | Palette roles only; test every custom widget in both themes |
| Qt version differences for system color scheme | Feature-check `colorScheme()`; default to Light if missing; keep the manual theme switch |
| Notes lost when switching books quickly | Save pending notes before changing the selection and on app close |
| Large author/genre lists make the filter panel slow | Show the top 20 with a "Show more…" search box; compute counts in SQL |

---

## 9. Definition of Done for v2

- [ ] Migration from v1 works on a copy of your real library with no data loss, and a backup is created
- [ ] Reading status can be set from the details pane, context menu and shortcuts, singly and in bulk, with visible badges
- [ ] Sidebar shows All Books, Continue Reading, Recently Added and the four status shelves with correct counts
- [ ] Search finds books by title, author, publisher, genre, ISBN, filename and notes, including non-English text, without errors
- [ ] Filters (status, format, author, genre, language, rating) work individually and combined with search, with chips and Clear all
- [ ] Grid and list views both work, share the selection, and remember view mode, columns and thumbnail size
- [ ] Ratings and notes save automatically and survive restarts
- [ ] Metadata can be edited singly and in bulk; edits survive rescans; revert works; undo/redo works
- [ ] "Open with" lists installed readers for the book's format, launches them correctly, and supports custom readers, per-format defaults and the OS chooser fallback
- [ ] Opening a book records last-opened data, and auto-mark-as-Reading works when enabled
- [ ] System, Light and Dark themes all render correctly and switch without restart
- [ ] Runs smoothly with 20,000 books
- [ ] Unit tests pass for migration, search, query, status, rescan protection, reader parsing and undo

---

## 10. What Comes Next (Preview of v3)

v2 prepares for v3 in several ways: `edited_fields` and `metadata_src` let online lookup respect manual edits, `status_changed_at` supports start and finish dates, the `LibraryQuery` object accepts new filters (tags, collections, series) without redesign, and the details pane can host new editable sections. Version 3 adds online metadata lookup (Open Library / Google Books), bulk metadata fetch, tags, collections and series, duplicate detection, watch folders, reading progress, and custom covers.

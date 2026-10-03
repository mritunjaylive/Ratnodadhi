# Book Library App: Version 4 Plan (Google Drive Integration)

**Goal of v4:** Bring your Google Drive book repository into the library. Sign in once with Google, pick Drive folders, and see those books next to your local ones, with covers, sorting, statuses and tags. Books are downloaded only when you open them and kept in a size-limited local cache. Optionally, back up your library database to Drive.

**Prerequisite:** v3 is complete and its definition of done is met (especially the job manager, `field_sources`, tags/collections, duplicate detection and the reserved `source` / `drive_file_id` columns from v1).

**Out of scope for v4:** two-way sync, uploading or renaming books in Drive, live multi-device sync of the library, other cloud providers (OneDrive, Dropbox: v6), converting or renaming files (v5).

> **Read this first: Google's rules matter for this version.** Google's policies decide which scope you can use and how long a sign-in lasts. These points were checked against Google's documentation while writing this plan:
> - `drive.readonly` (view and download all Drive files) and `drive.metadata.readonly` are **restricted** scopes. `drive.file` (only files the user opens or shares with the app through Google's file picker) and `drive.appdata` (the app's own hidden data folder) are **non-sensitive**.
> - A Google Cloud project whose OAuth consent screen is in **Testing** status issues sign-ins and refresh tokens that **expire after 7 days**. In **In production** status they generally last until revoked or unused for a long time (about six months).
> - Public apps using restricted Drive scopes must pass Google's verification and fit specific app categories. That is unrealistic for a hobby project, so this plan is designed for **your own Google Cloud project and your own account** (see section 3). Google policies change, so re-check the Cloud Console and the Drive API documentation when you start.

---

## 1. Feature List

### 1.1 Sign-in and accounts
- **Connect Google Drive** button in Settings and in the Add Folder menu.
- Standard Google sign-in in your browser; the app never sees your password.
- Sign-in survives restarts: the refresh token is stored in the operating system's secure credential store (Windows Credential Manager), never in the database, settings file or logs.
- Account list in Settings: email, connection state (OK / Needs sign-in), last sync time, **Reconnect** and **Disconnect**.
- Support more than one Google account (the data model allows it from day one; the interface can start with one).
- Disconnecting deletes the stored token and asks whether to also remove that account's books from the library and clear its cache.

### 1.2 Add Drive folders
- **Add Google Drive folder…** opens a folder browser: My Drive, and folders shared with you.
- Pick one or more folders; options per folder: include subfolders (default on), formats to include, deep indexing (1.3), and automatic sync.
- Prevents overlapping picks (a folder inside another already-synced folder is flagged).
- Optional: **create collections from the Drive folder structure** (for example `CS/DSA` becomes a collection).

### 1.3 Indexing (two levels)
- **Basic index (fast, no downloads):** from Drive's own information, so thousands of books appear within minutes.
  - Title and author guessed from the file name (the v1 filename parser), format, size, folder path, Drive link.
  - Cover from Drive's generated thumbnail when Drive has one (mostly PDFs), otherwise a placeholder.
- **Deep index (optional, per folder):** downloads each file once, reads real metadata and the real cover with the existing v1 extractors, page count for PDFs, ISBN from PDF text, then deletes the file again unless you chose to keep it. Shows the total download size before starting, is cancellable and resumable.
- Books can be deep-indexed later, for a selection or a whole folder.
- Online metadata lookup (v3) works on Drive books, either from a filename-based guess or from the ISBN found by deep indexing.

### 1.4 Sync
- **Incremental sync** using Drive's change feed: new, renamed, moved, modified and deleted files are picked up without listing the whole Drive again.
- Runs at startup, every 15 minutes while the app is open (configurable), and on demand with **Sync now**.
- Files removed or trashed in Drive are marked missing, not deleted, so your status, ratings, tags and notes are safe; **Remove missing** cleans them up as before.
- A renamed or moved Drive file keeps all your data, because its Drive file id never changes.
- Falls back to a full re-list automatically if Drive says the saved sync position is no longer valid.

### 1.5 Download on demand and local cache
- Opening a Drive book (double-click, Open, Open with…) downloads it first if needed, with a progress dialog and Cancel, then opens it in the chosen reader exactly like a local book.
- Downloads resume after an interruption and are verified against Drive's checksum before use.
- **Cache manager:** size limit (default 5 GB), least-recently-used cleanup, cache usage display, **Clear cache**, **Free up space**.
- **Keep offline:** pin books so they are never removed from the cache; **Download selected / folder** for bulk offline use, with a size and free-disk-space check first.
- If a Drive file changes, the cached copy is treated as stale and re-downloaded on the next open.

### 1.6 Source indicators and filters
- Small badge on each cover and a Source column in list view:
  - ☁ Drive only (not downloaded)
  - ☁✓ Drive, downloaded (available offline)
  - 📌 Kept offline
  - a plain (no badge) local file
- Sidebar **Sources** section: All, Local, Google Drive, Available offline. Filter and sort by source.
- Details pane shows the Drive folder path, account, size, Drive checksum, cache state, and buttons: Download, Keep offline, Remove download, **Open in Drive** (in your browser).
- "Show in folder" becomes "Show downloaded file" (if cached) or "Open in Drive" for Drive books.

### 1.7 Offline and error handling
- No internet: cached books open normally; other Drive books show a clear message. The library itself always works from the local database.
- Expired or revoked sign-in: a banner "Google Drive needs sign-in" with a Reconnect button; sync pauses instead of failing repeatedly.
- Clear messages for missing permission, quota limits, full disk and deleted files.

### 1.8 Backup and restore of the library (optional)
- **Back up library to Google Drive:** a consistent snapshot of the database plus your custom covers, stored in the app's hidden Drive data folder (it does not clutter your Drive).
- Manual **Back up now**, plus an optional automatic backup (when there are changes and the last backup is older than a chosen number of days). Keeps the last N backups (default 5).
- **Restore…** lists backups with date, computer name and book count; verifies the file, makes a local safety copy of the current library first, then restores after a restart.
- One-way backup and restore only. Live syncing the library between computers is not attempted.

### 1.9 Relocate folders (needed after a restore)
- **Relocate folder…** for local library folders: point a folder at its new location (new PC, new drive letter, renamed parent). Book paths are rewritten, then a rescan and relink confirm that files were found; all your data is kept.

### 1.10 Storage and cache cleanup (garbage collection)
- **Keep the last N opened books:** downloaded books you opened recently stay on disk (default the last 10). Books you marked **Reading** are kept too (option, on by default). Both are protected from routine cleanup.
- **The size cap always wins:** if the protected books alone exceed the cap, the oldest of them go first. **Kept offline (pinned)** books and books that are open in a reader are never removed; if they alone exceed the cap, the app warns instead of deleting.
- **Remove old downloads:** downloads not opened for a set number of days (default 30) are removed, unless protected.
- **Automatic sweeps** of leftovers: half-finished downloads, temporary indexing files, superseded or orphan cover files, expired online-lookup cache entries.
- **Disk-space guard:** before a download or deep-index run, the app checks free space (default minimum: the larger of 2 GB or 5% of the drive). If space is short it frees regenerable data automatically; if that is not enough, it stops with a clear message instead of filling the disk.
- **Safe by design:** cleanup only deletes files the app itself created, only inside its own cache folders, never inside your library folders.
- **Preview cleanup:** a dry run shows exactly what would be removed and why; the automatic cleanup uses the same plan.
- Controls in the Google Drive settings page (a full Storage page for all areas comes in v5): keep last N, size cap, remove after N days, minimum free space, **Clean now**.

---

## 2. Key Design Decisions

| Decision | Choice | Why |
|---|---|---|
| Drive permission | `drive.readonly` for browsing and downloading; `drive.appdata` for backups | Indexing whole folder trees needs read access to files you did not create with the app. `drive.file` is designed for files the user opens through Google's picker and does not fit browsing a folder tree (confirm in current docs if you want to try it). Read-only also means the app **cannot delete or change your Drive files** |
| Whose credentials | Your own Google Cloud project, imported as a `client_secret.json` file | Avoids Google's app verification for restricted scopes; anyone who later wants to use your app brings their own credentials |
| Sign-in flow | Desktop "loopback" flow with PKCE via `google-auth-oauthlib` | The standard flow for desktop apps; opens the system browser and receives the result on `127.0.0.1` |
| Token storage | `keyring` (Windows Credential Manager); store only the refresh token and account email | Secrets never enter SQLite, settings or logs |
| API access | `google-auth` `AuthorizedSession` with direct REST calls, one session per job | Thread-safe per session, streaming downloads and `Range` headers are simple. The `googleapiclient` service objects are not thread-safe |
| Book identity | Drive **file id** (stable), stored in `drive_file_id` | Rename and move keep your data automatically |
| Path for Drive books | Virtual path `gdrive://<account_id>/<file_id>` in the existing `path` column | `path` is `NOT NULL UNIQUE` since v1; a virtual path avoids rebuilding the table, and all code that touches real paths branches on `source` |
| Sync method | Changes API with a saved page token, plus a folder-tree mirror table | Only changed files are processed; ancestry checks decide whether a change is inside a synced folder |
| Integrity | Drive's `md5Checksum` | Verifies downloads and enables Drive-vs-local duplicate detection |
| Cache retention | **Keep-recent rule plus size cap plus age rule**, run by a storage manager (section 6.15) | Size-only least-recently-used cleanup can delete the book you opened yesterday. Keeping the last N opened books matches how people read; the hard cap still protects the disk |
| Deleting files | Only app-created files inside cache folders that contain a marker file; dry run equals real run | A cleanup feature that deletes the wrong folder is worse than a full disk |

---

## 3. Google Cloud Setup (One-Time, Written for the README and an In-App Help Page)

1. Go to the Google Cloud Console and create a **new project** (for example "BookLib").
2. **Enable the Google Drive API** for that project.
3. Configure the **OAuth consent screen**: user type *External*, app name, your email as support and developer contact.
4. Add these scopes: `.../auth/drive.readonly` and `.../auth/drive.appdata`.
5. **Publishing status:**
   - *Testing:* add your own Google account as a test user. Works, but **you must sign in again every 7 days**.
   - *In production:* recommended for daily use, so sign-ins do not expire weekly. Because the app is unverified, Google shows a "Google hasn't verified this app" screen the first time; for your own app and your own account choose **Advanced**, then continue. Unverified apps are limited to a small number of users, which is irrelevant for personal use.
6. Create an **OAuth client ID** of type **Desktop app** and download the JSON file.
7. In the app: **Settings, Google Drive, Import credentials…** and select that file. The app copies it into its data folder. **Never commit it to a public repository** (add `client_secret*.json` to `.gitignore`).
8. Click **Connect Google Drive** and complete the sign-in in the browser.

You can revoke access at any time from your Google Account's third-party access page.

---

## 4. What Changes in the v1 to v3 Code

| Area | Change |
|---|---|
| Database | Migration 4 (section 5); `user_version` becomes 4 |
| Every place that uses `book.path` | Must branch on `source`. Known places: scanner walker (must ignore Drive rows when checking files on disk), missing-file detection, open file, show in folder, relink, watcher, hashing, cover regeneration, duplicate actions |
| Opening books | New `ensure_local(book)` step returns a real file path (downloading if needed) before the v2 reader launcher runs |
| Folders | `folders` rows can now be of kind `drive`; the Manage Folders dialog shows both kinds with sync status |
| Job manager | Two lanes: a **heavy lane** (scan, sync, lookup, hashing, deep index) as in v3, and an **I/O lane** (downloads, uploads, thumbnails) with up to 2 concurrent jobs |
| EPUB/PDF extractors | Must work on a cached copy in the download folder and accept being run from the deep-index job |
| Duplicate finder | Also uses `md5`; Drive books cannot be sent to the Recycle Bin (read-only); offer **Open in Drive** instead |
| Covers | New `cover_source` value `'drive'`; replaced by real covers after deep indexing unless the cover is custom or online |
| Details pane | File section reworked for source, cache state and Drive actions |
| `LibraryQuery` | New filters: `source`, `offline_only`, `drive_folder_id`; new sort field: source |
| Settings | New Google Drive page (accounts, credentials, sync, cache, backup) |
| Cover cache (v3) | Superseded versions (`<id>_<n>.jpg`) and orphan files are swept by the storage manager; custom covers are never touched |
| Online cache (v3) | Expiry and size cap enforced by the storage manager instead of only at lookup time |
| Logging (v1) | Rotating file handler with a size limit, if not already set |
| New package | `storage/` (areas, planner, executor, guard, scheduler) used by the download engine, deep index, cache manager and thumbnails |
| Download and deep-index code | Call the disk-space guard before starting and register a lease while a cached book is in use |

---

## 5. Database Changes (Migration 4)

v1 already reserved `books.source` and `books.drive_file_id`. Back up the database file first; run everything in one transaction.

```sql
-- accounts
CREATE TABLE drive_accounts (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    display_name  TEXT,
    changes_token TEXT,                            -- Drive Changes API page token
    state         TEXT NOT NULL DEFAULT 'ok',      -- 'ok' | 'needs_signin'
    added_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_sync_at  TEXT
);

-- folders: local or Drive
ALTER TABLE folders ADD COLUMN kind              TEXT NOT NULL DEFAULT 'local';   -- 'local' | 'drive'
ALTER TABLE folders ADD COLUMN account_id        INTEGER REFERENCES drive_accounts(id) ON DELETE CASCADE;
ALTER TABLE folders ADD COLUMN drive_folder_id   TEXT;
ALTER TABLE folders ADD COLUMN drive_display     TEXT;                            -- 'My Drive/Books/CS'
ALTER TABLE folders ADD COLUMN include_subfolders INTEGER NOT NULL DEFAULT 1;
ALTER TABLE folders ADD COLUMN deep_index        INTEGER NOT NULL DEFAULT 0;
ALTER TABLE folders ADD COLUMN sync_enabled      INTEGER NOT NULL DEFAULT 1;
-- for Drive folders, folders.path holds the virtual value 'gdrive://<account_id>/<drive_folder_id>'

-- books
ALTER TABLE books ADD COLUMN md5            TEXT;       -- Drive md5Checksum, or lazily computed for local files
ALTER TABLE books ADD COLUMN drive_path     TEXT;       -- 'Books/CS/DSA' (display only)
ALTER TABLE books ADD COLUMN drive_web_link TEXT;       -- webViewLink
ALTER TABLE books ADD COLUMN index_level    TEXT NOT NULL DEFAULT 'full';   -- 'basic' | 'deep' | 'full'
ALTER TABLE books ADD COLUMN keep_offline   INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX idx_books_drive_file ON books(drive_file_id) WHERE drive_file_id IS NOT NULL;
CREATE INDEX idx_books_source ON books(source);
CREATE INDEX idx_books_md5    ON books(md5);

-- mirror of the Drive folder tree under synced roots (used for ancestry checks in sync)
CREATE TABLE drive_nodes (
    account_id INTEGER NOT NULL REFERENCES drive_accounts(id) ON DELETE CASCADE,
    file_id    TEXT NOT NULL,
    parent_id  TEXT,
    name       TEXT NOT NULL,
    root_folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,  -- which synced root it belongs to, NULL = outside
    PRIMARY KEY (account_id, file_id)
);

-- downloaded copies
CREATE TABLE drive_cache (
    book_id       INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    file_path     TEXT NOT NULL,               -- relative to the cache folder
    size_bytes    INTEGER NOT NULL,
    md5           TEXT,
    downloaded_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at  TEXT NOT NULL DEFAULT (datetime('now')),
    in_use_until  TEXT                         -- lease: do not evict before this UTC time
);
CREATE INDEX idx_drive_cache_used ON drive_cache(last_used_at);

-- small key/value store (last backup time, etc.)
CREATE TABLE app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

PRAGMA user_version = 4;
```

**Notes**
- `in_use_until` is the **lease** described in section 6.15. It is set when a cached book is handed to a reader and renewed while it is open. Cleanup never removes a book whose lease has not expired.
- Recency for the keep-recent rule comes from `books.last_opened_at` (v2), falling back to `drive_cache.downloaded_at` for books that were downloaded but never opened.
- No existing rows change: every v1 to v3 book keeps `source = 'local'`.
- `drive_nodes.root_folder_id = NULL` is a valid, cached answer meaning "this folder is outside all synced roots", which prevents repeated lookups during sync.
- Deleting an account cascades to its folders and, through them, its books. The interface must ask for confirmation first.
- The virtual `path` (`gdrive://...`) must never be passed to `os.path`, `open()` or Qt file functions. Add a helper `is_drive(book)` and a linter-style test that greps for risky uses.

---

## 6. Implementation Details

### 6.1 Package layout

```
booklib/
├── drive/
│   ├── auth.py            # OAuth flow, token storage, credentials import
│   ├── client.py          # REST calls, paging, backoff, error mapping
│   ├── models.py          # DriveFile dataclass, error types
│   ├── browser_model.py   # lazy tree model for the folder picker
│   ├── indexer.py         # initial listing and basic index
│   ├── sync.py            # Changes API, ancestry, apply changes
│   ├── download.py        # resumable download with verification
│   ├── cache.py           # cache table, limits, eviction, pinning
│   ├── deep_index.py      # download, extract, cleanup
│   └── backup.py          # snapshot, upload, list, prune, restore
├── ui/
│   ├── drive_connect_dialog.py
│   ├── drive_folder_picker.py
│   ├── download_dialog.py
│   ├── drive_settings_page.py
│   └── backup_dialog.py
└── tools/
    └── relocate.py        # relocate local folders
```
The `drive` package must not import from `ui`. Network code lives only here.

### 6.2 Authentication (`drive/auth.py`)

**Credentials file**
- Import the user's `client_secret.json` into `<app data>/google_client.json` (validate that it contains an `installed` section with `client_id`, `client_secret`, `token_uri`).

**Sign-in**
```python
flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
creds = flow.run_local_server(host="127.0.0.1", port=0,
                              access_type="offline", prompt="consent",
                              open_browser=True, timeout_seconds=180)
```
- Run it in a worker thread (it blocks until the browser step finishes) with a **Cancel** button and the 3-minute timeout; show "Waiting for you to sign in in your browser…".
- Use `prompt="consent"` so Google returns a refresh token even when you have authorized the app before.
- After sign-in read the account email from the Drive API (`about.get?fields=user(emailAddress,displayName)`), create the `drive_accounts` row.

**Token storage**
- `keyring.set_password("BookLib", email, refresh_token)`. Store **only the refresh token**, not the whole credentials JSON (Windows Credential Manager entries are limited to a few kilobytes).
- At run time rebuild `google.oauth2.credentials.Credentials(token=None, refresh_token=..., client_id=..., client_secret=..., token_uri=..., scopes=...)` and let `AuthorizedSession` refresh access tokens automatically.
- On `invalid_grant` (revoked, expired, password changed): set `drive_accounts.state = 'needs_signin'`, stop that account's jobs, show the Reconnect banner.
- Disconnect: delete the keyring entry, delete the account (after the confirmation described in 1.1).
- Wrap `keyring` in a small `TokenStore` class so tests can use an in-memory fake and a missing or locked keyring produces a clear error ("Could not access the system credential store").
- **Never log** access tokens, refresh tokens, authorization codes or the client secret. Add a test that scans the log output for token patterns.

### 6.3 Drive client (`drive/client.py`)

- One `AuthorizedSession` per job/thread. Base URL `https://www.googleapis.com/drive/v3`.
- Common parameters: `supportsAllDrives=true`; use `fields=` on every call to request only what you need.
- **Listing books in a folder:**
  `files.list` with `q="'<folderId>' in parents and trashed=false"`, `pageSize=1000`,
  `fields="nextPageToken, files(id,name,mimeType,size,md5Checksum,modifiedTime,parents,webViewLink,hasThumbnail,thumbnailLink,shortcutDetails(targetId,targetMimeType))"`; follow `nextPageToken` until it is empty.
  To reduce request count on big trees, query several folders at once: `('id1' in parents or 'id2' in parents or ...)` (batches of about 20 to 50 folder ids).
- **Classify each item:**
  - `mimeType = application/vnd.google-apps.folder` → folder (recurse if subfolders are included).
  - `application/vnd.google-apps.shortcut` → resolve `shortcutDetails.targetId`; if the target is a supported book file, index the target once (dedupe by target id).
  - Other `application/vnd.google-apps.*` (Docs, Sheets, Slides) → **skip and count** as "unsupported Google-format files". They have no size or checksum and cannot be downloaded as-is.
  - Books: decide by file extension and MIME type (`application/pdf`, `application/epub+zip`, `application/x-mobipocket-ebook`, `image/vnd.djvu`, and so on, plus name-based fallback because Drive often labels EPUB/MOBI as `application/octet-stream`).
- **Folder tree info:** `files.get?fields=id,name,parents,mimeType` for breadcrumbs and ancestry.
- **Changes:** `changes.getStartPageToken`, `changes.list` with `pageToken`, `includeRemoved=true`, `fields="nextPageToken,newStartPageToken,changes(fileId,removed,file(...))"`.
- **Download:** `GET files/<id>?alt=media` with `stream=True`; `Range: bytes=<n>-` for resume.
- **Thumbnail:** `GET thumbnailLink` with the authorized session, changing the size suffix (for example `=s400`); thumbnail links are short-lived, so fetch them soon after listing.

**Error handling and retries**
- Exponential backoff with random jitter (1, 2, 4, 8, up to about 32 seconds, max 5 tries) for HTTP 429, 5xx, and 403 with reasons `rateLimitExceeded` / `userRateLimitExceeded`.
- Map errors to app exceptions: `AuthExpired` (401 after refresh, `invalid_grant`), `NotFound` (404), `Forbidden` (403, no permission or download quota exceeded), `Offline` (connection errors), `Transient`. The UI shows a specific message for each.
- Detect offline state (three consecutive connection errors) and stop the job with a friendly message instead of marking anything missing.

### 6.4 Folder picker (`ui/drive_folder_picker.py`)
- Tree of folders loaded lazily as you expand (one `files.list` call per expanded node, folders only, `orderBy=name`).
- Top-level entries: **My Drive** and **Shared with me** (`q="sharedWithMe=true and mimeType='application/vnd.google-apps.folder'"`).
- A search box (`name contains '...'`) for jumping to a folder.
- Selecting a folder shows an estimate ("about N items, checking…") using a quick capped listing so you know what you are adding.
- Options panel: include subfolders, formats, deep indexing, create collections from folder structure, sync automatically.
- Save: creates a `folders` row (`kind='drive'`, virtual path), seeds `drive_nodes` with the root, and starts the initial index job.
- **Shared drives** (team drives) are optional: they need drive-specific listing parameters. Treat as a later addition unless you use them.

### 6.5 Initial index (`drive/indexer.py`)
Runs as a **heavy-lane job** with progress ("Indexed 1,200 files, 84 folders").

1. Breadth-first walk from the root folder using the batched queries in 6.3; upsert each folder into `drive_nodes` with `root_folder_id` set.
2. For each supported book file, build a `books` row:
   - `source='drive'`, `drive_file_id`, virtual `path`, `filename`, `format`, `size_bytes`, `file_mtime` (from `modifiedTime`), `md5` (from `md5Checksum`), `drive_path`, `drive_web_link`, `index_level='basic'`.
   - Metadata from the v1 filename parser only; `field_sources` = `file:filename`.
   - Cover: placeholder for now (`cover_source='placeholder'`); the thumbnail step below may replace it.
3. Upsert in batches of about 100 rows, commit per batch, so progress is visible and an interruption loses little. Books already known (same `drive_file_id`) are updated, never duplicated.
4. When the walk finishes, store the account's **changes start page token** (`changes.getStartPageToken`) **before** the walk began (record it at the start, save it at the end) so changes made during the walk are not missed.
5. Follow-up **thumbnail job (I/O lane):** for books with `hasThumbnail`, download the thumbnail (up to 4 concurrent requests), resize with the v1 cover pipeline, set `cover_source='drive'`. Cancelable; books without a thumbnail keep the placeholder.
6. Summary dialog: added N books, skipped M unsupported Google-format files, K files with unsupported extensions, errors E.
7. Optional: build collections from the folder structure (using the v3 collections API) for the folders the user chose.

### 6.6 Incremental sync (`drive/sync.py`)
1. Load `changes_token` for the account; call `changes.list` page by page.
2. For each change:
   - **Removed or trashed** (`removed=true` or `file.trashed=true`): if a book with that `drive_file_id` exists, set `is_missing=1`. If it was a folder in `drive_nodes`, mark books under it as missing after verifying with a direct lookup.
   - **Folder change** (new folder, rename, move): update `drive_nodes`; recompute `drive_path` for affected books.
   - **File change:** decide whether the file lies inside a synced root using `is_inside_root(file)`:
     - Walk up the `parents` chain using `drive_nodes`; for unknown parent ids fetch them with `files.get` and add them (with `root_folder_id` set when the chain reaches a synced root, or `NULL` when it reaches the top without one). Cache both outcomes.
     - Inside a root: add the book if new, or update size, md5, mtime, name and `drive_path` if known. If the md5 changed, delete the cached copy, set `index_level='basic'` again if it was deep-indexed, and clear `quick_hash`/`file_hash`.
     - Outside all roots but a book exists (moved out of the tree): mark missing.
3. Field updates respect v3 `field_sources`: a rename only updates the filename-derived title if that title's source is still `file:filename`; manual and online values are never touched.
4. Save `newStartPageToken` after all pages are processed, in the same transaction as the last batch.
5. Failure handling: if Drive answers that the saved token is invalid (the change history is no longer available), run a **full re-list** of each synced root, compare with the database by `drive_file_id`, and mark absent files missing. Expose this as **Full resync** in the folder menu as well.
6. Triggers: app start (after a short delay), timer (default 15 min), **Sync now**, and after Reconnect. Only one sync per account at a time. Status bar text: "Drive: synced 3 min ago", "Syncing…", "Offline", "Sign-in needed".

### 6.7 Download engine (`drive/download.py`)
```
cache/<file_id>/<sanitized original file name>
cache/<file_id>/<sanitized original file name>.part     # while downloading
```
- Keep the **original file name** inside a per-file folder, so the reader's title bar shows a readable name instead of an id. Sanitize: replace `<>:"/\|?*` and control characters, strip trailing dots and spaces, avoid Windows reserved names (`CON`, `NUL`, `COM1`…), and cap the name at about 120 characters while keeping the extension.
- Steps:
  1. Ask the **disk-space guard** (section 6.15) for `size + 10%` free space on the cache drive; the guard applies the cleanup policy first if space is short, and refuses the download with a clear message if it still cannot make room.
  2. Stream to the `.part` file in 1 MB chunks; if a `.part` exists, resume with `Range: bytes=<size>-`.
  3. Report progress (bytes, speed, remaining time) to the dialog; check the cancel flag each chunk.
  4. On completion verify the size and, when the book has an `md5`, the MD5 of the file. On mismatch delete the `.part` and retry once from scratch; a second mismatch shows a clear error.
  5. Rename `.part` to the final name (atomic), insert or update the `drive_cache` row, set `quick_hash`/`file_hash` if not yet known.
- `ensure_local(book)`: if a valid cache entry exists (file present, size matches) update `last_used_at` and return the path; otherwise run the download job and return the path when done. If the entry's `md5` differs from the book's current `md5`, treat the cache as stale.
- **Download dialog (`ui/download_dialog.py`):** modal with the book title, progress bar, speed, Cancel; if the user cancels, keep the `.part` file so a later open can resume.
- Bulk **Download selected / folder**: previews total size and free space, then queues I/O jobs (2 at a time) with an overall progress bar in the status bar.
- Opening happens through the v2 launcher with the cached path; **record the open** (`last_opened_at`, status auto-mark) exactly as for local books.

### 6.8 Cache manager (`drive/cache.py`)
- Location: `<app data>/drive_cache/` by default, changeable in Settings (moving the cache copies or clears it, with confirmation).
- **Limit and retention:** the cache is governed by the storage manager (section 6.15): the **keep-last-N-opened** rule, the **size cap** (default 5 GB), and an optional **age rule**. Pinned books and books with an active lease are never evicted, and the file just downloaded is never evicted.
- Files that cannot be deleted (Windows keeps files locked while a reader has them open): skip, keep the row, and retry at the next cleanup.
- **Pin/unpin:** the Keep offline toggle sets `keep_offline`; pinning a not-yet-downloaded book queues a download.
- **Consistency check at startup:** remove `drive_cache` rows whose files are gone; delete files in the cache folder that have no row (orphans older than one day); delete stale `.part` files older than seven days.
- Settings page: usage bar (used of limit), number of files, **Free up space** (evict down to a chosen size), **Clear cache** (keeps pinned unless the user ticks "including kept offline").

### 6.9 Deep index (`drive/deep_index.py`)
- Selectable per folder (setting) or on demand for selected books or a whole folder: **Read metadata from files**.
- **Before starting:** compute the total download size of the books involved (sum of `size_bytes` for `index_level='basic'`), skip files above a size limit (default 200 MB, configurable), and ask for confirmation showing "About 1,240 files, 3.4 GB".
- Runs in the I/O lane (download) with extraction in the heavy lane, processing sequentially or 2 at a time:
  1. Download to the cache (6.7).
  2. Run the v1 extractor for the format; for PDFs also run the v3 ISBN scan; generate the cover.
  3. Update metadata **respecting `field_sources`** (fill fields whose source is `file:*`; leave manual and online values untouched); set `pages`, `isbn`, cover (`cover_source='file'` unless the cover is custom or online), `index_level='deep'`.
  4. Delete the downloaded file unless the book is pinned or the setting **Keep files downloaded while indexing** is on (default off).
- Resumable: the job simply selects books still at `index_level='basic'`, so stopping and restarting continues where it left off. Failures (corrupt or password-protected files) are logged, the book stays `basic` with a marker so it is not retried endlessly.
- Optional later optimization: read only the tail and needed parts of large EPUBs using HTTP `Range` requests; unnecessary for typical book sizes.

### 6.10 Integration with existing features
- **Open with (v2):** unchanged; the launcher receives the cached path.
- **Reading status, ratings, notes, tags, collections, series (v2, v3):** identical for Drive books.
- **Details pane:** File section shows source, Drive folder path, account, size, checksum, cache state and the Drive actions.
- **Show in folder (v1):** for Drive books becomes **Show downloaded file** (opens the cache folder location) when cached, otherwise **Open in Drive** (`drive_web_link` in the default browser).
- **Watch folders (v3):** apply to local folders only; Drive folders use sync.
- **Relink (v3):** local only; Drive identity is the file id.
- **Missing books:** Drive books removed from Drive show as missing with the label "Removed from Drive".
- **Online lookup (v3):** works after the book has an ISBN (from deep indexing) or with a filename-based query; results are marked as uncertain when the title came only from a filename.

### 6.11 Duplicates across Drive and local (extends v3)
- **Exact duplicate level:** compare `md5`. Drive books already have it. For local books, compute MD5 **lazily** only when the file size equals the size of at least one Drive book, and store it in `books.md5`.
- The comparison table gets a Source column (Local/Drive) and shows the Drive folder path.
- Actions for a Drive book: **Remove from library** and **Open in Drive**. The Recycle Bin action is disabled, because the app is read-only towards Drive. This is a deliberate safety feature.
- Merging user data works across sources exactly as in v3.

### 6.12 Backup and restore (`drive/backup.py`)

**Scope and location:** uses `drive.appdata`, so backups live in Drive's hidden application data folder (`spaces=appDataFolder`, parent `appDataFolder`); they do not appear in the normal Drive file list and count toward your Drive storage.

**Creating a backup**
1. Take a consistent snapshot with SQLite's online backup API (`sqlite3.Connection.backup()`) into a temporary file. **Do not copy the live database file**: with WAL mode the file alone can be incomplete or inconsistent.
2. Run `PRAGMA integrity_check` on the snapshot.
3. Build a zip: `library.db` (snapshot), `covers/custom/` (custom covers cannot be regenerated; generated covers can, so they are excluded), `manifest.json` (app version, schema version, timestamp, computer name, book count), and a non-secret settings export. **Never include tokens or the Google client file.**
4. Upload: multipart upload for small files, **resumable upload** above a few megabytes, as an I/O-lane job with progress.
5. Name: `booklib-backup-YYYYMMDD-HHMMSS-<computer>.zip`. Prune to the newest N backups (default 5) after a successful upload.
6. Record `last_backup_at` in `app_meta`. **Automatic backup (optional):** at startup after a delay, if there are changes since the last backup (a `dirty` flag set by `library_changed`) and the last backup is older than the configured interval.

**Restoring**
1. List backups from the appData folder with date, computer name and book count (from the manifest).
2. Download and verify: zip integrity, `manifest.json`, `PRAGMA integrity_check`, and **schema version ≤ the app's** (refuse a backup from a newer app version with a clear message; older ones are migrated forward after restore).
3. Make a **local safety copy** of the current library (`library.db.pre-restore-<timestamp>` plus custom covers) and show its location.
4. Stage the restored files, then ask to restart; on the next start (before opening the database) swap the files in.
5. After restore: local folders may have different paths on this computer, so folders that cannot be reached show a warning (books are not marked missing) and the user is offered **Relocate folder…** (6.13). Drive folders work after the user signs in, then **Sync now**.
6. Restore replaces the current library. It is not a merge.

### 6.13 Relocate folder (`tools/relocate.py`)
- Choose a library folder, choose its new location; validation checks that the new folder exists and that a sample of known files (up to 50) exists there under the same relative paths; warn if fewer than about 80% are found.
- Rewrite paths in one transaction by replacing the old **folder prefix followed by a path separator** (matching `C:\Books` must not also rewrite `C:\Books2`); update `folders.path`.
- Then trigger a rescan with relinking (v3) so files that moved slightly are matched by size and quick hash, and nothing is duplicated.
- Not offered for Drive folders (they are identified by Drive ids).

### 6.14 Query, sidebar and settings
- `LibraryQuery` additions: `source: set[str]` (`local`, `drive`), `offline_only: bool` (has a `drive_cache` row or `keep_offline = 1`), `drive_folder_id`. New sort: `source`.
- SQL for offline: `id IN (SELECT book_id FROM drive_cache) OR keep_offline = 1`.
- Sidebar **Sources:** All, Local, Google Drive (expandable to show each synced root and its last sync time), Available offline.
- **Manage folders dialog:** adds Drive roots with a cloud icon, sync state, last sync time, **Sync now**, **Full resync**, **Stop syncing**, and toggles for subfolders, deep index and automatic sync.
- **Settings, Google Drive page:** accounts, import credentials, sync interval, cache location/limit/usage/clear, keep-downloaded-while-indexing, max file size for deep index, concurrent downloads (1 to 4), backup options and actions, **Remove all Drive data from this computer**.

### 6.15 Storage manager (`storage/`)

```
storage/
├── areas.py       # registry of storage areas
├── policy.py      # keep-recent, size cap and age rules
├── planner.py     # builds a CleanupPlan (used for both dry run and real run)
├── executor.py    # safe deletion with retries
├── guard.py       # free-disk-space checks
├── usage.py       # measures sizes
└── scheduler.py   # decides when cleanup runs
```
The `storage` package must not import from `ui`.

**Storage areas (`areas.py`)**
```python
@dataclass
class StorageArea:
    key: str                     # 'drive_downloads'
    label: str                   # 'Downloaded cloud books'
    root: Path                   # folder that holds the files
    kind: str                    # 'regenerable' | 'user_data' | 'protected'
    limit_bytes: int | None
    def plan(self, now, reason) -> list[Action]: ...    # never deletes anything itself
    def usage(self) -> int: ...
```
- **Regenerable:** can be recreated; generic cleanup may delete it under the area's policy. **User data** (custom covers, converted books, backups) and **protected** data (database, annotations) are never deleted by generic cleanup.
- Areas in v4:

| Area | What it holds | Default policy |
|---|---|---|
| `drive_downloads` | Downloaded books (`drive_cache/`) | Keep-recent, size cap 5 GB, age rule 30 days |
| `partial_downloads` | `.part` files | Removed after 7 days, sooner if disk space is low |
| `deep_index_tmp` | Temporary files from deep indexing | Deleted after each book; leftovers older than 1 day removed |
| `covers` | Generated cover files | Sweep orphans and superseded versions only; no size eviction (they are regenerated at a cost, especially for cloud books) |
| `online_cache` | Rows in `online_cache` (v3) | Expire after 30 days (7 for "not found"); cap about 100 MB, oldest first |
| `logs` | `app.log` and others | Rotating handler, 5 files of 5 MB |

**Settings (new, with defaults)**

| Setting | Default | Meaning |
|---|---|---|
| `keep_recent_books` | 10 (range 0 to 100; 0 turns the rule off) | The last N opened downloaded books are soft-protected |
| `keep_reading_books` | on | Books with status Reading are soft-protected |
| `cache_limit_bytes` | 5 GB | Hard cap for `drive_downloads` |
| `max_age_days` | 30 (0 turns it off) | Downloads not opened for this long are removed unless protected |
| `min_free_bytes` | larger of 2 GB or 5% of the drive | Free-space floor used by the guard |

**Protection tiers for downloaded books**
- **Tier 0, never removed:** pinned books (`keep_offline = 1`) and books whose lease is still valid (`in_use_until > now`).
- **Tier 1, soft-protected:** books with status Reading (if enabled) and the last N opened books, ranked by `coalesce(books.last_opened_at, drive_cache.downloaded_at)`.
- **Tier 2:** everything else.

**Cleanup plan for `drive_downloads` (`policy.py`)**
1. **Age rule** (if enabled): remove Tier 2 books whose recency is older than `max_age_days`.
2. **Size rule:** if the total is above the cap, remove books until the total is at or below 90% of the cap, in this order: (a) Tier 2, oldest recency first; (b) then Tier 1, oldest recency first. **The cap wins over the keep-recent rule.**
3. **Tier 0 is never removed.** If Tier 0 alone is above the cap, do not delete anything more; show a notice "Kept-offline and open books use X GB, above your limit of Y GB".
4. The file that was just downloaded is never a candidate in the same run.

**Leases (`in_use_until`)**
- When `ensure_local(book)` returns a path that is about to be opened in an **external reader**, set `in_use_until = now + 120 minutes` (setting `lease_minutes`) and renew it each time the book is opened again. External readers cannot tell the app when they close a file, so the lease is a time window.
- When a file cannot be deleted (Windows keeps it locked while a reader has it open), skip it, keep its row, and retry at the next cleanup.
- The built-in reader (v6) renews the lease while a tab is open and releases it when the tab closes.

**Planner and executor (`planner.py`, `executor.py`)**
- `plan_cleanup(now, reason)` collects `Action(area, path, size, reason_text)` objects from every area and returns a `CleanupPlan`. It **never deletes anything.**
- `execute(plan)` performs the deletions. The **dry run ("Preview cleanup") calls exactly the same `plan_cleanup`**, so what you preview is what runs. A test enforces this.
- Immediately before deleting each book's file, the executor **re-checks the lease and `last_used_at`** in the database (a book may have been opened after the plan was made) and skips it if it changed.
- **Safe deletion (`safe_delete`)**, all of which must hold or the file is skipped and reported:
  1. The cache folder contains a **marker file** (`.booklib-cache`, holding the area key) that the app created.
  2. The resolved path is inside that folder (`resolve()` then `is_relative_to`).
  3. The path is not a symbolic link or a Windows junction/reparse point, and no parent between the file and the cache root is one.
  4. The file is one the database knows about, or matches a known temporary name pattern (`*.part`, `*.tmp-*`).
- Delete the file first; if that succeeds, delete the database row and remove the now-empty `<file_id>/` folder with `rmdir`. A `PermissionError` keeps the row for the next run. A row whose file is already gone is simply deleted.
- Log each deletion (area, file name, size, reason) and a one-line summary (files removed, bytes freed). Keep the last summary in `app_meta` under `storage.last_cleanup` for the settings page.

**Disk-space guard (`guard.py`)**
```python
def ensure_space(path: Path, needed: int, purpose: str) -> None: ...   # raises LowDiskSpace
```
- Uses `shutil.disk_usage` on the drive that holds `path`. Passes if `free - needed >= min_free_bytes`.
- Otherwise runs an **emergency cleanup** (reason `low_space`) in this order and re-checks after each step: (1) temporary and partial files, (2) orphan cover files, (3) online cache, (4) `drive_downloads` Tier 2 oldest first, ignoring the age rule, (5) `drive_downloads` Tier 1 oldest first. **Tier 0 is never touched.**
- If space is still short, raise `LowDiskSpace` with a message that says how much is needed, how much is free and what the user can do; the calling job stops cleanly (a partial download keeps its `.part` file only if it is small; otherwise it is removed).
- Called by: the download engine (6.7), bulk downloads, deep index (once per book), and thumbnail fetches (small; checked once per batch).
- A **low-space banner** appears in the main window whenever free space on the cache drive is below `min_free_bytes` ("Low disk space: N GB free. [Clean up]").

**When cleanup runs (`scheduler.py`)**
- After each download and after each deep-indexed book (only that area's plan, so it is cheap).
- At startup, after a delay of about 60 seconds, low priority: consistency repair (remove `drive_cache` rows whose files are gone, delete files with no row older than one day, delete `.part` files older than seven days, delete leftover deep-index temp files) plus the full plan.
- Once a day while the app is running.
- On demand: **Clean now**, and automatically when the guard reports low space.
- Runs in the I/O lane as a light job; only one cleanup runs at a time; it never runs while a restore is staging.

**Cache location changes (extends the settings page)**
- A new cache folder must be **empty or created by the app** (it contains the marker file). If the chosen folder is non-empty and has no marker, refuse with an explanation. This prevents the cleaner from ever operating in a folder such as Documents.
- Moving the cache: offer **Move existing downloads** or **Start empty** (old files deleted after confirmation).

**Measuring usage (`usage.py`)**
- Sizes are measured with `os.scandir` in a background thread when a settings page is opened, and kept up to date incrementally by the download and eviction code. Never scan the whole cache during normal operation.

**Settings controls in v4 (Google Drive page, Cache section)**
- **Keep last [10] opened books**, **Keep books marked Reading** (checkbox), **Maximum cache size [5 GB]**, **Remove downloads not opened for [30] days**, **Minimum free disk space [2 GB]**, buttons **Preview cleanup** and **Clean now**, and the last cleanup summary ("Removed 6 files, 1.4 GB, 3 hours ago").

---

## 7. UI Sketches (v4 Additions)

**Add Drive folder dialog**
```
┌────────────── Add Google Drive folder ────────────────┐
│ Account: you@gmail.com  ▾                              │
│ 🔍 Search folders…                                     │
│ ▾ My Drive                                             │
│    ▾ Books                                             │
│       ▸ CS                                             │
│       ▸ Novels                                         │
│       ▸ Reference                                      │
│ ▸ Shared with me                                       │
│ ─────────────────────────────────────────────────────  │
│ Selected: My Drive/Books   (about 2,340 files)         │
│ ☑ Include subfolders     ☑ Sync automatically          │
│ ☐ Read metadata from files after indexing (3.4 GB)     │
│ ☐ Create collections from folder structure             │
│                             [Cancel]  [Add folder]     │
└────────────────────────────────────────────────────────┘
```

**Library badges and details (File section)**
```
Grid:  ┌────┐ ┌────┐ ┌────┐ ┌────┐        ☁  Drive only
       │ ☁  │ │ ☁✓ │ │ 📌 │ │    │        ☁✓ Downloaded
       └────┘ └────┘ └────┘ └────┘        📌 Kept offline
                                           (none) local file

▾ File
  Source:  Google Drive (you@gmail.com)
  Folder:  Books/CS/DSA
  Size:    4.2 MB     MD5: 9e107d9d…
  Cache:   ☁✓ Downloaded, 4.2 MB
  [Open] [Keep offline ☐] [Remove download] [Open in Drive]
```

**Status bar:** `Drive: synced 3 min ago` · `Syncing… 240 changes` · `Offline` · `⚠ Google Drive needs sign-in (Reconnect)`

---

## 8. Build Order (Milestones)

Finish and test each milestone before starting the next. Milestones 1 to 2 can be tested with a small command-line script before any interface exists.

| # | Milestone | What "done" looks like |
|---|---|---|
| 1 | **Cloud setup and sign-in** | README setup guide written; credentials import; browser sign-in works; refresh token in the credential store; app restarts without signing in again; disconnect works |
| 2 | **Drive client** | Listing (paged), folder info, changes, streaming download and thumbnail calls work; backoff and error mapping tested against a fake session; offline detection |
| 3 | **Migration 4 and source branching** | Backup and migration pass on a copy of your library; every code path that used `book.path` handles `source`; job manager has heavy and I/O lanes |
| 4 | **Folder picker and Add folder** | Lazy folder tree, shared-with-me, options, creates the folder row and starts the job |
| 5 | **Initial index** | Real Drive folder indexed with batches and progress; shortcuts resolved; Google-format files counted and skipped; rerun creates no duplicates; sync token saved |
| 6 | **Thumbnails, badges and sidebar** | Drive covers appear; source badges, Sources section, Drive info in the details pane, Open in Drive |
| 7 | **Download engine and open** | Double-click downloads with progress, resumes after cancel, verifies MD5, opens in the chosen reader |
| 8 | **Cache manager** | Limit and LRU eviction, keep offline, clear cache, consistency check, cache settings page |
| 8b | **Storage manager** | Areas registry, keep-recent, Reading and size-cap rules with protection tiers, leases, planner/executor with dry run equal to real run, marker files, disk-space guard with emergency cleanup, startup and daily sweeps, cache-location safety, settings controls |
| 9 | **Incremental sync** | Add, rename, move in/out, trash and delete in Drive are reflected correctly; full-resync fallback works; periodic and manual sync; status bar |
| 10 | **Deep index** | Size estimate and confirmation; metadata, cover, pages and ISBN filled; protected fields respected; resumable |
| 11 | **Duplicates across sources** | Drive vs local exact duplicates found by MD5; read-only safeguards |
| 12 | **Offline and error polish** | Offline behavior, Reconnect banner, quota and disk-full messages |
| 13 | **Relocate folder** | Prefix rewrite is correct, validation works, rescan relinks |
| 14 | **Backup** | Snapshot, zip, upload, list, prune, optional automatic backup |
| 15 | **Restore** | Verification, safety copy, restart swap, forward migration; tested on a fresh app-data folder |
| 16 | **Polish and testing** | 10,000-file Drive index, security review (no secrets in logs), updated README |

---

## 9. Testing Plan

**Unit tests (`pytest`), no real network calls**
- **Migration 3 to 4:** existing local books unchanged; new tables and columns present; running twice is safe.
- **Drive client with a fake session:** pagination, batched `in parents` queries, shortcuts, Google-native files skipped, files without `md5Checksum` or `size`, files with unusual MIME types, empty folders, and each retry class (429, 5xx, rate-limit 403) with backoff timing (patch the sleep function).
- **Auth wrapper:** in-memory fake `TokenStore`; `invalid_grant` sets `needs_signin`; a test that scans log output for tokens and secrets.
- **Ancestry logic:** a `drive_nodes` tree with nested roots, files moving in and out, unknown parents fetched once and cached (including the negative "outside" answer).
- **Change processing:** added, renamed, moved in, moved out, trashed, permanently removed, folder renamed (paths updated), md5 changed (cache invalidated, `index_level` reset); rename respects `field_sources`.
- **Token invalid → full resync:** simulate the invalid-token response and verify the fallback.
- **Download:** simulated interruption and resume with `Range`, MD5 mismatch retry once then error, atomic rename, cancel keeps `.part`, disk-space precheck.
- **File name sanitization:** reserved Windows names, illegal characters, trailing dots, very long names, Unicode names, duplicates with the same name in different Drive folders (separate per-id folders).
- **Cache:** LRU eviction order, pinned entries kept, just-downloaded file kept, locked file (simulate `PermissionError`) skipped, consistency check removes orphans.
- **Virtual paths:** uniqueness, and a test that fails if Drive `path` values reach filesystem functions in the scanner, opener and hasher.
- **Duplicates:** Drive/local MD5 matching, lazy MD5 only when sizes match, actions disabled for Drive books.
- **Backup:** snapshot taken with the backup API while another connection writes; zip contents (no tokens or credentials); manifest; prune keeps the newest N.
- **Restore:** integrity check failure refuses; newer schema refuses; older schema migrates; safety copy created.
- **Relocate:** prefix rewrite handles similar prefixes (`C:\Books` vs `C:\Books2`), trailing separators, and case differences on Windows.
- **Keep-recent rule:** with N = 10 and a cap large enough, the ten most recently opened books are never removed while older ones are; with a smaller cap the oldest of the ten go last and the cap is respected; N = 0 disables the rule.
- **Protection tiers:** pinned and leased books are never removed even when far above the cap (a notice is produced instead); Reading books are protected until the cap forces them out after all Tier 2 books.
- **Age rule:** removes only unprotected downloads older than the limit.
- **Recency:** ranking uses `last_opened_at`, and bulk-downloaded books that were never opened rank by `downloaded_at`.
- **Dry run equals real run:** the actions listed by the preview are exactly the ones executed on the same data.
- **Race safety:** a book opened between planning and execution is skipped.
- **Lease:** valid lease prevents removal; expired lease allows it; a locked file (simulated `PermissionError`) is skipped and kept in the table.
- **Safe deletion:** paths outside the cache root, symlinks and junctions, folders without the marker file, and files unknown to the database are refused; a cache location pointing at a non-empty folder without marker is rejected.
- **Sweeps:** stale `.part` files, orphan files, leftover deep-index temp files, superseded cover versions and orphan covers are removed; custom covers are not.
- **Online cache expiry:** 30-day and 7-day rules and the size cap.
- **Disk guard:** simulated low free space triggers the emergency order (temp, orphan covers, online cache, Tier 2, Tier 1), never touches Tier 0, and raises `LowDiskSpace` when it cannot free enough; downloads stop cleanly.
- **Startup repair:** after a simulated crash, rows without files and files without rows are repaired.

**Manual test checklist (with a real Drive account)**
- Complete the Cloud setup steps from the README on a clean machine; sign in; restart; still signed in.
- Revoke the app's access in your Google Account settings; the app shows the Reconnect banner and does not crash or spam errors; reconnect works.
- Index a folder with about 500 files including nested folders, a shortcut, a Google Doc and an unsupported file type; check counts in the summary.
- In Drive: add a file, rename one, move one within the synced folder, move one out, trash one; run **Sync now** and check each result; verify your status and rating survived the rename and the move.
- Open a PDF and an EPUB from Drive; check progress, cancel and resume, and that the reader window shows the real file name.
- Pin a book; fill the cache beyond the limit; pinned books stay and the oldest unpinned are removed.
- Turn off the network: cached books open, others show a clear message, the library still browses and searches.
- Deep-index a folder of about 50 books; compare metadata and covers with what the same files give locally.
- Duplicate a book locally and in Drive; the finder pairs them and the Recycle Bin action is unavailable for the Drive copy.
- Back up, then restore into a fresh app-data folder (or another computer): sign in, sync, relocate the local folder, check statuses, ratings, tags and custom covers.
- Performance with 10,000 Drive files: initial index completes with visible progress, the grid stays responsive, incremental sync of a few changes takes seconds.

---

## 10. Known Pitfalls and How to Handle Them

| Problem | Handling |
|---|---|
| Sign-in expires every 7 days | Consent screen left in Testing; switch to In production for your own app (section 3) and show a clear Reconnect banner when it happens anyway |
| "Google hasn't verified this app" screen | Expected for your own unverified project; documented in the setup guide |
| Restricted scope verification if you ever share the app | Do not ship your own credentials; users import their own `client_secret.json` |
| Keyring size limit or locked keyring | Store the refresh token only; clear error message if the store is unavailable |
| `googleapiclient` service objects are not thread-safe | REST via one `AuthorizedSession` per job |
| Google Docs, Sheets and Slides files | Skipped and counted; they have no size or checksum |
| Shortcuts to books | Index the target by its file id; dedupe repeated targets |
| Files with no `md5Checksum` or `size` | Treat as unsupported for download verification; skip verification but keep the size check where available |
| Files shared with you that live outside My Drive | Handled by the Shared with me root; ancestry uses `drive_nodes` with negative caching |
| Change feed contains changes for the entire account | Filter quickly with the ancestry cache; fetch unknown parents once; never scan all files |
| Saved change token becomes invalid | Automatic full re-list and comparison by file id |
| Rate limits (429 or 403 rate-limit reasons) | Backoff with jitter, limited concurrency (downloads 2 by default), batching of folder queries |
| Download quota errors on files shared by others | Show a clear message; suggest making a copy in your own Drive; your own files are normally unaffected (verify in the current documentation) |
| Partial or corrupt downloads | `.part` files, resume with `Range`, size and MD5 verification, atomic rename |
| Disk full | Pre-check free space, enforce the cache limit first, clear message |
| Windows keeps opened files locked, so eviction fails | Skip and retry later; never delete the file just opened |
| Very long or invalid Windows file names | Sanitized names in a per-file folder, length cap, reserved-name handling |
| The user deletes cache files by hand | Startup consistency check repairs the table |
| Thumbnail links expire | Fetch them during indexing; missing thumbnails fall back to placeholders and are retried by deep index |
| Drive file changes after it was cached | md5/mtime change from sync invalidates the cache entry and resets `index_level` |
| Code accidentally passes a virtual path to file functions | `is_drive()` helper, branching tests, a test that scans for risky calls |
| Backup made by copying a live WAL database | Always use `sqlite3` backup API and `integrity_check` |
| Restoring overwrites newer local data | Local safety copy first, show backup date and computer name, explicit confirmation |
| Restored local paths do not exist on a new computer | Unreachable folders warn instead of marking books missing; Relocate folder tool |
| Secrets end up in a Git repository or log | `.gitignore` for credentials, never log tokens, automated log scan test |
| App closed during an upload or sync | Resumable upload; sync token saved only with the last processed batch; jobs restartable |
| Accidentally deleting a Drive file | Not possible: read-only scope for library files; `drive.appdata` only touches the app's own backups |
| The cache fills the drive | Storage manager with cap, age rule, sweeps and the disk-space guard (6.15) |
| Cleanup removes the book you just opened or are still reading | Keep-recent and Reading protection, leases, re-check just before deleting, locked files skipped |
| The cache folder is pointed at a folder that holds other files | Marker file required; non-empty folders without a marker are refused |
| A junction or symbolic link makes cleanup delete outside the cache | Path containment and reparse-point checks on every deletion |
| Keep-recent and the cap conflict (10 huge recent books) | The cap wins; oldest recent books go last; pinned and open books are exempt with a warning |
| Old cover versions pile up after cover changes | Sweep files not referenced by `books.cover_path` (custom covers excluded) |
| Preview shows one thing and cleanup does another | One planner for both, covered by a test |

---

## 11. Definition of Done for v4

- [ ] Google sign-in works with your own credentials; sign-in survives restarts; the token is only in the credential store; disconnect works
- [ ] Drive folders can be browsed and added (My Drive and Shared with me), with subfolder and format options
- [ ] Initial indexing shows books quickly with filename-based metadata, Drive thumbnails where available, and a correct summary of skipped files
- [ ] Incremental sync reflects added, renamed, moved, trashed and deleted files, keeps your data through renames and moves, and recovers from an invalid sync token
- [ ] Opening a Drive book downloads it with progress, resume and MD5 verification, then opens it in the default or chosen reader
- [ ] Cache limit, LRU cleanup, Keep offline, Clear cache and Free up space work; the cache repairs itself after manual deletion
- [ ] Deep indexing fills real metadata, page counts, ISBNs and covers, respects your edits, and can be stopped and resumed
- [ ] Source badges, Sources sidebar section, source filter and sort, and Drive details (folder, account, Open in Drive) are in place
- [ ] Drive and local duplicates are detected; nothing in Drive can be deleted or changed by the app
- [ ] Offline mode and expired sign-in are handled gracefully with clear messages
- [ ] Library backup to Drive and restore work, including a restore on a fresh installation followed by folder relocation
- [ ] No tokens or secrets appear in logs, the database or the settings file
- [ ] A 10,000-file Drive library indexes and browses smoothly
- [ ] Unit tests pass for the Drive client, ancestry, changes, download, cache, sanitization, duplicates, backup, restore and relocate
- [ ] The download cache keeps the last N opened books and books marked Reading, respects the size cap and the age rule, and never removes pinned or open books
- [ ] Leftover files (`.part`, deep-index temp files, superseded or orphan covers, expired online cache) are swept automatically
- [ ] The disk-space guard stops downloads cleanly before the drive is full and frees regenerable data first
- [ ] **Preview cleanup** shows exactly what **Clean now** removes, and cleanup only ever deletes app-created files inside marked cache folders
- [ ] Unit tests pass for keep-recent, protection tiers, leases, safe deletion, sweeps and the disk guard

---

## 12. What Comes Next (Preview of v5)

v4 prepares v5 (Library Maintenance and Convenience) in several ways: `md5`, `keep_offline` and `drive_path` can be included in CSV/JSON export and import, the backup code is the foundation for local backup and restore, the cache and `ensure_local` step give format conversion a local copy to work on, and the read-only Drive scope keeps everything safe. Note for v5 planning: **auto-rename and organize files applies to local files only**, because renaming Drive files would need write access, which this app deliberately does not request. Version 5 adds file renaming to a pattern, format conversion through Calibre, import/export, reading statistics and yearly goals, keyboard shortcuts and drag-and-drop to add books.

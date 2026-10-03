# Addendum: Storage, Cache and Garbage Collection

This addendum adds a **Storage Manager** to the plans for **v4, v5 and v6**. It keeps cache and temporary files under control so that opening books never fills the drive, and it keeps the files of some recently opened books.

You will paste the text into the three existing plan files by hand. Everything below is arranged so you can do that without renumbering anything.

---

## 0. How to Use This File

### 0.1 Files and order
- `book-library-v4-plan.md` gets the **Part A** blocks (labels `V4-1` to `V4-9`).
- `book-library-v5-plan.md` gets the **Part B** blocks (labels `V5-1` to `V5-8`).
- `book-library-v6-plan.md` gets the **Part C** blocks (labels `V6-1` to `V6-8`).
- **Apply Part A first.** Part B and Part C refer to the storage manager that Part A introduces (section 6.15 in the v4 plan).

### 0.2 How each block is written
Every block has a small **"Where"** table telling you:
- **File**: which plan file to edit.
- **Section**: the heading in that file.
- **Position**: exactly where inside that section to put it.
- **Action**: `Append` (add new text), `Add rows` (add rows to an existing table), `Add items` (add checkboxes or bullets to a list), or `Replace` (swap old text for new text).

The text to paste sits between two marker lines:

**▼ PASTE START [label] ▼**
**▲ PASTE END [label] ▲**

Paste **only what is between the markers**. Do not paste the marker lines themselves.

### 0.3 Numbering (so nothing needs renumbering)
New numbers use a letter or a higher sub-number, for example feature `1.10`, section `6.15`, milestone `8b`. Existing numbers stay as they are. Where a milestone is added between two existing ones (like `8b`), keep the existing numbers.

### 0.4 Index of all insertions

| Label | File | Section | Position | Action |
|---|---|---|---|---|
| V4-1 | v4 plan | 1. Feature List | After 1.9 | Append feature 1.10 |
| V4-2 | v4 plan | 2. Key Design Decisions | Table end | Add rows |
| V4-3 | v4 plan | 4. What Changes | Table end | Add rows |
| V4-4 | v4 plan | 5. Database Changes | Replace the `drive_cache` table | Replace |
| V4-5 | v4 plan | 6.7 and 6.8 | Two small edits | Replace |
| V4-6 | v4 plan | 6. Implementation Details | After 6.14 | Append section 6.15 |
| V4-7 | v4 plan | 8. Build Order | After milestone 8 | Add row 8b |
| V4-8 | v4 plan | 9. Testing, 10. Pitfalls | Ends of both | Add items and rows |
| V4-9 | v4 plan | 11. Definition of Done | End of list | Add items |
| V5-1 | v5 plan | 1. Feature List | After 1.8 | Append feature 1.9 |
| V5-2 | v5 plan | 2. What Changes | Table end | Add rows |
| V5-3 | v5 plan | 3. Database Changes | Inside the migration 5 SQL | Add SQL |
| V5-4 | v5 plan | 4. Implementation Details | After 4.8 | Append section 4.9 and small edits |
| V5-5 | v5 plan | 5. Build Order | After milestones 1 and 10 | Add rows 1b and 10b |
| V5-6 | v5 plan | 6. Testing | End of the unit-test list | Add items |
| V5-7 | v5 plan | 7. Pitfalls | Table end | Add rows |
| V5-8 | v5 plan | 8. Definition of Done | End of list | Add items |
| V6-1 | v6 plan | 1. Feature List | After 1.7 | Append feature 1.8 |
| V6-2 | v6 plan | 3. What Changes | Table end | Add rows |
| V6-3 | v6 plan | 4. Database Changes | `fulltext.db` SQL | Replace |
| V6-4 | v6 plan | 5. Implementation Details | After 5.14 | Append section 5.15 and small edits |
| V6-5 | v6 plan | 6. Build Order | After milestones 6 and 9 and 15 | Add rows 6b, 9b, 15b |
| V6-6 | v6 plan | 7. Testing | End of the unit-test list | Add items |
| V6-7 | v6 plan | 8. Pitfalls | Table end | Add rows |
| V6-8 | v6 plan | 9. Definition of Done | End of list | Add items |

---

## 0.5 The Design in One Page (for your understanding; nothing here is pasted)

**The problem.** Opening a *local* book creates no copy: it is read from your folder. The disk risk comes from **cloud books** (downloaded to a cache when you open them), plus smaller leaks: half-finished downloads, temporary files from indexing and conversion, superseded cover files, the full-text index, logs and old snapshots.

**The solution.** One **Storage Manager** with:
1. A **registry of storage areas**, each with a kind, a limit and a cleanup policy.
2. A **keep-recent rule** for downloaded books: the last *N* opened books (default 10) and books marked Reading are protected from cleanup, but the size cap always wins.
3. A **disk-space guard** that checks free space before big operations and frees regenerable data automatically if space is short.
4. **Safe deletion:** only app-owned files, only inside marked folders, never your library folders.
5. A **dry run** ("Preview cleanup") that produces exactly the same plan the automatic cleanup would run.

**Three kinds of data**

| Kind | Meaning | Generic cleanup may delete it? |
|---|---|---|
| **Regenerable** | Can be recreated (downloaded copies, thumbnails, caches, temp files) | Yes, following each area's policy |
| **User data** | Cannot be recreated (custom covers, converted books, backups, exports) | No (backups follow their own retention rule) |
| **Protected** | The database, annotations, bookmarks, positions | Never |

**Areas by version**

| Area | Added in | Kind | Default policy |
|---|---|---|---|
| Downloaded cloud books | v4 | Regenerable | Keep last 10 opened and Reading books; size cap 5 GB; remove after 30 days unopened; pinned books exempt |
| Half-finished downloads (`.part`) | v4 | Regenerable | Removed after 7 days, sooner when disk space is low |
| Deep-index temp files | v4 | Regenerable | Deleted after each book; leftovers removed after 1 day |
| Cover files: orphans and superseded versions | v4 | Regenerable | Swept automatically (custom covers never touched) |
| Online lookup cache | v4 | Regenerable | Expires after 30 days (7 for "not found"); size cap 100 MB |
| Logs | v4 | Regenerable | Rotating files, 5 x 5 MB |
| Temp files outside the app folder (conversion, rename, copy, export) | v5 | Regenerable | Tracked in a registry; removed when the job ends and swept at startup |
| Safety snapshots | v5 | Regenerable | Newest 5 or 14 days |
| Local and Drive backups | v5 | User data | Retention rule only (keep newest N) |
| Full-text index | v6 | Regenerable | Size limit 2 GB: stop indexing and warn; never auto-delete; compact on request |
| Extractor worker temp folders | v6 | Regenerable | Removed on exit; swept at startup |
| Web-triggered cloud downloads | v6 | Regenerable | Same cache; daily download budget |
| Reader page cache | v6 | Memory only | 256 MB cap; nothing on disk |

**Not covered:** caches that *other* programs create when you open a file with them (for example an external reader's own cache folder). The app cannot manage those.

---

# PART A: Additions for `book-library-v4-plan.md`

## V4-1: New feature 1.10

| | |
|---|---|
| **File** | `book-library-v4-plan.md` |
| **Section** | 1. Feature List |
| **Position** | Directly after feature `1.9 Relocate folders` (before section 2) |
| **Action** | Append |

**▼ PASTE START [V4-1] ▼**

### 1.10 Storage and cache cleanup (garbage collection)
- **Keep the last N opened books:** downloaded books you opened recently stay on disk (default the last 10). Books you marked **Reading** are kept too (option, on by default). Both are protected from routine cleanup.
- **The size cap always wins:** if the protected books alone exceed the cap, the oldest of them go first. **Kept offline (pinned)** books and books that are open in a reader are never removed; if they alone exceed the cap, the app warns instead of deleting.
- **Remove old downloads:** downloads not opened for a set number of days (default 30) are removed, unless protected.
- **Automatic sweeps** of leftovers: half-finished downloads, temporary indexing files, superseded or orphan cover files, expired online-lookup cache entries.
- **Disk-space guard:** before a download or deep-index run, the app checks free space (default minimum: the larger of 2 GB or 5% of the drive). If space is short it frees regenerable data automatically; if that is not enough, it stops with a clear message instead of filling the disk.
- **Safe by design:** cleanup only deletes files the app itself created, only inside its own cache folders, never inside your library folders.
- **Preview cleanup:** a dry run shows exactly what would be removed and why; the automatic cleanup uses the same plan.
- Controls in the Google Drive settings page (a full Storage page for all areas comes in v5): keep last N, size cap, remove after N days, minimum free space, **Clean now**.

**▲ PASTE END [V4-1] ▲**

---

## V4-2: Two rows for the design decisions table

| | |
|---|---|
| **File** | `book-library-v4-plan.md` |
| **Section** | 2. Key Design Decisions |
| **Position** | End of the table (after the `Integrity` row) |
| **Action** | Add rows |

**▼ PASTE START [V4-2] ▼**

| Cache retention | **Keep-recent rule plus size cap plus age rule**, run by a storage manager (section 6.15) | Size-only least-recently-used cleanup can delete the book you opened yesterday. Keeping the last N opened books matches how people read; the hard cap still protects the disk |
| Deleting files | Only app-created files inside cache folders that contain a marker file; dry run equals real run | A cleanup feature that deletes the wrong folder is worse than a full disk |

**▲ PASTE END [V4-2] ▲**

---

## V4-3: Rows for the "What Changes" table

| | |
|---|---|
| **File** | `book-library-v4-plan.md` |
| **Section** | 4. What Changes in the v1 to v3 Code |
| **Position** | End of the table (after the `Settings` row) |
| **Action** | Add rows |

**▼ PASTE START [V4-3] ▼**

| Cover cache (v3) | Superseded versions (`<id>_<n>.jpg`) and orphan files are swept by the storage manager; custom covers are never touched |
| Online cache (v3) | Expiry and size cap enforced by the storage manager instead of only at lookup time |
| Logging (v1) | Rotating file handler with a size limit, if not already set |
| New package | `storage/` (areas, planner, executor, guard, scheduler) used by the download engine, deep index, cache manager and thumbnails |
| Download and deep-index code | Call the disk-space guard before starting and register a lease while a cached book is in use |

**▲ PASTE END [V4-3] ▲**

---

## V4-4: Replace the `drive_cache` table in migration 4

| | |
|---|---|
| **File** | `book-library-v4-plan.md` |
| **Section** | 5. Database Changes (Migration 4) |
| **Position** | Replace the existing `CREATE TABLE drive_cache (...)` block and its `CREATE INDEX idx_drive_cache_used` line |
| **Action** | Replace |

**▼ PASTE START [V4-4] ▼**

```sql
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
```

**Notes**
- `in_use_until` is the **lease** described in section 6.15. It is set when a cached book is handed to a reader and renewed while it is open. Cleanup never removes a book whose lease has not expired.
- Recency for the keep-recent rule comes from `books.last_opened_at` (v2), falling back to `drive_cache.downloaded_at` for books that were downloaded but never opened.

**▲ PASTE END [V4-4] ▲**

---

## V4-5: Two small edits in sections 6.7 and 6.8

| | |
|---|---|
| **File** | `book-library-v4-plan.md` |
| **Section** | 6.7 Download engine and 6.8 Cache manager |
| **Position** | See each edit below |
| **Action** | Replace |

**Edit 1: in 6.7, steps list, step 1.** Replace the sentence
`Check free disk space (needs size + 10%); enforce the cache limit first (6.8).`
with:

**▼ PASTE START [V4-5a] ▼**
Ask the **disk-space guard** (section 6.15) for `size + 10%` free space on the cache drive; the guard applies the cleanup policy first if space is short, and refuses the download with a clear message if it still cannot make room.
**▲ PASTE END [V4-5a] ▲**

**Edit 2: in 6.8, the bullet that starts `**Limit:**`.** Replace that whole bullet with:

**▼ PASTE START [V4-5b] ▼**
- **Limit and retention:** the cache is governed by the storage manager (section 6.15): the **keep-last-N-opened** rule, the **size cap** (default 5 GB), and an optional **age rule**. Pinned books and books with an active lease are never evicted, and the file just downloaded is never evicted.
**▲ PASTE END [V4-5b] ▲**

The other bullets of 6.8 (locked files, pin/unpin, consistency check, settings page) stay; the consistency check now runs as part of the storage manager's startup sweep (6.15).

---

## V4-6: New section 6.15 (the core of the storage manager)

| | |
|---|---|
| **File** | `book-library-v4-plan.md` |
| **Section** | 6. Implementation Details |
| **Position** | Directly after section `6.14 Query, sidebar and settings` (before section 7) |
| **Action** | Append |

**▼ PASTE START [V4-6] ▼**

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

**▲ PASTE END [V4-6] ▲**

---

## V4-7: Milestone 8b

| | |
|---|---|
| **File** | `book-library-v4-plan.md` |
| **Section** | 8. Build Order (Milestones) |
| **Position** | New row directly after milestone `8 Cache manager` |
| **Action** | Add row |

**▼ PASTE START [V4-7] ▼**

| 8b | **Storage manager** | Areas registry, keep-recent, Reading and size-cap rules with protection tiers, leases, planner/executor with dry run equal to real run, marker files, disk-space guard with emergency cleanup, startup and daily sweeps, cache-location safety, settings controls |

**▲ PASTE END [V4-7] ▲**

*(Tip: you can implement milestone 8 directly with the rules from section 6.15 and treat 8b as the checklist for finishing it.)*

---

## V4-8: Testing items and pitfalls rows

| | |
|---|---|
| **File** | `book-library-v4-plan.md` |
| **Section** | 9. Testing Plan (unit tests) and 10. Known Pitfalls |
| **Position** | End of the unit-test bullet list; end of the pitfalls table |
| **Action** | Add items / add rows |

**▼ PASTE START [V4-8a: testing bullets] ▼**

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

**▲ PASTE END [V4-8a] ▲**

**▼ PASTE START [V4-8b: pitfalls rows] ▼**

| The cache fills the drive | Storage manager with cap, age rule, sweeps and the disk-space guard (6.15) |
| Cleanup removes the book you just opened or are still reading | Keep-recent and Reading protection, leases, re-check just before deleting, locked files skipped |
| The cache folder is pointed at a folder that holds other files | Marker file required; non-empty folders without a marker are refused |
| A junction or symbolic link makes cleanup delete outside the cache | Path containment and reparse-point checks on every deletion |
| Keep-recent and the cap conflict (10 huge recent books) | The cap wins; oldest recent books go last; pinned and open books are exempt with a warning |
| Old cover versions pile up after cover changes | Sweep files not referenced by `books.cover_path` (custom covers excluded) |
| Preview shows one thing and cleanup does another | One planner for both, covered by a test |

**▲ PASTE END [V4-8b] ▲**

---

## V4-9: Definition of Done items

| | |
|---|---|
| **File** | `book-library-v4-plan.md` |
| **Section** | 11. Definition of Done for v4 |
| **Position** | End of the checkbox list (before section 12) |
| **Action** | Add items |

**▼ PASTE START [V4-9] ▼**

- [ ] The download cache keeps the last N opened books and books marked Reading, respects the size cap and the age rule, and never removes pinned or open books
- [ ] Leftover files (`.part`, deep-index temp files, superseded or orphan covers, expired online cache) are swept automatically
- [ ] The disk-space guard stops downloads cleanly before the drive is full and frees regenerable data first
- [ ] **Preview cleanup** shows exactly what **Clean now** removes, and cleanup only ever deletes app-created files inside marked cache folders
- [ ] Unit tests pass for keep-recent, protection tiers, leases, safe deletion, sweeps and the disk guard

**▲ PASTE END [V4-9] ▲**

---

# PART B: Additions for `book-library-v5-plan.md`

## V5-1: New feature 1.9

| | |
|---|---|
| **File** | `book-library-v5-plan.md` |
| **Section** | 1. Feature List |
| **Position** | Directly after feature `1.8 Drag and drop and Add files` (before section 2) |
| **Action** | Append |

**▼ PASTE START [V5-1] ▼**

### 1.9 Storage page and disk-space protection
- **Settings, Storage page:** one place that shows every area the app stores data in (downloaded books, covers, indexes, snapshots, backups, logs), its size, its limit and its policy, with **Preview cleanup**, **Clean now**, **Open folder**, and per-area controls.
- **Largest cached books** list with **Remove** and **Keep offline** buttons.
- **Temporary-file registry:** any temporary file the app creates outside its own folders (conversion output, rename temp names, copy temp names, export files being written, backup uploads) is recorded first and removed when the job ends. Leftovers from crashes are swept at startup.
- **Disk-space guard for v5 operations:** conversion, Add files, backup, restore, compact and export check free space before starting and refuse with a clear message instead of failing half-way.
- **Library health** gains storage checks (areas over their limit, leftover temp files, low free space, missing cache marker).
- **Retention** for v5 data: safety snapshots (newest 5 or 14 days), conversion log entries (180 days), backups (keep newest N).
- Command palette actions: **Clean up storage now**, **Open Storage settings**.

**▲ PASTE END [V5-1] ▲**

---

## V5-2: Rows for the "What Changes" table

| | |
|---|---|
| **File** | `book-library-v5-plan.md` |
| **Section** | 2. What Changes in the v1 to v4 Code |
| **Position** | End of the table (after the `Settings` row) |
| **Action** | Add rows |

**▼ PASTE START [V5-2] ▼**

| Storage manager (v4) | Extended with v5 areas (safety snapshots, backups, temp registry) and a Storage page that shows all areas |
| Conversion, rename, Add files, export, backup code | Register temporary files, call the disk-space guard first, release temp registrations when done |
| Library health | New storage checks (section 4.9) |
| Job manager | Cleanup jobs must not run while a maintenance-lane job (rename apply, restore, compact, import) is active |

**▲ PASTE END [V5-2] ▲**

---

## V5-3: SQL for the temp-file registry

| | |
|---|---|
| **File** | `book-library-v5-plan.md` |
| **Section** | 3. Database Changes (Migration 5) |
| **Position** | Inside the migration 5 SQL block, directly before the line `PRAGMA user_version = 5;` |
| **Action** | Add SQL |

**▼ PASTE START [V5-3] ▼**

```sql
-- registry of temporary files created outside the app's own folders
CREATE TABLE temp_files (
    id         INTEGER PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,
    purpose    TEXT NOT NULL,          -- 'convert' | 'rename' | 'copy' | 'export' | 'backup'
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_temp_files_created ON temp_files(created_at);
```

**▲ PASTE END [V5-3] ▲**

---

## V5-4: New section 4.9 and small edits to earlier subsections

| | |
|---|---|
| **File** | `book-library-v5-plan.md` |
| **Section** | 4. Implementation Details |
| **Position** | Directly after section `4.8 Drag and drop and Add files` (before section 5) |
| **Action** | Append (block V5-4a), then apply the small edits (block V5-4b) |

**▼ PASTE START [V5-4a] ▼**

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

**▲ PASTE END [V5-4a] ▲**

**▼ PASTE START [V5-4b: small edits to existing subsections] ▼**

Add the following sentence or bullet to each existing subsection listed (place it at the end of that subsection):

| Existing subsection | Text to add |
|---|---|
| 4.1 Rename and organize, **Executor** | "Register the temporary name used for case-only renames with `register_temp`, and release it after the final rename. Before creating the safety snapshot for large batches, call the disk-space guard (section 4.9)." |
| 4.2 Conversion, **Command** and **Job flow** | "Register the temporary output name with `register_temp` before starting Calibre and release it after the atomic rename or on failure or cancel. Call the disk-space guard (source size x 2, destination drive) before starting each conversion. If the guard refuses, report it as a skipped conversion with the reason." |
| 4.3 Export and import, **Export** | "Write exports to a registered temporary name and rename on success. Check free space on the destination first." |
| 4.4 Backup, restore and safety snapshots | "Safety snapshots and backups follow the retention table in section 4.9. Call the guard before a snapshot, a backup or a restore. Register the temporary upload name for local-folder backups." |
| 4.5 Library health | "Add the four storage checks from section 4.9. Compact (`VACUUM`) calls the guard first." |
| 4.8 Drag and drop and Add files | "Register the temporary copy name with `register_temp`; call the guard for the total size of the files before copying; if there is not enough space, tell the user how much is needed." |

**▲ PASTE END [V5-4b] ▲**

---

## V5-5: Milestones 1b and 10b

| | |
|---|---|
| **File** | `book-library-v5-plan.md` |
| **Section** | 5. Build Order (Milestones) |
| **Position** | Row `1b` directly after milestone `1`; row `10b` directly after milestone `10` |
| **Action** | Add rows |

**▼ PASTE START [V5-5: row 1b] ▼**

| 1b | **Temp-file registry and guard hooks** | `temp_files` table and `register_temp`/`release_temp`; startup sweep; guard estimates for v5 operations; a fake failing job leaves no temp file behind |

**▲ PASTE END [V5-5: row 1b] ▲**

**▼ PASTE START [V5-5: row 10b] ▼**

| 10b | **Storage page and health integration** | Storage page with all areas, preview and run cleanup, Clear regenerable data, largest cached books, low-space banner, four new health checks, command palette actions |

**▲ PASTE END [V5-5: row 10b] ▲**

---

## V5-6: Testing items

| | |
|---|---|
| **File** | `book-library-v5-plan.md` |
| **Section** | 6. Testing Plan |
| **Position** | End of the **Unit tests** bullet list (before the manual checklist) |
| **Action** | Add items |

**▼ PASTE START [V5-6] ▼**

- **Temp-file registry:** register then release leaves no row; a job that fails or is cancelled at every step leaves no temporary file; startup sweep removes registered leftovers; a registered path whose name does not match the temp pattern is **not** deleted.
- **Guard estimates:** each operation in the estimate table calls the guard with the right size and drive; a simulated low-space condition stops conversion, Add files, backup, restore and compact cleanly with a clear message and no partial output.
- **Retention:** safety snapshots (newest 5 or 14 days, never the one in use), backup retention (never deletes the last good backup or anything after a failed upload), log-row purges.
- **Storage page logic:** usage measurement, preview lists the same actions as the real run, **Clear regenerable data** never includes user data or protected data, pinned and open books are skipped.
- **Health checks:** the four storage checks detect a crafted bad state (over limit, leftover temp file, missing marker) and their fixes work.
- **Interaction with maintenance jobs:** cleanup does not start while a rename apply, restore, compact or import is running.

**▲ PASTE END [V5-6] ▲**

---

## V5-7: Pitfalls rows

| | |
|---|---|
| **File** | `book-library-v5-plan.md` |
| **Section** | 7. Known Pitfalls and How to Handle Them |
| **Position** | End of the table |
| **Action** | Add rows |

**▼ PASTE START [V5-7] ▼**

| A crashed conversion or copy leaves a temporary file inside a library folder | Register temp files first; sweep them at startup; only delete registered paths whose names match the temp pattern |
| Cleanup deletes something in a library folder | Cleanup only touches marked app folders and registered temp files; user data such as converted books and exports is never an area for generic cleanup |
| A conversion or backup fills the drive halfway | Disk-space guard with per-operation estimates; the job refuses to start rather than failing midway |
| Cleanup runs during a rename batch, restore or import | Mutual exclusion with the maintenance lane |
| Regenerable data is cleared but the user expected it kept | **Preview cleanup**, a confirmation listing exactly what will go, and a default that keeps recent, Reading, pinned and open books |
| `VACUUM` fails for lack of space | The guard checks database size plus 10% first |

**▲ PASTE END [V5-7] ▲**

---

## V5-8: Definition of Done items

| | |
|---|---|
| **File** | `book-library-v5-plan.md` |
| **Section** | 8. Definition of Done for v5 |
| **Position** | End of the checkbox list (before section 9) |
| **Action** | Add items |

**▼ PASTE START [V5-8] ▼**

- [ ] The Storage page shows every storage area with size, limit and policy, and **Preview cleanup** matches **Clean now**
- [ ] Temporary files created by conversion, rename, copy, export and backup are registered and never left behind after failures, cancels or crashes
- [ ] Conversion, Add files, backup, restore and compact check free disk space first and stop cleanly with a clear message when it is short
- [ ] Safety snapshots and backups follow their retention rules and never delete the last good backup
- [ ] Library health includes the four storage checks with working fixes
- [ ] Unit tests pass for the temp-file registry, guard integration, retention and the Storage page logic

**▲ PASTE END [V5-8] ▲**

---

# PART C: Additions for `book-library-v6-plan.md`

## V6-1: New feature 1.8

| | |
|---|---|
| **File** | `book-library-v6-plan.md` |
| **Section** | 1. Feature List |
| **Position** | Directly after feature `1.7 Other cloud sources (optional)` (before section 2) |
| **Action** | Append |

**▼ PASTE START [V6-1] ▼**

### 1.8 Storage limits for the new data
- **Full-text index size limit** (default 2 GB): when it is reached, indexing pauses and the app tells you; nothing is deleted automatically. You can raise the limit, remove the index of books you have not opened for a chosen time, remove the index of selected folders, or **Compact** the index to give the space back to the disk.
- **Books you are reading stay available:** a cloud book open in the reader is protected from cleanup while its tab is open, and the keep-recent and Reading rules from v4 apply to books opened in the built-in reader.
- **Worker temp folders** used by background extraction are removed when a worker ends and swept at startup, even after a crash.
- **Daily budget for web downloads:** cloud books requested from a phone through the web interface count against a daily limit (default 2 GB) and pass the disk-space guard, so a phone cannot fill the drive.
- **Log rotation** for the web access log.
- The Storage page (v5) shows the new areas and the reader's memory cache.

**▲ PASTE END [V6-1] ▲**

---

## V6-2: Rows for the "What Changes" table

| | |
|---|---|
| **File** | `book-library-v6-plan.md` |
| **Section** | 3. What Changes in the v1 to v5 Code |
| **Position** | End of the table (after the `Settings` row) |
| **Action** | Add rows |

**▼ PASTE START [V6-2] ▼**

| Storage manager (v4, v5) | New areas: full-text index, extractor temp folders, web-triggered downloads, web log; the reader and web server renew leases on cached books |
| `fulltext.db` creation | Creates the file with incremental auto-vacuum so space can be reclaimed after deletions |
| Extractor process pool | Each worker gets its own temp folder and a per-file temp-space limit |
| Web server | Downloads of cloud books use the disk-space guard and a daily budget |

**▲ PASTE END [V6-2] ▲**

---

## V6-3: Replace the `fulltext.db` SQL

| | |
|---|---|
| **File** | `book-library-v6-plan.md` |
| **Section** | 4. Database Changes (Migration 6), the **`fulltext.db`** block |
| **Position** | Replace the whole SQL block under the heading `fulltext.db (separate database file, created on first use)` |
| **Action** | Replace |

**▼ PASTE START [V6-3] ▼**

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

**▲ PASTE END [V6-3] ▲**

---

## V6-4: New section 5.15 and small edits to earlier subsections

| | |
|---|---|
| **File** | `book-library-v6-plan.md` |
| **Section** | 5. Implementation Details |
| **Position** | Directly after section `5.14 Settings (new pages)` (before section 6) |
| **Action** | Append (block V6-4a), then apply the small edits (block V6-4b) |

**▼ PASTE START [V6-4a] ▼**

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

**▲ PASTE END [V6-4a] ▲**

**▼ PASTE START [V6-4b: small edits to existing subsections] ▼**

Add the following sentence or bullet to each existing subsection listed (place it at the end of that subsection):

| Existing subsection | Text to add |
|---|---|
| 5.1 Reader architecture, **Process and thread model** | "Extractor worker processes use per-worker temp folders that are removed on exit and swept at startup (section 5.15)." |
| 5.2 Rendering pipeline | "The page cache is memory only (no disk spill); its cap is a setting and it can be cleared from the Storage page." |
| 5.9 Opening flow and integration | "`ensure_local(book, lease=True)` renews a lease on the cached file while the tab is open and releases it on close (section 5.15). Books opened in the reader count as recently opened for the keep-recent rule." |
| 5.10 Full-text search, **Scheduling** and **Storing** | "Before indexing a book, check the index size limit and free space (section 5.15); when either is exceeded, pause with reason `size_limit` or `low_space` and notify. After deleting a book's chunks, run an incremental vacuum step." |
| 5.12 Web server, **Cloud books** | "Cloud downloads triggered from the web interface check the guard and the daily budget first, hold a lease while streaming, and do not count as opened (section 5.15)." |
| 5.13 Other cloud sources | "Downloads from every provider go through the same cache table and the same storage policies as Google Drive." |

**▲ PASTE END [V6-4b] ▲**

---

## V6-5: Milestones 6b, 9b and 15b

| | |
|---|---|
| **File** | `book-library-v6-plan.md` |
| **Section** | 6. Build Order (Milestones) |
| **Position** | Row `6b` after milestone `6`; row `9b` after milestone `9`; row `15b` after milestone `15` |
| **Action** | Add rows |

**▼ PASTE START [V6-5: row 6b] ▼**

| 6b | **Leases for open books** | Built-in reader renews and releases leases on cached cloud books; the storage manager never evicts a book that is open in a tab; opens in the reader count as recent |

**▲ PASTE END [V6-5: row 6b] ▲**

**▼ PASTE START [V6-5: row 9b] ▼**

| 9b | **Index limit, compaction and extractor temp cleanup** | Index size limit with pause and notice; trim by age or folder; compact and incremental vacuum; extractor temp folders removed on exit and swept at startup; Storage page rows added |

**▲ PASTE END [V6-5: row 9b] ▲**

**▼ PASTE START [V6-5: row 15b] ▼**

| 15b | **Web download budget and guard** | Cloud downloads from the web interface respect the guard, the daily budget and leases; web log rotates |

**▲ PASTE END [V6-5: row 15b] ▲**

---

## V6-6: Testing items

| | |
|---|---|
| **File** | `book-library-v6-plan.md` |
| **Section** | 7. Testing Plan |
| **Position** | End of the **Unit tests** bullet list (before the manual checklist) |
| **Action** | Add items |

**▼ PASTE START [V6-6] ▼**

- **Index limit:** reaching the limit pauses the scheduler with reason `size_limit`, books stay `queued`, nothing is deleted; raising the limit resumes; low free space pauses with reason `low_space`.
- **Index trimming:** removing the index for books not opened for N days deletes only those books' chunks and resets their `fts_state`; other books remain searchable; a never-opened book is trimmed first.
- **Compaction:** with incremental auto-vacuum, the file size drops after deleting chunks; a database created without it is detected and offered a one-time `VACUUM`; the compact action uses the guard.
- **Extractor temp folders:** removed on normal exit and after a simulated crash (sweep at startup); a worker that exceeds the 500 MB temp limit aborts the file and marks it `failed`.
- **Leases:** an open reader tab keeps renewing; closing releases immediately; a crash lets the lease expire; the storage manager skips a book with a valid lease even when the cap is exceeded.
- **Recency:** opening a book in the reader updates `last_opened_at`; fetching it through the web server does not.
- **Web budget:** downloads stop at the daily budget, the counter resets on the next local day, low space blocks a download with a friendly message, and only one web-triggered download runs at a time.
- **Log rotation:** the web access log rotates at the configured size and count.

**▲ PASTE END [V6-6] ▲**

---

## V6-7: Pitfalls rows

| | |
|---|---|
| **File** | `book-library-v6-plan.md` |
| **Section** | 8. Known Pitfalls and How to Handle Them |
| **Position** | End of the table |
| **Action** | Add rows |

**▼ PASTE START [V6-7] ▼**

| The full-text index keeps growing and eats the drive | Size limit that pauses indexing, opt-in per folder, trim by age or folder, compaction, size shown on the Storage page |
| The index file does not shrink after deleting books | Incremental auto-vacuum set at creation, incremental vacuum after deletions, one-time `VACUUM` for older files |
| Extractor workers leave temp folders after a crash | Per-worker temp folders, cleanup in `finally`, startup sweep by process id and age |
| A book is evicted while it is open in the reader | Lease renewed while the tab is open; locked files are skipped |
| A phone (or anyone with the password) fills the drive through cloud downloads | Guard check, daily budget, one download at a time, log entries |
| Web browsing pushes your own books out of the recent list | Web downloads do not count as opened |
| Logs grow without limit | Rotating handlers for app and web logs |

**▲ PASTE END [V6-7] ▲**

---

## V6-8: Definition of Done items

| | |
|---|---|
| **File** | `book-library-v6-plan.md` |
| **Section** | 9. Definition of Done for v6 |
| **Position** | End of the checkbox list (before section 10) |
| **Action** | Add items |

**▼ PASTE START [V6-8] ▼**

- [ ] The full-text index has a size limit that pauses indexing with a clear notice, can be trimmed, compacted and deleted, and never removes anything automatically unless the optional rule is on
- [ ] Extractor temp folders never accumulate, even after crashes
- [ ] Books open in the built-in reader are never evicted while open, and count as recently opened
- [ ] Web-triggered cloud downloads respect the disk-space guard and the daily budget, and do not affect the keep-recent list
- [ ] Logs rotate; the Storage page shows all v6 areas and the reader's memory cache
- [ ] Unit tests pass for index limits and trimming, compaction, extractor temp cleanup, leases, recency and the web budget

**▲ PASTE END [V6-8] ▲**

---

## Quick Reference: Defaults

| Setting | Default | Where it appears |
|---|---|---|
| Keep last N opened books | 10 (0 to 100) | v4 settings, v5 Storage page |
| Keep books marked Reading | On | v4, v5 |
| Download cache size cap | 5 GB | v4, v5 |
| Remove downloads not opened for | 30 days (0 = off) | v4, v5 |
| Minimum free disk space | larger of 2 GB or 5% of the drive | v4, v5 |
| Lease length for external readers | 120 minutes | v4 |
| Lease length for the built-in reader | 5 minutes, renewed every 60 s | v6 |
| Partial downloads removed after | 7 days (sooner when space is low) | v4 |
| Online cache | 30 days (7 for not found), cap 100 MB | v4 |
| Logs | 5 files x 5 MB | v4, v6 |
| Safety snapshots | newest 5 or 14 days | v5 |
| Conversion log | 180 days | v5 |
| Full-text index limit | 2 GB | v6 |
| Web download daily budget | 2 GB | v6 |
| Reader page cache (memory) | 256 MB | v6 |

# Personal Book Library: Feature Roadmap (Desktop App)

A desktop app to organize PDF, EPUB and other ebooks into a browsable library, with cover thumbnails, a details pane, reading tracking and Google Drive integration.

**Legend:** ⭐ = original idea, no mark = added suggestion

**Suggested stack:** Python + PySide6 (Qt), SQLite, PyMuPDF (PDF), ebooklib (EPUB), Google API client (Drive)

---

## Version 1: Core Local Library (MVP)

*Goal: scan folders and browse your books.*

- [ ] ⭐ Add a folder (including subfolders) and scan for PDF, EPUB and other formats (MOBI, AZW3, DJVU, CBZ, TXT)
- [ ] SQLite database to store the library, so nothing is re-scanned on every launch
- [ ] ⭐ Basic metadata: title, author, format, size, page count (from the file where available, otherwise from the filename)
- [ ] ⭐ Cover thumbnails: EPUB cover image and first page of a PDF, generated once and cached
- [ ] ⭐ Library grid view with a details pane
- [ ] ⭐ Sorting by title, author, year, size, format, date added
- [ ] ⭐ Open with the system default app
- [ ] Rescan / remove-missing-files button

## Version 2: Reading Tracking and Better Browsing

*Goal: make it feel like a real library.*

- [ ] ⭐ Reading status: Want to Read / Reading / Read
- [ ] ⭐ "Open with" menu listing other installed readers
- [ ] Search bar (title, author, tags)
- [ ] Filters by status, format, genre, author
- [ ] List view alongside grid view
- [ ] Manual metadata editing (fix wrong titles, authors, etc.)
- [ ] Star ratings and personal notes
- [ ] Dark mode
- [ ] "Recently added" and "Continue reading" sections

## Version 3: Metadata Enrichment and Organization

*Goal: complete the details pane automatically.*

- [ ] Online lookup via Open Library / Google Books by ISBN or title (publisher, year, edition, ISBN, genre, better covers)
- [ ] Bulk metadata fetch and bulk edit
- [ ] Tags, collections/shelves, and series with reading order
- [ ] Duplicate detection (file hash and ISBN)
- [ ] Watch folders that auto-import new books
- [ ] Start and finish dates, and reading progress (page X of Y)
- [ ] Custom cover replacement

## Version 4: Google Drive Integration

*Goal: bring your Drive repository into the library.*

- [ ] ⭐ Google sign-in via OAuth, with the token stored securely
- [ ] ⭐ Browse and pick Drive folders, then index the books in them
- [ ] Download on demand and cache locally (cache size limit and "clear cache" option)
- [ ] Mark books as "Drive" or "Local" with an icon
- [ ] Optional: upload or back up the library database to Drive

## Version 5: Library Maintenance and Convenience

- [ ] Auto-rename and organize files as `Author - Title (Year)`
- [ ] Format conversion (EPUB ↔ PDF and others) through Calibre's `ebook-convert`
- [ ] Import/export the library as CSV or JSON, plus database backup and restore
- [ ] Reading stats and yearly goals (e.g. "read 20 books this year")
- [ ] Keyboard shortcuts and drag-and-drop to add books

## Version 6: Advanced Features

- [ ] Built-in reader for PDF and EPUB, with bookmarks and remembered position
- [ ] Full-text search inside book contents
- [ ] Highlights and annotations
- [ ] Recommendations based on your ratings
- [ ] Local web access to browse the library from a phone
- [ ] Optional: other cloud sources (OneDrive, Dropbox)

---

## Planning Tips

1. **Finish each version before starting the next.** Even v1 alone is a useful app.
2. **Design the database for later versions from day one.** Include columns such as `status`, `rating`, `source` (local or Drive) and `file_hash` even if v1 does not use them yet. This avoids painful migrations later.
3. **Metadata is the hardest part.** EPUB metadata is reliable, PDF metadata often is not. Plan for online lookup and manual editing.
4. **Keep the UI and the data layer separate**, so features like the phone web view (v6) can reuse the same database code.

# Test Fixtures

Place small sample files here for fixture-based tests:

- `sample.epub`  – an EPUB 2 or EPUB 3 with metadata
- `sample.pdf`   – a PDF with title/author metadata
- `sample_no_meta.pdf` – a PDF with no metadata (filename fallback)
- `sample.cbz`   – a CBZ archive
- `corrupt.pdf`  – a zero-byte or broken file (should be skipped silently)

These are used by `test_metadata.py` when present.

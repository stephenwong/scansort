# ScanSort

**ScanSort** is an intelligent, automated Windows desktop application that monitors a scanner drop folder, waits for scan completion, indexes your pre-existing `Documents` folder taxonomy, classifies documents via Google Gemini 2.5 Flash, auto-rotates skewed/upside-down pages, embeds searchable metadata for Windows Search, standardizes filenames to `YYMMDD_<Description>.pdf`, and dispatches them into the deepest matching subfolder.

## Features
- **Zero-Leak Secret Vault:** API keys are encrypted at the OS level using Windows Credential Manager (DPAPI via `keyring`).
- **Rust-Powered Filesystem Watcher:** Uses `watchfiles` (Rust `notify` crate) with native debouncing to handle multi-page ADF scanner writes.
- **Deepest Subfolder Matching:** Scans your real `Documents` folder and files into the most specific leaf folder.
- **Auto Page-Orientation:** Gemini detects upside-down or sideways scans; ScanSort automatically rotates pages right-side up.
- **Windows Search Indexing:** Embeds `Title`, `Subject` (summary), and `Keywords` directly into standard PDF XMP metadata.
- **SHA-256 Duplicate Detection:** Detects accidental re-scans, routes them to `_Review_Needed/Duplicates/`, and saves API tokens.
- **System Tray & Toast Integration:** Runs silently in the background with 1-click "Open in Folder" (`explorer.exe /select`) and "Undo Last Move".
- **Dry-Run Mode:** Test and preview classification decisions without altering files on disk.

## Development & Testing
Developed strictly using **Test-Driven Development (TDD)**:
```bash
# Run tests
uv run pytest -v

# Code quality check
uv run ruff check .
```

## Documentation
- Detailed product requirements and technical architecture: [Product Requirements Document (PRD)](docs/PRD.md)


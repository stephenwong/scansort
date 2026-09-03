# AGENTS.md — Agent & Contributor Guide for ScanSort

This document defines repository instructions, architectural invariants, coding conventions, and operational workflows for autonomous AI coding agents and human contributors working on **ScanSort**.

---

## 1. Project Overview & Philosophy

**ScanSort** is a zero-touch, privacy-conscious desktop document organizer for Windows (with cross-platform support). It monitors a physical scanner drop folder, waits for scan completion, discovers pre-existing `Documents` taxonomies, classifies documents via Google Gemini 2.5 Flash, rights page orientation, embeds XMP metadata for Windows Search, and dispatches files atomically to the deepest matching subfolder.

### Core Tenets
1. **Zero-Leak Security:** API keys are encrypted at the OS level (Windows Credential Manager / DPAPI via `keyring`). Keys must **NEVER** be written to `config.json`, committed to Git, or exposed in plaintext in logs or exception traces.
2. **Non-Destructive Routing:** ScanSort never deletes unmatched files or invents rogue directory paths. Unmatched, ambiguous (<70% confidence), or error states strictly route to `Documents/_Review_Needed/`.
3. **Atomic File Safety:** All file movements must be atomic with automatic collision resolution (`YYMMDD_Desc_1.pdf`) to guarantee zero data loss.
4. **Offline First & Rate Limited:** Sequential queue-based processing prevents scanner write collisions and avoids hitting Google Gemini API rate limits.

---

## 2. Repository Layout & Module Map

```
scansort/
├── .github/workflows/          # CI and Release workflows (Windows runners)
├── docs/
│   └── PRD.md                  # Comprehensive technical specification & requirements
├── scansort/                   # Core Python package (Python >=3.12)
│   ├── __init__.py             # Version definition
│   ├── __main__.py             # CLI entrypoint & subcommands (watch, config, undo, rescan)
│   ├── audit_logger.py         # Dual crash-safe JSONL and CSV logging engine
│   ├── autorun.py              # Windows Registry (HKCU Run) & Linux autostart manager
│   ├── config.py               # Pydantic configuration loader (%APPDATA%\ScanSort\config.json)
│   ├── dispatcher.py           # Collision resolution, atomic moves, and move reversal
│   ├── file_stabilizer.py      # Exclusive file-lock polling and size growth tracker
│   ├── folder_hints.py         # User keyword aliases loader (folder_hints.json)
│   ├── folder_mapper.py        # Recursive taxonomy scanner with noise & dotfile filtering
│   ├── gemini_client.py        # Multimodal Gemini 2.5 Flash structured classification
│   ├── hasher.py               # Streaming SHA-256 duplicate scan interception
│   ├── image_converter.py      # Lossless JPEG stream wrapping (img2pdf) & image normalization
│   ├── pdf_metadata.py         # XMP metadata embedding & pypdf auto-rotation
│   ├── pipeline.py             # End-to-end coordinator & sequential queue worker
│   ├── secrets.py              # OS credential vault, key masking, & regex log redaction
│   └── watcher.py              # Rust-powered watchfiles monitor with debouncing
├── tests/                      # Pytest automated test suite (>=95% coverage enforced)
├── pyproject.toml              # Astral uv project config, ruff, & pytest-cov settings
├── scansort.spec               # PyInstaller standalone Windows executable build spec
├── config.example.json         # Reference configuration template
├── folder_hints.example.json   # Reference keyword hints template
└── README.md                   # User-facing manual with Mermaid architecture diagrams
```

---

## 3. Mandatory Development Invariants

When modifying or extending ScanSort, you **MUST** uphold the following rules:

### A. Secret Protection
- **Never** add fields to `AppConfig` that serialize API keys to `config.json`.
- When displaying keys in UI or CLI, always wrap with `scansort.secrets.mask_api_key()` (`AIza••••••••XXXX`).
- When logging exception strings that may touch the API client, wrap with `scansort.secrets.redact_secrets_from_text()`.

### B. Filename & Path Sanitization
- Generated filenames must strictly adhere to `YYMMDD_<Description>.pdf`.
- Document descriptions must be sanitized via `sanitize_description()`:
  - English only (translated if foreign).
  - Format: `Title_Case_With_Underscores`.
  - Strip Windows-illegal characters: `< > : " / \ | ? *` and excessive punctuation.
  - Maximum character cap: 60 characters.

### C. File Ingestion & Stability
- Physical scanners write files progressively. **Never** process an incoming file immediately on filesystem notification.
- Always wait for write stabilization via `file_stabilizer.wait_for_file_stability()` which verifies file size stagnation and non-blocking exclusive file handle availability.

### D. Duplicate Prevention
- Compute streaming SHA-256 before invoking Gemini OCR.
- Check against `history.jsonl`. Duplicates must be routed to `Documents/_Review_Needed/Duplicates/` with status `DUPLICATE` without invoking Gemini, saving API quota.

### E. Orientation & Windows Search Indexing
- If Gemini returns non-zero `orientation_correction` (90°, 180°, 270°), rotate pages using `pypdf`.
- Embed DocInfo and XMP metadata (`Title`, `Subject`, `Keywords`, `Author`) into every output PDF to enable native Windows Start Menu search indexing.

---

## 4. Development Toolchain & Commands

ScanSort is built with modern Python 3.12+ and managed with Astral's `uv` toolchain.

### Common Commands
```bash
# Sync virtual environment & dependencies
uv sync

# Run complete test suite (automatically enforces >=95% coverage)
uv run pytest

# Run tests in quiet mode
uv run pytest -q

# Run Ruff linter
uv run ruff check .

# Auto-fix Ruff lint errors
uv run ruff check --fix .

# Check code formatting
uv run ruff format --check .

# Format code
uv run ruff format .

# Build standalone Windows executable via PyInstaller
uv run pyinstaller scansort.spec
```

---

## 5. Testing & Code Quality Standards

1. **Coverage Threshold:** Every file in `scansort/` must maintain at least **95% line coverage**. Total repository coverage must not fall below **95%**. This is strictly enforced in `pyproject.toml` via:
   ```toml
   [tool.pytest.ini_options]
   addopts = "--cov=scansort --cov-report=term-missing --cov-fail-under=95"
   ```
2. **Mocking Standards:**
   - Never make live network requests to Google Gemini in unit tests. Mock `google.genai.Client` and `types.GenerateContentConfig`.
   - Never write to real OS credential managers during test execution. Mock `keyring.get_password`, `keyring.set_password`, and `keyring.delete_password`.
   - Use `tmp_path` fixtures for all filesystem tests.
3. **Style & Linting:** Code must adhere to strict Ruff rules (`E`, `F`, `I`, `B`, `SIM`, `DTZ`, `BLE`). Do not use bare `except Exception:` unless re-raising or wrapping specific expected I/O and network exceptions.

---

## 6. CI/CD Build Pipeline & Pre-Push Verification Protocol

GitHub Actions runs the `.github/workflows/ci.yml` pipeline on a `windows-latest` runner for every pull request and push to `main`. To ensure the build **NEVER goes red**, agents and contributors must execute and verify the exact 3 gates that CI checks before pushing:

### The 3 Mandatory CI Gates (Run before every push):
```bash
# Gate 1: Lint check (Must exit 0 with 0 errors)
uv run ruff check .

# Gate 2: Code formatting check (Must exit 0 with 0 unformatted files)
# IMPORTANT: Always run `uv run ruff format .` before pushing!
uv run ruff format --check .

# Gate 3: Test suite & Coverage check (Must exit 0, 100% tests passing, >=95% coverage)
uv run pytest
```

### Why Builds Fail & How to Prevent It:
1. **Unformatted Code (`ruff format --check` failure):**
   - *Cause:* Code or tests were written/edited without running `uv run ruff format .`.
   - *Fix:* Always run `uv run ruff format .` before staging files with `git add`.
2. **Coverage Drop below 95% (`--cov-fail-under=95` failure):**
   - *Cause:* New branches, conditions, or exception blocks were introduced without corresponding test coverage.
   - *Fix:* Add unit tests for both happy and error paths so coverage stays $\ge 95\%$.
3. **OS-Specific Assumptions (Windows Runner):**
   - *Cause:* Paths hardcoded as strings instead of `pathlib.Path`, or platform-specific modules invoked without `sys.platform == "win32"` checks.
   - *Fix:* Use `pathlib.Path` objects everywhere and mock platform-specific APIs (`winreg`, `msvcrt`) properly.

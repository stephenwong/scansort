# AGENTS.md — Agent & Contributor Guide for ScanSort

This document defines repository instructions, architectural invariants, coding conventions, and operational workflows for autonomous AI coding agents and human contributors working on **ScanSort**.

---

## 1. Project Overview & Philosophy

**ScanSort** is a zero-touch, privacy-conscious desktop document organizer for Windows (with cross-platform support). It monitors a physical scanner drop folder, waits for scan completion, discovers pre-existing `Documents` taxonomies, classifies documents via Google Gemini, rights page orientation, embeds XMP metadata for Windows Search, and dispatches files atomically to the deepest matching subfolder.

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
├── working-docs/               # Working documentation & PRD
│   └── PRD.md                  # Comprehensive technical specification & requirements
├── scansort/                   # Core Python package (Python >=3.14)
│   ├── __init__.py             # Version definition
│   ├── __main__.py             # Thin CLI entrypoint shim
│   ├── classification/         # Multimodal Gemini classification & taxonomy mapping
│   │   ├── __init__.py         # Package interface re-exports
│   │   ├── client.py           # Multimodal Gemini structured classification client
│   │   ├── hints.py            # User keyword aliases loader (folder_hints.json)
│   │   ├── models.py           # Classification domain models & sanitizers
│   │   └── taxonomy.py         # Recursive taxonomy scanner with noise filtering & caching
│   ├── cli/                    # Modular CLI subcommands and entrypoint router
│   │   ├── __init__.py         # Package interface re-exports
│   │   ├── config.py           # Configuration viewing and editing handler
│   │   ├── parser.py           # Unified argument parser builder
│   │   ├── rescan.py           # Taxonomy discovery and display handler
│   │   ├── root.py             # Main CLI execution router and console attachment
│   │   ├── undo.py             # Reversal command handler
│   │   ├── update.py           # Check-update and self-update handlers
│   │   └── watch.py            # Watch and background monitor handler
│   ├── core/                   # Shared foundational utilities, constants, and configuration
│   │   ├── __init__.py         # Package interface re-exports
│   │   ├── config.py           # Pydantic configuration loader (%APPDATA%\ScanSort\config.json)
│   │   ├── constants.py        # Shared domain constants & defaults
│   │   ├── fs.py               # Atomic writes, collision resolution, safe path validation, & advisory locks
│   │   └── timeutil.py         # Australia/Sydney wall-clock time helpers
│   ├── document/               # Document conversion, normalization, and PDF manipulation
│   │   ├── __init__.py         # Package interface re-exports
│   │   ├── converter.py        # Lossless JPEG/PNG/TIFF to PDF stream wrapping (img2pdf / Pillow)
│   │   └── metadata.py         # XMP metadata embedding & pypdf auto-rotation
│   ├── logging/                # Modular diagnostics, auditing, and cost accounting
│   │   ├── __init__.py         # Package interface re-exports
│   │   ├── audit.py            # Dual crash-safe JSONL and CSV logging engine
│   │   ├── cost.py             # Gemini API token usage accounting & USD cost estimation (3.1 & 3.5 Flash Lite)
│   │   ├── gemini_logger.py    # Structured model response, reasoning, and token logging
│   │   └── setup.py            # Persistent rotating file + stderr console logging (scansort.log)
│   ├── pipeline/               # Ingestion pipeline, watcher, stabilizer, hasher, dispatcher, & worker
│   │   ├── __init__.py         # Package interface re-exports
│   │   ├── coordinator.py      # End-to-end ScanSortPipeline coordinator
│   │   ├── dispatcher.py       # Destination safety resolution, collision handling, and atomic filing
│   │   ├── hasher.py           # Streaming SHA-256 duplicate scan interception
│   │   ├── stabilizer.py       # Exclusive file-lock polling and size growth tracker
│   │   ├── undo.py             # Filing move reversal, drop folder restoration, & audit update
│   │   ├── watcher.py          # Rust-powered watchfiles monitor with debouncing
│   │   └── worker.py           # Sequential queue worker with shutdown draining
│   ├── platform/               # Platform and OS integrations (Windows Registry, toasts, credentials, locks, console)
│   │   ├── __init__.py         # Package interface re-exports
│   │   ├── autorun.py          # Windows Registry (HKCU Run) & Linux autostart manager
│   │   ├── console.py          # Windows GUI-subsystem console attachment (AttachConsole/stdout/stderr)
│   │   ├── instance_guard.py   # Non-blocking single-instance lock (fcntl/msvcrt)
│   │   ├── notifications.py    # Reusable filing-lifecycle toast messages (success/failure/stranded)
│   │   ├── secrets.py          # OS credential vault, key masking, & regex log redaction
│   │   └── toasts.py           # Windows native toast notifications (lazy optional 'windows' extra)
│   └── updater/                # Modular GitHub Releases self-update engine
│       ├── __init__.py         # Package interface re-exports
│       ├── downloader.py       # Chunked streaming, SHA-256 verification, zip extraction, & staging
│       ├── feed.py             # Release feed query, tag parsing, & candidate evaluation
│       ├── installer.py        # Rollback-safe directory swap, collision handling, & lock retry
│       ├── process.py          # Process waiting, detached child spawn, & helper orchestration
│       └── state.py            # Update state persistence & check interval tracking
├── tests/                      # Pytest automated test suite (>=95% coverage enforced)
│   ├── classification/         # Tests for client, hints, models, and taxonomy
│   ├── cli/                    # Tests for modular CLI subcommands and parser
│   ├── core/                   # Tests for config, constants, and fs utilities
│   ├── document/               # Tests for converter and metadata engines
│   ├── logging/                # Tests for audit, setup, cost, and gemini_logger
│   ├── pipeline/               # Tests for coordinator, dispatcher, hasher, stabilizer, undo, watcher, worker
│   ├── platform/               # Tests for autorun, console, instance_guard, notifications, secrets, toasts
│   ├── updater/                # Tests for downloader, feed, installer, process, and state
│   └── conftest.py             # Global test isolation fixtures & hermetic mocks
├── pyproject.toml              # Astral uv project config, ruff, & pytest-cov settings
├── scansort.spec               # PyInstaller standalone Windows executable build spec (embeds dynamic PE version info)
├── config.example.json         # Reference configuration template
├── folder_hints.example.json   # Reference keyword hints template
└── README.md                   # User-facing manual with Mermaid architecture diagrams
```

---

## 3. Mandatory Development Invariants

When modifying or extending ScanSort, you **MUST** uphold the following rules:

### A. Secret Protection
- **Never** add fields to `AppConfig` that serialize API keys to `config.json`.
- When displaying keys in UI or CLI, always wrap with `scansort.platform.secrets.mask_api_key()` (`AIza••••••••XXXX`).
- When logging exception strings that may touch the API client, wrap with `scansort.platform.secrets.redact_secrets_from_text()`.

### B. Filename & Path Sanitization
- Generated filenames must strictly adhere to `YYMMDD_<Description>.pdf`.
- Document descriptions must be sanitized via `sanitize_description()`:
  - English only (translated if foreign).
  - Format: `Title_Case_With_Underscores`.
  - Strip Windows-illegal characters: `< > : " / \ | ? *` and excessive punctuation.
  - Maximum character cap: 60 characters (whole-word truncation; NFKC-normalized, Unicode format characters removed).
- Dates are validated as real calendar dates; date-stamped fallbacks use **Australia/Sydney** wall-clock time (see `scansort.core.timeutil`, bundled `tzdata` dependency).

### C. File Ingestion & Stability
- Physical scanners write files progressively. **Never** process an incoming file immediately on filesystem notification.
- Always wait for write stabilization via `scansort.pipeline.stabilizer.wait_for_file_stability()` which verifies file size stagnation and non-blocking exclusive file handle availability.
- Advisory lock probes cannot detect plain `write()`-based writers: the pipeline requires a ~1 s size-quiescence window and re-verifies the source (size + mtime) immediately before dispatch; defer rather than file a partial snapshot. Stabilization on a vanished file must fail fast (never spin the timeout).
- The watcher must sweep pre-existing drop-folder files at every cycle start so scans that arrived while the app was off are still filed.

### D. Duplicate Prevention & Safe Move Reversal
- Compute streaming SHA-256 before invoking Gemini OCR.
- Check against `history.jsonl`. Duplicates must be routed to `Documents/_Review_Needed/Duplicates/` with status `DUPLICATE` without invoking Gemini, saving API quota.
- When reversing moves via `scansort undo`, restored files in the drop folder are prefixed with `_undone_` (e.g., `_undone_YYMMDD_Desc.pdf`). The drop folder watcher strictly ignores files with this prefix to prevent automated re-filing loops. Both `history.jsonl` and `history.csv` are atomically updated with `UNDONE` status.
- `undo_last_move` may raise `OSError` on a failed physical restore (the CLI reports it); records lacking `original_path` or whose recorded destination is a directory are skipped.

### E. Orientation & Windows Search Indexing
- If Gemini returns non-zero `orientation_correction` (90°, 180°, 270°), rotate pages using `pypdf` (assign `page.rotation` so `/Rotate` stays canonical mod 360).
- Embed DocInfo and XMP metadata (`Title`, `Subject`, `Keywords`, `Author`) into every output PDF to enable native Windows Start Menu search indexing: generate an XMP packet on every output and preserve any pre-existing `/Metadata` stream.

### F. In-Place PDF Modification on Windows
- Always buffer PDF bytes into `io.BytesIO` before parsing with `pypdf` when replacing files in-place. On Windows, active file handles cause `PermissionError: [WinError 32]` during atomic replacement (`tmp_path.replace(target_path)`).
- Always clean up temporary files in `try...finally` blocks.

### G. Path Traversal & Destination Defenses
- Never trust model-generated `target_folder` values or user-specified `fallback_folder` settings. Reject leading slashes, Windows drive letters (e.g., `C:\`, `D:/`), and `..` traversal segments.
- Verify that destination directories strictly satisfy `target_dir.is_relative_to(docs_root)`.
- Enforce that `watch_folder` and `documents_root` cannot be the same directory **or contain each other** (containment in either direction enables self-filing feedback loops). Paths located under a regular file are rejected.
- Only the exact `_Review_Needed` literal may bypass the taxonomy membership gate — never a `_Review_Needed*` prefix — so model-invented subfolders are never auto-created.
- Semantically invalid `config.json` settings cause fail-fast `ValueError`s naming the offending fields; never silently reset a parseable config to defaults or persist a fallback model.
- Taxonomy discovery must skip symlinks/junctions (escape- or cycle-prone) and, on Windows, hidden-attribute folders; the folder cache is revalidated on a TTL so deleted folders are never advertised/re-created.

### H. Intermediate File Isolation
- Never write intermediate PDFs or temporary conversion files into the monitored drop folder. Always store working files in the application temp directory (`app_dir / "tmp"`).

### I. Worker Fault Tolerance & Rate Limiting
- The background processing worker must never crash on transient API rate limits (429/503) or network disconnects.
- Route failing items to `_Review_Needed/` (fallback folder) with a `FAILED` audit record and diagnostic logging, and keep the queue worker alive. The worker drains the queue on shutdown.
- Resolve-then-move critical sections (`dispatch_file`, duplicate routing, `undo_last_move`) must hold the cross-process advisory lock (`app_dir/operations.lock`, `scansort.core.fs.interprocess_file_lock`); on a move failure, clean up any partial destination before re-raising.
- Audit CSV headers must be created without truncation (`"x"`/append-when-empty, never `"w"`), cells are neutralized against spreadsheet-formula prefixes and un-encodable surrogates, and CSV/JSONL writes guard `(OSError, UnicodeError)`.

### J. Strict Test-Driven Development (TDD) & Zero "Test Slop"
- **Always write tests first:** For any new feature, bug fix, or behavioral change, write failing automated tests before writing production code.
- **Purposeful & Functional Tests:** Every test must have a distinct functional purpose and test a real contract, behavior, edge condition, or failure mode.
- **Zero Test Slop:** Never write shallow, hollow, or meaningless tests purely to inflate coverage metrics (e.g., testing tautologies, over-mocking until no production logic executes, or executing code paths without meaningful assertions). All tests must rigorously validate expected outputs and side-effects.

### K. Mandatory Documentation Synchronization
- **Always Update Context & Documentation:** Whenever modifying, adding, or refactoring features, CLI options, architectural invariants, configuration settings, or error handling, you **MUST** update `README.md` and repository context files (`AGENTS.md`) to reflect the changes before committing. Never leave user documentation or agent context files stale or out of sync with production code.

### L. Windows Text File & BOM Compatibility
- Always use `encoding="utf-8-sig"` when reading user configuration and hint files (`config.json`, `folder_hints.json`) to transparently support files saved with a UTF-8 Byte Order Mark (BOM) by Windows Notepad.

### M. Single-Instance Guard & Self-Update Safety
- The background watcher must hold the non-blocking single-instance lock (`app_dir/instance.lock`, `scansort.platform.instance_guard.instance_guard`) for its entire lifetime; a second `watch` process exits immediately instead of running a duplicate, double-filing watcher. The self-update swap must re-acquire this guard (plus `app_dir/update.lock`) before touching the install directory.
- `scansort.updater` must **never** run an update check, download, or install outside a frozen Windows build with `auto_update` enabled: development runs (Linux or `python -m scansort`) are inert. Do not add API keys, tokens, or other secrets to the update channel or state files.
- Release candidates must satisfy every gate: tag parses as clean `vMAJOR.MINOR.PATCH` (no pre-releases), asset name is exactly `ScanSort-<tag>-windows-x64.zip`, and the version is strictly newer than both the embedded `__version__` and the last applied version recorded in `app_dir/update_state.json` (malformed/missing state must count as "due for a check"). Updates check on every launch by default (`update_check_interval_days: 0`, bounded `0..60`). Users can manually check for updates anytime via `scansort check-update`. Persist check timestamps only after a completed decision/hand-off so failed installs retry on the next launch.
- Downloads must be streamed to `app_dir/tmp` and verified against the declared size and, when GitHub publishes one, the SHA-256 digest. Archive extraction must reject absolute paths, `..` segments, and Windows drive prefixes (ZipSlip), and require a root `ScanSort.exe` before any swap.
- **Installer & Process Separation (`scansort.updater.installer`, `scansort.updater.process`):** Installation swapping, directory management, process waiting, and helper execution are encapsulated in the modular `scansort.updater` package. Install swaps are rollback-safe: rename the current install aside, rename the staged tree into place, and only then remove the backup; on any step failure rename the backup back and exit nonzero — the auto-start target must never point at a missing directory. Staging lives in a sibling directory of the install directory (same volume).
- **CWD Safety & Transient Lock Tolerance:** On Windows, holding a directory as CWD prevents rename or deletion. The parent process shifts CWD to `install_dir.parent` before spawning the helper, the helper is spawned with `cwd=install_dir.parent`, and `perform_self_update` ensures its own CWD is outside `install_dir` and `staged_dir`. Directory renames (`_rename_dir_with_retry`) retry with backoff on transient sharing violations (`WinError 32` / `WinError 5`) while antivirus (Windows Defender) and kernel handle teardown finish clearing.
- The helper (spawned staged build, hidden `--self-update` mode) waits for the old PID using a native `OpenProcess`/`WaitForSingleObject` handle — never `os.kill(pid, 0)`, which is not an existence probe on Windows. If `OpenProcess` fails with `ERROR_ACCESS_DENIED` during parent termination, it polls until handle acquisition or `ERROR_INVALID_PARAMETER` (process gone). Detached children must use `DETACHED_PROCESS | CREATE_NO_WINDOW` with all standard handles closed.
- Toasts (`scansort.platform.toasts`) are best-effort and never raise: they no-op off-Windows, lazily import the optional `windows-toasts` extra, and swallow display failures. The "update installed" toast must be fired by the *relaunched* app from the `just_installed` state marker — never by the helper after the swap, whose bundled module paths no longer exist. Filing-lifecycle messages (filed / failed-with-reason / stranded) live in `scansort.platform.notifications` with word-for-word testable builders under the `ScanSort` title; failure reasons shown in toasts must be whitespace-collapsed, secret-redacted, and truncated (~140 chars). Notifications support interactive click-to-open targeting the destination directory (`os.startfile` / system file manager) and, on failure states, provide a native "View Logs" action button opening `scansort.log`. The toast backend retains active toasts in a bounded memory buffer so WinRT activation callbacks survive garbage collection during background operation.

### N. Windowed Build Console Attachment (`ScanSort.exe` CLI Visibility)
- The packaged exe is a GUI-subsystem build (`console=False`) whose standard streams are null writers, so `print()` output is invisible unless attached to a console. `main_cli` calls `scansort.platform.console.attach_parent_console()` on entry (re-exported as `scansort.__main__._attach_parent_console` for backward compatibility): in a frozen Windows build only, best-effort `AttachConsole(ATTACH_PARENT_PROCESS)` re-points `sys.stdout`/`sys.stderr` at the launching terminal's console (streams line-buffered and encoded for `GetConsoleOutputCP`, falling back to UTF-8). Every failure mode (no parent console from double-click/auto-start/detached self-update helper, missing/invalid standard handles, Win32 API errors, missing `msvcrt`) must return silently so tray/background operation never raises or flashes a terminal. Attachment must never run in development (`python -m scansort`) — guard on `sys.frozen` and `sys.platform == "win32"`, and only when stdout is not already a TTY.

### O. Persistent & Modular Logging Architecture (Diagnostics & Cost Visibility)
- Logging is modularized in `scansort/logging/` (`setup.py`, `audit.py`, `cost.py`, `gemini_logger.py`).
- Every `main_cli` entry (all subcommands, including the detached `--self-update` helper) calls `scansort.logging.configure_file_logging(level=...)` so diagnostics survive operation where no console exists. It attaches a rotating `scansort.log` handler (INFO or DEBUG with `--verbose` / `-v`, 1 MB × 3 backups, UTF-8) in `app_dir` plus a console stderr handler. Repeat calls for the same directory reuse handlers without stacking duplicates.
- Root-logger level is lowered to INFO (or DEBUG under `--verbose`) so messages pass logger-level filtering. File logging is best-effort and never raises: `mkdir` or log-file open failures return `None` silently and must not abort any command, filing, update, or self-update path.
- **Model Evaluation & Cost Visibility:** ScanSort supports only `gemini-3.1-flash-lite` (default) and `gemini-3.5-flash-lite`. Multimodal Gemini calls log structured classification events via `gemini_logger.py` including prompt/candidate/total token counts, execution latency (ms), and estimated USD cost based on official Gemini Flash Lite pricing ($0.075 input / $0.30 output per 1M tokens) in `cost.py`. Gemini's natural language `folder_reasoning` and ScanSort's deterministic `routing_rationale` are captured and logged at INFO level (raw API payloads at DEBUG), and recorded in `history.jsonl` for auditability.
- Secrets stay covered by invariant A: only pre-redacted text (via `scansort.platform.secrets.redact_secrets_from_text()`) may ever reach the log file — audit summaries in `history.jsonl` remain truncated to 100 chars, the full redacted reason lives in `scansort.log`.

### P. Version Bumping (Single Source of Truth)
- `scansort/__init__.py::__version__` is the **only place** the version is defined.
- **To bump the version:**
  1. Edit `__version__ = "X.Y.Z"` in `scansort/__init__.py`.
  2. Commit and push the matching git tag:
     ```bash
     git commit -am "chore: bump version to X.Y.Z"
     git tag vX.Y.Z
     git push origin main --tags
     ```
- `pyproject.toml`, the CLI (`--version`), and `scansort.spec` (Windows `ProductVersion`) all derive the version automatically. Never hardcode version strings anywhere else.

---

## 4. Development Toolchain & Commands

ScanSort is built with modern Python 3.14+ and managed with Astral's `uv` toolchain.

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

1. **Mandatory Test-Driven Development (TDD):**
   - **Step 1 (Red):** Before implementing any bug fix, enhancement, or new feature, write automated unit tests that reproduce the defect or specify the intended behavior. Run `uv run pytest` and verify that the tests fail for the expected reason.
   - **Step 2 (Green):** Write the minimal clean production code necessary to satisfy the test requirements.
   - **Step 3 (Refactor):** Refactor for code quality, clarity, and architectural adherence while keeping tests 100% passing.
2. **Zero Test "Slop" Policy:**
   - Tests must have a concrete, functional purpose. Every test must validate real business logic, error propagation, safety invariants, or edge conditions.
   - **No Coverage Hacks / Dummy Tests:** Do not write tests whose only goal is to artificially satisfy coverage lines (e.g., executing code without asserting results, asserting trivial tautologies like `assert True`, or mocking away all actual behavior).
   - **Meaningful Assertions:** Always assert specific return values, raised exception types and messages, file mutations, and filesystem side-effects.
3. **Coverage Threshold:** Every file in `scansort/` must maintain at least **95% line coverage**. Total repository coverage must not fall below **95%**. This is strictly enforced in `pyproject.toml` via:
   ```toml
   [tool.pytest.ini_options]
   addopts = "--cov=scansort --cov-report=term-missing --cov-fail-under=95"
   ```
 4. **Mocking Standards:**
   - Never make live network requests to Google Gemini in unit tests. Mock `google.genai.Client` and `types.GenerateContentConfig`.
   - Never write to real OS credential managers during test execution. Mock `keyring.get_password`, `keyring.set_password`, and `keyring.delete_password`.
   - Never make live requests to the GitHub Releases API in unit tests. Inject a fake `opener` (a callable accepting `(Request, timeout)` and returning a context-managed byte stream) into `fetch_latest_release` / `download_release`.
   - Simulate the optional `windows_toasts` library by injecting a fake module via `patch.dict("sys.modules", {"windows_toasts": fake})`; never construct the real WinRT backend in tests.
   - Windows-native branches (`sys.platform == "win32"`) must be exercised with `monkeypatch.setattr("sys.platform", "win32")` plus fakes injected for `msvcrt`/`ctypes`, mirroring the existing `winreg` seam pattern, so coverage is identical on Linux and Windows runners.
   - Use `tmp_path` fixtures for all filesystem tests.
5. **Style & Linting:** Code must adhere to strict Ruff rules (`E`, `F`, `I`, `B`, `SIM`, `DTZ`, `BLE`). Do not use bare `except Exception:` unless re-raising or wrapping specific expected I/O and network exceptions.

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

# ScanSort

> **Intelligent, Automated Desktop Document Organizer Powered by Google Gemini 2.5 Flash**

ScanSort is a zero-touch Windows desktop utility designed for automated, local document management. It monitors a scanner drop folder, waits for physical scanner writes to complete, indexes your pre-existing `Documents` directory hierarchy, classifies incoming scans via Google Gemini 2.5 Flash, automatically rights upside-down or sideways pages, embeds searchable metadata for native Windows Search indexing, standardizes filenames to `YYMMDD_<Description>.pdf`, and dispatches documents directly into the deepest matching subfolder.

---

## Architecture & System Design

ScanSort is built with modular, loosely coupled components designed around safety, speed, and privacy.

### System Component Architecture

```mermaid
graph TB
    subgraph Input ["Scanner Input & Ingestion"]
        Scanner["Physical Scanner / ADF"] -->|Writes PDF/JPG/PNG| DropFolder["Scanner Drop Folder\n(%USERPROFILE%\\Scans\\Inbox)"]
        DropFolder -->|Rust Inotify Event| Watcher["Watcher Engine\n(watchfiles debounce: 1500ms)"]
        Watcher -->|Thread-safe Push| Queue["Worker Queue\n(FIFO Producer-Consumer)"]
    end

    subgraph Processing ["Processing Pipeline (scansort.pipeline)"]
        Queue -->|Pop Item| Stabilizer["File Stabilizer\n(Lock Polling & Growth Tracking)"]
        Stabilizer --> Hasher["SHA-256 Hasher\n(Duplicate Scan Interceptor)"]
        Hasher -->|New Scan| Converter["Image Normalizer\n(img2pdf Lossless / Pillow)"]
        Hasher -->|Duplicate Detected| DupReview["Documents\\_Review_Needed\\Duplicates"]
        
        Converter --> Mapper["Folder Mapper & Taxonomy\n(Documents Tree & folder_hints.json)"]
        Mapper --> Gemini["Gemini 2.5 Flash Client\n(Multimodal OCR & Classification)"]
        
        Gemini --> MetadataEngine["PDF Metadata & Orientation\n(pypdf Auto-Rotate & XMP Embedding)"]
        MetadataEngine --> Dispatcher["Dispatcher\n(Collision Resolution & Atomic Move)"]
    end

    subgraph Storage ["Destination & Audit"]
        Dispatcher --> DestDocs["Target Leaf Folder\n(Documents\\Utilities\\Electricity\\...)"]
        Dispatcher --> FallbackReview["Documents\\_Review_Needed"]
        Dispatcher --> Audit["Audit Logger\n(history.jsonl & history.csv)"]
    end

    subgraph Security ["Security & OS Integration"]
        Vault["Windows Credential Vault\n(DPAPI via keyring)"] -.->|Supplies API Key| Gemini
        Config["Configuration Manager\n(%APPDATA%\\ScanSort\\config.json)"] -.-> Pipeline
        Autorun["Windows Registry\n(HKCU Run Key)"] -.->|Boot Auto-Start| Watcher
    end
```

---

### Ingestion & Processing Lifecycle

```mermaid
flowchart TD
    A["Incoming File in Drop Folder"] --> B{"Is File Extension Supported?\n(.pdf, .jpg, .jpeg, .png, .tiff)"}
    B -- No --> C["Ignore Temporary / System Swap File"]
    B -- Yes --> D["Wait for File Stability\n(Exclusive Lock & Size Growth Check)"]
    
    D --> E{"Did File Stabilize?"}
    E -- Timeout --> F["Log Warning & Skip File"]
    E -- Ready --> G["Compute Streaming SHA-256 Hash"]
    
    G --> H{"Hash Exists in history.jsonl?"}
    H -- Yes (Duplicate) --> I["Route to Documents/_Review_Needed/Duplicates\nLog status: DUPLICATE"]
    H -- No (Fresh Scan) --> J{"Is File Image?\n(.jpg, .png, .tiff)"}
    
    J -- Yes --> K["Wrap Losslessly into PDF via img2pdf / Pillow"]
    J -- No (Already PDF) --> L["Pass Through Original PDF"]
    
    K --> M["Load Discovered Taxonomy & folder_hints.json"]
    L --> M
    
    M --> N["Call Google Gemini 2.5 Flash\n(Multimodal OCR & Classification Schema)"]
    
    N --> O["Sanitize Metadata & English Title\n(Format: Title_Case_With_Underscores, max 60 chars)"]
    O --> P{"Orientation Correction Needed?\n(90 deg, 180 deg, 270 deg)"}
    P -- Yes --> Q["Rotate Pages Clockwise via pypdf"]
    P -- No --> R["Retain Current Rotation"]
    
    Q --> S["Embed XMP Metadata\n(Title, Subject, Keywords for Windows Search)"]
    R --> S
    
    S --> T{"Dry-Run Mode Active?"}
    T -- Yes --> U["Log Simulated Destination Path\nLeave Source File Untouched"]
    T -- No --> V["Resolve Filename Collisions\n(e.g., YYMMDD_Desc_1.pdf)"]
    
    V --> W["Atomic File Move to Deepest Matching Subfolder"]
    W --> X["Append Record to history.jsonl & history.csv"]
    X --> Y["Show Windows Notification Toast"]
```

---

## Core Features

- **Zero-Leak Secret Vault:** Your Gemini API key is never written to plaintext config files. It is stored directly in the OS-encrypted credential vault (Windows Credential Manager / DPAPI via `keyring`).
- **Rust-Powered Filesystem Watcher:** Built on `watchfiles` (wrapping Rust's `notify` crate) with native debouncing to handle scanner buffers and multi-page ADF batch scans.
- **Deepest Subfolder Matching:** Scans your real `Documents` directory hierarchy and classifies scans into the most specific leaf folder. If no existing folder fits or confidence is below 70%, files route safely to `Documents/_Review_Needed/` (never inventing rogue folders).
- **Multi-Page TIFF & Image Support:** Automatically normalizes single and multi-page TIFFs, JPEGs, and PNGs into standard searchable PDFs without dropping pages.
- **Auto Page-Orientation:** Automatically corrects skewed, sideways, or upside-down scans (0°, 90°, 180°, 270°) using `pypdf`.
- **Native Windows Search Indexing:** Embeds document title, summary, and category keywords into standard PDF DocInfo and XMP metadata streams, enabling instant Windows Start Menu and Explorer search.
- **SHA-256 Duplicate Interception:** Computes cryptographic SHA-256 hashes for all scans. Re-scans are identified before filing and routed to `_Review_Needed/Duplicates/`, saving Gemini API quota.
- **Sequential Undo Support:** Provides single-command undo (`scansort undo`) that can be executed repeatedly to roll back successive moves, restoring files safely with collision handling and resetting duplicate status.
- **Resilient Background Worker:** Robust queue worker designed to handle transient API rate limits (429/503) and network drops by falling back to review folders without terminating the daemon.
- **Dual Crash-Safe Audit Logs:** Maintains append-only `history.jsonl` (machine-readable structured log) and `history.csv` (Excel-compatible spreadsheet) in `%APPDATA%\ScanSort\`.
- **Dry-Run Mode:** Test and preview classification logic on your documents without moving or modifying files (`--dry-run`).
- **System Boot Auto-Start:** Automatically launches on user login via Windows Registry (`HKCU\Run`) or Linux XDG desktop autostart.

---

## Prerequisites & Installation

### Prerequisites
- Python 3.12 or newer
- [Astral `uv`](https://docs.astral.sh/uv/) (recommended for fast package management)
- A Google Gemini API key ([Google AI Studio](https://aistudio.google.com/))

### Installation via `uv`

```bash
# Clone repository
git clone https://github.com/stephen/scansort.git
cd scansort

# Install dependencies into virtual environment
uv sync
```

---

## Usage & CLI Reference

ScanSort provides an intuitive command-line interface:

### 1. Store Your Gemini API Key Securely
Store your API key in the Windows Credential Manager:
```bash
uv run python -m scansort config --set-key AIzaSyYourActualKeyHere
```
*The key is encrypted via DPAPI and never saved to any file on disk.*

### 2. View Current Configuration
Check active settings, folders, and verify your key is stored:
```bash
uv run python -m scansort config --show
```
*Output safely masks the API key (e.g. `AIza••••••••1234`).*

### 3. Customize Monitored Folders
```bash
# Set custom scanner drop folder
uv run scansort config --watch-folder "C:\Scans\Inbox"

# Set custom documents destination directory
uv run scansort config --documents-folder "D:\My Documents"
```
*Validation guarantees:* ScanSort prevents configuring regular files as directory endpoints, rejects identical `watch_folder` and `documents_folder` paths, and blocks path traversal or Windows drive letters in `fallback_folder`.

### 4. Configure Auto-Start on Boot (Windows & Linux)
```bash
# Enable run-on-startup (sets HKCU registry key on Windows, XDG autostart on Linux)
uv run scansort config --autostart enable

# Disable run-on-startup
uv run scansort config --autostart disable
```

### 5. Preview Scans in Dry-Run Mode
Simulate categorization without moving files or modifying PDFs:
```bash
# Via subcommand or root flag
uv run scansort watch --dry-run
uv run scansort --dry-run
```

### 6. Start Live Background Monitoring
```bash
# Standard interactive foreground monitor
uv run scansort watch

# Run silently / minimized without banner output (supported via root or subparser)
uv run scansort watch --minimized
uv run scansort --minimized watch

# Optional: Override drop folder or documents root for a single session
uv run scansort watch --watch-folder "C:\Scans\Inbox" --documents-root "D:\Documents"
```

### 7. Reverse Document Moves (Undo)
Misplaced a document or want to re-scan? Reverse the last move instantly. You can run `undo` successively to roll back multiple previous filings:
```bash
uv run scansort undo
```
*Restores the file to its original location in your drop folder prefixed with `_undone_` (e.g., `_undone_YYMMDD_Desc.pdf`) with automatic numerical collision resolution so existing files are never overwritten. The active watcher strictly ignores the `_undone_` prefix to prevent automated re-filing loops, while `history.jsonl`, `history.csv`, and the optional mirrored CSV in your Documents folder are atomically updated with `UNDONE` status.*

### 8. Inspect Discovered Taxonomy
Verify the folders ScanSort will use for classification (respecting `max_folder_depth` between 1 and 10, and `fallback_folder` exclusions):
```bash
uv run scansort rescan
```

---

## Folder Hints & Aliases (`folder_hints.json`)

If you have specific taxonomy folders whose purpose may not be obvious from the folder name alone, create a `folder_hints.json` file in `%APPDATA%\ScanSort\` (or `~/.config/scansort/` on Linux):

```json
{
  "Finances/Utilities/Electricity": ["Origin Energy", "AGL", "power bill", "kWh"],
  "Medical/Dental": ["Bupa Dental", "cleaning", "orthodontics"],
  "Taxes/2026": ["ATO", "group certificate", "PAYG", "tax return"]
}
```

ScanSort automatically injects these keyword hints into the Gemini classification prompt to ensure 100% filing accuracy. Both standard UTF-8 and Windows Notepad UTF-8 with BOM (`utf-8-sig`) are supported for both `config.json` and `folder_hints.json`.

---

## File Naming & Collision Resolution

Documents are standardized following this format:
```
YYMMDD_<Description>.pdf
```
- **Date (`YYMMDD`):** Extracted issuance/statement date from document text. Defaults to today's date if absent.
- **Description:** English summary in `Title_Case_With_Underscores` (max 60 characters). Invalid Windows characters (`< > : " / \ | ? *`) and extra punctuation are stripped.
- **Collisions:** If a file with the target name already exists in that destination folder, ScanSort appends an incrementing counter:
  - `260901_Origin_Energy_Electricity_Bill.pdf`
  - `260901_Origin_Energy_Electricity_Bill_1.pdf`
  - `260901_Origin_Energy_Electricity_Bill_2.pdf`

---

## Building Standalone Windows Executable

ScanSort can be compiled into a standalone, portable Windows executable (`ScanSort.exe`) requiring zero runtime dependencies or Python installation on the client machine:

```bash
# Build standalone binary using PyInstaller spec
uv run pyinstaller scansort.spec
```

The output bundle is produced in `dist/ScanSort/ScanSort.exe`.

---

## Testing & Quality Gates

ScanSort enforces strict quality and test-driven development standards:

```bash
# Gate 1: Code quality & linting
uv run ruff check .

# Gate 2: Code formatting check
uv run ruff format --check .

# Gate 3: Test suite & strict >=95% coverage enforcement
uv run pytest
```

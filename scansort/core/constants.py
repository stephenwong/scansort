"""Shared domain constants used across ScanSort modules."""

REVIEW_NEEDED_DIR: str = "_Review_Needed"
DUPLICATES_DIR: str = "Duplicates"
BLANK_SCANS_DIR: str = "Blank_Scans"
UNDONE_PREFIX: str = "_undone_"

CONFIG_FILENAME: str = "config.json"
HINTS_FILENAME: str = "folder_hints.json"
# Single canonical source of truth for the default Gemini model across the application.
DEFAULT_GEMINI_MODEL: str = "gemini-3.5-flash-lite"
SUPPORTED_GEMINI_MODELS: tuple[str, ...] = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
)

# Gemini classification preview payload bounds (full staging PDF is still archived).
MAX_CLASSIFICATION_PAGES: int = 4
MAX_CLASSIFICATION_PDF_BYTES: int = 10 * 1024 * 1024  # 10 MiB

# Conservative local blank-page pre-check thresholds.
BLANK_MAX_TEXT_CHARS: int = 15
BLANK_MIN_PAGE_DIMENSION: int = 400
BLANK_MAX_DARK_PIXEL_RATIO: float = 0.002
BLANK_MAX_STDDEV: float = 4.0
DEFAULT_MAX_FOLDER_DEPTH: int = 3

DEFAULT_IGNORED_FOLDERS: set[str] = {
    "my games",
    "zoom",
    "custom office templates",
    "onenote notebooks",
    "outlook files",
    "windowspowershell",
    "adobe",
    "audacity",
    "camtasia",
    "power bi desktop",
    "electronic arts",
    "square enix",
    "rockstar games",
    "call of duty",
    "$recycle.bin",
    "system volume information",
}

MIN_CONFIDENCE_THRESHOLD: float = 0.70
# Upper bound for learned per-folder confidence thresholds (RAG memory
# calibration only ever raises thresholds, never below the global minimum).
MAX_CONFIDENCE_THRESHOLD: float = 0.95
# Per-correction increment applied to a folder's calibrated threshold.
CALIBRATION_STEP: float = 0.05
DEFAULT_DESCRIPTION: str = "Scanned_Document"
MAX_DESCRIPTION_LENGTH: int = 60

# RAG self-improving classifier memory (local-only retrieval over history).
# Examples injected into the system prompt are capped to bound token cost.
MAX_MEMORY_EXAMPLES: int = 3
MEMORY_EXAMPLE_SUMMARY_CHARS: int = 80
MEMORY_VECTOR_DIM: int = 512
MEMORY_QUERY_MAX_CHARS: int = 2000
MEMORY_MIN_QUERY_CHARS: int = 25
# Measured separation on hashed lexical vectors: repeat bills sharing vendor
# words score >= 0.25 while unrelated documents score <= 0.08.
MEMORY_MIN_SIMILARITY: float = 0.20
# One-time lazy backfill budget (rows) so large histories never stall the worker.
MEMORY_BACKFILL_LIMIT: int = 2000
# Bound on the most-recent vector rows scored per retrieval so the hot path
# cannot degrade linearly with an ever-growing store.
MEMORY_SEARCH_CANDIDATE_LIMIT: int = 2000
# Best-effort memory writes must fail fast rather than hold the dispatch lock on
# a busy/corrupt database.
MEMORY_WRITE_TIMEOUT_S: float = 0.5
MEMORY_DIRNAME: str = "vectors"
MEMORY_DB_FILENAME: str = "memory.sqlite3"
MEMORY_INDEX_LOCK_FILENAME: str = "index.lock"

STATUS_SUCCESS: str = "SUCCESS"
STATUS_DUPLICATE: str = "DUPLICATE"
STATUS_COLLISION_RENAMED: str = "COLLISION_RENAMED"
STATUS_UNDONE: str = "UNDONE"
STATUS_FAILED: str = "FAILED"
STATUS_REVIEWED: str = "REVIEWED"
STATUS_OCR_BACKFILLED: str = "OCR_BACKFILLED"
STATUS_DOCTOR_MERGED: str = "DOCTOR_MERGED"
REVERSIBLE_STATUSES: set[str] = {STATUS_SUCCESS, STATUS_COLLISION_RENAMED}
FILING_STATUSES: tuple[str, ...] = (
    STATUS_SUCCESS,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_UNDONE,
    STATUS_COLLISION_RENAMED,
    STATUS_REVIEWED,
    STATUS_OCR_BACKFILLED,
    STATUS_DOCTOR_MERGED,
)

# Taxonomy Doctor (offline folder-health analyzer) tuning.
DOCTOR_GHOST_MONTHS: int = 6
DOCTOR_NEARDUP_NAME_THRESHOLD: float = 0.85
DOCTOR_NEARDUP_PROFILE_THRESHOLD: float = 0.75
DOCTOR_NEARDUP_PROFILE_MIN_DOCS: int = 3
DOCTOR_OVERBROAD_MIN_DOCS: int = 5
DOCTOR_OVERBROAD_TYPES: int = 3
DOCTOR_CLUSTER_MIN_SIZE: int = 3
DOCTOR_CLUSTER_SIMILARITY: float = 0.55

DEFAULT_DPI: float = 300.0
DEFAULT_AUTHOR: str = "ScanSort"
DEFAULT_CREATOR: str = "ScanSort Desktop Engine"
DEFAULT_OCR_LANGUAGE: str = "eng"

TEMPORARY_EXTENSIONS: tuple[str, ...] = (".crdownload", ".part", ".tmp")
IGNORED_PREFIXES: tuple[str, ...] = (".", "~", UNDONE_PREFIX)

HISTORY_JSONL_NAME: str = "history.jsonl"
HISTORY_CSV_NAME: str = "history.csv"
MIRROR_HISTORY_CSV_NAME: str = "_ScanSort_History.csv"
FOLDER_MAP_FILENAME: str = "folder_map.json"

UPDATE_STATE_FILENAME: str = "update_state.json"
INSTANCE_LOCK_FILENAME: str = "instance.lock"
UPDATE_LOCK_FILENAME: str = "update.lock"
OPERATIONS_LOCK_FILENAME: str = "operations.lock"
LOG_FILENAME: str = "scansort.log"

SUPPORTED_EXTENSIONS: set[str] = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".tiff",
    ".tif",
}

# Pipeline timing tuning (invariant C: ~1 s quiescence window is 10 x 0.1 s).
SCAN_STABILITY_TIMEOUT_S: float = 10.0
SCAN_STABILITY_POLL_INTERVAL_S: float = 0.1
SCAN_STABLE_COUNT: int = 10
DEFAULT_WATCH_DEBOUNCE_MS: int = 1500
DEFAULT_RATE_LIMIT_DELAY_S: float = 1.0
WATCHER_ERROR_BACKOFF_S: float = 2.0

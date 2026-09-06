"""Shared domain constants used across ScanSort modules."""

REVIEW_NEEDED_DIR: str = "_Review_Needed"
DUPLICATES_DIR: str = "Duplicates"
UNDONE_PREFIX: str = "_undone_"

CONFIG_FILENAME: str = "config.json"
HINTS_FILENAME: str = "folder_hints.json"
# Single canonical source of truth for the default Gemini model across the application.
DEFAULT_GEMINI_MODEL: str = "gemini-3.1-flash-lite"
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
DEFAULT_DESCRIPTION: str = "Scanned_Document"
MAX_DESCRIPTION_LENGTH: int = 60

STATUS_SUCCESS: str = "SUCCESS"
STATUS_DUPLICATE: str = "DUPLICATE"
STATUS_COLLISION_RENAMED: str = "COLLISION_RENAMED"
STATUS_UNDONE: str = "UNDONE"
STATUS_FAILED: str = "FAILED"
REVERSIBLE_STATUSES: set[str] = {STATUS_SUCCESS, STATUS_COLLISION_RENAMED}

DEFAULT_DPI: float = 300.0
DEFAULT_AUTHOR: str = "ScanSort"
DEFAULT_CREATOR: str = "ScanSort Desktop Engine"

TEMPORARY_EXTENSIONS: tuple[str, ...] = (".crdownload", ".part", ".tmp")
IGNORED_PREFIXES: tuple[str, ...] = (".", "~", UNDONE_PREFIX)

HISTORY_JSONL_NAME: str = "history.jsonl"
HISTORY_CSV_NAME: str = "history.csv"
MIRROR_HISTORY_CSV_NAME: str = "_ScanSort_History.csv"
FOLDER_MAP_FILENAME: str = "folder_map.json"

UPDATE_STATE_FILENAME: str = "update_state.json"
INSTANCE_LOCK_FILENAME: str = "instance.lock"
UPDATE_LOCK_FILENAME: str = "update.lock"
LOG_FILENAME: str = "scansort.log"

SUPPORTED_EXTENSIONS: set[str] = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".tiff",
    ".tif",
}

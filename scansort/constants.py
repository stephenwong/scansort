"""Shared domain constants used across ScanSort modules."""

REVIEW_NEEDED_DIR: str = "_Review_Needed"
DUPLICATES_DIR: str = "Duplicates"
UNDONE_PREFIX: str = "_undone_"

CONFIG_FILENAME: str = "config.json"
HINTS_FILENAME: str = "folder_hints.json"
DEFAULT_GEMINI_MODEL: str = "gemini-2.5-flash"
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
STATUS_UNDONE: str = "UNDONE"
DEFAULT_CREATOR: str = "ScanSort Desktop Engine"

TEMPORARY_EXTENSIONS: tuple[str, ...] = (".crdownload", ".part", ".tmp")
IGNORED_PREFIXES: tuple[str, ...] = (".", "~", UNDONE_PREFIX)

HISTORY_JSONL_NAME: str = "history.jsonl"
HISTORY_CSV_NAME: str = "history.csv"
MIRROR_HISTORY_CSV_NAME: str = "_ScanSort_History.csv"

SUPPORTED_EXTENSIONS: set[str] = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".tiff",
    ".tif",
}

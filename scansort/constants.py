"""Shared domain constants used across ScanSort modules."""

REVIEW_NEEDED_DIR: str = "_Review_Needed"
DUPLICATES_DIR: str = "Duplicates"
UNDONE_PREFIX: str = "_undone_"

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

"""Document classification, Gemini multimodal API client, taxonomy mapping, and hints."""

from scansort.classification.client import GeminiClassifier
from scansort.classification.hints import (
    get_default_hints_path,
    load_folder_hints,
    normalize_folder_key,
)
from scansort.classification.models import (
    DocumentClassification,
    GeminiClassificationResponse,
    sanitize_date,
    sanitize_description,
)
from scansort.classification.taxonomy import (
    DEFAULT_IGNORED_FOLDERS,
    FolderMapper,
    format_taxonomy_for_prompt,
    scan_documents_folders,
)

__all__ = [
    "GeminiClassifier",
    "DocumentClassification",
    "GeminiClassificationResponse",
    "sanitize_date",
    "sanitize_description",
    "FolderMapper",
    "format_taxonomy_for_prompt",
    "scan_documents_folders",
    "DEFAULT_IGNORED_FOLDERS",
    "load_folder_hints",
    "normalize_folder_key",
    "get_default_hints_path",
]

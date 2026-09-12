"""Document classification, Gemini multimodal API client, taxonomy mapping, and hints."""

from scansort.classification.client import GeminiClassifier
from scansort.classification.doctor import (
    DoctorFinding,
    DoctorReport,
    apply_doctor_action,
    render_doctor_report,
    run_doctor,
)
from scansort.classification.hints import (
    add_folder_hint,
    get_default_hints_path,
    load_folder_hints,
    normalize_folder_key,
    save_folder_hints,
)
from scansort.classification.memory import (
    MemoryExample,
    MemoryStore,
    build_retrieval_query,
    compute_folder_thresholds,
    format_examples_for_prompt,
    memory_db_path_for,
    memory_lock_path_for,
    propose_hint_keywords,
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
    "save_folder_hints",
    "add_folder_hint",
    "normalize_folder_key",
    "get_default_hints_path",
    "MemoryExample",
    "MemoryStore",
    "build_retrieval_query",
    "compute_folder_thresholds",
    "format_examples_for_prompt",
    "memory_db_path_for",
    "memory_lock_path_for",
    "propose_hint_keywords",
    "DoctorFinding",
    "DoctorReport",
    "run_doctor",
    "render_doctor_report",
    "apply_doctor_action",
]

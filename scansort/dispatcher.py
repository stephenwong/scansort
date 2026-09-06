"""File naming, collision handling, and atomic filing engine."""

import logging
import shutil
from contextlib import nullcontext
from pathlib import Path

from scansort.constants import (
    DUPLICATES_DIR,
    OPERATIONS_LOCK_FILENAME,
    REVIEW_NEEDED_DIR,
)
from scansort.fs_utils import (
    interprocess_file_lock,
    relative_folder_is_safe,
    resolve_collision,
)
from scansort.models import DocumentClassification
from scansort.undo import undo_last_move

logger = logging.getLogger(__name__)

__all__ = [
    "OPERATIONS_LOCK_FILENAME",
    "dispatch_file",
    "generate_target_filename",
    "resolve_collision",
    "resolve_destination_dir",
    "resolve_duplicates_dir",
    "undo_last_move",
]


def generate_target_filename(classification: DocumentClassification) -> str:
    """Generate the uniform YYMMDD_<Description>.pdf filename.

    Args:
        classification: Extracted document classification.

    Returns:
        Standardized filename string.
    """
    return classification.target_filename


def _resolve_safe_subfolder(
    docs_root: Path,
    relative_folder: str,
    context_name: str = "target",
) -> Path:
    """Resolve and validate a relative subfolder against docs_root with safety fallback."""
    clean_folder = relative_folder.strip("/\\")
    resolved_docs = docs_root.resolve()
    review_dir = (docs_root / REVIEW_NEEDED_DIR).resolve()

    if not clean_folder or clean_folder == ".":
        return review_dir

    if not relative_folder_is_safe(clean_folder):
        logger.warning(
            "Path traversal attempt or root folder %s: %s. Routing to %s.",
            context_name,
            relative_folder,
            REVIEW_NEEDED_DIR,
        )
        return review_dir

    candidate_dir = (docs_root / clean_folder).resolve()
    if (
        not candidate_dir.is_relative_to(resolved_docs)
        or candidate_dir == resolved_docs
    ):
        logger.warning(
            "Path traversal attempt or root folder %s: %s. Routing to %s.",
            context_name,
            relative_folder,
            REVIEW_NEEDED_DIR,
        )
        return review_dir

    return candidate_dir


def resolve_destination_dir(docs_root: Path, relative_target: str) -> Path:
    """Resolve and validate the destination directory against the taxonomy and docs root.

    Ambiguous, traversal, or root matches are strictly redirected to the
    ``_Review_Needed`` directory to guarantee nothing is filed outside the root.

    Args:
        docs_root: Root of Documents folder.
        relative_target: Relative destination folder path.

    Returns:
        Absolute, resolved destination directory guaranteed to sit under docs_root.
    """
    return _resolve_safe_subfolder(docs_root, relative_target, context_name="target")


def resolve_duplicates_dir(docs_root: Path, fallback_folder: str) -> Path:
    """Resolve the destination directory for duplicate scans.

    Duplicates are routed to ``<fallback_folder>/Duplicates``, or to
    ``_Review_Needed/Duplicates`` when the fallback folder is empty, is the
    documents root, or is unsafe (path traversal / absolute).

    Args:
        docs_root: Root of Documents folder.
        fallback_folder: User-configured fallback directory.

    Returns:
        Absolute resolved path to the duplicates directory under docs_root.
    """
    safe_base = _resolve_safe_subfolder(
        docs_root, fallback_folder, context_name="fallback folder"
    )
    return (safe_base / DUPLICATES_DIR).resolve()


def dispatch_file(
    source_path: Path,
    docs_root: Path,
    classification: DocumentClassification,
    lock_path: Path | None = None,
) -> Path:
    """Execute the atomic move of the source file to its classified destination.

    Resolves destination folder safely, resolves collisions via incremental counters,
    creates required parent directories, and executes an atomic move.

    Args:
        source_path: Path to the processed (or stabilized) file in drop folder.
        docs_root: Root of Documents directory.
        classification: Extracted classification from Gemini.
        lock_path: Optional cross-process lock file guarding resolve+move.

    Returns:
        Final destination Path of the filed document.

    Raises:
        OSError: If destination cannot be created or file move fails.
    """
    dest_dir = resolve_destination_dir(docs_root, classification.target_folder)
    dest_dir.mkdir(parents=True, exist_ok=True)

    target_filename = generate_target_filename(classification)

    with interprocess_file_lock(lock_path) if lock_path else nullcontext():
        dest_path = resolve_collision(dest_dir, target_filename)
        try:
            shutil.move(str(source_path), str(dest_path))
        except OSError:
            # Remove any partially copied destination (e.g. EXDEV copy fallback).
            dest_path.unlink(missing_ok=True)
            raise
    logger.info("Filed document: %s -> %s", source_path.name, dest_path)
    return dest_path

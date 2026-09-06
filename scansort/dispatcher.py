"""File naming, collision handling, atomic filing, and move reversal engine."""

import json
import logging
import os
import shutil
from contextlib import nullcontext
from pathlib import Path

from scansort.constants import (
    DUPLICATES_DIR,
    REVERSIBLE_STATUSES,
    REVIEW_NEEDED_DIR,
    STATUS_UNDONE,
    UNDONE_PREFIX,
)
from scansort.fs_utils import (
    interprocess_file_lock,
    relative_folder_is_safe,
    resolve_collision,
)
from scansort.logging import AuditLogger
from scansort.models import DocumentClassification

logger = logging.getLogger(__name__)

OPERATIONS_LOCK_FILENAME: str = "operations.lock"

__all__ = [
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


def _find_last_reversible_record(jsonl_path: Path) -> dict[str, object] | None:
    """Find the most recent SUCCESS or COLLISION_RENAMED record not yet undone."""
    if not jsonl_path.exists():
        return None

    try:
        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        logger.warning("Error reading history file at %s: %s", jsonl_path, e)
        return None

    if not lines:
        return None

    undone_destinations: set[str] = set()

    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
            if not isinstance(record, dict):
                continue
            status = record.get("status")
            dest_p = record.get("destination_path")
            if not dest_p:
                continue
            norm_dest = os.path.normcase(os.path.normpath(str(dest_p)))
            if status == STATUS_UNDONE:
                undone_destinations.add(norm_dest)
            elif status in REVERSIBLE_STATUSES:
                if norm_dest in undone_destinations:
                    continue
                if not record.get("original_path"):
                    logger.debug(
                        "Skipping record without original_path during undo search."
                    )
                    continue
                if not Path(str(dest_p)).is_file():
                    logger.debug("Skipping missing file %s during undo search.", dest_p)
                    continue
                return record
        except json.JSONDecodeError:
            continue

    return None


def _resolve_restored_path(original_path: Path, dest_path: Path) -> Path:
    """Determine the destination path in the drop folder with extension and collision handling."""
    target_name = original_path.name
    if dest_path.suffix.lower() == ".pdf" and original_path.suffix.lower() != ".pdf":
        target_name = original_path.with_suffix(".pdf").name

    if not target_name.startswith(UNDONE_PREFIX):
        target_name = f"{UNDONE_PREFIX}{target_name}"

    return resolve_collision(original_path.parent, target_name)


def undo_last_move(
    jsonl_path: Path,
    csv_path: Path | None = None,
    mirror_csv_path: Path | None = None,
    lock_path: Path | None = None,
) -> Path | None:
    """Reverse the last successful document move recorded in the audit log.

    Args:
        jsonl_path: Path to history.jsonl.
        csv_path: Optional path to the paired CSV audit log. Defaults to the
            sibling of jsonl_path.
        mirror_csv_path: Optional mirrored CSV audit log to update alongside.
        lock_path: Optional cross-process lock file guarding the restore.

    Returns:
        Path of restored file in drop folder, or None if no reversible action found.

    Raises:
        OSError: If the physical restore fails (e.g. the destination is locked).
    """
    target_record = _find_last_reversible_record(jsonl_path)
    if target_record is None:
        return None

    dest_path = Path(str(target_record["destination_path"]))
    original_path = Path(str(target_record["original_path"]))
    lock_file = lock_path or (jsonl_path.parent / OPERATIONS_LOCK_FILENAME)

    with interprocess_file_lock(lock_file):
        restore_path = _resolve_restored_path(original_path, dest_path)

        try:
            restore_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest_path), str(restore_path))
        except (PermissionError, OSError) as e:
            logger.error("Failed to restore file %s: %s", dest_path, e)
            # Remove any partially restored copy (e.g. cross-device copy failure).
            restore_path.unlink(missing_ok=True)
            raise

    undo_record = dict(target_record)
    undo_record.pop("timestamp", None)
    undo_record.pop("local_time", None)
    undo_record["status"] = STATUS_UNDONE
    undo_record["note"] = f"Reversed move of {dest_path.name} back to {restore_path}"

    AuditLogger(
        jsonl_path=jsonl_path,
        csv_path=csv_path or jsonl_path.with_suffix(".csv"),
        mirror_csv_path=mirror_csv_path,
    ).log_scan(undo_record)

    logger.info("Undid filing: %s moved back to %s", dest_path.name, restore_path)
    return restore_path

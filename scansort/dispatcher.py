"""File naming, collision handling, atomic filing, and move reversal engine."""

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from scansort.audit_logger import AuditLogger
from scansort.constants import DUPLICATES_DIR, REVIEW_NEEDED_DIR, UNDONE_PREFIX
from scansort.fs_utils import relative_folder_is_safe
from scansort.models import DocumentClassification

logger = logging.getLogger(__name__)


def generate_target_filename(classification: DocumentClassification) -> str:
    """Generate the uniform YYMMDD_<Description>.pdf filename.

    Args:
        classification: Extracted document classification.

    Returns:
        Standardized filename string.
    """
    return f"{classification.document_date}_{classification.description}.pdf"


def resolve_collision(dest_folder: Path, filename: str) -> Path:
    """Check if a filename collision exists and append incrementing counter _1, _2 if needed.

    Args:
        dest_folder: Directory where file will be placed.
        filename: Desired filename.

    Returns:
        Available non-colliding Path.
    """
    candidate = dest_folder / filename
    if not candidate.exists():
        return candidate

    p = Path(filename)
    stem = p.stem
    suffix = p.suffix

    counter = 1
    while True:
        candidate = dest_folder / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def resolve_destination_dir(docs_root: Path, relative_target: str) -> Path:
    """Resolve a model/user-supplied relative folder to an absolute directory inside docs_root.

    Empty, root-referencing (``/``, ``\\``, ``.``), and unsafe targets (path
    traversal, absolute paths, or the documents root itself) fall back to the
    ``_Review_Needed`` directory to guarantee nothing is filed outside the root.

    Args:
        docs_root: Root of Documents folder.
        relative_target: Relative destination folder path.

    Returns:
        Absolute, resolved destination directory guaranteed to sit under docs_root.
    """
    clean_target = relative_target.strip("/\\")
    resolved_docs = docs_root.resolve()
    if not clean_target or clean_target == ".":
        return (docs_root / REVIEW_NEEDED_DIR).resolve()

    if not relative_folder_is_safe(clean_target):
        logger.warning(
            "Path traversal attempt or root folder target: %s. Routing to %s.",
            relative_target,
            REVIEW_NEEDED_DIR,
        )
        return (docs_root / REVIEW_NEEDED_DIR).resolve()

    target_dir = (docs_root / clean_target).resolve()
    if not target_dir.is_relative_to(resolved_docs) or target_dir == resolved_docs:
        logger.warning(
            "Path traversal attempt or root folder target: %s. Routing to %s.",
            relative_target,
            REVIEW_NEEDED_DIR,
        )
        return (docs_root / REVIEW_NEEDED_DIR).resolve()
    return target_dir


def resolve_duplicates_dir(docs_root: Path, fallback_folder: str) -> Path:
    """Resolve the destination directory for duplicate scans.

    Duplicates are routed to ``<fallback_folder>/Duplicates``, or to
    ``_Review_Needed/Duplicates`` when the fallback folder is empty, is the
    documents root, or is unsafe (path traversal / absolute).

    Args:
        docs_root: Root of Documents folder.
        fallback_folder: Configured review folder name (may be empty or unsafe).

    Returns:
        Absolute, resolved duplicates directory guaranteed to sit under docs_root.
    """
    clean_fallback = fallback_folder.strip("/\\")
    review_dup = (docs_root / REVIEW_NEEDED_DIR / DUPLICATES_DIR).resolve()
    if not clean_fallback or clean_fallback == ".":
        return review_dup

    if not relative_folder_is_safe(clean_fallback):
        logger.warning(
            "Unsafe fallback folder %r. Routing duplicates to %s/%s.",
            fallback_folder,
            REVIEW_NEEDED_DIR,
            DUPLICATES_DIR,
        )
        return review_dup

    dup_dir = (docs_root / clean_fallback / DUPLICATES_DIR).resolve()
    if (
        not dup_dir.is_relative_to(docs_root.resolve())
        or dup_dir == docs_root.resolve()
    ):
        logger.warning(
            "Unsafe fallback folder %r. Routing duplicates to %s/%s.",
            fallback_folder,
            REVIEW_NEEDED_DIR,
            DUPLICATES_DIR,
        )
        return review_dup
    return dup_dir


def dispatch_file(
    source_path: Path,
    docs_root: Path,
    classification: DocumentClassification,
) -> Path:
    """Move the document atomically into its destination folder with collision handling.

    Args:
        source_path: Path to the stabilized source file.
        docs_root: Root of Documents folder.
        classification: Document classification metadata.

    Returns:
        Path of the filed document in its destination folder.
    """
    target_dir = resolve_destination_dir(docs_root, classification.target_folder)
    target_dir.mkdir(parents=True, exist_ok=True)

    desired_filename = generate_target_filename(classification)
    dest_path = resolve_collision(target_dir, desired_filename)

    shutil.move(str(source_path), str(dest_path))
    logger.info("Filed %s -> %s", source_path.name, dest_path)
    return dest_path


def undo_last_move(
    jsonl_path: Path,
    csv_path: Path | None = None,
    mirror_csv_path: Path | None = None,
) -> Path | None:
    """Reverse the last successful document move recorded in the audit log.

    Args:
        jsonl_path: Path to history.jsonl.
        csv_path: Optional path to the paired CSV audit log. Defaults to the
            sibling of jsonl_path.
        mirror_csv_path: Optional mirrored CSV audit log to update alongside.

    Returns:
        Path of restored file in drop folder, or None if no reversible action found.
    """
    if not jsonl_path.exists():
        return None

    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return None

    # Search backwards for last SUCCESS or COLLISION_RENAMED record that hasn't been undone
    target_idx = None
    target_record = None
    undone_destinations: set[str] = set()

    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                continue
            status = record.get("status")
            dest_p = record.get("destination_path")
            if status == "UNDONE" and dest_p:
                undone_destinations.add(dest_p)
            elif status in {"SUCCESS", "COLLISION_RENAMED"} and dest_p:
                if dest_p in undone_destinations:
                    continue
                # Skip missing destination files (e.g. if deleted/moved manually by user)
                if not Path(dest_p).exists():
                    logger.debug("Skipping missing file %s during undo search.", dest_p)
                    continue
                target_idx = i
                target_record = record
                break
        except json.JSONDecodeError:
            continue

    if target_record is None or target_idx is None:
        return None

    dest_path = Path(target_record["destination_path"])
    original_path = Path(target_record["original_path"])

    if not dest_path.exists():
        logger.warning("Cannot undo: file %s no longer exists.", dest_path)
        return None

    # Preserve .pdf extension if original was converted from an image
    target_name = original_path.name
    if dest_path.suffix.lower() == ".pdf" and original_path.suffix.lower() != ".pdf":
        target_name = original_path.with_suffix(".pdf").name

    # Prefix with _undone_ to avoid immediate re-ingestion by watcher (S1-07)
    if not target_name.startswith(UNDONE_PREFIX):
        target_name = f"{UNDONE_PREFIX}{target_name}"

    # Move back to original drop folder with collision handling
    original_path.parent.mkdir(parents=True, exist_ok=True)
    restore_path = resolve_collision(original_path.parent, target_name)

    try:
        shutil.move(str(dest_path), str(restore_path))
    except (PermissionError, OSError) as e:
        logger.error("Failed to restore file %s: %s", dest_path, e)
        return None

    # Append an undo marker record via the shared audit logger so JSONL, CSV,
    # and the optional mirrored CSV stay consistent (S1-10)
    undo_record = dict(target_record)
    now_utc = datetime.now(UTC)
    undo_record["status"] = "UNDONE"
    undo_record["timestamp"] = now_utc.isoformat()
    undo_record["local_time"] = now_utc.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    undo_record["note"] = f"Reversed move of {dest_path.name} back to {restore_path}"

    AuditLogger(
        jsonl_path=jsonl_path,
        csv_path=csv_path or jsonl_path.with_suffix(".csv"),
        mirror_csv_path=mirror_csv_path,
    ).log_scan(undo_record)

    logger.info("Undid filing: %s moved back to %s", dest_path.name, restore_path)
    return restore_path

"""File naming, collision handling, atomic filing, and move reversal engine."""

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from scansort.gemini_client import DocumentClassification

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
    clean_target = classification.target_folder.lstrip("/\\")
    resolved_docs = docs_root.resolve()
    target_dir = (docs_root / clean_target).resolve()
    if not target_dir.is_relative_to(resolved_docs):
        logger.warning(
            "Path traversal attempt: %s. Routing to _Review_Needed.",
            classification.target_folder,
        )
        target_dir = (docs_root / "_Review_Needed").resolve()

    target_dir.mkdir(parents=True, exist_ok=True)

    desired_filename = generate_target_filename(classification)
    dest_path = resolve_collision(target_dir, desired_filename)

    shutil.move(str(source_path), str(dest_path))
    logger.info("Filed %s -> %s", source_path.name, dest_path)
    return dest_path


def undo_last_move(jsonl_path: Path) -> Path | None:
    """Reverse the last successful document move recorded in the audit log.

    Args:
        jsonl_path: Path to history.jsonl.

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

    # Move back to original drop folder with collision handling
    original_path.parent.mkdir(parents=True, exist_ok=True)
    restore_path = resolve_collision(original_path.parent, target_name)
    shutil.move(str(dest_path), str(restore_path))

    # Append an undo marker record to history with current UTC timestamp
    undo_record = dict(target_record)
    now_utc = datetime.now(UTC)
    undo_record["status"] = "UNDONE"
    undo_record["timestamp"] = now_utc.isoformat()
    undo_record["local_time"] = now_utc.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    undo_record["note"] = f"Reversed move of {dest_path.name} back to {restore_path}"

    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(undo_record) + "\n")

    logger.info("Undid filing: %s moved back to %s", dest_path.name, restore_path)
    return restore_path

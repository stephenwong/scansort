"""Filing move reversal engine for ScanSort.

Scans the audit history for the most recent reversible filing (SUCCESS or
COLLISION_RENAMED), restores the file to the drop folder with a collision-safe
'_undone_' prefix, and logs an UNDONE status to both JSONL and CSV audit logs.
"""

import json
import logging
import os
import shutil
from pathlib import Path

from scansort.core.constants import (
    OPERATIONS_LOCK_FILENAME,
    REVERSIBLE_STATUSES,
    STATUS_UNDONE,
    UNDONE_PREFIX,
)
from scansort.core.fs import interprocess_file_lock, resolve_collision
from scansort.logging import AuditLogger

logger = logging.getLogger(__name__)

__all__ = [
    "undo_last_move",
]


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

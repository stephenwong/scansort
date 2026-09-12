"""Cryptographic hashing and duplicate scan detection engine."""

import hashlib
import json
import logging
from pathlib import Path

from scansort.core.constants import STATUS_UNDONE

logger = logging.getLogger(__name__)


def compute_file_sha256(path: Path, chunk_size: int = 65536) -> str:
    """Compute the SHA-256 hex digest of a file in streaming chunks.

    Args:
        path: Path to the target file.
        chunk_size: Byte size of chunks to read into memory.

    Returns:
        64-character hexadecimal SHA-256 string.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0.")

    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def check_duplicate(
    file_hash: str, history_file: Path, ignore_path: Path | None = None
) -> dict | None:
    """Check whether a given SHA-256 file hash was previously recorded in history.jsonl.

    Args:
        file_hash: 64-character SHA-256 hex digest.
        history_file: Path to history.jsonl.
        ignore_path: Optional path whose own prior routing record should be
            ignored (used when filing a review item so it is not treated as a
            duplicate of itself).

    Returns:
        The matched record dictionary if duplicate found, otherwise None.
    """
    if not history_file.exists():
        return None

    ignore_resolved = None
    if ignore_path is not None:
        try:
            ignore_resolved = str(Path(ignore_path).resolve())
        except OSError:
            ignore_resolved = None

    latest_record = None
    with open(history_file, encoding="utf-8") as f:
        for line in f:
            clean_line = line.strip()
            if not clean_line or file_hash not in clean_line:
                continue
            try:
                record = json.loads(clean_line)
                if not isinstance(record, dict) or record.get("sha256") != file_hash:
                    continue
                if ignore_resolved is not None:
                    destination = record.get("destination_path")
                    try:
                        if (
                            destination
                            and str(Path(destination).resolve()) == ignore_resolved
                        ):
                            # The item's own routing record, not a prior filing.
                            continue
                    except OSError:
                        pass
                latest_record = record
            except json.JSONDecodeError:
                continue

    if latest_record and latest_record.get("status") != STATUS_UNDONE:
        return latest_record

    return None

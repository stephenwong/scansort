"""Shared atomic file-writing and relative-path safety utilities."""

import os
import tempfile
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import BinaryIO


def atomic_write(
    target: Path,
    data: str | bytes | Callable[[BinaryIO], None],
) -> None:
    """Atomically write ``data`` to ``target`` via a sibling temp file and rename.

    The temporary file is created next to ``target`` (same filesystem) and is
    always cleaned up, even when the write or rename fails. Disk buffers are
    explicitly flushed and synchronized via ``os.fsync`` before the atomic rename.

    Args:
        target: Destination file path. Parent directories are created as needed.
        data: Content to write; strings are UTF-8 encoded, bytes are written raw,
            or a callable accepting a binary file object for zero-copy streaming.

    Raises:
        OSError: If the directory cannot be created, the write fails, or the
            atomic replace fails.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, delete=False, suffix=".tmp"
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            if callable(data):
                data(tmp_file)
            elif isinstance(data, str):
                tmp_file.write(data.encode("utf-8"))
            else:
                tmp_file.write(data)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        tmp_path.replace(target)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def relative_folder_is_safe(rel: str) -> bool:
    """Return True when ``rel`` is a plain relative folder path.

    Rejects leading slashes, Windows drive prefixes, and any ``..`` traversal
    segments. Empty and whitespace-only values are rejected too.

    Args:
        rel: Candidate relative folder path (forward or backslash separated).

    Returns:
        True if the value can be safely joined under a documents root.
    """
    value = str(rel).strip()
    if not value or value.startswith(("/", "\\")):
        return False

    normalized = value.replace("\\", "/")
    if any(segment == ".." for segment in normalized.split("/")):
        return False
    return not PureWindowsPath(normalized).drive


def normalize_relative_folder(folder: str | Path) -> str:
    """Normalize a folder path to a clean, forward-slash-separated relative string without leading/trailing slashes.

    Example:
        'Finances\\\\Tax\\\\2024/' -> 'Finances/Tax/2024'
        '' or '.' -> ''
    """
    cleaned = str(folder).replace("\\", "/").strip()
    segments = [p.strip() for p in cleaned.split("/") if p.strip() and p.strip() != "."]
    return "/".join(segments)


def resolve_collision(dest_folder: Path, filename: str) -> Path:
    """Check if the target file already exists, appending a numeric suffix if needed.

    E.g., ``240510_Invoice.pdf`` -> ``240510_Invoice_1.pdf``, ``240510_Invoice_2.pdf``, etc.

    Args:
        dest_folder: Destination directory.
        filename: Proposed base filename.

    Returns:
        Path to an available filename that does not currently exist.
    """
    candidate = dest_folder / filename
    if not candidate.exists():
        return candidate

    stem = Path(filename).stem
    suffix = Path(filename).suffix

    counter = 1
    while True:
        collision_candidate = dest_folder / f"{stem}_{counter}{suffix}"
        if not collision_candidate.exists():
            return collision_candidate
        counter += 1

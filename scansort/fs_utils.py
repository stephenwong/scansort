"""Shared atomic file-writing and relative-path safety utilities."""

import tempfile
from pathlib import Path, PureWindowsPath


def atomic_write(target: Path, data: str | bytes) -> None:
    """Atomically write ``data`` to ``target`` via a sibling temp file and rename.

    The temporary file is created next to ``target`` (same filesystem) and is
    always cleaned up, even when the write or rename fails.

    Args:
        target: Destination file path. Parent directories are created as needed.
        data: Content to write; strings are encoded as UTF-8, bytes are written raw.

    Raises:
        OSError: If the directory cannot be created, the write fails, or the
            atomic replace fails.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        payload = data.encode("utf-8") if isinstance(data, str) else data
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, delete=False, suffix=".tmp"
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_file.write(payload)
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

"""Shared Linux XDG file helpers for user-level desktop integration."""

import logging
import stat
from pathlib import Path

from scansort.core.fs import atomic_write

logger = logging.getLogger(__name__)


def write_xdg_file(
    path: Path, content: str, *, description: str, executable: bool = False
) -> bool:
    """Create a user XDG file, logging and returning False on ``OSError``."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, content)
        if executable:
            current_mode = path.stat().st_mode
            path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return True
    except OSError as e:
        logger.warning("Failed to create Linux %s: %s", description, e)
        return False


def remove_xdg_file(path: Path, *, description: str) -> bool:
    """Remove a user XDG file, logging and returning False on ``OSError``."""
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError as e:
        logger.warning("Failed to remove Linux %s: %s", description, e)
        return False


def xdg_file_has_markers(path: Path, *markers: str) -> bool:
    """Return True when *path* exists, is readable, and contains every marker.

    A truncated or stale file must never report the integration as enabled.
    """
    if not path.exists():
        return False
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return all(marker in content for marker in markers)

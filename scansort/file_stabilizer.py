"""File stabilization engine ensuring scanner write completion and releasing of file locks."""

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _try_open_exclusive(path: Path) -> None:
    """Attempt opening the file in read/append mode to verify that the scanner process has closed it."""
    with open(path, "r+b"):
        pass


def is_file_locked(path: Path) -> bool:
    """Check whether a file is locked by another process (such as a scanner driver writing to disk).

    Args:
        path: Path to the target file.

    Returns:
        True if locked or inaccessible, False if available for exclusive read.
    """
    if not path.exists():
        return True

    try:
        _try_open_exclusive(path)
        return False
    except (OSError, PermissionError):
        return True


def wait_for_file_stability(
    path: Path,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
    stable_count: int = 2,
) -> bool:
    """Poll a file until its size stops growing, is non-zero, and is not locked by the writer.

    Args:
        path: Path to the scanned file.
        timeout: Maximum time to wait in seconds.
        poll_interval: Delay between consecutive size/lock checks.
        stable_count: Number of consecutive identical size checks required.

    Returns:
        True if file stabilized and is readable, False on timeout or missing file.
    """
    start_time = time.monotonic()
    consecutive_stable = 0
    last_size = -1

    while (time.monotonic() - start_time) < timeout:
        if not path.exists():
            time.sleep(poll_interval)
            continue

        try:
            current_size = path.stat().st_size
        except OSError:
            time.sleep(poll_interval)
            continue

        if current_size == 0:
            # Scanner created the file handle but has not flushed bytes yet
            consecutive_stable = 0
            time.sleep(poll_interval)
            continue

        if current_size == last_size:
            consecutive_stable += 1
        else:
            consecutive_stable = 0
            last_size = current_size

        if consecutive_stable >= stable_count and not is_file_locked(path):
            logger.debug("File %s stabilized at %d bytes.", path.name, current_size)
            return True

        time.sleep(poll_interval)

    logger.warning("File %s failed to stabilize within %.1fs timeout.", path.name, timeout)
    return False

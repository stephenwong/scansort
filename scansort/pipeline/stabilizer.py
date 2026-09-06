"""Exclusive file-lock polling and size growth tracker."""

import logging
import os
import stat
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def is_file_locked(path: Path) -> bool:
    """Check whether a file is locked by another process (such as a scanner driver writing to disk).

    Args:
        path: Path to the target file.

    Returns:
        True if locked or inaccessible, False if available for exclusive read.
    """
    if not path.exists() or path.is_dir():
        return True

    try:
        with open(path, "rb") as f:
            if sys.platform == "win32":
                import msvcrt

                size = os.fstat(f.fileno()).st_size
                if size > 0:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return False
    except OSError:
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
        try:
            st = path.stat()
        except OSError:
            # File disappeared (deleted or temporarily locked from stat):
            # immediately fail rather than spinning the timeout.
            logger.debug(
                "File %s disappeared or inaccessible during stabilization.", path.name
            )
            return False

        current_size = st.st_size

        # Inode / File Mode sanity check
        if stat.S_ISDIR(st.st_mode):
            return False

        if current_size > 0 and current_size == last_size:
            consecutive_stable += 1
        else:
            consecutive_stable = 0
            last_size = current_size

        # If size has been identical for required checks AND file is not locked
        if consecutive_stable >= stable_count and not is_file_locked(path):
            logger.debug(
                "File %s stabilized at %d bytes (%.2fs)",
                path.name,
                current_size,
                time.monotonic() - start_time,
            )
            return True

        time.sleep(poll_interval)

    logger.warning(
        "File %s did not stabilize within %.1fs timeout (final size: %d bytes)",
        path.name,
        timeout,
        last_size,
    )
    return False

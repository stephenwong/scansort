"""Single-instance process guard shared by every ScanSort watcher process.

A second ``watch`` process (manual launch while autorun is active, or a
self-update helper racing a live instance) must never run a concurrent watcher
on the same drop folder: both would sweep and file the same scans. Acquisition
is non-blocking so the loser exits immediately instead of waiting.
"""

import errno
import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


@contextmanager
def instance_guard(lock_path: Path) -> Iterator[bool]:
    """Yield True when this process holds the single-instance lock.

    When another process already holds the lock the generator yields False and
    exits immediately without blocking. The lock is released on exit, so a
    process crash never leaves a stale lock behind.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock_file:
        if os.fstat(lock_file.fileno()).st_size == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            _file_lock(lock_file, acquire=True)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                # A genuine lock-subsystem failure must not masquerade as
                # "another instance is running" (which silently disables watch).
                raise
            logger.debug("Another ScanSort instance already holds %s", lock_path)
            yield False
            return
        try:
            yield True
        finally:
            _file_lock(lock_file, acquire=False)


def _file_lock(lock_file, *, acquire: bool) -> None:
    """Acquire or release the non-blocking platform advisory lock on *lock_file*."""
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(
            lock_file.fileno(), msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK, 1
        )
    else:
        import fcntl

        fcntl.flock(
            lock_file.fileno(),
            (fcntl.LOCK_EX | fcntl.LOCK_NB) if acquire else fcntl.LOCK_UN,
        )

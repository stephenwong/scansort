"""Rollback-safe installation swapping and directory management.

Handles atomic replacement of the installation directory with retry on
transient Windows sharing violations and collision-free backup restoration.
"""

import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

EXECUTABLE_NAME = "ScanSort.exe"

SWAP_RETRY_TIMEOUT = 10.0
SWAP_RETRY_INTERVAL = 0.1


class UpdateError(Exception):
    """Raised when an update check, download, or install step fails."""


def cleanup_stale_updates(install_dir: Path, keep: Path | None = None) -> None:
    """Remove leftover stage and backup siblings from earlier attempts.

    Deletion failures (e.g. a file still held open by another process) are
    tolerated and deferred to the next update run.
    """
    install_dir = Path(install_dir)
    for pattern in (
        f"{install_dir.name}.stage-*",
        f"{install_dir.name}.old-*",
    ):
        for entry in install_dir.parent.glob(pattern):
            if keep is not None and entry == keep:
                continue
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink(missing_ok=True)
            except OSError as e:
                logger.warning(
                    "Could not remove stale update artifact %s: %s", entry, e
                )


def _rename_dir_with_retry(
    source: Path,
    target: Path,
    timeout: float | None = None,
    interval: float | None = None,
) -> None:
    """Rename a directory, retrying on transient Windows sharing violations.

    On Windows, when a process exits, antivirus scanners (e.g. Windows Defender)
    or kernel-level handle teardown may hold transient locks on executables or
    DLLs in the installation directory for tens to hundreds of milliseconds.
    Retrying with a short backoff allows these transient locks to clear.
    """
    timeout_val = timeout if timeout is not None else SWAP_RETRY_TIMEOUT
    interval_val = interval if interval is not None else SWAP_RETRY_INTERVAL
    deadline = time.monotonic() + timeout_val
    last_error: OSError | None = None
    while True:
        try:
            source.rename(target)
            return
        except OSError as e:
            last_error = e
            if time.monotonic() >= deadline:
                break
            time.sleep(interval_val)
    raise last_error  # type: ignore[misc]


def replace_install_dir(
    install_dir: Path,
    staged_dir: Path,
    *,
    timeout: float | None = None,
    interval: float | None = None,
) -> None:
    """Swap the staged tree into the install directory with rollback.

    Ordering: rename the current install to a backup, rename the staged tree
    into place, then delete the backup. If the second rename fails the backup
    is renamed back before the error propagates, so the auto-start target is
    never left pointing at a missing directory.

    Raises:
        UpdateError: If either directory lacks ``ScanSort.exe``, the initial
            rename fails, or the swap fails and cannot be rolled back.
    """
    install_dir = Path(install_dir)
    staged_dir = Path(staged_dir)
    if not (staged_dir / EXECUTABLE_NAME).is_file():
        raise UpdateError("Staged update does not contain ScanSort.exe.")
    if not (install_dir / EXECUTABLE_NAME).is_file():
        raise UpdateError("Install directory does not contain ScanSort.exe.")

    base_name = f"{install_dir.name}.old-{int(time.time())}"
    backup_dir = install_dir.parent / base_name
    counter = 0
    while backup_dir.exists():
        counter += 1
        backup_dir = install_dir.parent / f"{base_name}-{counter}"

    try:
        _rename_dir_with_retry(
            install_dir, backup_dir, timeout=timeout, interval=interval
        )
    except OSError as e:
        raise UpdateError(f"Could not move the current installation aside: {e}") from e

    try:
        _rename_dir_with_retry(
            staged_dir, install_dir, timeout=timeout, interval=interval
        )
    except OSError as e:
        try:
            _rename_dir_with_retry(
                backup_dir, install_dir, timeout=timeout, interval=interval
            )
        except OSError as rollback_error:
            raise UpdateError(
                "Update swap failed and rollback failed; the previous install "
                f"is preserved at {backup_dir}: {rollback_error}"
            ) from rollback_error
        raise UpdateError(
            f"Update swap failed; the previous installation was restored: {e}"
        ) from e

    try:
        shutil.rmtree(backup_dir)
    except OSError as e:
        logger.warning(
            "Could not remove backup %s; it will be cleaned on a later run: %s",
            backup_dir,
            e,
        )


__all__ = [
    "EXECUTABLE_NAME",
    "SWAP_RETRY_INTERVAL",
    "SWAP_RETRY_TIMEOUT",
    "UpdateError",
    "cleanup_stale_updates",
    "replace_install_dir",
]

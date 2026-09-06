"""Process waiting, detached child launching, and self-update orchestration."""

import contextlib
import ctypes
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from scansort.core.config import get_default_app_dir
from scansort.core.constants import (
    INSTANCE_LOCK_FILENAME,
    UPDATE_LOCK_FILENAME,
    UPDATE_STATE_FILENAME,
)
from scansort.core.fs import interprocess_file_lock
from scansort.platform.instance_guard import instance_guard
from scansort.updater.installer import (
    EXECUTABLE_NAME,
    UpdateError,
    cleanup_stale_updates,
    replace_install_dir,
)
from scansort.updater.state import record_applied_update

logger = logging.getLogger(__name__)

DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000
WAIT_POLL_INTERVAL = 0.25


def _wait_posix_process(pid: int, timeout: float) -> bool:
    """Poll a PID with ``os.kill(pid, 0)`` until it disappears or times out.

    ``os.kill`` is only a valid liveness probe on POSIX; the Windows build uses
    ``_wait_windows_process`` instead (on Windows ``os.kill`` maps to console
    events or TerminateProcess and can never probe existence).
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            pass  # e.g. permission denied: the process still exists
        if time.monotonic() >= deadline:
            return False
        time.sleep(WAIT_POLL_INTERVAL)


def _wait_windows_process(pid: int, timeout: float) -> bool:
    """Wait on a native process handle for termination.

    The handle is opened with SYNCHRONIZE so PID recycling cannot make the wait
    target a different process. If OpenProcess fails with ERROR_ACCESS_DENIED
    (common when a process is in the middle of terminating), it polls until
    the process handle can be opened or until ERROR_INVALID_PARAMETER indicates
    the PID is no longer in the process table.
    """
    process_query_limited = 0x1000
    synchronize = 0x00100000
    wait_object_0 = 0
    error_access_denied = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)

    deadline = time.monotonic() + timeout
    while True:
        handle = kernel32.OpenProcess(process_query_limited | synchronize, False, pid)
        if handle:
            try:
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                result = kernel32.WaitForSingleObject(handle, remaining_ms)
                return result == wait_object_0
            finally:
                kernel32.CloseHandle(handle)

        err = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
        if err != error_access_denied:
            # ERROR_INVALID_PARAMETER (87) means the PID does not exist; any other
            # non-access-denied error also indicates the process is gone.
            return True

        if time.monotonic() >= deadline:
            return False
        time.sleep(WAIT_POLL_INTERVAL)


def wait_for_process_exit(pid: int, timeout: float = 60.0, impl=None) -> bool:
    """Return True when the process exits within ``timeout`` seconds.

    ``impl`` is an optional waiter override used by tests; it defaults to the
    native waiter for the current platform.
    """
    if impl is None:
        if sys.platform == "win32":
            impl = _wait_windows_process
        else:
            impl = _wait_posix_process
    return bool(impl(pid, timeout))


def _popen_detached(argv: list[str], cwd: Path | str | None = None) -> None:
    """Launch a console-less detached child, raising UpdateError on failure."""
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NO_WINDOW
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except OSError as e:
        raise UpdateError(f"Could not launch helper process: {e}") from e


def spawn_update_helper(
    install_dir: Path, staged_dir: Path, version: str, parent_pid: int
) -> None:
    """Spawn the staged build as the detached ``--self-update`` helper.

    The old process must exit right after this returns so the helper can take
    over the instance lock and swap the install directory.

    Raises:
        UpdateError: If the staged executable is missing or cannot be launched.
    """
    executable = Path(staged_dir) / EXECUTABLE_NAME
    if not executable.is_file():
        raise UpdateError("Staged update does not contain ScanSort.exe.")
    logger.info(
        "Spawning self-update helper (PID: %d, version: %s)...", parent_pid, version
    )
    _popen_detached(
        [
            str(executable),
            "--self-update",
            str(parent_pid),
            str(install_dir),
            str(staged_dir),
            version,
        ],
        cwd=Path(install_dir).parent,
    )


def launch_installed_app(install_dir: Path, args: list[str] | None = None) -> None:
    """Relaunch the freshly installed executable in background watch mode."""
    executable = Path(install_dir) / EXECUTABLE_NAME
    if not executable.is_file():
        raise UpdateError("Installed ScanSort.exe not found.")
    argv = [str(executable), *(args if args is not None else ["watch", "--minimized"])]
    _popen_detached(argv)


def perform_self_update(
    pid: int,
    install_dir: Path | str,
    staged_dir: Path | str,
    version: str,
    *,
    app_dir: Path | None = None,
    relaunch: bool = True,
) -> int:
    """Wait for the old process, swap the install, and relaunch the new build.

    Returns a process exit code: 0 on success, 1 on any failure (the previous
    install is preserved or restored in every failure path).
    """
    install_dir = Path(install_dir)
    staged_dir = Path(staged_dir)
    logger.info(
        "Self-update helper launched for version %s (waiting for parent PID %d)...",
        version,
        pid,
    )
    # Ensure this helper process's current working directory is outside both
    # install_dir and staged_dir, so Windows does not lock either directory.
    with contextlib.suppress(OSError):
        os.chdir(install_dir.parent)

    try:
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            raise UpdateError(
                "The --self-update helper requires a frozen Windows build."
            )
        if not (staged_dir / EXECUTABLE_NAME).is_file():
            raise UpdateError("Staged update does not contain ScanSort.exe.")
        if not (install_dir / EXECUTABLE_NAME).is_file():
            raise UpdateError("Installed ScanSort.exe not found.")

        app_dir = Path(app_dir) if app_dir is not None else get_default_app_dir()
        app_dir.mkdir(parents=True, exist_ok=True)

        if not wait_for_process_exit(pid):
            raise UpdateError(
                "Timed out waiting for the previous ScanSort instance to exit."
            )
        with (
            interprocess_file_lock(app_dir / UPDATE_LOCK_FILENAME),
            instance_guard(app_dir / INSTANCE_LOCK_FILENAME) as acquired,
        ):
            if not acquired:
                raise UpdateError(
                    "Another ScanSort instance is running; "
                    "the update will apply on a later start."
                )
            logger.info(
                "Acquired instance and update locks. Swapping installation %s with staged %s...",
                install_dir,
                staged_dir,
            )
            replace_install_dir(install_dir, staged_dir)

        record_applied_update(app_dir / UPDATE_STATE_FILENAME, version)
        cleanup_stale_updates(install_dir)
        logger.info(
            "Update to version %s installed successfully. Relaunching application...",
            version,
        )
        if relaunch:
            launch_installed_app(install_dir)
        return 0
    except UpdateError as e:
        logger.error("Update installation failed: %s", e)
        return 1


__all__ = [
    "CREATE_NO_WINDOW",
    "DETACHED_PROCESS",
    "WAIT_POLL_INTERVAL",
    "launch_installed_app",
    "perform_self_update",
    "spawn_update_helper",
    "wait_for_process_exit",
]

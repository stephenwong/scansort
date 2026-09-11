"""Console attachment utilities for windowed (GUI-subsystem) builds on Windows."""

import ctypes
import os
import sys

ATTACH_PARENT_PROCESS = -1
STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12

__all__ = [
    "ATTACH_PARENT_PROCESS",
    "STD_ERROR_HANDLE",
    "STD_OUTPUT_HANDLE",
    "attach_parent_console",
]


def attach_parent_console() -> None:
    """Bind stdout/stderr to the parent console in frozen windowed builds.

    The packaged ``ScanSort.exe`` is a GUI-subsystem build (``console=False``)
    whose standard streams are null writers, so CLI output such as
    ``config --show`` would otherwise be invisible. When the exe is launched
    from an interactive cmd/PowerShell window, attach to that window's console
    and re-point the standard streams at it (encoded for the console's output
    code page). When launched by double-click or auto-start there is no console
    to attach to: the call fails silently and output stays discarded, exactly
    as before, so the background tray watcher never flashes a terminal.
    """
    if (
        sys.platform != "win32"
        or not getattr(sys, "frozen", False)
        or (sys.stdout is not None and sys.stdout.isatty())
    ):
        return
    try:
        import msvcrt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            return
        output_cp = kernel32.GetConsoleOutputCP()
        encoding = f"cp{output_cp}" if output_cp else "utf-8"
        for name, std_handle in (
            ("stdout", STD_OUTPUT_HANDLE),
            ("stderr", STD_ERROR_HANDLE),
        ):
            handle = kernel32.GetStdHandle(std_handle)
            if not handle or handle == -1:
                continue
            fd = msvcrt.open_osfhandle(handle, os.O_WRONLY)
            setattr(sys, name, os.fdopen(fd, "w", encoding=encoding, buffering=1))
    except AttributeError, ImportError, LookupError, OSError, ValueError:
        return

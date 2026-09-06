"""Windows native toast notifications backed by the optional ``windows-toasts`` extra.

The library is only imported lazily on Windows. Off-Windows development and CI
runs exercise every reachable path through an injected fake backend, while the
real WinRT display code is confined to ``WindowsToastBackend``.
"""

import logging
import os
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_backend = None


def open_path(target_path: Path | str) -> bool:
    """Open a file or directory with its default associated application (never raises).

    Returns True if the open command was successfully issued, False otherwise.
    """
    try:
        path = Path(target_path).resolve()
        if not path.exists():
            # If target has an extension (like a log file) and parent exists, create it
            if path.suffix and path.parent.exists():
                path.touch(exist_ok=True)
            else:
                logger.warning("Target path does not exist: %s", path)
                return False

        if hasattr(os, "startfile"):
            os.startfile(str(path))
        elif sys.platform == "win32":
            subprocess.Popen(["explorer.exe", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Could not open path %s: %s", target_path, e)
        return False


class WindowsToastBackend:
    """Thin wrapper isolating every ``windows_toasts`` interaction."""

    def __init__(self) -> None:
        import windows_toasts

        toaster_cls = getattr(
            windows_toasts,
            "InteractableWindowsToaster",
            getattr(windows_toasts, "WindowsToaster", None),
        )
        if toaster_cls is None:
            raise ImportError(
                "Neither InteractableWindowsToaster nor WindowsToaster found"
            )

        self._toaster = toaster_cls("ScanSort")
        self._toast_class = windows_toasts.Toast
        self._toast_button_class = getattr(windows_toasts, "ToastButton", None)
        self._recent_toasts: deque[Any] = deque(maxlen=20)

    def show(
        self,
        title: str,
        body: str,
        on_click: Callable[..., Any] | None = None,
        folder_path: Path | str | None = None,
        log_path: Path | str | None = None,
    ) -> None:
        toast = self._toast_class()
        toast.text_fields = [title, body]

        if log_path is not None and self._toast_button_class is not None:
            btn = self._toast_button_class(content="View Logs", arguments="view_log")
            toast.AddAction(btn)

        def _handle_activated(args: Any = None) -> None:
            arg_str = getattr(args, "arguments", None)
            if arg_str == "view_log" and log_path is not None:
                open_path(log_path)
            elif folder_path is not None:
                open_path(folder_path)
            elif on_click is not None:
                on_click()

        if on_click is not None or folder_path is not None or log_path is not None:
            toast.on_activated = _handle_activated

        self._recent_toasts.append(toast)
        self._toaster.show_toast(toast)


def _get_backend() -> WindowsToastBackend:
    """Return the process-wide toast backend, building it on first use."""
    global _backend
    if _backend is None:
        _backend = WindowsToastBackend()
    return _backend


def show_toast(
    title: str,
    body: str,
    on_click: Callable[..., Any] | None = None,
    folder_path: Path | str | None = None,
    log_path: Path | str | None = None,
) -> bool:
    """Display a Windows toast notification, never raising.

    Returns False when toasts are unsupported on this platform, the optional
    ``windows-toasts`` backend is unavailable, or the display call fails.
    """
    if sys.platform != "win32":
        return False
    try:
        _get_backend().show(
            title,
            body,
            on_click=on_click,
            folder_path=folder_path,
            log_path=log_path,
        )
    except (ImportError, OSError, RuntimeError) as e:
        logger.warning("Could not display toast notification: %s", e)
        return False
    return True

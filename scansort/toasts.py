"""Windows native toast notifications backed by the optional ``windows-toasts`` extra.

The library is only imported lazily on Windows. Off-Windows development and CI
runs exercise every reachable path through an injected fake backend, while the
real WinRT display code is confined to ``WindowsToastBackend``.
"""

import logging
import sys

logger = logging.getLogger(__name__)

_backend = None


class WindowsToastBackend:
    """Thin wrapper isolating every ``windows_toasts`` interaction."""

    def __init__(self) -> None:
        from windows_toasts import Toast, WindowsToaster

        self._toaster = WindowsToaster("ScanSort")
        self._toast_class = Toast

    def show(self, title: str, body: str) -> None:
        toast = self._toast_class()
        toast.text_fields = [title, body]
        self._toaster.show_toast(toast)


def _get_backend() -> WindowsToastBackend:
    """Return the process-wide toast backend, building it on first use."""
    global _backend
    if _backend is None:
        _backend = WindowsToastBackend()
    return _backend


def show_toast(title: str, body: str) -> bool:
    """Display a Windows toast notification, never raising.

    Returns False when toasts are unsupported on this platform, the optional
    ``windows-toasts`` backend is unavailable, or the display call fails.
    """
    if sys.platform != "win32":
        return False
    try:
        _get_backend().show(title, body)
    except (ImportError, OSError, RuntimeError) as e:
        logger.warning("Could not display toast notification: %s", e)
        return False
    return True

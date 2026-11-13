"""Windows native toast notifications backed by the optional ``windows`` (PyWinRT) extra.

The WinRT projection packages are imported lazily on Windows. Off-Windows
development and CI runs exercise every reachable path through injected fake
``winrt`` modules, while real WinRT display calls are confined to
``WindowsToastBackend``.
"""

import logging
import os
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

# Attribution label and known AUMID enabling foreground action buttons without
# requiring system-wide AppUserModelId registry registration.
TOASTER_AUM_ID = "ScanSort"
_DEFAULT_AUM_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\cmd.exe"
# Bounded retention so WinRT activation callbacks survive garbage collection.
_RECENT_TOAST_LIMIT = 20

_backend = None
_backend_lock = threading.Lock()


def open_path(target_path: Path | str, *, create_file: bool = False) -> bool:
    """Open a file or directory with its default associated application (never raises).

    ``create_file`` explicitly permits creating a missing file (used for the log
    file); directories are never inferred from a dotted name.

    Returns True if the open command was successfully issued, False otherwise.
    """
    try:
        path = Path(target_path).resolve()
        if not path.exists():
            if create_file and path.parent.exists():
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
    """Thin wrapper isolating every PyWinRT toast notification interaction."""

    def __init__(self) -> None:
        import winrt.windows.data.xml.dom as winrt_dom
        import winrt.windows.ui.notifications as winrt_notifications

        xml_doc_cls = getattr(winrt_dom, "XmlDocument", None)
        if xml_doc_cls is None:
            raise ImportError("winrt.windows.data.xml.dom.XmlDocument not found")

        manager_cls = getattr(winrt_notifications, "ToastNotificationManager", None)
        if manager_cls is None:
            raise ImportError(
                "winrt.windows.ui.notifications.ToastNotificationManager not found"
            )

        create_notifier = getattr(
            manager_cls,
            "create_toast_notifier_with_id",
            getattr(manager_cls, "create_toast_notifier", None),
        )
        if create_notifier is None:
            raise ImportError("ToastNotificationManager notifier factory not found")

        toast_cls = getattr(winrt_notifications, "ToastNotification", None)
        if toast_cls is None:
            raise ImportError(
                "winrt.windows.ui.notifications.ToastNotification not found"
            )

        self._notifier = create_notifier(_DEFAULT_AUM_ID)
        self._xml_document_cls = xml_doc_cls
        self._toast_notification_cls = toast_cls
        self._activated_args_cls = getattr(
            winrt_notifications, "ToastActivatedEventArgs", None
        )
        self._recent_toasts: deque[Any] = deque(maxlen=_RECENT_TOAST_LIMIT)

    def show(
        self,
        title: str,
        body: str,
        on_click: Callable[..., Any] | None = None,
        folder_path: Path | str | None = None,
        log_path: Path | str | None = None,
    ) -> None:
        actions_xml = ""
        if log_path is not None:
            actions_xml = (
                "<actions>"
                '<action content="View Logs" arguments="view_log" activationType="foreground"/>'
                "</actions>"
            )

        toast_xml = (
            '<toast useButtonStyle="true">'
            "<visual>"
            '<binding template="ToastGeneric">'
            f"<text>{escape(title)}</text>"
            f"<text>{escape(body)}</text>"
            f'<text placement="attribution">{escape(TOASTER_AUM_ID)}</text>'
            "</binding>"
            "</visual>"
            f"{actions_xml}"
            "</toast>"
        )

        xml_doc = self._xml_document_cls()
        xml_doc.load_xml(toast_xml)
        toast = self._toast_notification_cls(xml_doc)

        def _handle_activated(_sender: Any = None, args: Any = None) -> None:
            if (
                args is not None
                and not hasattr(args, "arguments")
                and self._activated_args_cls is not None
                and hasattr(args, "as_")
            ):
                args = args.as_(self._activated_args_cls)
            arg_str = getattr(args, "arguments", None)
            if arg_str == "view_log" and log_path is not None:
                open_path(log_path, create_file=True)
            elif folder_path is not None:
                open_path(folder_path)
            elif on_click is not None:
                on_click()

        if on_click is not None or folder_path is not None or log_path is not None:
            toast.add_activated(_handle_activated)

        self._recent_toasts.append(toast)
        self._notifier.show(toast)


def _get_backend() -> WindowsToastBackend:
    """Return the process-wide toast backend, building it on first use."""
    global _backend
    if _backend is None:
        with _backend_lock:
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
    ``winrt`` backend is unavailable, or the display call fails.
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
    except Exception as e:  # noqa: BLE001 - toasts must never raise
        logger.warning("Could not display toast notification: %s", e)
        return False
    return True

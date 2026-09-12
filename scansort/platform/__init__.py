"""Platform and operating system integration (Windows Registry, toasts, credentials, locks, console)."""

from scansort.platform.autorun import (
    disable_autorun,
    enable_autorun,
    is_autorun_enabled,
)
from scansort.platform.console import attach_parent_console
from scansort.platform.context_menu import (
    disable_context_menu,
    disable_ocr_menu,
    enable_context_menu,
    enable_ocr_menu,
    is_context_menu_enabled,
    is_ocr_menu_enabled,
)
from scansort.platform.instance_guard import instance_guard
from scansort.platform.notifications import (
    file_filed_message,
    filing_failed_message,
    notify_file_filed,
    notify_filing_failed,
    notify_scan_stranded,
    scan_stranded_message,
)
from scansort.platform.secrets import (
    delete_api_key,
    get_api_key,
    mask_api_key,
    redact_secrets_from_text,
    set_api_key,
)
from scansort.platform.toasts import open_path, show_toast

__all__ = [
    "disable_autorun",
    "enable_autorun",
    "is_autorun_enabled",
    "disable_context_menu",
    "enable_context_menu",
    "is_context_menu_enabled",
    "disable_ocr_menu",
    "enable_ocr_menu",
    "is_ocr_menu_enabled",
    "attach_parent_console",
    "instance_guard",
    "delete_api_key",
    "get_api_key",
    "mask_api_key",
    "redact_secrets_from_text",
    "set_api_key",
    "open_path",
    "show_toast",
    "file_filed_message",
    "filing_failed_message",
    "notify_file_filed",
    "notify_filing_failed",
    "notify_scan_stranded",
    "scan_stranded_message",
]

"""User-facing toast messages for document filing lifecycle events.

Message builders are kept separate from the best-effort display call so the
exact wording can be unit-tested and reused by any caller; the ``notify_*``
wrappers degrade silently off Windows or when toasts are unavailable.
"""

import logging

from scansort.secrets import redact_secrets_from_text
from scansort.toasts import show_toast

logger = logging.getLogger(__name__)

MAX_REASON_CHARS = 140


def _clean_reason(reason: str) -> str:
    """Collapse whitespace, redact secrets, and truncate an error reason."""
    text = " ".join(reason.split())
    text = redact_secrets_from_text(text)
    if len(text) > MAX_REASON_CHARS:
        cutoff = text[:MAX_REASON_CHARS].rfind(" ")
        end = cutoff if cutoff > MAX_REASON_CHARS // 2 else MAX_REASON_CHARS
        text = text[:end].rstrip() + "…"
    return text


def file_filed_message(filed_name: str, folder: str) -> tuple[str, str]:
    """Return (title, body) announcing a successfully filed document."""
    return ("Document filed", f"{filed_name} → {folder}")


def filing_failed_message(
    source_name: str, folder: str, reason: str | None = None
) -> tuple[str, str]:
    """Return (title, body) announcing a scan routed to the review folder."""
    body = f"{source_name} → {folder}"
    if reason:
        cleaned = _clean_reason(reason)
        if cleaned:
            body = f"{body}\nReason: {cleaned}"
    return ("Document filing failed", body)


def scan_stranded_message(source_name: str, folder: str) -> tuple[str, str]:
    """Return (title, body) announcing a scan that could not be routed."""
    return (
        "ScanSort needs attention",
        f"{source_name} could not be processed or moved to {folder}.\n"
        "Please check your drop folder.",
    )


def notify_file_filed(filed_name: str, folder: str) -> bool:
    """Toast that a document was filed into ``folder`` (best effort)."""
    return show_toast(*file_filed_message(filed_name, folder))


def notify_filing_failed(
    source_name: str, folder: str, reason: str | None = None
) -> bool:
    """Toast that a document failed and was routed to ``folder`` (best effort)."""
    return show_toast(*filing_failed_message(source_name, folder, reason))


def notify_scan_stranded(source_name: str, folder: str) -> bool:
    """Toast that a document needs manual attention in the drop folder."""
    return show_toast(*scan_stranded_message(source_name, folder))

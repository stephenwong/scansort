"""Unit tests for filing lifecycle toast message builders."""

from pathlib import Path
from unittest.mock import patch

from scansort.notifications import (
    MAX_REASON_CHARS,
    file_filed_message,
    filing_failed_message,
    notify_file_filed,
    notify_filing_failed,
    notify_scan_stranded,
    scan_stranded_message,
)


def test_file_filed_message_exact_wording():
    title, body = file_filed_message(
        "260901_Origin_Energy.pdf", "Utilities/Electricity"
    )
    assert title == "ScanSort"
    assert body == "260901_Origin_Energy.pdf → Utilities/Electricity"


def test_filing_failed_message_exact_wording_with_reason():
    title, body = filing_failed_message(
        "scan001.pdf", "_Review_Needed", "Gemini rate limit exceeded (429)"
    )
    assert title == "ScanSort"
    assert body == (
        "Filing failed: scan001.pdf → _Review_Needed\nReason: Gemini rate limit exceeded (429)"
    )


def test_filing_failed_message_omits_reason_line_when_empty():
    _, body = filing_failed_message("scan001.pdf", "_Review_Needed", None)
    assert body == "Filing failed: scan001.pdf → _Review_Needed"
    _, body = filing_failed_message("scan001.pdf", "_Review_Needed", "   ")
    assert body == "Filing failed: scan001.pdf → _Review_Needed"
    _, body = filing_failed_message("scan001.pdf", "_Review_Needed", "")
    assert body == "Filing failed: scan001.pdf → _Review_Needed"


def test_filing_failed_message_collapses_whitespace_and_redacts_secrets():
    secret = f"AIza{'X' * 34}"
    _, body = filing_failed_message(
        "scan001.pdf",
        "_Review_Needed",
        f"Connection  reset\n{secret} token leaked",
    )
    assert secret not in body
    assert "\n\n" not in body


def test_filing_failed_message_truncates_long_reasons():
    _, body = filing_failed_message(
        "scan001.pdf", "_Review_Needed", "x" * (MAX_REASON_CHARS * 2)
    )
    assert (
        body
        == f"Filing failed: scan001.pdf → _Review_Needed\nReason: {'x' * MAX_REASON_CHARS}…"
    )


def test_filing_failed_message_truncates_on_word_boundary():
    words = " ".join(["overlongword"] * 60)
    _, body = filing_failed_message("scan001.pdf", "_Review_Needed", words)
    reason = body.split("Reason: ", 1)[1]
    assert reason.endswith("…")
    assert len(reason) <= MAX_REASON_CHARS + 1


def test_scan_stranded_message_exact_wording():
    title, body = scan_stranded_message("scan001.pdf", "_Review_Needed")
    assert title == "ScanSort"
    assert body == (
        "Attention needed: scan001.pdf could not be processed or moved to _Review_Needed.\n"
        "Please check your drop folder."
    )


def test_notify_file_filed_dispatches_built_message():
    folder_path = Path("/docs/Bills")
    with patch("scansort.notifications.show_toast", return_value=True) as mock_toast:
        assert notify_file_filed("doc.pdf", "Bills", folder_path=folder_path) is True
    mock_toast.assert_called_once_with(
        "ScanSort", "doc.pdf → Bills", folder_path=folder_path, log_path=None
    )


def test_notify_filing_failed_dispatches_built_message():
    folder_path = Path("/docs/_Review_Needed")
    log_path = Path("/appdata/scansort.log")
    with patch("scansort.notifications.show_toast", return_value=False) as mock_toast:
        assert (
            notify_filing_failed(
                "a.pdf",
                "_Review_Needed",
                "boom",
                folder_path=folder_path,
                log_path=log_path,
            )
            is False
        )
    mock_toast.assert_called_once_with(
        "ScanSort",
        "Filing failed: a.pdf → _Review_Needed\nReason: boom",
        folder_path=folder_path,
        log_path=log_path,
    )


def test_notify_scan_stranded_dispatches_built_message():
    folder_path = Path("/inbox")
    log_path = Path("/appdata/scansort.log")
    with patch("scansort.notifications.show_toast", return_value=True) as mock_toast:
        assert (
            notify_scan_stranded(
                "a.pdf",
                "_Review_Needed",
                folder_path=folder_path,
                log_path=log_path,
            )
            is True
        )
    mock_toast.assert_called_once_with(
        "ScanSort",
        "Attention needed: a.pdf could not be processed or moved to _Review_Needed.\n"
        "Please check your drop folder.",
        folder_path=folder_path,
        log_path=log_path,
    )

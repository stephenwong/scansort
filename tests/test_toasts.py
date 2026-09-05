"""Unit tests for Windows toast notifications."""

import sys
from unittest.mock import MagicMock, patch

from scansort import toasts


def _install_fake_windows_toasts(monkeypatch) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Inject a fake ``windows_toasts`` library and simulate a Windows host."""
    monkeypatch.setattr("sys.platform", "win32")
    fake_lib = MagicMock()
    fake_toaster = fake_lib.WindowsToaster.return_value
    fake_toast = fake_lib.Toast.return_value
    fake_toast.text_fields = []
    toasts._backend = None
    with patch.dict(sys.modules, {"windows_toasts": fake_lib}):
        yield fake_lib, fake_toaster, fake_toast
    toasts._backend = None


def test_show_toast_noop_off_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    assert toasts.show_toast("ScanSort updated", "body") is False


def test_show_toast_builds_backend_and_displays(monkeypatch):
    for fake_lib, fake_toaster, fake_toast in _install_fake_windows_toasts(monkeypatch):
        assert (
            toasts.show_toast("ScanSort update available", "Version 1.2.3 found.")
            is True
        )
        fake_lib.WindowsToaster.assert_called_once_with("ScanSort")
        fake_lib.Toast.assert_called_once()
        assert fake_toast.text_fields == [
            "ScanSort update available",
            "Version 1.2.3 found.",
        ]
        fake_toaster.show_toast.assert_called_once_with(fake_toast)


def test_show_toast_swallows_missing_library(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    toasts._backend = None
    try:
        with patch.dict(sys.modules, {"windows_toasts": None}):
            assert toasts.show_toast("t", "b") is False
    finally:
        toasts._backend = None


def test_show_toast_swallows_display_failure(monkeypatch):
    for _, fake_toaster, _ in _install_fake_windows_toasts(monkeypatch):
        fake_toaster.show_toast.side_effect = OSError("no interactive session")
        assert toasts.show_toast("t", "b") is False


def test_show_toast_reuses_cached_backend(monkeypatch):
    backend = MagicMock()
    toasts._backend = backend
    monkeypatch.setattr("sys.platform", "win32")
    try:
        assert toasts.show_toast("t", "b") is True
        backend.show.assert_called_once_with("t", "b")
    finally:
        toasts._backend = None

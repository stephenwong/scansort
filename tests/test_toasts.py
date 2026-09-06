import os
import sys
from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock, patch

from scansort import toasts


def _install_fake_windows_toasts(monkeypatch) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Inject a fake ``windows_toasts`` library and simulate a Windows host."""
    monkeypatch.setattr("sys.platform", "win32")
    fake_lib = MagicMock()
    fake_toaster = MagicMock()
    fake_lib.InteractableWindowsToaster.return_value = fake_toaster
    fake_lib.WindowsToaster.return_value = fake_toaster

    fake_toast = MagicMock()
    fake_toast.text_fields = []
    fake_toast.actions = []

    def _add_action(action):
        fake_toast.actions.append(action)

    fake_toast.AddAction.side_effect = _add_action
    fake_lib.Toast.return_value = fake_toast

    ToastButton = namedtuple("ToastButton", ["content", "arguments"], defaults=["", ""])
    fake_lib.ToastButton = ToastButton

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
        fake_lib.InteractableWindowsToaster.assert_called_once_with("ScanSort")
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
        backend.show.assert_called_once_with(
            "t", "b", on_click=None, folder_path=None, log_path=None
        )
    finally:
        toasts._backend = None


def test_open_path_windows_os_startfile(tmp_path: Path, monkeypatch):
    target = tmp_path / "folder"
    target.mkdir()
    mock_startfile = MagicMock()
    monkeypatch.setattr(os, "startfile", mock_startfile, raising=False)
    monkeypatch.setattr("sys.platform", "win32")

    assert toasts.open_path(target) is True
    mock_startfile.assert_called_once_with(str(target.resolve()))


def test_open_path_windows_creates_missing_file_in_existing_parent(
    tmp_path: Path, monkeypatch
):
    log_file = tmp_path / "scansort.log"
    mock_startfile = MagicMock()
    monkeypatch.setattr(os, "startfile", mock_startfile, raising=False)
    monkeypatch.setattr("sys.platform", "win32")

    assert not log_file.exists()
    assert toasts.open_path(log_file) is True
    assert log_file.exists()
    mock_startfile.assert_called_once_with(str(log_file.resolve()))


def test_open_path_nonexistent_parent_returns_false(tmp_path: Path, monkeypatch):
    target = tmp_path / "nonexistent_dir" / "file.log"
    mock_startfile = MagicMock()
    monkeypatch.setattr(os, "startfile", mock_startfile, raising=False)
    monkeypatch.setattr("sys.platform", "win32")

    assert toasts.open_path(target) is False
    mock_startfile.assert_not_called()


def test_open_path_windows_subprocess_fallback(tmp_path: Path, monkeypatch):
    target = tmp_path / "folder"
    target.mkdir()
    if hasattr(os, "startfile"):
        monkeypatch.delattr(os, "startfile")
    monkeypatch.setattr("sys.platform", "win32")

    with patch("subprocess.Popen") as mock_popen:
        assert toasts.open_path(target) is True
        mock_popen.assert_called_once_with(["explorer.exe", str(target.resolve())])


def test_open_path_macos_and_linux(tmp_path: Path, monkeypatch):
    target = tmp_path / "folder"
    target.mkdir()
    if hasattr(os, "startfile"):
        monkeypatch.delattr(os, "startfile")

    monkeypatch.setattr("sys.platform", "darwin")
    with patch("subprocess.Popen") as mock_popen:
        assert toasts.open_path(target) is True
        mock_popen.assert_called_once_with(["open", str(target.resolve())])

    monkeypatch.setattr("sys.platform", "linux")
    with patch("subprocess.Popen") as mock_popen:
        assert toasts.open_path(target) is True
        mock_popen.assert_called_once_with(["xdg-open", str(target.resolve())])


def test_open_path_swallows_launcher_exception(tmp_path: Path, monkeypatch):
    target = tmp_path / "folder"
    target.mkdir()
    mock_startfile = MagicMock(side_effect=OSError("Access denied"))
    monkeypatch.setattr(os, "startfile", mock_startfile, raising=False)
    monkeypatch.setattr("sys.platform", "win32")

    assert toasts.open_path(target) is False


def test_show_toast_interactive_activation(tmp_path: Path, monkeypatch):
    folder = tmp_path / "FiledFolder"
    folder.mkdir()
    log_path = tmp_path / "scansort.log"

    for _, _fake_toaster, fake_toast in _install_fake_windows_toasts(monkeypatch):
        with patch("scansort.toasts.open_path") as mock_open:
            assert (
                toasts.show_toast(
                    "ScanSort",
                    "Filing failed",
                    folder_path=folder,
                    log_path=log_path,
                )
                is True
            )

            # Assert "View Logs" button was attached
            assert len(fake_toast.actions) == 1
            assert fake_toast.actions[0].content == "View Logs"
            assert fake_toast.actions[0].arguments == "view_log"

            # Simulate clicking "View Logs" button
            Args = namedtuple("Args", ["arguments"])
            fake_toast.on_activated(Args(arguments="view_log"))
            mock_open.assert_called_with(log_path)

            mock_open.reset_mock()
            # Simulate clicking the toast body (no argument)
            fake_toast.on_activated(Args(arguments=""))
            mock_open.assert_called_with(folder)


def test_show_toast_retains_recent_toasts_in_memory(monkeypatch):
    for _, _, _ in _install_fake_windows_toasts(monkeypatch):
        backend = toasts._get_backend()
        for i in range(25):
            toasts.show_toast("Title", f"Body {i}")
        assert len(backend._recent_toasts) == 20
        assert backend._recent_toasts[-1].text_fields == ["Title", "Body 24"]


def test_backend_fallback_when_interactable_toaster_missing(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    fake_lib = MagicMock(spec=["WindowsToaster", "Toast"])
    fake_toaster = fake_lib.WindowsToaster.return_value
    fake_toast = fake_lib.Toast.return_value
    fake_toast.text_fields = []
    fake_toast.actions = []

    toasts._backend = None
    with patch.dict(sys.modules, {"windows_toasts": fake_lib}):
        assert toasts.show_toast("Title", "Body") is True
        fake_lib.WindowsToaster.assert_called_once_with("ScanSort")
        fake_toaster.show_toast.assert_called_once_with(fake_toast)
    toasts._backend = None


def test_show_toast_custom_on_click_callback(monkeypatch):
    for _, _, fake_toast in _install_fake_windows_toasts(monkeypatch):
        mock_cb = MagicMock()
        assert toasts.show_toast("Title", "Body", on_click=mock_cb) is True
        assert fake_toast.on_activated is not None
        fake_toast.on_activated(None)
        mock_cb.assert_called_once()


def test_backend_missing_toaster_classes(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    fake_lib = MagicMock(spec=["Toast"])
    toasts._backend = None
    with patch.dict(sys.modules, {"windows_toasts": fake_lib}):
        assert toasts.show_toast("Title", "Body") is False
    toasts._backend = None

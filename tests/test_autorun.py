"""Unit tests for scansort.autorun module."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from scansort.autorun import disable_autorun, enable_autorun, is_autorun_enabled


def test_autorun_non_windows(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    autostart_dir = tmp_path / ".config" / "autostart"
    desktop_file = autostart_dir / "scansort.desktop"

    with patch("scansort.autorun._get_linux_autostart_path", return_value=desktop_file):
        assert is_autorun_enabled() is False

        assert enable_autorun(executable_path="/usr/bin/scansort") is True
        assert desktop_file.exists()
        assert is_autorun_enabled() is True

        assert disable_autorun() is True
        assert not desktop_file.exists()
        assert is_autorun_enabled() is False


def test_autorun_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")

    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_winreg.OpenKey.return_value = mock_key
    mock_winreg.QueryValueEx.return_value = (
        '"C:\\Programs\\ScanSort.exe" --minimized',
        1,
    )

    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.autorun._winreg", mock_winreg, create=True),
    ):
        # Test enabled check
        enabled = is_autorun_enabled()
        assert enabled is True

        # Test enable
        enable_autorun("C:\\Programs\\ScanSort.exe")
        mock_winreg.SetValueEx.assert_called()

        # Test disable
        disable_autorun()
        mock_winreg.DeleteValue.assert_called()


def test_autorun_windows_exceptions(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")

    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = OSError("Access denied")
    mock_winreg.SetValueEx.side_effect = OSError("Write failed")
    mock_winreg.DeleteValue.side_effect = OSError("Delete failed")

    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.autorun._winreg", mock_winreg, create=True),
    ):
        assert is_autorun_enabled() is False
        assert enable_autorun("C:\\app.exe") is False
        assert disable_autorun() is False


def test_autorun_linux_os_errors(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    desktop_file = tmp_path / "autostart" / "app.desktop"

    with patch("scansort.autorun._get_linux_autostart_path", return_value=desktop_file):
        with patch.object(Path, "write_text", side_effect=OSError("Permission denied")):
            assert enable_autorun() is False

        desktop_file.parent.mkdir(parents=True, exist_ok=True)
        desktop_file.touch()
        with patch.object(Path, "unlink", side_effect=OSError("Cannot delete")):
            assert disable_autorun() is False


def test_autorun_windows_file_not_found_returns_true(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    mock_winreg = MagicMock()
    mock_winreg.DeleteValue.side_effect = FileNotFoundError("Value not found")

    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.autorun._winreg", mock_winreg, create=True),
    ):
        assert disable_autorun() is True


def test_autorun_command_formatting(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    desktop_file = tmp_path / "autostart" / "app.desktop"

    with patch("scansort.autorun._get_linux_autostart_path", return_value=desktop_file):
        enable_autorun(executable_path="/opt/my path/scansort")
        content = desktop_file.read_text(encoding="utf-8")
        assert 'Exec="/opt/my path/scansort" watch --minimized' in content


def test_autorun_macos_unsupported(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")

    assert is_autorun_enabled() is False
    assert enable_autorun() is False
    assert disable_autorun() is True


def test_linux_autostart_path_respects_xdg_config_home(tmp_path: Path, monkeypatch):
    custom_xdg = tmp_path / "custom_xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(custom_xdg))
    monkeypatch.setattr("sys.platform", "linux")

    from scansort.autorun import _get_linux_autostart_path

    path = _get_linux_autostart_path()
    assert path == custom_xdg / "autostart" / "scansort.desktop"


def test_autorun_windows_import_error(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")

    with (
        patch("builtins.__import__", side_effect=ImportError("No module winreg")),
        patch.dict("sys.modules", {"winreg": None}),
    ):
        assert is_autorun_enabled() is False
        assert enable_autorun("C:\\app.exe") is False
        assert disable_autorun() is False


def test_autorun_frozen_executable(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.frozen", True, raising=False)
    desktop_file = tmp_path / "autostart" / "app.desktop"

    with patch("scansort.autorun._get_linux_autostart_path", return_value=desktop_file):
        enable_autorun()
        content = desktop_file.read_text(encoding="utf-8")
        assert f'Exec="{sys.executable}" watch --minimized' in content


def test_autorun_linux_disable_missing_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    desktop_file = tmp_path / "autostart" / "nonexistent.desktop"

    with patch("scansort.autorun._get_linux_autostart_path", return_value=desktop_file):
        assert disable_autorun() is True

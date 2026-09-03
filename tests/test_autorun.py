"""Unit tests for scansort.autorun module (TDD Cycle 10)."""

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
    mock_winreg.QueryValueEx.return_value = ('"C:\\Programs\\ScanSort.exe" --minimized', 1)

    with patch.dict("sys.modules", {"winreg": mock_winreg}), patch("scansort.autorun._winreg", mock_winreg, create=True):
            # Test enabled check
            enabled = is_autorun_enabled()
            assert enabled is True

            # Test enable
            enable_autorun("C:\\Programs\\ScanSort.exe")
            mock_winreg.SetValueEx.assert_called()

            # Test disable
            disable_autorun()
            mock_winreg.DeleteValue.assert_called()

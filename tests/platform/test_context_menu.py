"""Unit tests for scansort.platform.context_menu module."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from scansort.core.constants import SUPPORTED_EXTENSIONS
from scansort.platform.context_menu import (
    _build_context_menu_command,
    _get_linux_nautilus_script_path,
    disable_context_menu,
    enable_context_menu,
    is_context_menu_enabled,
)


def test_build_context_menu_command_custom_executable():
    cmd = _build_context_menu_command(executable_path="C:\\MyPath\\ScanSort.exe")
    assert cmd == '"C:\\MyPath\\ScanSort.exe" file "%1"'


def test_build_context_menu_command_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:\\ScanSort\\ScanSort.exe")
    cmd = _build_context_menu_command()
    assert cmd == '"C:\\ScanSort\\ScanSort.exe" file "%1"'


def test_build_context_menu_command_unfrozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    cmd = _build_context_menu_command()
    assert cmd == '"/usr/bin/python3" -m scansort file "%1"'


def test_context_menu_linux(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    script_path = tmp_path / "nautilus" / "scripts" / "File with ScanSort"

    with patch(
        "scansort.platform.context_menu._get_linux_nautilus_script_path",
        return_value=script_path,
    ):
        assert is_context_menu_enabled() is False

        assert enable_context_menu(executable_path="/usr/bin/scansort") is True
        assert script_path.exists()
        assert is_context_menu_enabled() is True
        content = script_path.read_text(encoding="utf-8")
        assert 'scansort file "$f"' in content

        assert disable_context_menu() is True
        assert not script_path.exists()
        assert is_context_menu_enabled() is False


def test_context_menu_linux_truncated_not_enabled(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    script_path = tmp_path / "scripts" / "File with ScanSort"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("invalid")

    with patch(
        "scansort.platform.context_menu._get_linux_nautilus_script_path",
        return_value=script_path,
    ):
        assert is_context_menu_enabled() is False


def test_context_menu_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")

    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    mock_winreg.CreateKey.return_value.__enter__.return_value = mock_key
    mock_winreg.QueryValueEx.return_value = (
        '"C:\\Programs\\ScanSort.exe" file "%1"',
        1,
    )

    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.platform.context_menu._winreg", mock_winreg, create=True),
    ):
        enabled = is_context_menu_enabled()
        assert enabled is True

        assert enable_context_menu("C:\\Programs\\ScanSort.exe") is True
        # Verify CreateKey was called for each extension (for verb key and command key)
        assert mock_winreg.CreateKey.call_count == len(SUPPORTED_EXTENSIONS) * 2

        assert disable_context_menu() is True
        assert mock_winreg.DeleteKey.call_count >= len(SUPPORTED_EXTENSIONS)


def test_context_menu_windows_partial_enable(monkeypatch):
    """Enabled status is reported only when every supported extension has a command."""
    monkeypatch.setattr("sys.platform", "win32")

    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key

    probed = 0

    def fake_query_value_ex(key, value_name):
        nonlocal probed
        probed += 1
        # First probed extension carries a command; the rest are missing it.
        return ('"C:\\Programs\\ScanSort.exe" file "%1"', 1) if probed == 1 else ("", 1)

    mock_winreg.QueryValueEx = fake_query_value_ex
    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.platform.context_menu._winreg", mock_winreg, create=True),
    ):
        assert is_context_menu_enabled() is False
    # Short-circuits on the first extension whose command value is empty.
    assert probed == 2


def test_context_menu_windows_disabled_when_empty_or_missing(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")

    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    mock_winreg.QueryValueEx.return_value = ("", 1)

    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.platform.context_menu._winreg", mock_winreg, create=True),
    ):
        assert is_context_menu_enabled() is False

    mock_winreg.OpenKey.side_effect = FileNotFoundError()
    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.platform.context_menu._winreg", mock_winreg, create=True),
    ):
        assert is_context_menu_enabled() is False


def test_context_menu_windows_enable_error(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")

    mock_winreg = MagicMock()
    mock_winreg.CreateKey.side_effect = OSError("Permission denied")

    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.platform.context_menu._winreg", mock_winreg, create=True),
    ):
        assert enable_context_menu("C:\\Programs\\ScanSort.exe") is False


def test_context_menu_windows_disable_error(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")

    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = OSError("Registry error")

    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.platform.context_menu._winreg", mock_winreg, create=True),
    ):
        assert disable_context_menu() is False


def test_context_menu_linux_xdg_data_home(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    custom_data = tmp_path / "custom_share"
    monkeypatch.setenv("XDG_DATA_HOME", str(custom_data))

    path = _get_linux_nautilus_script_path()
    assert str(custom_data) in str(path)


def test_context_menu_linux_read_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    script_path = tmp_path / "scripts" / "File with ScanSort"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("scansort file")

    with (
        patch(
            "scansort.platform.context_menu._get_linux_nautilus_script_path",
            return_value=script_path,
        ),
        patch.object(Path, "read_text", side_effect=OSError("Read error")),
    ):
        assert is_context_menu_enabled() is False


def test_context_menu_linux_enable_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    script_path = tmp_path / "scripts" / "File with ScanSort"

    with (
        patch(
            "scansort.platform.context_menu._get_linux_nautilus_script_path",
            return_value=script_path,
        ),
        patch.object(Path, "mkdir", side_effect=OSError("Disk full")),
    ):
        assert enable_context_menu("/usr/bin/scansort") is False


def test_context_menu_linux_disable_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    script_path = tmp_path / "scripts" / "File with ScanSort"

    with (
        patch(
            "scansort.platform.context_menu._get_linux_nautilus_script_path",
            return_value=script_path,
        ),
        patch.object(Path, "unlink", side_effect=OSError("Cannot delete")),
    ):
        assert disable_context_menu() is False


def test_context_menu_unsupported_platform(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    assert is_context_menu_enabled() is False
    assert enable_context_menu() is False
    assert disable_context_menu() is True

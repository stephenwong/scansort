"""Unit tests for scansort.platform.context_menu module."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from scansort.core.constants import SUPPORTED_EXTENSIONS
from scansort.platform.context_menu import (
    _build_context_menu_command,
    _build_ocr_menu_command,
    _get_linux_nautilus_script_path,
    disable_context_menu,
    disable_ocr_menu,
    enable_context_menu,
    enable_ocr_menu,
    is_context_menu_enabled,
    is_ocr_menu_enabled,
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


def _winreg_with_strict_delete():
    """Build a winreg fake exposing only the real stdlib constant surface.

    The stdlib ``winreg`` module defines no ``DELETE`` constant, so any code
    referencing ``reg.DELETE`` must fail here. ``RegDeleteKey`` needs the Win32
    DELETE access right (0x00010000), which the module does not export.
    """
    mock_winreg = MagicMock(
        spec=[
            "HKEY_CURRENT_USER",
            "KEY_SET_VALUE",
            "KEY_READ",
            "REG_SZ",
            "OpenKey",
            "CreateKey",
            "DeleteKey",
            "QueryValueEx",
            "SetValueEx",
        ]
    )
    mock_winreg.KEY_SET_VALUE = 0x0002
    mock_winreg.KEY_READ = 0x00020019
    seen_access: list[int] = []

    def fake_open_key(hive, path, reserved, access):
        seen_access.append(access)
        ctx = MagicMock()
        ctx.__enter__.return_value = MagicMock()
        return ctx

    def fake_delete_key(key, name):
        if not (seen_access[-1] & 0x00010000):
            raise PermissionError("Access is denied")

    mock_winreg.OpenKey.side_effect = fake_open_key
    mock_winreg.DeleteKey.side_effect = fake_delete_key
    return mock_winreg, seen_access


def test_context_menu_windows_deletekey_requires_delete_access(monkeypatch):
    """F51: parent keys must be opened with DELETE so RegDeleteKey succeeds."""
    monkeypatch.setattr("sys.platform", "win32")
    mock_winreg, seen_access = _winreg_with_strict_delete()

    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.platform.context_menu._winreg", mock_winreg, create=True),
    ):
        assert disable_context_menu() is True

    assert seen_access, "OpenKey was never invoked"
    assert all(mask & 0x00010000 for mask in seen_access)


def test_context_menu_windows_disable_isolates_per_extension_failures(monkeypatch):
    """F47: one extension's registry failure must not abort the remaining loop."""
    monkeypatch.setattr("sys.platform", "win32")
    mock_winreg = MagicMock(
        spec=[
            "HKEY_CURRENT_USER",
            "KEY_SET_VALUE",
            "KEY_READ",
            "REG_SZ",
            "OpenKey",
            "CreateKey",
            "DeleteKey",
            "QueryValueEx",
            "SetValueEx",
        ]
    )
    mock_winreg.KEY_SET_VALUE = 0x0002
    mock_winreg.KEY_READ = 0x00020019
    attempts: list[str] = []
    ext_order = sorted(SUPPORTED_EXTENSIONS)
    failing_ext = ext_order[2]

    def fake_open_key(hive, path, reserved, access):
        attempts.append(path)
        if f"\\{failing_ext}\\" in path:
            raise OSError("Registry error")
        ctx = MagicMock()
        ctx.__enter__.return_value = MagicMock()
        return ctx

    mock_winreg.OpenKey.side_effect = fake_open_key
    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.platform.context_menu._winreg", mock_winreg, create=True),
    ):
        assert disable_context_menu() is False

    for ext in ext_order:
        assert any(f"\\{ext}\\" in path for path in attempts)


def test_context_menu_windows_enable_isolates_per_extension_failures(monkeypatch):
    """F47: one extension's CreateKey failure must not abort enable's remaining loop."""
    monkeypatch.setattr("sys.platform", "win32")
    mock_winreg = MagicMock()
    mock_winreg.REG_SZ = 1
    ext_order = sorted(SUPPORTED_EXTENSIONS)
    failing_ext = ext_order[2]
    attempts: list[str] = []

    def fake_create_key(hive, path):
        attempts.append(path)
        if f"\\{failing_ext}\\" in path:
            raise OSError("Registry error")
        ctx = MagicMock()
        ctx.__enter__.return_value = MagicMock()
        return ctx

    mock_winreg.CreateKey.side_effect = fake_create_key
    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.platform.context_menu._winreg", mock_winreg, create=True),
    ):
        assert enable_context_menu("C:\\Programs\\ScanSort.exe") is False

    for ext in ext_order:
        assert any(f"\\{ext}\\" in path for path in attempts)


def test_build_ocr_menu_command_custom_executable():
    cmd = _build_ocr_menu_command(executable_path="C:\\MyPath\\ScanSort.exe")
    assert cmd == '"C:\\MyPath\\ScanSort.exe" ocr-backfill "%1"'


def test_ocr_menu_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")

    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    mock_winreg.CreateKey.return_value.__enter__.return_value = mock_key
    mock_winreg.QueryValueEx.return_value = (
        '"C:\\Programs\\ScanSort.exe" ocr-backfill "%1"',
        1,
    )

    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.platform.context_menu._winreg", mock_winreg, create=True),
    ):
        assert is_ocr_menu_enabled() is True
        assert enable_ocr_menu("C:\\Programs\\ScanSort.exe") is True
        # PDF-only: one verb key + one command key.
        assert mock_winreg.CreateKey.call_count == 2
        assert disable_ocr_menu() is True
        assert mock_winreg.DeleteKey.call_count >= 1


def test_ocr_menu_windows_partial(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")

    mock_winreg = MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = MagicMock()
    mock_winreg.QueryValueEx.return_value = ("", 1)

    with (
        patch.dict("sys.modules", {"winreg": mock_winreg}),
        patch("scansort.platform.context_menu._winreg", mock_winreg, create=True),
    ):
        assert is_ocr_menu_enabled() is False


def test_ocr_menu_linux(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    script_path = tmp_path / "nautilus" / "scripts" / "Make searchable with ScanSort"

    with patch(
        "scansort.platform.context_menu._get_linux_ocr_nautilus_script_path",
        return_value=script_path,
    ):
        assert is_ocr_menu_enabled() is False
        assert enable_ocr_menu(executable_path="/usr/bin/scansort") is True
        assert is_ocr_menu_enabled() is True
        assert 'scansort ocr-backfill "$f"' in script_path.read_text(encoding="utf-8")
        assert disable_ocr_menu() is True
        assert not script_path.exists()


def test_ocr_menu_unsupported_platform(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    assert is_ocr_menu_enabled() is False
    assert enable_ocr_menu() is False
    assert disable_ocr_menu() is True

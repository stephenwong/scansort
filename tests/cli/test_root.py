"""Unit tests for scansort.cli.root module (main_cli, version flags, logging level)."""

import logging
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from scansort.cli.root import main_cli
from scansort.core.config import AppConfig


@contextmanager
def _granted_guard(*args, **kwargs):
    yield True


def test_cli_version_flag_long(capsys):
    from scansort import __version__

    with pytest.raises(SystemExit) as exc_info:
        main_cli(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert f"scansort {__version__}" in captured.out


def test_cli_version_flag_short(capsys):
    from scansort import __version__

    with pytest.raises(SystemExit) as exc_info:
        main_cli(["-V"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert f"scansort {__version__}" in captured.out


def test_spec_version_resource_synchronization(tmp_path: Path):
    """Verify scansort.spec generates version metadata dynamically from scansort.__version__."""
    import re

    from scansort import __version__

    spec_path = Path(__file__).resolve().parent.parent.parent / "scansort.spec"
    assert spec_path.is_file()
    spec_content = spec_path.read_text(encoding="utf-8")

    assert "scansort" in spec_content
    assert "__version__" in spec_content
    assert "ProductVersion" in spec_content
    assert "FileVersion" in spec_content
    assert "version=" in spec_content

    spec_globals = {
        "SPECPATH": str(tmp_path),
        "workpath": str(tmp_path / "build"),
        "Path": Path,
        "re": re,
    }
    (tmp_path / "scansort").mkdir()
    (tmp_path / "scansort" / "__init__.py").write_text(
        f'__version__ = "{__version__}"\n', encoding="utf-8"
    )

    start_marker = "# Synchronize version_info.txt"
    end_marker = "datas = []"
    block = spec_content[
        spec_content.index(start_marker) : spec_content.index(end_marker)
    ]
    exec(compile(block, "scansort.spec", "exec"), spec_globals)

    generated_file = tmp_path / "build" / "version_info.txt"
    assert generated_file.is_file()
    text = generated_file.read_text(encoding="utf-8")
    assert f"StringStruct('ProductVersion', '{__version__}')" in text
    assert f"StringStruct('FileVersion', '{__version__}.0')" in text
    assert "StringStruct('ProductName', 'ScanSort')" in text


def test_cli_root_flags_inherited_by_watch(capsys):
    with (
        patch("scansort.cli.watch.DropFolderWatcher"),
        patch("scansort.cli.watch.ScanSortPipeline"),
        patch("scansort.cli.watch.instance_guard", _granted_guard),
    ):
        # Root --minimized before watch
        exit_code = main_cli(["--minimized", "watch"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Starting ScanSort monitor" not in captured.out

        # Root --dry-run before watch
        exit_code = main_cli(["--dry-run", "watch"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "DRY-RUN MODE ACTIVE" in captured.out

        # Root --dry-run without subcommand defaults to watch
        exit_code = main_cli(["--dry-run"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "DRY-RUN MODE ACTIVE" in captured.out


def test_main_cli_attaches_console_on_entry():
    with (
        patch("scansort.cli.root.attach_parent_console") as mock_attach,
        patch("scansort.cli.config.get_api_key", return_value="AIzaSyTestKey123456"),
        patch("scansort.cli.config.load_config", return_value=AppConfig()),
        patch("scansort.cli.config.is_autorun_enabled", return_value=False),
    ):
        exit_code = main_cli(["config", "--show"])
    assert exit_code == 0
    mock_attach.assert_called_once()


def test_main_cli_verbose_sets_debug_logging(monkeypatch):
    captured_level = []

    def fake_configure(log_dir=None, level=None):
        captured_level.append(level)

    monkeypatch.setattr("scansort.cli.root.configure_file_logging", fake_configure)

    # Prefix flag
    main_cli(["-v", "undo"])
    assert captured_level[-1] == logging.DEBUG

    # Trailing flag on subcommands
    main_cli(["undo", "-v"])
    assert captured_level[-1] == logging.DEBUG

    main_cli(["check-update", "--verbose"])
    assert captured_level[-1] == logging.DEBUG

    # Default without verbose flag is INFO
    main_cli(["undo"])
    assert captured_level[-1] == logging.INFO

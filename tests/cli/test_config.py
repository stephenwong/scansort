"""Unit tests for scansort.cli.config module."""

from pathlib import Path
from unittest.mock import patch

from scansort import __version__
from scansort.cli.root import main_cli
from scansort.core.config import AppConfig


def test_cli_config_show(capsys):
    with (
        patch(
            "scansort.cli.config.get_api_key",
            return_value="AIzaSyTest1234567890",
        ),
        patch("scansort.cli.config.load_config", return_value=AppConfig()),
    ):
        exit_code = main_cli(["config", "--show"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert f"Version:           {__version__}" in captured.out
        assert "AIza" in captured.out
        assert "••••••••" in captured.out
        assert "1234567890" not in captured.out


def test_cli_config_set_key():
    with patch("scansort.cli.config.set_api_key") as mock_set:
        exit_code = main_cli(["config", "--set-key", "AIzaSyNewKey12345"])
        assert exit_code == 0
        mock_set.assert_called_once_with("AIzaSyNewKey12345")


def test_cli_config_set_key_error(capsys):
    with patch(
        "scansort.cli.config.set_api_key",
        side_effect=ValueError("Secret key error AIzaSySecret123"),
    ):
        exit_code = main_cli(["config", "--set-key", "AIzaSySecret123"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error saving Gemini API key" in captured.err
        assert "AIzaSySecret123" not in captured.err


def test_cli_config_autostart_failure():
    with (
        patch("scansort.cli.config.enable_autorun", return_value=False),
        patch("scansort.cli.config.save_config") as mock_save,
    ):
        exit_code = main_cli(["config", "--autostart", "enable"])
        assert exit_code == 1
        assert not mock_save.called

    with (
        patch("scansort.cli.config.disable_autorun", return_value=False),
        patch("scansort.cli.config.save_config") as mock_save,
    ):
        exit_code = main_cli(["config", "--autostart", "disable"])
        assert exit_code == 1
        assert not mock_save.called


def test_cli_config_update_folders(tmp_path: Path):
    new_watch = tmp_path / "NewInbox"
    new_docs = tmp_path / "NewDocs"

    with patch("scansort.cli.config.save_config") as mock_save:
        assert main_cli(["config", "--watch-folder", str(new_watch)]) == 0
        assert mock_save.called

        assert main_cli(["config", "--documents-folder", str(new_docs)]) == 0
        assert mock_save.called


def test_cli_config_swap_folders(tmp_path: Path):
    folder_a = tmp_path / "FolderA"
    folder_b = tmp_path / "FolderB"
    initial_cfg = AppConfig(watch_folder=folder_a, documents_root=folder_b)

    with (
        patch("scansort.cli.config.load_config", return_value=initial_cfg),
        patch("scansort.cli.config.save_config") as mock_save,
    ):
        # Swapping watch_folder and documents_root in a single CLI command
        exit_code = main_cli(
            [
                "config",
                "--watch-folder",
                str(folder_b),
                "--documents-folder",
                str(folder_a),
            ]
        )
        assert exit_code == 0
        assert mock_save.called
        saved_cfg = mock_save.call_args[0][0]
        assert saved_cfg.watch_folder == folder_b.resolve()
        assert saved_cfg.documents_root == folder_a.resolve()


def test_cli_config_autostart_toggle():
    with (
        patch("scansort.cli.config.enable_autorun", return_value=True) as mock_enable,
        patch("scansort.cli.config.save_config"),
    ):
        assert main_cli(["config", "--autostart", "enable"]) == 0
        mock_enable.assert_called_once()

    with (
        patch("scansort.cli.config.disable_autorun", return_value=True) as mock_disable,
        patch("scansort.cli.config.save_config"),
    ):
        assert main_cli(["config", "--autostart", "disable"]) == 0
        mock_disable.assert_called_once()


def test_cli_config_rejects_regular_files(tmp_path: Path, capsys):
    reg_file = tmp_path / "regular_file.txt"
    reg_file.touch()

    exit_code = main_cli(["config", "--watch-folder", str(reg_file)])
    assert exit_code == 1
    assert "cannot be a regular file" in capsys.readouterr().err

    exit_code = main_cli(["config", "--documents-folder", str(reg_file)])
    assert exit_code == 1
    assert "cannot be a regular file" in capsys.readouterr().err


def test_cli_config_rejects_identical_folders(tmp_path: Path, capsys):
    shared = tmp_path / "Shared"
    shared.mkdir()
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=shared)

    with patch("scansort.cli.config.load_config", return_value=cfg):
        exit_code = main_cli(["config", "--watch-folder", str(shared)])
        assert exit_code == 1
        assert "cannot be the same directory" in capsys.readouterr().err


def test_cli_config_save_config_error(tmp_path: Path, capsys):
    folder = tmp_path / "ValidFolder"
    folder.mkdir()

    with patch(
        "scansort.cli.config.save_config",
        side_effect=OSError("Disk write failure"),
    ):
        exit_code = main_cli(["config", "--watch-folder", str(folder)])
        assert exit_code == 1
        assert "Error saving configuration" in capsys.readouterr().err


def test_cli_config_rejects_documents_folder_identical(tmp_path: Path, capsys):
    shared = tmp_path / "Shared"
    shared.mkdir()
    cfg = AppConfig(watch_folder=shared, documents_root=tmp_path / "Docs")

    with patch("scansort.cli.config.load_config", return_value=cfg):
        exit_code = main_cli(["config", "--documents-folder", str(shared)])
        assert exit_code == 1
        assert "cannot be the same directory" in capsys.readouterr().err


def test_cli_config_documents_folder_save_error(tmp_path: Path, capsys):
    folder = tmp_path / "ValidDocs"
    folder.mkdir()

    with patch(
        "scansort.cli.config.save_config",
        side_effect=OSError("Permission denied"),
    ):
        exit_code = main_cli(["config", "--documents-folder", str(folder)])
        assert exit_code == 1
        assert "Error saving configuration" in capsys.readouterr().err


def test_cli_config_autostart_save_error(capsys):
    with (
        patch("scansort.cli.config.enable_autorun", return_value=True),
        patch(
            "scansort.cli.config.save_config",
            side_effect=OSError("Read-only config"),
        ),
    ):
        exit_code = main_cli(["config", "--autostart", "enable"])
        assert exit_code == 1
        assert "Error saving configuration" in capsys.readouterr().err

    with (
        patch("scansort.cli.config.disable_autorun", return_value=True),
        patch(
            "scansort.cli.config.save_config",
            side_effect=OSError("Read-only config"),
        ),
    ):
        exit_code = main_cli(["config", "--autostart", "disable"])
        assert exit_code == 1
        assert "Error saving configuration" in capsys.readouterr().err


def test_cli_config_refuses_semantically_invalid_config_file(tmp_path: Path, capsys):
    """A parseable-but-invalid config must never be reset or persisted."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        '{"documents_root": "%s/docs", "watch_folder": "%s/inbox", '
        '"max_folder_depth": 99}' % (tmp_path, tmp_path),
        encoding="utf-8",
    )

    with (
        patch(
            "scansort.cli.config.load_config",
            side_effect=ValueError("bad field"),
        ),
        patch("scansort.cli.config.save_config") as mock_save,
    ):
        assert main_cli(["config", "--watch-folder", str(tmp_path / "NewInbox")]) == 1
        assert not mock_save.called
        captured = capsys.readouterr()
        assert "Configuration error" in captured.err


def test_cli_config_nested_watch_folder_rejected(tmp_path: Path, capsys):
    docs_root = tmp_path / "Documents"
    docs_root.mkdir(parents=True)
    initial_cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=docs_root)

    with (
        patch("scansort.cli.config.load_config", return_value=initial_cfg),
        patch("scansort.cli.config.save_config") as mock_save,
    ):
        nested = docs_root / "NestedInbox"
        exit_code = main_cli(["config", "--watch-folder", str(nested)])
        assert exit_code == 1
        assert not mock_save.called
        captured = capsys.readouterr()
        assert "Configuration error" in captured.err

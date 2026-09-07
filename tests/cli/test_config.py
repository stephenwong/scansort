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


def test_cli_config_path(capsys, tmp_path: Path):
    expected_path = tmp_path / "config.json"
    with patch(
        "scansort.cli.config.get_default_config_path", return_value=expected_path
    ):
        exit_code = main_cli(["config", "--path"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert str(expected_path) in captured.out


def test_cli_config_get(capsys):
    cfg = AppConfig(gemini_model="gemini-3.5-flash-lite", max_folder_depth=4)
    with patch("scansort.cli.config.load_config", return_value=cfg):
        assert main_cli(["config", "--get", "gemini_model"]) == 0
        assert "gemini-3.5-flash-lite" in capsys.readouterr().out

        assert main_cli(["config", "--get", "max_folder_depth"]) == 0
        assert "4" in capsys.readouterr().out


def test_cli_config_get_api_key(capsys):
    with (
        patch("scansort.cli.config.load_config", return_value=AppConfig()),
        patch("scansort.cli.config.get_api_key", return_value="AIzaSyTest1234567890"),
    ):
        assert main_cli(["config", "--get", "gemini_key"]) == 0
        out = capsys.readouterr().out
        assert "AIza" in out
        assert "••••••••" in out
        assert "1234567890" not in out


def test_cli_config_get_unknown_key(capsys):
    with patch("scansort.cli.config.load_config", return_value=AppConfig()):
        assert main_cli(["config", "--get", "unknown_field"]) == 1
        assert "Unknown configuration field" in capsys.readouterr().err


def test_cli_config_set_generic(capsys):
    cfg = AppConfig()
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.config.save_config") as mock_save,
    ):
        assert (
            main_cli(["config", "--set", "gemini_model", "gemini-3.5-flash-lite"]) == 0
        )
        assert mock_save.called
        saved_cfg = mock_save.call_args[0][0]
        assert saved_cfg.gemini_model == "gemini-3.5-flash-lite"


def test_cli_config_set_unknown_key(capsys):
    with patch("scansort.cli.config.load_config", return_value=AppConfig()):
        assert main_cli(["config", "--set", "not_a_field", "value"]) == 1
        assert "Unknown configuration field" in capsys.readouterr().err


def test_cli_config_direct_flags(tmp_path: Path, capsys):
    cfg = AppConfig()
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.config.save_config") as mock_save,
    ):
        exit_code = main_cli(
            [
                "config",
                "--gemini-model",
                "gemini-3.5-flash-lite",
                "--fallback-folder",
                "_Custom_Review",
                "--max-depth",
                "5",
                "--mirror-csv",
                "enable",
                "--auto-update",
                "disable",
                "--update-check-interval",
                "7",
                "--dry-run",
                "enable",
            ]
        )
        assert exit_code == 0
        assert mock_save.called
        saved = mock_save.call_args[0][0]
        assert saved.gemini_model == "gemini-3.5-flash-lite"
        assert saved.fallback_folder == "_Custom_Review"
        assert saved.max_folder_depth == 5
        assert saved.mirror_log_to_documents is True
        assert saved.auto_update is False
        assert saved.update_check_interval_days == 7
        assert saved.dry_run is True


def test_cli_config_show_json(capsys):
    import json

    with (
        patch("scansort.cli.config.load_config", return_value=AppConfig()),
        patch("scansort.cli.config.get_api_key", return_value="AIzaSySecretKey0000"),
        patch("scansort.cli.config.is_autorun_enabled", return_value=True),
    ):
        assert main_cli(["config", "--show", "--json"]) == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["gemini_model"] == "gemini-3.1-flash-lite"
        assert data["start_on_boot"] is True
        assert "AIza" in data["gemini_api_key"]
        assert "SecretKey" not in data["gemini_api_key"]


def test_cli_config_set_type_variants(tmp_path: Path, capsys):
    cfg = AppConfig()
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.config.save_config") as mock_save,
    ):
        # Boolean
        assert main_cli(["config", "--set", "dry_run", "true"]) == 0
        assert mock_save.call_args[0][0].dry_run is True

        # Int
        assert main_cli(["config", "--set", "max_folder_depth", "5"]) == 0
        assert mock_save.call_args[0][0].max_folder_depth == 5

        # Path
        target_dir = tmp_path / "Target"
        assert main_cli(["config", "--set", "watch_folder", str(target_dir)]) == 0
        assert mock_save.call_args[0][0].watch_folder == target_dir.resolve()

        # Invalid int
        assert main_cli(["config", "--set", "max_folder_depth", "not_an_int"]) == 1
        assert "Invalid integer value" in capsys.readouterr().err

        # Validation error
        assert main_cli(["config", "--set", "gemini_model", "invalid_model"]) == 1
        assert "Configuration error" in capsys.readouterr().err


def test_cli_config_set_save_failure(capsys):
    cfg = AppConfig()
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.config.save_config", side_effect=OSError("Disk full")),
    ):
        assert (
            main_cli(["config", "--set", "gemini_model", "gemini-3.5-flash-lite"]) == 1
        )
        assert "Error saving configuration" in capsys.readouterr().err

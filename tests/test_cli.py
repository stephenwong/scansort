"""Unit tests for CLI commands in scansort.__main__."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scansort.__main__ import build_parser, main_cli
from scansort.config import AppConfig


def test_build_parser():
    parser = build_parser()
    args = parser.parse_args(["watch", "--dry-run"])
    assert args.command == "watch"
    assert args.dry_run is True

    args_cfg = parser.parse_args(["config", "--set-key", "AIzaSyTest123"])
    assert args_cfg.command == "config"
    assert args_cfg.set_key == "AIzaSyTest123"


def test_cli_config_show(capsys):
    with (
        patch("scansort.__main__.get_api_key", return_value="AIzaSyTest1234567890"),
        patch("scansort.__main__.load_config", return_value=AppConfig()),
    ):
        exit_code = main_cli(["config", "--show"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "AIza" in captured.out
        assert "••••••••" in captured.out
        assert "1234567890" not in captured.out


def test_cli_config_set_key():
    with patch("scansort.__main__.set_api_key") as mock_set:
        exit_code = main_cli(["config", "--set-key", "AIzaSyNewKey12345"])
        assert exit_code == 0
        mock_set.assert_called_once_with("AIzaSyNewKey12345")


def test_cli_undo(tmp_path: Path):
    with patch(
        "scansort.__main__.undo_last_move", return_value=Path("/inbox/doc.pdf")
    ) as mock_undo:
        exit_code = main_cli(["undo"])
        assert exit_code == 0
        mock_undo.assert_called_once()


def test_cli_watch_overrides(capsys, tmp_path: Path):
    custom_inbox = tmp_path / "MyInbox"
    custom_docs = tmp_path / "MyDocs"
    with (
        patch("scansort.__main__.DropFolderWatcher") as mock_watcher_cls,
        patch("scansort.__main__.ScanSortPipeline"),
    ):
        exit_code = main_cli(
            [
                "watch",
                "--watch-folder",
                str(custom_inbox),
                "--documents-root",
                str(custom_docs),
                "--dry-run",
            ]
        )
        assert exit_code == 0
        mock_watcher_cls.return_value.start.assert_called_once()
        captured = capsys.readouterr()
        assert str(custom_inbox) in captured.out
        assert str(custom_docs) in captured.out
        assert "DRY-RUN MODE ACTIVE" in captured.out


def test_cli_watch_minimized_suppresses_banner(capsys, tmp_path: Path):
    with (
        patch("scansort.__main__.DropFolderWatcher"),
        patch("scansort.__main__.ScanSortPipeline"),
    ):
        exit_code = main_cli(["watch", "--minimized"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Starting ScanSort monitor" not in captured.out


def test_cli_config_set_key_error(capsys):
    with patch(
        "scansort.__main__.set_api_key",
        side_effect=ValueError("Secret key error AIzaSySecret123"),
    ):
        exit_code = main_cli(["config", "--set-key", "AIzaSySecret123"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error saving Gemini API key" in captured.err
        assert "AIzaSySecret123" not in captured.err


def test_cli_config_autostart_failure():
    with (
        patch("scansort.__main__.enable_autorun", return_value=False),
        patch("scansort.__main__.save_config") as mock_save,
    ):
        exit_code = main_cli(["config", "--autostart", "enable"])
        assert exit_code == 1
        assert not mock_save.called

    with (
        patch("scansort.__main__.disable_autorun", return_value=False),
        patch("scansort.__main__.save_config") as mock_save,
    ):
        exit_code = main_cli(["config", "--autostart", "disable"])
        assert exit_code == 1
        assert not mock_save.called


def test_cli_config_update_folders(tmp_path: Path):
    new_watch = tmp_path / "NewInbox"
    new_docs = tmp_path / "NewDocs"

    with patch("scansort.__main__.save_config") as mock_save:
        assert main_cli(["config", "--watch-folder", str(new_watch)]) == 0
        assert mock_save.called

        assert main_cli(["config", "--documents-folder", str(new_docs)]) == 0
        assert mock_save.called


def test_cli_config_swap_folders(tmp_path: Path):
    folder_a = tmp_path / "FolderA"
    folder_b = tmp_path / "FolderB"
    initial_cfg = AppConfig(watch_folder=folder_a, documents_root=folder_b)

    with (
        patch("scansort.__main__.load_config", return_value=initial_cfg),
        patch("scansort.__main__.save_config") as mock_save,
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
        patch("scansort.__main__.enable_autorun", return_value=True) as mock_enable,
        patch("scansort.__main__.save_config"),
    ):
        assert main_cli(["config", "--autostart", "enable"]) == 0
        mock_enable.assert_called_once()

    with (
        patch("scansort.__main__.disable_autorun", return_value=True) as mock_disable,
        patch("scansort.__main__.save_config"),
    ):
        assert main_cli(["config", "--autostart", "disable"]) == 0
        mock_disable.assert_called_once()


def test_cli_undo_nothing_to_undo(capsys):
    with patch("scansort.__main__.undo_last_move", return_value=None):
        exit_code = main_cli(["undo"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No reversible" in captured.out


def test_cli_rescan(capsys, tmp_path: Path):
    docs = tmp_path / "Docs"
    (docs / "Bills").mkdir(parents=True)
    cfg = AppConfig(
        documents_root=docs, max_folder_depth=5, fallback_folder="_Special_Review"
    )

    with (
        patch("scansort.__main__.load_config", return_value=cfg),
        patch("scansort.__main__.FolderMapper") as mock_mapper_cls,
    ):
        mock_mapper = mock_mapper_cls.return_value
        mock_mapper.refresh.return_value = ["Bills"]
        exit_code = main_cli(["rescan"])
        assert exit_code == 0
        mock_mapper_cls.assert_called_once_with(
            docs_root=docs,
            max_depth=5,
            fallback_folder="_Special_Review",
        )
        captured = capsys.readouterr()
        assert "Discovered 1 destination folders" in captured.out
        assert "Bills" in captured.out


def test_cli_root_flags_inherited_by_watch(capsys):
    with (
        patch("scansort.__main__.DropFolderWatcher"),
        patch("scansort.__main__.ScanSortPipeline"),
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

    with patch("scansort.__main__.load_config", return_value=cfg):
        exit_code = main_cli(["config", "--watch-folder", str(shared)])
        assert exit_code == 1
        assert "cannot be the same directory" in capsys.readouterr().err


def test_cli_config_save_config_error(tmp_path: Path, capsys):
    folder = tmp_path / "ValidFolder"
    folder.mkdir()

    with patch(
        "scansort.__main__.save_config", side_effect=OSError("Disk write failure")
    ):
        exit_code = main_cli(["config", "--watch-folder", str(folder)])
        assert exit_code == 1
        assert "Error saving configuration" in capsys.readouterr().err


def test_cli_undo_os_error(capsys):
    with patch(
        "scansort.__main__.undo_last_move",
        side_effect=PermissionError("File locked by process"),
    ):
        exit_code = main_cli(["undo"])
        assert exit_code == 1
        assert "Error reversing last move" in capsys.readouterr().err


def test_cli_watch_worker_join_timeout():
    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = True
    with (
        patch("scansort.__main__.DropFolderWatcher"),
        patch("scansort.__main__.ScanSortPipeline"),
        patch("threading.Thread", return_value=mock_thread),
    ):
        exit_code = main_cli(["watch"])
        assert exit_code == 0
        mock_thread.join.assert_called_once_with(timeout=20.0)


def test_cli_watch_keyboard_interrupt():
    mock_watcher_cls = MagicMock()
    mock_watcher_cls.return_value.start.side_effect = KeyboardInterrupt
    with (
        patch("scansort.__main__.DropFolderWatcher", mock_watcher_cls),
        patch("scansort.__main__.ScanSortPipeline"),
    ):
        exit_code = main_cli(["watch"])
        assert exit_code == 0


def test_cli_config_rejects_documents_folder_identical(tmp_path: Path, capsys):
    shared = tmp_path / "Shared"
    shared.mkdir()
    cfg = AppConfig(watch_folder=shared, documents_root=tmp_path / "Docs")

    with patch("scansort.__main__.load_config", return_value=cfg):
        exit_code = main_cli(["config", "--documents-folder", str(shared)])
        assert exit_code == 1
        assert "cannot be the same directory" in capsys.readouterr().err


def test_cli_config_documents_folder_save_error(tmp_path: Path, capsys):
    folder = tmp_path / "ValidDocs"
    folder.mkdir()

    with patch(
        "scansort.__main__.save_config", side_effect=OSError("Permission denied")
    ):
        exit_code = main_cli(["config", "--documents-folder", str(folder)])
        assert exit_code == 1
        assert "Error saving configuration" in capsys.readouterr().err


def test_cli_config_autostart_save_error(capsys):
    with (
        patch("scansort.__main__.enable_autorun", return_value=True),
        patch("scansort.__main__.save_config", side_effect=OSError("Read-only config")),
    ):
        exit_code = main_cli(["config", "--autostart", "enable"])
        assert exit_code == 1
        assert "Error saving configuration" in capsys.readouterr().err

    with (
        patch("scansort.__main__.disable_autorun", return_value=True),
        patch("scansort.__main__.save_config", side_effect=OSError("Read-only config")),
    ):
        exit_code = main_cli(["config", "--autostart", "disable"])
        assert exit_code == 1
        assert "Error saving configuration" in capsys.readouterr().err

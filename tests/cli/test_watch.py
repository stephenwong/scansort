"""Unit tests for scansort.cli.watch module."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from scansort.cli.root import main_cli
from scansort.core.config import AppConfig


@contextmanager
def _granted_guard(*args, **kwargs):
    yield True


@contextmanager
def _denied_guard(*args, **kwargs):
    yield False


def test_cli_watch_overrides(capsys, tmp_path: Path, mock_watch_stack):
    mock_watcher, _, _ = mock_watch_stack
    custom_inbox = tmp_path / "MyInbox"
    custom_docs = tmp_path / "MyDocs"
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
    mock_watcher.start.assert_called_once()
    captured = capsys.readouterr()
    assert str(custom_inbox) in captured.out
    assert str(custom_docs) in captured.out
    assert "DRY-RUN MODE ACTIVE" in captured.out


def test_cli_watch_minimized_suppresses_banner(capsys, mock_watch_stack):
    exit_code = main_cli(["watch", "--minimized"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Starting ScanSort monitor" not in captured.out


def test_cli_watch_worker_join_timeout(mock_watch_stack, monkeypatch):
    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = True
    monkeypatch.setattr(
        "scansort.cli.watch.threading.Thread", MagicMock(return_value=mock_thread)
    )

    exit_code = main_cli(["watch"])
    assert exit_code == 0
    mock_thread.join.assert_called_once_with(timeout=20.0)


def test_cli_watch_keyboard_interrupt(mock_watch_stack):
    mock_watcher, _, _ = mock_watch_stack
    mock_watcher.start.side_effect = KeyboardInterrupt
    exit_code = main_cli(["watch"])
    assert exit_code == 0


def test_cli_watch_graceful_when_directories_unavailable(tmp_path: Path, capsys):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")

    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch.object(
            AppConfig,
            "ensure_directories",
            side_effect=OSError("Access denied"),
        ),
        patch("scansort.cli.watch.DropFolderWatcher") as mock_watcher_cls,
        patch("scansort.cli.watch.ScanSortPipeline"),
    ):
        exit_code = main_cli(["watch"])
        assert exit_code == 1
        mock_watcher_cls.return_value.start.assert_not_called()
        captured = capsys.readouterr()
        assert "Error preparing directories" in captured.err


def test_cli_watch_applies_update_and_skips_watcher(tmp_path: Path):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.watch.instance_guard", _granted_guard),
        patch("scansort.cli.watch.maybe_apply_auto_update", return_value=True),
        patch("scansort.cli.watch.DropFolderWatcher") as mock_watcher_cls,
        patch("scansort.cli.watch.ScanSortPipeline"),
    ):
        assert main_cli(["watch", "--minimized"]) == 0
        mock_watcher_cls.return_value.start.assert_not_called()


def test_cli_watch_exits_when_another_instance_runs(tmp_path: Path, capsys):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.watch.instance_guard", _denied_guard),
        patch("scansort.cli.watch.DropFolderWatcher") as mock_watcher_cls,
        patch("scansort.cli.watch.ScanSortPipeline"),
    ):
        assert main_cli(["watch", "--minimized"]) == 0
        mock_watcher_cls.return_value.start.assert_not_called()
        assert "already running" in capsys.readouterr().err


def test_cli_watch_config_error(capsys):
    with patch("scansort.cli.config.load_config", side_effect=ValueError("bad config")):
        assert main_cli(["watch"]) == 1
        assert "Configuration error" in capsys.readouterr().err


def test_cli_watch_invalid_updated_config(tmp_path: Path, capsys):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with patch("scansort.cli.config.load_config", return_value=cfg):
        assert main_cli(["watch", "--watch-folder", str(tmp_path / "Docs")]) == 1
        assert "Configuration error" in capsys.readouterr().err


def test_cli_watch_instance_guard_os_error(tmp_path: Path, capsys):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch(
            "scansort.cli.watch.instance_guard",
            side_effect=OSError("Lock device unavailable"),
        ),
    ):
        assert main_cli(["watch"]) == 1
        assert "Error acquiring instance lock" in capsys.readouterr().err


def test_cli_watch_pipeline_os_error(tmp_path: Path, capsys):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.watch.instance_guard", _granted_guard),
        patch(
            "scansort.cli.watch.ScanSortPipeline",
            side_effect=OSError("Disk failed"),
        ),
    ):
        assert main_cli(["watch"]) == 1
        assert "Error preparing application directories" in capsys.readouterr().err


def test_cli_watch_initializes_system_tray(tmp_path: Path):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.watch.instance_guard", _granted_guard),
        patch("scansort.cli.watch.DropFolderWatcher"),
        patch("scansort.cli.watch.ScanSortPipeline"),
        patch("scansort.cli.watch.SystemTrayApp") as mock_tray_cls,
    ):
        mock_tray = mock_tray_cls.return_value
        exit_code = main_cli(["watch"])
        assert exit_code == 0
        mock_tray_cls.assert_called_once()
        mock_tray.start.assert_called_once()
        mock_tray.stop.assert_called_once()


def test_cli_watch_handles_tray_stop_error(tmp_path: Path):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.watch.instance_guard", _granted_guard),
        patch("scansort.cli.watch.DropFolderWatcher") as mock_watcher_cls,
        patch("scansort.cli.watch.ScanSortPipeline"),
        patch("scansort.cli.watch.SystemTrayApp") as mock_tray_cls,
    ):
        mock_tray = mock_tray_cls.return_value
        mock_tray.stop.side_effect = RuntimeError("Tray shutdown failure")
        mock_watcher = mock_watcher_cls.return_value

        exit_code = main_cli(["watch"])
        assert exit_code == 0
        mock_watcher.stop.assert_called_once()


def test_cli_watch_downstream_oserror_not_mislabeled_as_lock(tmp_path: Path, capsys):
    """F27: a runtime OSError must not be reported as an instance-lock failure."""
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.watch.instance_guard", _granted_guard),
        patch("scansort.cli.watch.announce_applied_update"),
        patch("scansort.cli.watch.maybe_apply_auto_update", return_value=False),
        patch(
            "scansort.cli.watch._run_monitor",
            side_effect=OSError("console pipe broken"),
        ),
    ):
        assert main_cli(["watch", "--minimized"]) == 1
    assert "acquiring instance lock" not in capsys.readouterr().err

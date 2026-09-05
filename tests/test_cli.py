"""Unit tests for CLI commands in scansort.__main__."""

import io
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from scansort.__main__ import build_parser, main_cli
from scansort.config import AppConfig


def _fake_console_api(
    monkeypatch,
    *,
    attach_result=1,
    output_cp=437,
    stdout_handle=11,
    stderr_handle=12,
):
    """Fake a frozen windowed Windows build running under a parent console.

    Returns ``(kernel32, msvcrt, opened)`` where ``opened`` records each
    ``os.fdopen`` call as ``(fd, mode, kwargs)``.
    """
    import scansort.__main__ as cli_module
    from scansort.__main__ import _attach_parent_console

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    fake_ctypes = MagicMock()
    kernel32 = fake_ctypes.WinDLL.return_value
    kernel32.AttachConsole.return_value = attach_result
    kernel32.GetConsoleOutputCP.return_value = output_cp
    kernel32.GetStdHandle.side_effect = [stdout_handle, stderr_handle]
    monkeypatch.setattr(cli_module, "ctypes", fake_ctypes)

    fake_msvcrt = MagicMock()
    fake_msvcrt.open_osfhandle.side_effect = [100, 101]
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    opened = []

    def fake_fdopen(fd, mode, **kwargs):
        opened.append((fd, mode, kwargs))
        return io.StringIO()

    monkeypatch.setattr(cli_module.os, "fdopen", fake_fdopen)
    return kernel32, fake_msvcrt, opened, _attach_parent_console


@contextmanager
def _granted_guard(*args, **kwargs):
    yield True


@contextmanager
def _denied_guard(*args, **kwargs):
    yield False


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
        patch("scansort.__main__.instance_guard", _granted_guard),
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
        patch("scansort.__main__.instance_guard", _granted_guard),
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
        patch("scansort.__main__.instance_guard", _granted_guard),
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
        patch("scansort.__main__.instance_guard", _granted_guard),
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
        patch("scansort.__main__.instance_guard", _granted_guard),
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


def test_cli_config_refuses_semantically_invalid_config_file(tmp_path: Path, capsys):
    """A parseable-but-invalid config must never be reset or persisted."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        '{"documents_root": "%s/docs", "watch_folder": "%s/inbox", '
        '"max_folder_depth": 99}' % (tmp_path, tmp_path),
        encoding="utf-8",
    )

    with (
        patch("scansort.__main__.load_config", side_effect=ValueError("bad field")),
        patch("scansort.__main__.save_config") as mock_save,
    ):
        assert main_cli(["config", "--watch-folder", str(tmp_path / "NewInbox")]) == 1
        assert not mock_save.called
        captured = capsys.readouterr()
        assert "Configuration error" in captured.err


def test_cli_watch_graceful_when_directories_unavailable(tmp_path: Path, capsys):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")

    with (
        patch("scansort.__main__.load_config", return_value=cfg),
        patch.object(
            AppConfig, "ensure_directories", side_effect=OSError("Access denied")
        ),
        patch("scansort.__main__.DropFolderWatcher") as mock_watcher_cls,
        patch("scansort.__main__.ScanSortPipeline"),
    ):
        exit_code = main_cli(["watch"])
        assert exit_code == 1
        mock_watcher_cls.return_value.start.assert_not_called()
        captured = capsys.readouterr()
        assert "Error preparing directories" in captured.err


def test_cli_config_nested_watch_folder_rejected(tmp_path: Path, capsys):
    docs_root = tmp_path / "Documents"
    docs_root.mkdir(parents=True)
    initial_cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=docs_root)

    with (
        patch("scansort.__main__.load_config", return_value=initial_cfg),
        patch("scansort.__main__.save_config") as mock_save,
    ):
        nested = docs_root / "NestedInbox"
        exit_code = main_cli(["config", "--watch-folder", str(nested)])
        assert exit_code == 1
        assert not mock_save.called
        captured = capsys.readouterr()
        assert "Configuration error" in captured.err


# ---------------------------------------------------------------------------
# Self-update CLI wiring
# ---------------------------------------------------------------------------


def test_build_parser_self_update_argument_suppressed():
    parser = build_parser()
    args = parser.parse_args(
        ["--self-update", "1234", "C:\\ScanSort", "C:\\Stage", "0.2.0"]
    )
    assert args.self_update == ["1234", "C:\\ScanSort", "C:\\Stage", "0.2.0"]
    # The helper argument must not surface in help text.
    assert "--self-update" not in parser.format_help()


def test_cli_self_update_dispatches_to_updater():
    with patch("scansort.__main__.perform_self_update", return_value=0) as mock_fn:
        exit_code = main_cli(["--self-update", "42", "/x/install", "/x/stage", "0.2.0"])
        assert exit_code == 0
    mock_fn.assert_called_once_with(42, "/x/install", "/x/stage", "0.2.0")


def test_cli_watch_applies_update_and_skips_watcher(tmp_path: Path):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with (
        patch("scansort.__main__.load_config", return_value=cfg),
        patch("scansort.__main__.instance_guard", _granted_guard),
        patch("scansort.__main__._maybe_apply_auto_update", return_value=True),
        patch("scansort.__main__.DropFolderWatcher") as mock_watcher_cls,
        patch("scansort.__main__.ScanSortPipeline"),
    ):
        assert main_cli(["watch", "--minimized"]) == 0
        mock_watcher_cls.return_value.start.assert_not_called()


def test_cli_watch_exits_when_another_instance_runs(tmp_path: Path, capsys):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with (
        patch("scansort.__main__.load_config", return_value=cfg),
        patch("scansort.__main__.instance_guard", _denied_guard),
        patch("scansort.__main__.DropFolderWatcher") as mock_watcher_cls,
        patch("scansort.__main__.ScanSortPipeline"),
    ):
        assert main_cli(["watch", "--minimized"]) == 0
        mock_watcher_cls.return_value.start.assert_not_called()
        assert "already running" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Auto-update trigger at watch startup
# ---------------------------------------------------------------------------


def test_maybe_apply_auto_update_inert_in_development(tmp_path: Path):
    from scansort.__main__ import _maybe_apply_auto_update

    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with patch("scansort.__main__.fetch_latest_release") as mock_fetch:
        assert _maybe_apply_auto_update(cfg, tmp_path / "appdata") is False
        mock_fetch.assert_not_called()


def test_maybe_apply_auto_update_disabled_by_config(tmp_path: Path, monkeypatch):
    from scansort.__main__ import _maybe_apply_auto_update

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/fake/ScanSort/ScanSort.exe", raising=False)
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Docs",
        auto_update=False,
    )
    with patch("scansort.__main__.fetch_latest_release") as mock_fetch:
        assert _maybe_apply_auto_update(cfg, tmp_path / "appdata") is False
        mock_fetch.assert_not_called()


def test_maybe_apply_auto_update_skips_within_interval(tmp_path: Path, monkeypatch):
    import scansort.updater as updater
    from scansort.__main__ import _maybe_apply_auto_update

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/fake/ScanSort/ScanSort.exe", raising=False)
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    updater.record_update_check(app_dir / "update_state.json")
    with patch("scansort.__main__.fetch_latest_release") as mock_fetch:
        assert _maybe_apply_auto_update(cfg, app_dir) is False
        mock_fetch.assert_not_called()


def test_maybe_apply_auto_update_installs_when_release_found(
    tmp_path: Path, monkeypatch
):

    from scansort.__main__ import _maybe_apply_auto_update

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe_path = tmp_path / "Programs" / "ScanSort" / "ScanSort.exe"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_bytes(b"old")
    monkeypatch.setattr(sys, "executable", str(exe_path), raising=False)

    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    app_dir = tmp_path / "appdata"
    payload = {
        "tag_name": "v0.3.0",
        "assets": [
            {
                "name": "ScanSort-v0.3.0-windows-x64.zip",
                "browser_download_url": "https://example.com/a.zip",
                "size": 1,
            }
        ],
    }
    staged = tmp_path / "ScanSort.stage-0.3.0"
    staged.mkdir()
    (staged / "ScanSort.exe").write_bytes(b"new")
    with (
        patch("scansort.__main__.fetch_latest_release", return_value=payload),
        patch("scansort.__main__.download_and_stage", return_value=staged),
        patch("scansort.__main__.spawn_update_helper") as mock_spawn,
        patch("scansort.__main__.show_toast") as mock_toast,
    ):
        applied = _maybe_apply_auto_update(cfg, app_dir)
    assert applied is True
    mock_spawn.assert_called_once()
    args = mock_spawn.call_args[0]
    assert args[1] == staged
    assert args[2] == "0.3.0"
    assert args[3] == os.getpid()
    mock_toast.assert_called_once()
    assert "update available" in mock_toast.call_args[0][0].lower()
    state = json.loads((app_dir / "update_state.json").read_text(encoding="utf-8"))
    assert state["checked_at"]


def test_maybe_apply_auto_update_no_release_records_check(tmp_path: Path, monkeypatch):
    from scansort.__main__ import _maybe_apply_auto_update

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/fake/ScanSort/ScanSort.exe", raising=False)
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    app_dir = tmp_path / "appdata"
    with patch(
        "scansort.__main__.fetch_latest_release", return_value={"tag_name": "v0.1.0"}
    ):
        assert _maybe_apply_auto_update(cfg, app_dir) is False
    assert (app_dir / "update_state.json").exists()


def test_maybe_apply_auto_update_recovers_from_check_errors(
    tmp_path: Path, monkeypatch
):
    from scansort.__main__ import _maybe_apply_auto_update
    from scansort.updater import UpdateError

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/fake/ScanSort/ScanSort.exe", raising=False)
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    app_dir = tmp_path / "appdata"
    with patch(
        "scansort.__main__.fetch_latest_release",
        side_effect=UpdateError("offline"),
    ):
        assert _maybe_apply_auto_update(cfg, app_dir) is False
    assert not (app_dir / "update_state.json").exists()


def test_maybe_apply_auto_update_recovers_from_spawn_failure(
    tmp_path: Path, monkeypatch
):
    from scansort.__main__ import _maybe_apply_auto_update
    from scansort.updater import UpdateError

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/fake/ScanSort/ScanSort.exe", raising=False)
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    app_dir = tmp_path / "appdata"
    payload = {
        "tag_name": "v0.2.0",
        "assets": [
            {
                "name": "ScanSort-v0.2.0-windows-x64.zip",
                "browser_download_url": "https://example.com/a.zip",
            }
        ],
    }
    staged = tmp_path / "ScanSort.stage-0.2.0"
    staged.mkdir()
    (staged / "ScanSort.exe").write_bytes(b"new")
    with (
        patch("scansort.__main__.fetch_latest_release", return_value=payload),
        patch("scansort.__main__.download_and_stage", return_value=staged),
        patch(
            "scansort.__main__.spawn_update_helper",
            side_effect=UpdateError("launch denied"),
        ),
    ):
        assert _maybe_apply_auto_update(cfg, app_dir) is False


def test_announce_applied_update_shows_once_then_clears(tmp_path: Path, monkeypatch):
    import scansort.updater as updater
    from scansort.__main__ import _announce_applied_update

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    updater.record_applied_update(app_dir / "update_state.json", "0.2.0")
    with patch("scansort.__main__.show_toast") as mock_toast:
        _announce_applied_update(app_dir)
    mock_toast.assert_called_once()
    title, body = mock_toast.call_args[0]
    assert title == "ScanSort updated"
    assert "0.2.0" in body
    state = json.loads((app_dir / "update_state.json").read_text(encoding="utf-8"))
    assert state["just_installed"] is False


def test_announce_applied_update_noop_without_marker(tmp_path: Path):
    from scansort.__main__ import _announce_applied_update

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    with patch("scansort.__main__.show_toast") as mock_toast:
        _announce_applied_update(app_dir)
    mock_toast.assert_not_called()


# ---------------------------------------------------------------------------
# Parent-console attachment for the frozen windowed build
# ---------------------------------------------------------------------------


def test_attach_parent_console_noop_off_windows(monkeypatch):
    from scansort.__main__ import _attach_parent_console

    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    real_out = sys.stdout
    _attach_parent_console()
    assert sys.stdout is real_out


def test_attach_parent_console_noop_when_not_frozen(monkeypatch):
    from scansort.__main__ import _attach_parent_console

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.delattr(sys, "frozen", raising=False)
    real_out = sys.stdout
    _attach_parent_console()
    assert sys.stdout is real_out


def test_attach_parent_console_skips_when_stdout_is_terminal(monkeypatch):
    import scansort.__main__ as cli_module
    from scansort.__main__ import _attach_parent_console

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    tty_out = MagicMock()
    tty_out.isatty.return_value = True
    monkeypatch.setattr(sys, "stdout", tty_out)
    fake_ctypes = MagicMock()
    monkeypatch.setattr(cli_module, "ctypes", fake_ctypes)

    _attach_parent_console()
    fake_ctypes.WinDLL.assert_not_called()
    assert sys.stdout is tty_out


def test_attach_parent_console_silent_without_parent_console(monkeypatch):
    kernel32, fake_msvcrt, opened, attach = _fake_console_api(
        monkeypatch, attach_result=0
    )
    real_out = sys.stdout

    assert attach() is None
    kernel32.AttachConsole.assert_called_once_with(-1)
    kernel32.GetStdHandle.assert_not_called()
    fake_msvcrt.open_osfhandle.assert_not_called()
    assert opened == []
    assert sys.stdout is real_out


def test_attach_parent_console_binds_stdout_and_stderr(monkeypatch):
    kernel32, fake_msvcrt, opened, attach = _fake_console_api(monkeypatch)
    original_out, original_err = sys.stdout, sys.stderr

    assert attach() is None
    kernel32.AttachConsole.assert_called_once_with(-1)
    kernel32.GetConsoleOutputCP.assert_called_once_with()
    assert kernel32.GetStdHandle.call_args_list == [
        call(-11),
        call(-12),
    ]
    assert fake_msvcrt.open_osfhandle.call_args_list == [
        call(11, os.O_WRONLY),
        call(12, os.O_WRONLY),
    ]
    assert opened == [
        (100, "w", {"encoding": "cp437", "buffering": 1}),
        (101, "w", {"encoding": "cp437", "buffering": 1}),
    ]
    assert sys.stdout is not original_out
    assert sys.stderr is not original_err


def test_attach_parent_console_skips_missing_stdout_handle(monkeypatch):
    _, fake_msvcrt, opened, attach = _fake_console_api(monkeypatch, stdout_handle=0)
    original_out, original_err = sys.stdout, sys.stderr

    assert attach() is None
    assert fake_msvcrt.open_osfhandle.call_args_list == [call(12, os.O_WRONLY)]
    assert opened == [(100, "w", {"encoding": "cp437", "buffering": 1})]
    assert sys.stdout is original_out
    assert sys.stderr is not original_err


def test_attach_parent_console_falls_back_to_utf8_without_codepage(monkeypatch):
    _, _, opened, attach = _fake_console_api(monkeypatch, output_cp=0)

    assert attach() is None
    assert opened == [
        (100, "w", {"encoding": "utf-8", "buffering": 1}),
        (101, "w", {"encoding": "utf-8", "buffering": 1}),
    ]


def test_attach_parent_console_swallows_win32_api_failures(monkeypatch):
    import scansort.__main__ as cli_module

    _, _, _, attach = _fake_console_api(monkeypatch)
    cli_module.ctypes.WinDLL.side_effect = OSError(5, "access denied")
    original_out, original_err = sys.stdout, sys.stderr

    assert attach() is None
    assert sys.stdout is original_out
    assert sys.stderr is original_err


def test_main_cli_config_show_writes_to_attached_console(monkeypatch):
    from scansort.__main__ import main_cli

    kernel32, _, opened, _ = _fake_console_api(monkeypatch, output_cp=65001)
    kernel32.AttachConsole.return_value = 1
    with (
        patch("scansort.__main__.get_api_key", return_value="AIzaSyTestKey123456"),
        patch("scansort.__main__.load_config", return_value=AppConfig()),
        patch("scansort.__main__.is_autorun_enabled", return_value=False),
    ):
        exit_code = main_cli(["config", "--show"])
    assert exit_code == 0
    assert len(opened) == 2
    out = sys.stdout.getvalue()
    assert "================ ScanSort Configuration" in out
    assert "Watch Folder:" in out
    assert "AIza" in out
    assert "••••••••" in out

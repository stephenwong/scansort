"""Unit tests for scansort.cli.update module."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from scansort.cli.root import main_cli
from scansort.cli.update import (
    _announce_applied_update,
    _maybe_apply_auto_update,
)
from scansort.core.config import AppConfig


def test_cli_self_update_dispatches_to_updater():
    with patch("scansort.cli.update.perform_self_update", return_value=0) as mock_fn:
        exit_code = main_cli(["--self-update", "42", "/x/install", "/x/stage", "0.2.0"])
        assert exit_code == 0
    mock_fn.assert_called_once_with(42, "/x/install", "/x/stage", "0.2.0")


def test_maybe_apply_auto_update_inert_in_development(tmp_path: Path):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with patch("scansort.cli.update.fetch_latest_release") as mock_fetch:
        assert _maybe_apply_auto_update(cfg, tmp_path / "appdata") is False
        mock_fetch.assert_not_called()


def test_maybe_apply_auto_update_disabled_by_config(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/fake/ScanSort/ScanSort.exe", raising=False)
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Docs",
        auto_update=False,
    )
    with patch("scansort.cli.update.fetch_latest_release") as mock_fetch:
        assert _maybe_apply_auto_update(cfg, tmp_path / "appdata") is False
        mock_fetch.assert_not_called()


def test_maybe_apply_auto_update_skips_within_interval(tmp_path: Path, monkeypatch):
    import scansort.updater as updater

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/fake/ScanSort/ScanSort.exe", raising=False)
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Docs",
        update_check_interval_days=1,
    )
    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    updater.record_update_check(app_dir / "update_state.json")
    with patch("scansort.cli.update.fetch_latest_release") as mock_fetch:
        assert _maybe_apply_auto_update(cfg, app_dir) is False
        mock_fetch.assert_not_called()


def test_maybe_apply_auto_update_installs_when_release_found(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe_path = tmp_path / "Programs" / "ScanSort" / "ScanSort.exe"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_bytes(b"old")
    monkeypatch.setattr(sys, "executable", str(exe_path), raising=False)

    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    app_dir = tmp_path / "appdata"
    payload = {
        "tag_name": "v1.0.0",
        "assets": [
            {
                "name": "ScanSort-v1.0.0-windows-x64.zip",
                "browser_download_url": "https://example.com/a.zip",
                "size": 1,
            }
        ],
    }
    staged = tmp_path / "ScanSort.stage-1.0.0"
    staged.mkdir()
    (staged / "ScanSort.exe").write_bytes(b"new")
    with (
        patch("scansort.cli.update.fetch_latest_release", return_value=payload),
        patch("scansort.cli.update.download_and_stage", return_value=staged),
        patch("scansort.cli.update.spawn_update_helper") as mock_spawn,
        patch("scansort.cli.update.show_toast") as mock_toast,
    ):
        applied = _maybe_apply_auto_update(cfg, app_dir)
    assert applied is True
    mock_spawn.assert_called_once()
    args = mock_spawn.call_args[0]
    assert args[1] == staged
    assert args[2] == "1.0.0"
    assert args[3] == os.getpid()
    mock_toast.assert_called_once()
    assert "update available" in mock_toast.call_args[0][0].lower()
    state = json.loads((app_dir / "update_state.json").read_text(encoding="utf-8"))
    assert state["checked_at"]


def test_maybe_apply_auto_update_tolerates_chdir_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe_path = tmp_path / "ScanSort" / "ScanSort.exe"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_bytes(b"old")
    monkeypatch.setattr(sys, "executable", str(exe_path), raising=False)
    monkeypatch.setattr("os.chdir", MagicMock(side_effect=OSError("permission denied")))

    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    app_dir = tmp_path / "appdata"
    payload = {
        "tag_name": "v1.0.0",
        "assets": [
            {
                "name": "ScanSort-v1.0.0-windows-x64.zip",
                "browser_download_url": "https://example.com/a.zip",
                "size": 1,
            }
        ],
    }
    staged = tmp_path / "ScanSort.stage-1.0.0"
    staged.mkdir()
    (staged / "ScanSort.exe").write_bytes(b"new")
    with (
        patch("scansort.cli.update.fetch_latest_release", return_value=payload),
        patch("scansort.cli.update.download_and_stage", return_value=staged),
        patch("scansort.cli.update.spawn_update_helper"),
        patch("scansort.cli.update.show_toast"),
    ):
        assert _maybe_apply_auto_update(cfg, app_dir) is True


def test_maybe_apply_auto_update_no_release_records_check(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/fake/ScanSort/ScanSort.exe", raising=False)
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    app_dir = tmp_path / "appdata"
    with patch(
        "scansort.cli.update.fetch_latest_release",
        return_value={"tag_name": "v0.1.0"},
    ):
        assert _maybe_apply_auto_update(cfg, app_dir) is False
    assert (app_dir / "update_state.json").exists()


def test_maybe_apply_auto_update_recovers_from_check_errors(
    tmp_path: Path, monkeypatch
):
    from scansort.updater import UpdateError

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/fake/ScanSort/ScanSort.exe", raising=False)
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    app_dir = tmp_path / "appdata"
    with patch(
        "scansort.cli.update.fetch_latest_release",
        side_effect=UpdateError("offline"),
    ):
        assert _maybe_apply_auto_update(cfg, app_dir) is False
    assert not (app_dir / "update_state.json").exists()


def test_maybe_apply_auto_update_recovers_from_spawn_failure(
    tmp_path: Path, monkeypatch
):
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
        patch("scansort.cli.update.fetch_latest_release", return_value=payload),
        patch("scansort.cli.update.download_and_stage", return_value=staged),
        patch(
            "scansort.cli.update.spawn_update_helper",
            side_effect=UpdateError("launch denied"),
        ),
    ):
        assert _maybe_apply_auto_update(cfg, app_dir) is False


def test_announce_applied_update_shows_once_then_clears(tmp_path: Path, monkeypatch):
    import scansort.updater as updater

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    updater.record_applied_update(app_dir / "update_state.json", "0.2.0")
    with patch("scansort.cli.update.show_toast") as mock_toast:
        _announce_applied_update(app_dir)
    mock_toast.assert_called_once()
    title, body = mock_toast.call_args[0]
    assert title == "ScanSort updated"
    assert "0.2.0" in body
    state = json.loads((app_dir / "update_state.json").read_text(encoding="utf-8"))
    assert state["just_installed"] is False


def test_announce_applied_update_noop_without_marker(tmp_path: Path):
    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    with patch("scansort.cli.update.show_toast") as mock_toast:
        _announce_applied_update(app_dir)
    mock_toast.assert_not_called()


def test_main_cli_check_update_up_to_date(capsys, monkeypatch):
    monkeypatch.setattr(
        "scansort.cli.update.fetch_latest_release",
        lambda: {"tag_name": "v0.1.0"},
    )
    monkeypatch.setattr(
        "scansort.cli.update.available_update",
        lambda *args, **kwargs: None,
    )
    code = main_cli(["check-update"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Checking for updates" in captured.out
    assert "up to date" in captured.out


def test_main_cli_check_update_available(capsys, monkeypatch):
    from scansort.updater import ReleaseInfo

    fake_info = ReleaseInfo(
        version="2.0.0",
        tag_name="v2.0.0",
        asset_name="ScanSort-v2.0.0-windows-x64.zip",
        download_url="https://example.com/download.zip",
        size_bytes=1024000,
        sha256=None,
        published_at="2026-09-06",
    )
    monkeypatch.setattr(
        "scansort.cli.update.fetch_latest_release",
        lambda: {"tag_name": "v2.0.0"},
    )
    monkeypatch.setattr(
        "scansort.cli.update.available_update",
        lambda *args, **kwargs: fake_info,
    )
    code = main_cli(["check-update"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Update available: version 2.0.0" in captured.out
    assert "ScanSort-v2.0.0-windows-x64.zip" in captured.out
    assert "https://example.com/download.zip" in captured.out


def test_main_cli_check_update_failure(capsys, monkeypatch):
    from scansort.updater import UpdateError

    def fail():
        raise UpdateError("Network error 503")

    monkeypatch.setattr("scansort.cli.update.fetch_latest_release", fail)
    code = main_cli(["check-update"])
    assert code == 1
    captured = capsys.readouterr()
    assert "Update check failed: Network error 503" in captured.err

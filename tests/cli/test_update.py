"""Unit tests for scansort.cli.update module."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scansort.updater as updater
from scansort import __version__
from scansort.cli.root import main_cli
from scansort.cli.update import (
    announce_applied_update,
    maybe_apply_auto_update,
)
from scansort.core.config import AppConfig
from scansort.updater import ReleaseInfo, UpdateError
from scansort.updater.feed import GITHUB_REPO, parse_version

_current_v = parse_version(__version__) or (1, 0, 0)
NEXT_VERSION = f"{_current_v[0] + 1}.0.0"
NEXT_TAG = f"v{NEXT_VERSION}"
NEXT_ZIP = f"ScanSort-{NEXT_TAG}-windows-x64.zip"
NEXT_URL = f"https://github.com/{GITHUB_REPO}/releases/download/{NEXT_TAG}/{NEXT_ZIP}"


@pytest.fixture(autouse=True)
def _fake_msvcrt(monkeypatch):
    """Provide a no-op msvcrt so win32-faked tests can exercise instance_guard."""
    import types

    fake = types.ModuleType("msvcrt")
    fake.LK_NBLCK = 1
    fake.LK_LOCK = 2
    fake.LK_UNLCK = 0
    fake.locking = MagicMock()
    monkeypatch.setitem(sys.modules, "msvcrt", fake)


def test_cli_self_update_dispatches_to_updater():
    with patch("scansort.cli.update.perform_self_update", return_value=0) as mock_fn:
        exit_code = main_cli(
            ["--self-update", "42", "/x/install", "/x/stage", __version__]
        )
        assert exit_code == 0
    mock_fn.assert_called_once_with(42, "/x/install", "/x/stage", __version__)


def test_maybe_apply_auto_update_inert_in_development(tmp_path: Path):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    with patch("scansort.cli.update.fetch_latest_release") as mock_fetch:
        assert maybe_apply_auto_update(cfg, tmp_path / "appdata") is False
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
        assert maybe_apply_auto_update(cfg, tmp_path / "appdata") is False
        mock_fetch.assert_not_called()


def test_maybe_apply_auto_update_skips_within_interval(tmp_path: Path, monkeypatch):
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
        assert maybe_apply_auto_update(cfg, app_dir) is False
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
        "tag_name": NEXT_TAG,
        "assets": [
            {
                "name": NEXT_ZIP,
                "browser_download_url": NEXT_URL,
                "size": 1,
            }
        ],
    }
    staged = tmp_path / f"ScanSort.stage-{NEXT_VERSION}"
    staged.mkdir()
    (staged / "ScanSort.exe").write_bytes(b"new")
    with (
        patch("scansort.cli.update.fetch_latest_release", return_value=payload),
        patch("scansort.cli.update.download_and_stage", return_value=staged),
        patch("scansort.cli.update.spawn_update_helper") as mock_spawn,
        patch("scansort.cli.update.show_toast") as mock_toast,
    ):
        applied = maybe_apply_auto_update(cfg, app_dir)
    assert applied is True
    mock_spawn.assert_called_once()
    args = mock_spawn.call_args[0]
    assert args[1] == staged
    assert args[2] == NEXT_VERSION
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
        "tag_name": NEXT_TAG,
        "assets": [
            {
                "name": NEXT_ZIP,
                "browser_download_url": NEXT_URL,
                "size": 1,
            }
        ],
    }
    staged = tmp_path / f"ScanSort.stage-{NEXT_VERSION}"
    staged.mkdir()
    (staged / "ScanSort.exe").write_bytes(b"new")
    with (
        patch("scansort.cli.update.fetch_latest_release", return_value=payload),
        patch("scansort.cli.update.download_and_stage", return_value=staged),
        patch("scansort.cli.update.spawn_update_helper"),
        patch("scansort.cli.update.show_toast"),
    ):
        assert maybe_apply_auto_update(cfg, app_dir) is True


def test_maybe_apply_auto_update_no_release_records_check(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/fake/ScanSort/ScanSort.exe", raising=False)
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    app_dir = tmp_path / "appdata"
    with patch(
        "scansort.cli.update.fetch_latest_release",
        return_value={"tag_name": f"v{__version__}"},
    ):
        assert maybe_apply_auto_update(cfg, app_dir) is False
    assert (app_dir / "update_state.json").exists()


def test_maybe_apply_auto_update_recovers_from_check_errors(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/fake/ScanSort/ScanSort.exe", raising=False)
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    app_dir = tmp_path / "appdata"
    with patch(
        "scansort.cli.update.fetch_latest_release",
        side_effect=UpdateError("offline"),
    ):
        assert maybe_apply_auto_update(cfg, app_dir) is False
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
        "tag_name": NEXT_TAG,
        "assets": [
            {
                "name": NEXT_ZIP,
                "browser_download_url": NEXT_URL,
            }
        ],
    }
    staged = tmp_path / f"ScanSort.stage-{NEXT_VERSION}"
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
        assert maybe_apply_auto_update(cfg, app_dir) is False


def test_announce_applied_update_shows_once_then_clears(tmp_path: Path, monkeypatch):
    import scansort.updater as updater

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    updater.record_applied_update(app_dir / "update_state.json", __version__)
    with patch("scansort.cli.update.show_toast") as mock_toast:
        announce_applied_update(app_dir)
    mock_toast.assert_called_once()
    title, body = mock_toast.call_args[0]
    assert title == "ScanSort updated"
    assert __version__ in body
    state = json.loads((app_dir / "update_state.json").read_text(encoding="utf-8"))
    assert state["just_installed"] is False


def test_announce_applied_update_noop_without_marker(tmp_path: Path):
    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    with patch("scansort.cli.update.show_toast") as mock_toast:
        announce_applied_update(app_dir)
    mock_toast.assert_not_called()


def test_announce_applied_update_cleans_stale_update_dirs(tmp_path: Path, monkeypatch):
    import scansort.updater as updater

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    updater.record_applied_update(app_dir / "update_state.json", __version__)

    install_dir = tmp_path / "ScanSort"
    install_dir.mkdir()
    (install_dir / "ScanSort.exe").write_bytes(b"installed")
    helper_dir = tmp_path / "ScanSort.helper-1.1.0"
    helper_dir.mkdir()
    (helper_dir / "ScanSort.exe").write_bytes(b"helper")

    monkeypatch.setattr("sys.executable", str(install_dir / "ScanSort.exe"))
    with patch("scansort.cli.update.show_toast"):
        announce_applied_update(app_dir, install_dir=install_dir)

    assert not helper_dir.exists()


def test_main_cli_check_update_up_to_date(capsys, monkeypatch):
    monkeypatch.setattr(
        "scansort.cli.update.fetch_latest_release",
        lambda: {"tag_name": f"v{__version__}"},
    )
    monkeypatch.setattr(
        "scansort.cli.update.available_update",
        lambda *args, **kwargs: None,
    )
    code = main_cli(["check-update"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Checking for updates" in captured.out
    assert (
        f"ScanSort is up to date (version {__version__}). No new updates available."
        in captured.out
    )


def test_main_cli_check_update_available(capsys, monkeypatch):
    fake_info = ReleaseInfo(
        version=NEXT_VERSION,
        tag_name=NEXT_TAG,
        asset_name=NEXT_ZIP,
        download_url="https://example.com/download.zip",
        size_bytes=1024000,
        sha256=None,
        published_at="2026-09-06",
    )
    monkeypatch.setattr(
        "scansort.cli.update.fetch_latest_release",
        lambda: {"tag_name": NEXT_TAG},
    )
    monkeypatch.setattr(
        "scansort.cli.update.available_update",
        lambda *args, **kwargs: fake_info,
    )
    code = main_cli(["check-update"])
    assert code == 0
    captured = capsys.readouterr()
    assert f"Update available: version {NEXT_VERSION}" in captured.out
    assert NEXT_ZIP in captured.out
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


def test_main_cli_check_update_json_up_to_date(capsys, monkeypatch):
    monkeypatch.setattr(
        "scansort.cli.update.fetch_latest_release",
        lambda: {"tag_name": f"v{__version__}"},
    )
    monkeypatch.setattr(
        "scansort.cli.update.available_update",
        lambda *args, **kwargs: None,
    )
    code = main_cli(["check-update", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["update_available"] is False
    assert data["current_version"] == __version__
    assert data["latest_version"] == __version__


def test_main_cli_check_update_json_available(capsys, monkeypatch):
    fake_info = ReleaseInfo(
        version=NEXT_VERSION,
        tag_name=NEXT_TAG,
        asset_name=NEXT_ZIP,
        download_url="https://example.com/download.zip",
        size_bytes=1024000,
        sha256=None,
        published_at="2026-09-06",
    )
    monkeypatch.setattr(
        "scansort.cli.update.fetch_latest_release",
        lambda: {"tag_name": NEXT_TAG},
    )
    monkeypatch.setattr(
        "scansort.cli.update.available_update",
        lambda *args, **kwargs: fake_info,
    )
    code = main_cli(["check-update", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["update_available"] is True
    assert data["latest_version"] == NEXT_VERSION
    assert data["asset_name"] == NEXT_ZIP


def test_main_cli_check_update_json_failure(capsys, monkeypatch):
    def fail():
        raise UpdateError("Network unreachable")

    monkeypatch.setattr("scansort.cli.update.fetch_latest_release", fail)
    code = main_cli(["check-update", "--json"])
    assert code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["update_available"] is False
    assert "Network unreachable" in data["error"]


def test_maybe_apply_auto_update_defers_when_update_lock_held(
    tmp_path: Path, monkeypatch
):
    """F56: a concurrent update must not delete a live helper's directory."""
    from contextlib import contextmanager

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe_path = tmp_path / "Programs" / "ScanSort" / "ScanSort.exe"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_bytes(b"old")
    monkeypatch.setattr(sys, "executable", str(exe_path), raising=False)

    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    release = ReleaseInfo(
        version=NEXT_VERSION,
        tag_name=NEXT_TAG,
        asset_name=NEXT_ZIP,
        download_url=NEXT_URL,
        size_bytes=1,
        sha256=None,
        published_at=None,
    )

    @contextmanager
    def _held_guard(_path):
        yield False

    with (
        patch("scansort.cli.update.fetch_latest_release", return_value={}),
        patch("scansort.cli.update.available_update", return_value=release),
        patch("scansort.cli.update.download_and_stage") as mock_download,
        patch("scansort.cli.update.instance_guard", _held_guard),
    ):
        assert maybe_apply_auto_update(cfg, app_dir) is False

    mock_download.assert_not_called()

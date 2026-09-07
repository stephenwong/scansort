"""Unit tests for scansort.ui.tray module."""

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from scansort import __version__
from scansort.core.config import AppConfig
from scansort.ui.tray import SystemTrayApp
from scansort.updater.feed import (
    WINDOWS_ASSET_PREFIX,
    WINDOWS_ASSET_SUFFIX,
    ReleaseInfo,
    parse_version,
)

_current_v = parse_version(__version__) or (1, 0, 0)
NEXT_VERSION = f"{_current_v[0] + 1}.0.0"
NEXT_TAG = f"v{NEXT_VERSION}"
NEXT_ZIP = f"{WINDOWS_ASSET_PREFIX}{NEXT_TAG}{WINDOWS_ASSET_SUFFIX}"


def _create_app(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Documents"
    inbox.mkdir()
    docs.mkdir()
    (docs / "Receipts" / "2026").mkdir(parents=True)

    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    mock_watcher = MagicMock()
    mock_watcher.is_paused.return_value = False
    mock_pipeline = MagicMock()
    mock_pipeline.config = cfg
    stop_event = threading.Event()

    app = SystemTrayApp(
        config=cfg,
        watcher=mock_watcher,
        pipeline=mock_pipeline,
        stop_event=stop_event,
    )
    return app, cfg, mock_watcher, mock_pipeline, stop_event


def test_tray_app_initialization(tmp_path: Path):
    app, cfg, mock_watcher, mock_pipeline, stop_event = _create_app(tmp_path)
    assert app.config == cfg
    assert app.watcher is mock_watcher
    assert app.pipeline is mock_pipeline
    assert app.icon is not None
    assert app.icon.title == "ScanSort"


def test_tray_app_toggle_pause(tmp_path: Path):
    app, cfg, mock_watcher, mock_pipeline, stop_event = _create_app(tmp_path)

    with patch("scansort.ui.tray.show_toast") as mock_toast:
        # Pause
        app.toggle_pause()
        mock_watcher.pause.assert_called_once()
        mock_toast.assert_called_with("ScanSort", "Monitoring paused.")

        # Resume
        mock_watcher.is_paused.return_value = True
        app.toggle_pause()
        mock_watcher.resume.assert_called_once()
        mock_toast.assert_called_with("ScanSort", "Monitoring resumed.")


def test_tray_app_undo_action(tmp_path: Path):
    app, cfg, mock_watcher, mock_pipeline, stop_event = _create_app(tmp_path)

    with (
        patch(
            "scansort.ui.tray.run_undo",
            return_value=(True, "Restored scan.pdf", Path("/inbox/scan.pdf")),
        ) as mock_undo,
        patch("scansort.ui.tray.show_toast") as mock_toast,
    ):
        app.undo_last(async_task=False)
        mock_undo.assert_called_once_with(cfg)
        mock_toast.assert_called_with("ScanSort Undo", "Restored scan.pdf")


def test_tray_app_rescan_action(tmp_path: Path):
    app, cfg, mock_watcher, mock_pipeline, stop_event = _create_app(tmp_path)

    with (
        patch(
            "scansort.ui.tray.run_rescan", return_value=["Receipts", "Receipts/2026"]
        ) as mock_rescan,
        patch("scansort.ui.tray.show_toast") as mock_toast,
    ):
        app.rescan_taxonomy(async_task=False)
        mock_rescan.assert_called_once_with(cfg)
        mock_toast.assert_called_with(
            "ScanSort Taxonomy", "Discovered 2 destination folders under Documents."
        )


def test_tray_app_open_folders(tmp_path: Path):
    app, cfg, mock_watcher, mock_pipeline, stop_event = _create_app(tmp_path)

    with patch("scansort.ui.tray.open_in_file_manager") as mock_open:
        app.open_drop_folder()
        mock_open.assert_called_with(cfg.watch_folder)

        app.open_docs_folder()
        mock_open.assert_called_with(cfg.documents_root)

        app.open_log_folder()
        mock_open.assert_called()

        app.view_scan_history()
        mock_open.assert_called()


def test_tray_app_check_updates(tmp_path: Path):
    app, cfg, mock_watcher, mock_pipeline, stop_event = _create_app(tmp_path)

    fake_release = ReleaseInfo(
        version=NEXT_VERSION,
        tag_name=NEXT_TAG,
        asset_name=NEXT_ZIP,
        download_url="https://example.com",
        size_bytes=1000,
        sha256=None,
        published_at=None,
    )

    with (
        patch("scansort.ui.tray.check_for_updates", return_value=(fake_release, None)),
        patch("scansort.ui.tray.show_toast") as mock_toast,
    ):
        app.check_updates(async_task=False)
        mock_toast.assert_called_with(
            "ScanSort Update Available",
            f"Version {NEXT_VERSION} is available to download.",
        )


def test_tray_app_hot_reload_on_settings_applied(tmp_path: Path):
    app, cfg, mock_watcher, mock_pipeline, stop_event = _create_app(tmp_path)

    new_inbox = tmp_path / "NewInbox"
    new_inbox.mkdir()
    new_cfg = AppConfig(watch_folder=new_inbox, documents_root=cfg.documents_root)

    app.on_settings_applied(new_cfg)
    assert app.config == new_cfg
    mock_watcher.switch_folder.assert_called_once_with(new_inbox)
    assert mock_pipeline.config == new_cfg
    mock_pipeline.update_config.assert_called_once_with(new_cfg)


def test_tray_app_exit(tmp_path: Path):
    app, cfg, mock_watcher, mock_pipeline, stop_event = _create_app(tmp_path)
    mock_icon = MagicMock()
    app.icon = mock_icon

    app.exit_app()
    assert stop_event.is_set()
    mock_watcher.stop.assert_called_once()
    mock_icon.stop.assert_called_once()


def test_tray_app_check_updates_no_update_and_error(tmp_path: Path):
    app, cfg, mock_watcher, mock_pipeline, stop_event = _create_app(tmp_path)

    # No update available
    with (
        patch("scansort.ui.tray.check_for_updates", return_value=(None, None)),
        patch("scansort.ui.tray.show_toast") as mock_toast,
    ):
        app.check_updates(async_task=False)
        mock_toast.assert_called_with(
            "ScanSort Update", "ScanSort is up to date. No updates available."
        )

    # Error checking for updates
    with (
        patch(
            "scansort.ui.tray.check_for_updates",
            return_value=(None, "GitHub unreachable"),
        ),
        patch("scansort.ui.tray.show_toast") as mock_toast,
    ):
        app.check_updates(async_task=False)
        mock_toast.assert_called_with(
            "ScanSort Update", "Update check failed: GitHub unreachable"
        )


def test_tray_app_start_stop(tmp_path: Path):
    app, cfg, mock_watcher, mock_pipeline, stop_event = _create_app(tmp_path)
    mock_icon = MagicMock()
    app.icon = mock_icon

    app.start()
    mock_icon.run_detached.assert_called_once()

    app.stop()
    mock_icon.stop.assert_called_once()


def test_tray_app_empty_taxonomy_submenus(tmp_path: Path):
    app, cfg, mock_watcher, mock_pipeline, stop_event = _create_app(tmp_path)

    with patch("scansort.ui.tray.scan_documents_folders", return_value=[]):
        menu = app._build_taxonomy_submenus()
        assert menu is not None
        assert len(menu.items) >= 1


def test_tray_app_open_settings(tmp_path: Path):
    app, cfg, mock_watcher, mock_pipeline, stop_event = _create_app(tmp_path)

    with patch("scansort.ui.tray.open_settings_dialog") as mock_dialog:
        app.open_settings()
        # Thread spawns and invokes open_settings_dialog
        import time

        time.sleep(0.1)
        mock_dialog.assert_called_once()


def test_tray_app_is_paused_none():
    cfg = AppConfig()
    app = SystemTrayApp(config=cfg, watcher=None)
    assert app.is_paused() is False

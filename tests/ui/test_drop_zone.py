"""Unit tests for scansort.ui.drop_zone module."""

import contextlib
import threading
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scansort.core.config import AppConfig
from scansort.ui import drop_zone
from scansort.ui.drop_zone import DropZoneWindow, open_drop_zone_window


@pytest.fixture
def tk_root():
    """Create a headless root Tkinter instance and destroy it after test."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("Tkinter display not available")
    yield root
    with contextlib.suppress(tk.TclError):
        root.destroy()


def test_drop_zone_initialization(tk_root, tmp_path: Path):
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )
    window = DropZoneWindow(master=tk_root, config=cfg)
    assert window.title() == "ScanSort Quick File & Drop Zone"
    assert window.copy_var.get() is False
    assert window.topmost_var.get() is False
    assert "Ready" in window.status_var.get()
    window.destroy()


def test_drop_zone_file_documents_success(tk_root, tmp_path: Path):
    test_pdf = tmp_path / "receipt.pdf"
    test_pdf.write_bytes(b"%PDF-1.4")
    dest_pdf = tmp_path / "Documents" / "Receipts" / "260912_Receipt.pdf"

    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )

    mock_pipeline = MagicMock()
    mock_pipeline.process_file.return_value = dest_pdf
    filed_callbacks = []

    window = DropZoneWindow(
        master=tk_root,
        config=cfg,
        pipeline=mock_pipeline,
        on_filed=lambda p: filed_callbacks.append(p),
    )

    # File without background thread for deterministic test
    window._process_paths_sync([test_pdf])

    assert len(filed_callbacks) == 1
    assert filed_callbacks[0] == dest_pdf
    assert "Filed 1 document(s)" in window.status_var.get()
    window.destroy()


def test_drop_zone_file_documents_copy_toggle(tk_root, tmp_path: Path):
    test_pdf = tmp_path / "receipt.pdf"
    test_pdf.write_bytes(b"%PDF-1.4")
    dest_pdf = tmp_path / "Documents" / "Receipts" / "260912_Receipt.pdf"

    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )

    mock_pipeline = MagicMock()
    mock_pipeline.process_file.return_value = dest_pdf

    window = DropZoneWindow(master=tk_root, config=cfg, pipeline=mock_pipeline)
    window.copy_var.set(True)

    window._process_paths_sync([test_pdf], copy_mode=True)

    mock_pipeline.process_file.assert_called_once_with(
        test_pdf.resolve(), preserve_source=True
    )
    window.destroy()


def test_drop_zone_file_documents_unsupported_or_missing(tk_root, tmp_path: Path):
    bad_txt = tmp_path / "notes.txt"
    bad_txt.write_text("Hello")
    ghost = tmp_path / "ghost.pdf"

    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )
    mock_pipeline = MagicMock()

    window = DropZoneWindow(master=tk_root, config=cfg, pipeline=mock_pipeline)
    window._process_paths_sync([bad_txt, ghost])

    assert mock_pipeline.process_file.call_count == 0
    assert "error" in window.status_var.get().lower()
    window.destroy()


def test_drop_zone_file_documents_exception(tk_root, tmp_path: Path):
    test_pdf = tmp_path / "crash.pdf"
    test_pdf.write_bytes(b"%PDF-1.4")

    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )
    mock_pipeline = MagicMock()
    mock_pipeline.process_file.side_effect = RuntimeError("Disk fault")

    window = DropZoneWindow(master=tk_root, config=cfg, pipeline=mock_pipeline)
    window._process_paths_sync([test_pdf])

    assert "error" in window.status_var.get().lower()
    window.destroy()


def test_drop_zone_file_documents_async_thread(tk_root, tmp_path: Path):
    test_pdf = tmp_path / "doc.pdf"
    test_pdf.write_bytes(b"%PDF-1.4")

    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )
    mock_pipeline = MagicMock()
    mock_pipeline.process_file.return_value = tmp_path / "Documents" / "doc.pdf"

    window = DropZoneWindow(master=tk_root, config=cfg, pipeline=mock_pipeline)

    worker_done = threading.Event()
    with (
        patch.object(window.progress, "start") as mock_start,
        patch.object(
            window, "_process_paths_sync", side_effect=lambda *args: worker_done.set()
        ) as mock_sync,
    ):
        window.copy_var.set(True)
        window.file_documents([test_pdf])
        mock_start.assert_called_once()
        # Deterministic: wait for the worker thread to invoke _process_paths_sync
        assert worker_done.wait(timeout=5)
        mock_sync.assert_called_once_with([test_pdf], True)
    window.destroy()


def test_drop_zone_browse_files(tk_root, tmp_path: Path):
    test_pdf = tmp_path / "browse.pdf"
    test_pdf.write_bytes(b"%PDF-1.4")

    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )
    mock_pipeline = MagicMock()
    mock_pipeline.process_file.return_value = tmp_path / "Documents" / "browse.pdf"

    window = DropZoneWindow(master=tk_root, config=cfg, pipeline=mock_pipeline)
    with (
        patch("tkinter.filedialog.askopenfilenames", return_value=[str(test_pdf)]),
        patch.object(window, "file_documents") as mock_file,
    ):
        window.browse_files()
        mock_file.assert_called_once_with([test_pdf])
    window.destroy()


def test_drop_zone_paste_clipboard_missing(tk_root, tmp_path: Path):
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )
    window = DropZoneWindow(master=tk_root, config=cfg)
    with patch.object(window, "clipboard_get", return_value="/nonexistent/path.pdf"):
        window.paste_from_clipboard()
        assert "not found" in window.status_var.get().lower()

    with patch.object(window, "clipboard_get", side_effect=tk.TclError("No clipboard")):
        window.paste_from_clipboard()
        assert "could not read clipboard" in window.status_var.get().lower()
    window.destroy()


def test_drop_zone_paste_clipboard(tk_root, tmp_path: Path):
    test_pdf = tmp_path / "clip.pdf"
    test_pdf.write_bytes(b"%PDF-1.4")

    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )
    mock_pipeline = MagicMock()

    window = DropZoneWindow(master=tk_root, config=cfg, pipeline=mock_pipeline)
    with (
        patch.object(window, "clipboard_get", return_value=f'"{test_pdf}"'),
        patch.object(window, "file_documents") as mock_file,
    ):
        window.paste_from_clipboard()
        mock_file.assert_called_once_with([test_pdf])
    window.destroy()


def test_drop_zone_toggle_topmost(tk_root, tmp_path: Path):
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )
    window = DropZoneWindow(master=tk_root, config=cfg)
    with patch.object(window, "attributes") as mock_attr:
        window.topmost_var.set(True)
        window._toggle_topmost()
        mock_attr.assert_called_with("-topmost", True)

        window.topmost_var.set(False)
        window._toggle_topmost()
        mock_attr.assert_called_with("-topmost", False)
    window.destroy()


def test_open_drop_zone_window_singleton(tk_root, tmp_path: Path):
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )
    win1 = open_drop_zone_window(master=tk_root, config=cfg)
    win2 = open_drop_zone_window(master=tk_root, config=cfg)
    assert win1 is win2
    assert drop_zone._ACTIVE_DROP_ZONE_INSTANCE is win1
    win1.destroy()

    assert drop_zone._ACTIVE_DROP_ZONE_INSTANCE is None

    win3 = open_drop_zone_window(master=tk_root, config=cfg)
    assert win3 is not win1
    assert drop_zone._ACTIVE_DROP_ZONE_INSTANCE is win3
    win3.destroy()


def test_open_drop_zone_window_after_dead_instance(tk_root, tmp_path: Path):
    """A stale singleton whose Tcl interpreter is gone must not raise; a fresh window opens."""
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )
    win = open_drop_zone_window(master=tk_root, config=cfg)
    stale = MagicMock()
    stale.winfo_exists.side_effect = tk.TclError("interpreter gone")
    from scansort.ui import drop_zone as dz

    with dz._DROP_ZONE_LOCK:
        dz._ACTIVE_DROP_ZONE_INSTANCE = stale
    win_new = open_drop_zone_window(master=tk_root, config=cfg)
    assert win_new is not stale
    assert dz._ACTIVE_DROP_ZONE_INSTANCE is win_new
    win_new.destroy()
    # Restore: destroy the lingering original window so tk_root stays clean
    with contextlib.suppress(tk.TclError):
        win.destroy()


def test_drop_zone_mainloop_guard(tk_root, tmp_path: Path):
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )
    window = DropZoneWindow(master=tk_root, config=cfg)
    with patch("tkinter.Toplevel.mainloop") as mock_loop:
        window.mainloop()
        mock_loop.assert_called_once()
        # Redundant call while already marked running
        window._mainloop_running = True
        window.mainloop()
        assert mock_loop.call_count == 1
    window.destroy()


def test_drop_zone_does_not_shadow_tk_config_method(tk_root, tmp_path: Path):
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Documents"
    )
    window = DropZoneWindow(master=tk_root, config=cfg, pipeline=MagicMock())
    assert window.app_config is cfg
    assert callable(window.config)
    window.destroy()


def test_drop_zone_busy_guard_blocks_overlapping_runs(tk_root, tmp_path: Path):
    test_pdf = tmp_path / "doc.pdf"
    test_pdf.write_bytes(b"%PDF-1.4")
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Documents"
    )
    mock_pipeline = MagicMock()
    mock_pipeline.process_file.return_value = tmp_path / "Documents" / "doc.pdf"
    window = DropZoneWindow(master=tk_root, config=cfg, pipeline=mock_pipeline)

    window._processing = True
    with patch.object(window, "_process_paths_sync") as mock_sync:
        window.file_documents([test_pdf])
    mock_sync.assert_not_called()
    assert "already processing" in window.status_var.get().lower()
    window.destroy()


def test_drop_zone_on_filed_called_once_per_batch(tk_root, tmp_path: Path):
    files = []
    for i in range(3):
        f = tmp_path / f"doc{i}.pdf"
        f.write_bytes(b"%PDF-1.4")
        files.append(f)
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Documents"
    )
    mock_pipeline = MagicMock()
    mock_pipeline.process_file.side_effect = [
        tmp_path / "Documents" / f"doc{i}.pdf" for i in range(3)
    ]
    calls = []
    window = DropZoneWindow(
        master=tk_root,
        config=cfg,
        pipeline=mock_pipeline,
        on_filed=lambda d: calls.append(d),
    )
    window._process_paths_sync(files)
    assert len(calls) == 1
    window.destroy()


def test_drop_zone_on_filed_exception_does_not_count_as_filing_error(
    tk_root, tmp_path: Path
):
    test_pdf = tmp_path / "doc.pdf"
    test_pdf.write_bytes(b"%PDF-1.4")
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Documents"
    )
    mock_pipeline = MagicMock()
    mock_pipeline.process_file.return_value = tmp_path / "Documents" / "doc.pdf"

    def _boom(_dest):
        raise RuntimeError("tray rebuild failed")

    window = DropZoneWindow(
        master=tk_root, config=cfg, pipeline=mock_pipeline, on_filed=_boom
    )
    window._process_paths_sync([test_pdf])
    assert "Filed 1 document(s) successfully" in window.status_var.get()
    window.destroy()


def test_drop_zone_filetypes_use_space_separated_patterns(tk_root, tmp_path: Path):
    cfg = AppConfig(
        watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Documents"
    )
    window = DropZoneWindow(master=tk_root, config=cfg, pipeline=MagicMock())
    captured = {}

    def _fake(**kwargs):
        captured.update(kwargs)
        return ()

    with patch("tkinter.filedialog.askopenfilenames", side_effect=_fake):
        window.browse_files()
    pattern = dict(captured["filetypes"])["Supported Documents"]
    assert ";" not in pattern
    assert "*.pdf" in pattern
    window.destroy()

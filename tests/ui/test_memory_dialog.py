"""Unit tests for scansort.ui.memory dialog."""

import contextlib
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest

from scansort.classification.memory import MemoryStore, memory_db_path_for
from scansort.core.config import AppConfig
from scansort.ui.memory import MemoryDialog, open_memory_dialog


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("Tkinter display not available")
    yield root
    with contextlib.suppress(tk.TclError):
        root.destroy()


def _make_cfg(tmp_path: Path) -> AppConfig:
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir(exist_ok=True)
    docs.mkdir(exist_ok=True)
    return AppConfig(watch_folder=inbox, documents_root=docs)


def _seed(app_dir: Path) -> None:
    store = MemoryStore(memory_db_path_for(app_dir))
    store.index_record(
        {
            "sha256": "a" * 64,
            "status": "SUCCESS",
            "destination_folder": "Finances/Utilities",
            "summary": "Origin Energy bill",
            "timestamp": "2026-09-13T14:00:00",
        }
    )


def test_memory_dialog_lists_examples(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    _seed(app_dir)
    cfg = _make_cfg(tmp_path)
    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        dialog = MemoryDialog(master=tk_root, config=cfg)
        assert len(dialog._rows) == 1
        assert len(dialog.tree.get_children()) == 1
        dialog.destroy()


def test_memory_dialog_forget_selected(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    _seed(app_dir)
    cfg = _make_cfg(tmp_path)
    notified: list[bool] = []
    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        dialog = MemoryDialog(
            master=tk_root, config=cfg, on_changed=lambda: notified.append(True)
        )
        dialog.tree.selection_set("0")
        dialog.forget_selected()
        assert MemoryStore(memory_db_path_for(app_dir)).count() == 0
        assert notified
        dialog.destroy()


def test_memory_dialog_clear_confirmed(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    _seed(app_dir)
    cfg = _make_cfg(tmp_path)
    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        dialog = MemoryDialog(master=tk_root, config=cfg)
        with patch("tkinter.messagebox.askyesno", return_value=True):
            dialog.clear_all()
        assert MemoryStore(memory_db_path_for(app_dir)).count() == 0
        dialog.destroy()


def test_memory_dialog_rebuild(tk_root, tmp_path: Path):
    import json

    import scansort.ui.memory as mem_mod
    from scansort.core.constants import HISTORY_JSONL_NAME

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    (app_dir / HISTORY_JSONL_NAME).write_text(
        json.dumps(
            {
                "sha256": "b" * 64,
                "status": "SUCCESS",
                "destination_folder": "Health/Dental",
                "summary": "Dental invoice",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = _make_cfg(tmp_path)
    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        dialog = MemoryDialog(master=tk_root, config=cfg)
        dialog.rebuild_from_history()
        assert MemoryStore(memory_db_path_for(app_dir)).count() == 1
        dialog.destroy()


def test_open_memory_dialog_singleton(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    cfg = _make_cfg(tmp_path)
    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        d1 = open_memory_dialog(config=cfg)
        d2 = open_memory_dialog(config=cfg)
        assert d1 is d2
        d1.destroy()


def test_memory_dialog_invalid_config_falls_back(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    with (
        patch.object(mem_mod, "get_default_app_dir", return_value=app_dir),
        patch("scansort.ui.memory.load_config", side_effect=ValueError("bad")),
    ):
        dialog = MemoryDialog(master=tk_root, config=None)
        assert isinstance(dialog.app_config, AppConfig)
        dialog.destroy()


def test_memory_dialog_on_changed_exception_isolated(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    _seed(app_dir)
    cfg = _make_cfg(tmp_path)

    def _boom():
        raise RuntimeError("menu rebuild crashed")

    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        dialog = MemoryDialog(master=tk_root, config=cfg, on_changed=_boom)
        dialog.tree.selection_set("0")
        dialog.forget_selected()
        assert MemoryStore(memory_db_path_for(app_dir)).count() == 0
        dialog.destroy()


def test_memory_dialog_refresh_failure_does_not_crash(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    cfg = _make_cfg(tmp_path)
    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        dialog = MemoryDialog(master=tk_root, config=cfg)
        with patch(
            "scansort.classification.memory.MemoryStore.list_examples",
            side_effect=RuntimeError("locked"),
        ):
            dialog.refresh_examples()
            assert dialog._rows == []
        dialog.destroy()


def test_memory_dialog_forget_without_selection_shows_info(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    _seed(app_dir)
    cfg = _make_cfg(tmp_path)
    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        dialog = MemoryDialog(master=tk_root, config=cfg)
        with patch("tkinter.messagebox.showinfo") as mock_info:
            dialog.forget_selected()
            mock_info.assert_called_once()
        dialog.destroy()


def test_memory_dialog_forget_error_shows_error(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    _seed(app_dir)
    cfg = _make_cfg(tmp_path)
    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        dialog = MemoryDialog(master=tk_root, config=cfg)
        dialog.tree.selection_set("0")
        with (
            patch(
                "scansort.classification.memory.MemoryStore.forget_folder",
                side_effect=RuntimeError("db locked"),
            ),
            patch("tkinter.messagebox.showerror") as mock_err,
        ):
            dialog.forget_selected()
            mock_err.assert_called_once()
        dialog.destroy()


def test_memory_dialog_clear_declined_does_nothing(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    _seed(app_dir)
    cfg = _make_cfg(tmp_path)
    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        dialog = MemoryDialog(master=tk_root, config=cfg)
        with patch("tkinter.messagebox.askyesno", return_value=False):
            dialog.clear_all()
        assert MemoryStore(memory_db_path_for(app_dir)).count() == 1
        dialog.destroy()


def test_memory_dialog_clear_error_shows_error(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    _seed(app_dir)
    cfg = _make_cfg(tmp_path)
    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        dialog = MemoryDialog(master=tk_root, config=cfg)
        with (
            patch("tkinter.messagebox.askyesno", return_value=True),
            patch(
                "scansort.classification.memory.MemoryStore.clear",
                side_effect=RuntimeError("disk full"),
            ),
            patch("tkinter.messagebox.showerror") as mock_err,
        ):
            dialog.clear_all()
            mock_err.assert_called_once()
        dialog.destroy()


def test_memory_dialog_rebuild_error_shows_error(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    cfg = _make_cfg(tmp_path)
    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        dialog = MemoryDialog(master=tk_root, config=cfg)
        with (
            patch(
                "scansort.classification.memory.rebuild_memory",
                side_effect=RuntimeError("locked"),
            ),
            patch("tkinter.messagebox.showerror") as mock_err,
        ):
            dialog.rebuild_from_history()
            mock_err.assert_called_once()
        dialog.destroy()


def test_memory_dialog_invalid_selection_returns_none(tk_root, tmp_path: Path):
    import scansort.ui.memory as mem_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()
    cfg = _make_cfg(tmp_path)
    with patch.object(mem_mod, "get_default_app_dir", return_value=app_dir):
        dialog = MemoryDialog(master=tk_root, config=cfg)
        dialog._rows = []
        with patch.object(dialog.tree, "selection", return_value=["99"]):
            assert dialog._selected_folder() is None
        dialog.destroy()

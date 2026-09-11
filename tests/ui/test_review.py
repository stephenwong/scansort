"""Unit tests for scansort.ui.review module."""

import contextlib
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfWriter

from scansort.core.config import AppConfig
from scansort.pipeline.review import ReviewItem
from scansort.ui.review import ReviewDialog, open_review_dialog


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


def _create_dummy_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def test_review_dialog_empty_queue(tk_root, tmp_path: Path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    dialog = ReviewDialog(master=tk_root, config=cfg)
    assert len(dialog.queue) == 0
    dialog.destroy()


def test_review_dialog_populated_and_navigation(tk_root, tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    pdf1 = _create_dummy_pdf(review_dir / "260815_Doc1.pdf")
    pdf2 = _create_dummy_pdf(review_dir / "260816_Doc2.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    item1 = ReviewItem(
        file_path=pdf1,
        filename=pdf1.name,
        file_size_bytes=1024,
        modified_time=1000.0,
        summary="Doc 1 summary",
        suggested_folder="Health/Dental",
        confidence=0.6,
        document_date="260815",
        description="Doc1",
    )
    item2 = ReviewItem(
        file_path=pdf2,
        filename=pdf2.name,
        file_size_bytes=2048,
        modified_time=2000.0,
        summary="Doc 2 summary",
        suggested_folder="Utilities/Power",
        confidence=0.55,
        document_date="260816",
        description="Doc2",
    )

    with patch("scansort.ui.review.get_review_queue", return_value=[item1, item2]):
        dialog = ReviewDialog(master=tk_root, config=cfg)

        assert len(dialog.queue) == 2
        assert dialog._current_index == 0
        assert dialog.desc_var.get() == "Doc1"
        assert dialog.date_var.get() == "260815"

        # Apply suggestion
        dialog._use_suggestion()
        assert dialog.folder_var.get() == "Health/Dental"

        # Navigate next
        dialog._next_item()
        assert dialog._current_index == 1
        assert dialog.desc_var.get() == "Doc2"

        # Navigate previous
        dialog._prev_item()
        assert dialog._current_index == 0

        dialog.destroy()


def test_review_dialog_file_action(tk_root, tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    pdf = _create_dummy_pdf(review_dir / "260815_Bill.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")
    item = ReviewItem(
        file_path=pdf,
        filename=pdf.name,
        file_size_bytes=1024,
        modified_time=1000.0,
        summary="Electricity bill",
        suggested_folder="Utilities/Electricity",
        confidence=0.65,
        document_date="260815",
        description="Bill",
    )

    filed_calls = []

    def _on_filed(dest):
        filed_calls.append(dest)

    with patch("scansort.ui.review.get_review_queue", return_value=[item]):
        dialog = ReviewDialog(master=tk_root, config=cfg, on_filed=_on_filed)
        dialog.folder_var.set("Utilities/Electricity")
        dialog.hint_var.set(False)  # disable hint for this test

        dialog._file_current_item()

        assert len(filed_calls) == 1
        assert len(dialog.queue) == 0
        dialog.destroy()


def test_review_dialog_dismiss_action(tk_root, tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    pdf = _create_dummy_pdf(review_dir / "junk.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")
    item = ReviewItem(
        file_path=pdf,
        filename=pdf.name,
        file_size_bytes=1024,
        modified_time=1000.0,
    )

    with patch("scansort.ui.review.get_review_queue", return_value=[item]):
        dialog = ReviewDialog(master=tk_root, config=cfg)
        dialog._dismiss_current_item(confirm=False)

        assert not pdf.exists()
        assert len(dialog.queue) == 0
        dialog.destroy()


def test_open_review_dialog_singleton(tk_root, tmp_path: Path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    cfg = AppConfig(documents_root=docs)

    d1 = open_review_dialog(config=cfg)
    d2 = open_review_dialog(config=cfg)
    assert d1 is d2
    d1.destroy()


def test_review_dialog_open_in_viewer(tk_root, tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    pdf = _create_dummy_pdf(review_dir / "scan.pdf")
    cfg = AppConfig(documents_root=docs)

    item = ReviewItem(
        file_path=pdf,
        filename=pdf.name,
        file_size_bytes=1024,
        modified_time=1000.0,
    )
    opened = []
    with (
        patch("scansort.ui.review.get_review_queue", return_value=[item]),
        patch("scansort.ui.review.open_in_file_manager", lambda p: opened.append(p)),
    ):
        dialog = ReviewDialog(master=tk_root, config=cfg)
        dialog._open_in_viewer()
        assert len(opened) == 1
        dialog.destroy()


def test_review_dialog_empty_folder_warning(tk_root, tmp_path: Path):
    docs = tmp_path / "Documents"
    cfg = AppConfig(documents_root=docs)
    item = ReviewItem(
        file_path=tmp_path / "file.pdf",
        filename="file.pdf",
        file_size_bytes=100,
        modified_time=100.0,
    )
    with (
        patch("scansort.ui.review.get_review_queue", return_value=[item]),
        patch("tkinter.messagebox.showwarning") as mock_warn,
    ):
        dialog = ReviewDialog(master=tk_root, config=cfg)
        dialog.folder_var.set("")
        dialog._file_current_item()
        mock_warn.assert_called_once()
        dialog.destroy()


def test_review_dialog_dismiss_cancelled(tk_root, tmp_path: Path):
    docs = tmp_path / "Documents"
    cfg = AppConfig(documents_root=docs)
    item = ReviewItem(
        file_path=tmp_path / "file.pdf",
        filename="file.pdf",
        file_size_bytes=100,
        modified_time=100.0,
    )
    with (
        patch("scansort.ui.review.get_review_queue", return_value=[item]),
        patch("tkinter.messagebox.askyesno", return_value=False),
    ):
        dialog = ReviewDialog(master=tk_root, config=cfg)
        dialog._dismiss_current_item(confirm=True)
        assert len(dialog.queue) == 1
        dialog.destroy()


def test_review_dialog_mainloop_safe(tk_root, tmp_path: Path):
    docs = tmp_path / "Documents"
    cfg = AppConfig(documents_root=docs)
    with (
        patch("scansort.ui.review.get_review_queue", return_value=[]),
        patch.object(tk.Toplevel, "mainloop") as mock_base_mainloop,
    ):
        dialog = ReviewDialog(master=tk_root, config=cfg)
        dialog.mainloop()
        mock_base_mainloop.assert_called_once()
        dialog.destroy()


def test_review_dialog_empty_queue_frame_cleanup(tk_root, tmp_path: Path):
    from tkinter import ttk

    docs = tmp_path / "Documents"
    cfg = AppConfig(documents_root=docs)
    with patch("scansort.ui.review.get_review_queue", return_value=[]):
        dialog = ReviewDialog(master=tk_root, config=cfg)
        frames = [c for c in dialog.winfo_children() if isinstance(c, ttk.Frame)]
        assert len(frames) == 1
        # Calling _load_current_item again should not leave an orphaned frame
        dialog._load_current_item()
        frames_after = [c for c in dialog.winfo_children() if isinstance(c, ttk.Frame)]
        assert len(frames_after) == 1
        dialog.destroy()


def test_review_dialog_on_filed_callback_exception_isolation(tk_root, tmp_path: Path):
    docs = tmp_path / "Documents"
    cfg = AppConfig(documents_root=docs)
    item = ReviewItem(
        file_path=tmp_path / "file.pdf",
        filename="file.pdf",
        file_size_bytes=100,
        modified_time=100.0,
    )

    def _failing_callback(_dest):
        raise RuntimeError("Tray menu rebuild crashed")

    with (
        patch("scansort.ui.review.get_review_queue", return_value=[item]),
        patch(
            "scansort.ui.review.file_reviewed_item",
            return_value=tmp_path / "dest.pdf",
        ),
        patch("scansort.ui.review.show_toast"),
    ):
        dialog = ReviewDialog(master=tk_root, config=cfg, on_filed=_failing_callback)
        dialog.folder_var.set("Finance")
        dialog._file_current_item()
        assert len(dialog.queue) == 0
        dialog.destroy()


def test_review_dialog_dismiss_oserror_handled(tk_root, tmp_path: Path):
    docs = tmp_path / "Documents"
    cfg = AppConfig(documents_root=docs)
    item = ReviewItem(
        file_path=tmp_path / "file.pdf",
        filename="file.pdf",
        file_size_bytes=100,
        modified_time=100.0,
    )

    with (
        patch("scansort.ui.review.get_review_queue", return_value=[item]),
        patch("tkinter.messagebox.askyesno", return_value=True),
        patch(
            "scansort.ui.review.dismiss_review_item",
            side_effect=OSError("Permission denied"),
        ),
        patch("tkinter.messagebox.showerror") as mock_err,
    ):
        dialog = ReviewDialog(master=tk_root, config=cfg)
        dialog._dismiss_current_item(confirm=True)
        mock_err.assert_called_once()
        assert len(dialog.queue) == 1
        dialog.destroy()

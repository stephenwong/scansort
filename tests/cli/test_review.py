"""Unit tests for scansort.cli.review subcommand handler."""

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

from pypdf import PdfWriter

from scansort.cli.parser import build_parser
from scansort.cli.review import handle_review
from scansort.core.config import AppConfig


def _create_dummy_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def test_parser_has_review_subcommand():
    parser = build_parser()
    args = parser.parse_args(["review", "--gui", "--limit", "5"])
    assert args.command == "review"
    assert args.gui is True
    assert args.limit == 5


def test_handle_review_empty_queue(tmp_path: Path, capsys):
    docs = tmp_path / "Documents"
    docs.mkdir()
    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    with patch("scansort.cli.review.load_config", return_value=cfg):
        args = argparse.Namespace(gui=False, cli=True, limit=None)
        code = handle_review(args)

    assert code == 0
    captured = capsys.readouterr()
    assert "No documents currently require review" in captured.out


def test_handle_review_cli_file_item(tmp_path: Path, monkeypatch, capsys):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    _create_dummy_pdf(review_dir / "260815_Dental_Receipt.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    # Inputs:
    # 1: File to AI suggestion (or enter folder)
    # Target folder: Health/Dental
    # Date: (accept default)
    # Description: (accept default)
    # Hint: (accept default)
    inputs = iter(["2", "Health/Dental", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch(
            "scansort.cli.review.get_default_app_dir", return_value=tmp_path / "app_dir"
        ),
    ):
        args = argparse.Namespace(gui=False, cli=True, limit=None)
        code = handle_review(args)

    assert code == 0
    captured = capsys.readouterr()
    assert "Successfully filed" in captured.out or "Filed to" in captured.out
    dest_file = docs / "Health" / "Dental" / "260815_Dental_Receipt.pdf"
    assert dest_file.exists()


def test_handle_review_cli_dismiss_item(tmp_path: Path, monkeypatch, capsys):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    pdf = _create_dummy_pdf(review_dir / "junk_scan.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    # Choice 5: dismiss, confirm: y
    inputs = iter(["5", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch(
            "scansort.cli.review.get_default_app_dir", return_value=tmp_path / "app_dir"
        ),
    ):
        args = argparse.Namespace(gui=False, cli=True, limit=None)
        code = handle_review(args)

    assert code == 0
    assert not pdf.exists()


def test_handle_review_gui_delegation(tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    _create_dummy_pdf(review_dir / "item.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    mock_dialog = MagicMock()
    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch(
            "scansort.ui.review.open_review_dialog", return_value=mock_dialog
        ) as mock_open,
    ):
        args = argparse.Namespace(gui=True, cli=False, limit=None)
        code = handle_review(args)

    assert code == 0
    mock_open.assert_called_once()
    mock_dialog.mainloop.assert_called_once()


def test_handle_review_cli_skip_and_quit(tmp_path: Path, monkeypatch, capsys):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    _create_dummy_pdf(review_dir / "item1.pdf")
    _create_dummy_pdf(review_dir / "item2.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    # item1: choice 3 (open), choice 4 (skip); item2: choice q (quit)
    inputs = iter(["3", "4", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    opened = []
    monkeypatch.setattr(
        "scansort.cli.review.open_in_file_manager", lambda p: opened.append(p)
    )

    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch(
            "scansort.cli.review.get_default_app_dir", return_value=tmp_path / "app_dir"
        ),
    ):
        args = argparse.Namespace(gui=False, cli=True, limit=None)
        code = handle_review(args)

    assert code == 0
    assert len(opened) == 1
    captured = capsys.readouterr()
    assert "Skipped" in captured.out
    assert "Review session ended" in captured.out


def test_handle_review_cli_dismiss_cancelled_and_eof(
    tmp_path: Path, monkeypatch, capsys
):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    pdf = _create_dummy_pdf(review_dir / "item.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    # Dismiss cancel ('5' then 'n'), then EOF on next choice
    inputs = iter(["5", "n", EOFError()])

    def _mock_input(prompt=""):
        val = next(inputs)
        if isinstance(val, Exception):
            raise val
        return val

    monkeypatch.setattr("builtins.input", _mock_input)

    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch(
            "scansort.cli.review.get_default_app_dir", return_value=tmp_path / "app_dir"
        ),
    ):
        args = argparse.Namespace(gui=False, cli=True, limit=None)
        code = handle_review(args)

    assert code == 0
    assert pdf.exists()


def test_has_gui_display(monkeypatch):
    from scansort.cli.review import _has_gui_display

    monkeypatch.setattr("sys.platform", "win32")
    assert _has_gui_display() is True

    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert _has_gui_display() is False

    monkeypatch.setenv("DISPLAY", ":0")
    assert _has_gui_display() is True


def test_handle_review_cli_accept_ai_suggestion(tmp_path: Path, monkeypatch, capsys):
    from scansort.pipeline.review import ReviewItem

    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    pdf = _create_dummy_pdf(review_dir / "260815_Tax_Bill.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    item = ReviewItem(
        file_path=pdf,
        filename=pdf.name,
        file_size_bytes=1024,
        modified_time=0.0,
        suggested_folder="Finance/Tax",
        confidence=0.88,
        summary="Annual tax assessment",
        folder_reasoning="Document is a tax bill matching Finance/Tax",
        document_date="260815",
        description="Tax_Bill",
        document_type="Invoice",
    )

    # Choice '1' (accept suggestion 'Finance/Tax'), date default, desc default, hint 'y'
    inputs = iter(["1", "", "", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch("scansort.cli.review.get_review_queue", return_value=[item]),
        patch(
            "scansort.cli.review.get_default_app_dir", return_value=tmp_path / "app_dir"
        ),
    ):
        args = argparse.Namespace(gui=False, cli=True, limit=None)
        code = handle_review(args)

    assert code == 0
    captured = capsys.readouterr()
    assert "AI Suggestion: Finance/Tax" in captured.out
    assert "Annual tax assessment" in captured.out
    assert "Confidence: 88%" in captured.out
    assert (docs / "Finance" / "Tax" / "260815_Tax_Bill.pdf").exists()


def test_handle_review_cli_empty_folder_and_filing_error(
    tmp_path: Path, monkeypatch, capsys
):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    _create_dummy_pdf(review_dir / "item.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    # Inputs:
    # Choice '1' (no suggestion -> prompts target folder):
    # Target folder: "" (empty -> error)
    # Choice '4' (skip)
    inputs = iter(["1", "", "4"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch(
            "scansort.cli.review.get_default_app_dir", return_value=tmp_path / "app_dir"
        ),
    ):
        args = argparse.Namespace(gui=False, cli=True, limit=1)
        code = handle_review(args)

    assert code == 0
    captured = capsys.readouterr()
    assert "Error: Target folder cannot be empty" in captured.out
    assert "Skipped item.pdf" in captured.out


def test_handle_review_cli_filing_error_retry(tmp_path: Path, monkeypatch, capsys):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    _create_dummy_pdf(review_dir / "item.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    # Choice '2' (enter folder), target 'Bad/Folder', date default, desc default, hint default
    # Then retry: choice '4' (skip)
    inputs = iter(["2", "Bad/Folder", "", "", "", "4"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch(
            "scansort.cli.review.file_reviewed_item",
            side_effect=[ValueError("Unsafe destination"), None],
        ),
        patch(
            "scansort.cli.review.get_default_app_dir", return_value=tmp_path / "app_dir"
        ),
    ):
        args = argparse.Namespace(gui=False, cli=True, limit=None)
        code = handle_review(args)

    assert code == 0
    captured = capsys.readouterr()
    assert "Error filing document: Unsafe destination" in captured.out
    assert "Skipped item.pdf" in captured.out


def test_handle_review_cli_interrupts(tmp_path: Path, monkeypatch):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    _create_dummy_pdf(review_dir / "item.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    def _raise_interrupt(prompt=""):
        raise KeyboardInterrupt()

    monkeypatch.setattr("builtins.input", _raise_interrupt)

    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch(
            "scansort.cli.review.get_default_app_dir", return_value=tmp_path / "app_dir"
        ),
    ):
        args = argparse.Namespace(gui=False, cli=True, limit=None)
        code = handle_review(args)

    assert code == 0


def test_handle_review_auto_gui_when_available(tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    _create_dummy_pdf(review_dir / "item.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")
    mock_dialog = MagicMock()

    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch("scansort.cli.review._has_gui_display", return_value=True),
        patch(
            "scansort.ui.review.open_review_dialog", return_value=mock_dialog
        ) as mock_open,
    ):
        # gui and cli both False, display available -> opens GUI
        args = argparse.Namespace(gui=False, cli=False, limit=None)
        code = handle_review(args)

    assert code == 0
    mock_open.assert_called_once()


def test_handle_review_cli_invalid_choice_and_recovery(
    tmp_path: Path, monkeypatch, capsys
):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    _create_dummy_pdf(review_dir / "item.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    # Invalid choice '9', followed by '4' (skip)
    inputs = iter(["9", "4"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch(
            "scansort.cli.review.get_default_app_dir", return_value=tmp_path / "app_dir"
        ),
    ):
        args = argparse.Namespace(gui=False, cli=True, limit=None)
        code = handle_review(args)

    assert code == 0
    captured = capsys.readouterr()
    assert "Invalid choice '9'" in captured.out
    assert "Skipped item.pdf" in captured.out


def test_handle_review_cli_secondary_prompt_interrupt(tmp_path: Path, monkeypatch, capsys):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    _create_dummy_pdf(review_dir / "item.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    def _mock_input(prompt=""):
        if "Choice" in prompt:
            return "2"
        if "Target folder" in prompt:
            return "Finance/Invoices"
        if "Document date" in prompt:
            raise KeyboardInterrupt()
        return ""

    monkeypatch.setattr("builtins.input", _mock_input)

    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch(
            "scansort.cli.review.get_default_app_dir", return_value=tmp_path / "app_dir"
        ),
    ):
        args = argparse.Namespace(gui=False, cli=True, limit=None)
        code = handle_review(args)

    assert code == 0
    captured = capsys.readouterr()
    assert "Review session cancelled." in captured.out


def test_handle_review_cli_limit_truncation(tmp_path: Path, monkeypatch, capsys):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    for i in range(5):
        _create_dummy_pdf(review_dir / f"scan_{i}.pdf")

    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")

    # Skip all presented items
    inputs = iter(["4", "4"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    with (
        patch("scansort.cli.review.load_config", return_value=cfg),
        patch(
            "scansort.cli.review.get_default_app_dir", return_value=tmp_path / "app_dir"
        ),
    ):
        # Limit to 2
        args = argparse.Namespace(gui=False, cli=True, limit=2)
        code = handle_review(args)

    assert code == 0
    captured = capsys.readouterr()
    assert "2 documents to review" in captured.out

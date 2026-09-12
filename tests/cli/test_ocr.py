"""Unit tests for the 'scansort ocr-backfill' CLI subcommand."""

import argparse
from pathlib import Path
from unittest.mock import patch

from scansort.cli.ocr import handle_ocr_backfill
from scansort.core.config import AppConfig
from scansort.pipeline.ocr_backfill import OcrBackfillResult


def _cfg(tmp_path: Path) -> AppConfig:
    docs = tmp_path / "Documents"
    docs.mkdir()
    return AppConfig(watch_folder=tmp_path / "Inbox", documents_root=docs)


def test_handle_ocr_backfill_requires_tesseract(tmp_path: Path, capsys):
    cfg = _cfg(tmp_path)
    with (
        patch("scansort.cli.ocr._load_config_or_exit", return_value=cfg),
        patch("scansort.cli.ocr.has_ocr_support", return_value=False),
    ):
        code = handle_ocr_backfill(argparse.Namespace(targets=[], dry_run=False))

    assert code == 1
    assert "tesseract" in capsys.readouterr().err


def test_handle_ocr_backfill_dry_run_summary(tmp_path: Path, capsys):
    cfg = _cfg(tmp_path)
    result = OcrBackfillResult(candidates=[tmp_path / "a.pdf"], skipped=2)
    with (
        patch("scansort.cli.ocr._load_config_or_exit", return_value=cfg),
        patch("scansort.cli.ocr.has_ocr_support", return_value=True),
        patch("scansort.cli.ocr.run_ocr_backfill", return_value=result) as fake_run,
    ):
        code = handle_ocr_backfill(
            argparse.Namespace(targets=[], dry_run=True, limit=5, language="eng")
        )

    assert code == 0
    assert fake_run.call_args.kwargs["dry_run"] is True
    assert fake_run.call_args.kwargs["limit"] == 5
    out = capsys.readouterr().out
    assert "1 PDF(s) need OCR" in out
    assert "2 already searchable" in out


def test_handle_ocr_backfill_dry_run_bypasses_tesseract_gate(tmp_path: Path, capsys):
    """--dry-run only needs pypdf, so a missing tesseract must not block it."""
    cfg = _cfg(tmp_path)
    result = OcrBackfillResult(candidates=[tmp_path / "a.pdf"])
    with (
        patch("scansort.cli.ocr._load_config_or_exit", return_value=cfg),
        patch("scansort.cli.ocr.has_ocr_support", return_value=False),
        patch("scansort.cli.ocr.run_ocr_backfill", return_value=result) as fake_run,
    ):
        code = handle_ocr_backfill(
            argparse.Namespace(targets=[], dry_run=True, limit=None, language=None)
        )

    assert code == 0
    fake_run.assert_called_once()


def test_handle_ocr_backfill_dry_run_summary_includes_failures(tmp_path: Path, capsys):
    cfg = _cfg(tmp_path)
    result = OcrBackfillResult(
        candidates=[tmp_path / "a.pdf"], failed=[tmp_path / "b.pdf"], skipped=1
    )
    with (
        patch("scansort.cli.ocr._load_config_or_exit", return_value=cfg),
        patch("scansort.cli.ocr.has_ocr_support", return_value=True),
        patch("scansort.cli.ocr.run_ocr_backfill", return_value=result),
    ):
        code = handle_ocr_backfill(
            argparse.Namespace(targets=[], dry_run=True, limit=None, language=None)
        )

    assert code == 1
    assert "1 failed" in capsys.readouterr().out


def test_handle_ocr_backfill_rejects_invalid_language(tmp_path: Path, capsys):
    """An unsupported --language code must fail fast, not route scans to review."""
    cfg = _cfg(tmp_path)
    with (
        patch("scansort.cli.ocr._load_config_or_exit", return_value=cfg),
        patch("scansort.cli.ocr.has_ocr_support", return_value=True),
        patch("scansort.cli.ocr.run_ocr_backfill") as fake_run,
    ):
        code = handle_ocr_backfill(
            argparse.Namespace(targets=[], dry_run=False, limit=None, language="xx_YY!")
        )

    assert code == 1
    assert "ocr_language must be a Tesseract code" in capsys.readouterr().err
    fake_run.assert_not_called()


def test_handle_ocr_backfill_reports_pipeline_valueerror(tmp_path: Path, capsys):
    """A pipeline ValueError must become a diagnostic, not a traceback."""
    cfg = _cfg(tmp_path)
    with (
        patch("scansort.cli.ocr._load_config_or_exit", return_value=cfg),
        patch("scansort.cli.ocr.has_ocr_support", return_value=True),
        patch(
            "scansort.cli.ocr.run_ocr_backfill",
            side_effect=ValueError("Review folder escapes documents root"),
        ),
    ):
        code = handle_ocr_backfill(argparse.Namespace(targets=[], dry_run=False))

    assert code == 1
    assert "escapes documents root" in capsys.readouterr().err


def test_handle_ocr_backfill_rejects_non_pdf_target(tmp_path: Path, capsys):
    cfg = _cfg(tmp_path)
    not_pdf = tmp_path / "notes.txt"
    not_pdf.write_text("hello", encoding="utf-8")

    with (
        patch("scansort.cli.ocr._load_config_or_exit", return_value=cfg),
        patch("scansort.cli.ocr.has_ocr_support", return_value=True),
    ):
        code = handle_ocr_backfill(argparse.Namespace(targets=[not_pdf], dry_run=False))

    assert code == 1
    assert "not a PDF" in capsys.readouterr().err


def test_handle_ocr_backfill_missing_path(tmp_path: Path, capsys):
    cfg = _cfg(tmp_path)
    with (
        patch("scansort.cli.ocr._load_config_or_exit", return_value=cfg),
        patch("scansort.cli.ocr.has_ocr_support", return_value=True),
    ):
        code = handle_ocr_backfill(
            argparse.Namespace(targets=[tmp_path / "missing.pdf"], dry_run=False)
        )

    assert code == 1
    assert "path not found" in capsys.readouterr().err


def test_handle_ocr_backfill_reports_failures(tmp_path: Path, capsys):
    cfg = _cfg(tmp_path)
    target = tmp_path / "a.pdf"
    target.write_bytes(b"%PDF-1.4")
    result = OcrBackfillResult(processed=[target], failed=[tmp_path / "b.pdf"])
    with (
        patch("scansort.cli.ocr._load_config_or_exit", return_value=cfg),
        patch("scansort.cli.ocr.has_ocr_support", return_value=True),
        patch("scansort.cli.ocr.run_ocr_backfill", return_value=result),
    ):
        code = handle_ocr_backfill(argparse.Namespace(targets=[target], dry_run=False))

    assert code == 1
    assert "1 failed" in capsys.readouterr().out

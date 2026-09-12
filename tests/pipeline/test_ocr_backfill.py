"""Unit tests for the OCR backfill pipeline orchestrator."""

import json
from pathlib import Path
from unittest.mock import patch

from scansort.core.config import AppConfig
from scansort.document.ocr import OcrError
from scansort.pipeline.ocr_backfill import run_ocr_backfill


def _make_cfg(tmp_path: Path, **overrides) -> AppConfig:
    docs = tmp_path / "Documents"
    docs.mkdir(exist_ok=True)
    return AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=docs,
        **overrides,
    )


def _write_pdf(path: Path, content: bytes = b"%PDF-1.4 scan") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _read_history(app_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (app_dir / "history.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_ocr_output(
    path: Path, language: str = "eng", output_path: Path | None = None
) -> tuple[Path, float]:
    """Fake OCR that writes a text-layered PDF to the requested output path."""
    target = output_path or path
    target.write_bytes(b"%PDF-1.4 scan plus text layer")
    return target, 90.0


def _write_ocr_output_80(
    path: Path, language: str = "eng", output_path: Path | None = None
) -> tuple[Path, float]:
    target = output_path or path
    target.write_bytes(b"%PDF-1.4 scan plus text layer")
    return target, 80.0


def test_dry_run_lists_candidates_without_mutating(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    pdf = _write_pdf(cfg.documents_root / "Utilities" / "bill.pdf")
    app_dir = tmp_path / "app"
    printed: list[str] = []

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", return_value=True),
        patch("scansort.pipeline.ocr_backfill.ocr_pdf_inplace") as fake_ocr,
    ):
        result = run_ocr_backfill(cfg, app_dir, dry_run=True, progress=printed.append)

    assert result.candidates == [pdf.resolve()]
    assert result.processed == []
    fake_ocr.assert_not_called()
    assert pdf.read_bytes() == b"%PDF-1.4 scan"
    assert not (app_dir / "history.jsonl").exists()
    assert any("[DRY RUN]" in line for line in printed)


def test_backfill_rewrites_pdf_and_audits_hashes(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    pdf = _write_pdf(cfg.documents_root / "Utilities" / "bill.pdf")
    app_dir = tmp_path / "app"

    def fake_ocr(path, language="eng", output_path=None):
        target = output_path or path
        target.write_bytes(b"%PDF-1.4 scan plus text layer")
        return target, 88.0

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", return_value=True),
        patch("scansort.pipeline.ocr_backfill.ocr_pdf_inplace", side_effect=fake_ocr),
    ):
        result = run_ocr_backfill(cfg, app_dir, language="eng")

    assert result.processed == [pdf.resolve()]
    assert result.failed == []
    assert pdf.read_bytes() == b"%PDF-1.4 scan plus text layer"
    record = _read_history(app_dir)[-1]
    assert record["status"] == "OCR_BACKFILLED"
    assert record["ocr_engine"] == "tesseract"
    assert record["ocr_confidence"] == 88.0
    assert record["ocr_language"] == "eng"
    assert record["original_sha256"] != record["sha256"]
    assert record["destination_path"] == str(pdf.resolve())


def test_backfill_skips_already_searchable_pdf(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    _write_pdf(cfg.documents_root / "digital.pdf")
    app_dir = tmp_path / "app"

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", return_value=False),
        patch("scansort.pipeline.ocr_backfill.ocr_pdf_inplace") as fake_ocr,
    ):
        result = run_ocr_backfill(cfg, app_dir)

    assert result.skipped == 1
    assert result.processed == []
    fake_ocr.assert_not_called()
    assert not (app_dir / "history.jsonl").exists()


def test_backfill_routes_corrupt_pdf_to_review(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    pdf = _write_pdf(cfg.documents_root / "Utilities" / "corrupt.pdf")
    app_dir = tmp_path / "app"

    with (
        patch(
            "scansort.pipeline.ocr_backfill.needs_ocr",
            side_effect=OcrError("unreadable"),
        ),
        patch("scansort.pipeline.ocr_backfill.notify_filing_failed") as notify,
    ):
        result = run_ocr_backfill(cfg, app_dir)

    assert result.failed == [pdf.resolve()]
    assert not pdf.exists()
    review_dir = cfg.documents_root / "_Review_Needed"
    assert (review_dir / "corrupt.pdf").exists()
    record = _read_history(app_dir)[-1]
    assert record["status"] == "FAILED"
    assert "OCR backfill failed" in record["summary"]
    notify.assert_called_once()


def test_backfill_respects_limit(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    _write_pdf(cfg.documents_root / "a.pdf")
    _write_pdf(cfg.documents_root / "b.pdf")
    app_dir = tmp_path / "app"

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", return_value=True),
        patch(
            "scansort.pipeline.ocr_backfill.ocr_pdf_inplace",
            side_effect=_write_ocr_output,
        ),
    ):
        result = run_ocr_backfill(cfg, app_dir, limit=1)

    assert len(result.processed) == 1


def test_backfill_accepts_explicit_single_file_target(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    pdf = _write_pdf(cfg.documents_root / "Utilities" / "bill.pdf")
    app_dir = tmp_path / "app"

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", return_value=True),
        patch(
            "scansort.pipeline.ocr_backfill.ocr_pdf_inplace",
            side_effect=_write_ocr_output,
        ),
    ):
        result = run_ocr_backfill(cfg, app_dir, targets=[pdf])

    assert result.processed == [pdf.resolve()]


def test_backfill_skips_review_folder_candidates(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    _write_pdf(cfg.documents_root / "_Review_Needed" / "pending.pdf")
    app_dir = tmp_path / "app"

    with patch("scansort.pipeline.ocr_backfill.needs_ocr") as fake_needs:
        result = run_ocr_backfill(cfg, app_dir)

    fake_needs.assert_not_called()
    assert result.candidates == []


def test_backfill_skips_when_race_recheck_finds_text(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    pdf = _write_pdf(cfg.documents_root / "bill.pdf")
    original = pdf.read_bytes()
    app_dir = tmp_path / "app"

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", side_effect=[True, False]),
        patch(
            "scansort.pipeline.ocr_backfill.ocr_pdf_inplace",
            side_effect=_write_ocr_output,
        ),
    ):
        result = run_ocr_backfill(cfg, app_dir)

    # OCR ran before the under-lock recheck, but the recheck skipped the replace.
    assert result.skipped == 1
    assert result.processed == []
    assert pdf.read_bytes() == original


def test_backfill_holds_lock_only_across_replace_and_audit(tmp_path: Path):
    """Tesseract must run outside operations.lock; only replace/audit hold it."""
    from contextlib import contextmanager

    cfg = _make_cfg(tmp_path)
    pdf = _write_pdf(cfg.documents_root / "bill.pdf")
    app_dir = tmp_path / "app"
    state = {"held": False, "free_during_ocr": None, "held_during_audit": None}

    @contextmanager
    def fake_lock(_path):
        state["held"] = True
        try:
            yield
        finally:
            state["held"] = False

    def fake_ocr(path, language="eng", output_path=None):
        state["free_during_ocr"] = not state["held"]
        return _write_ocr_output(path, language, output_path)

    def fake_log_scan(_entry):
        state["held_during_audit"] = state["held"]

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", return_value=True),
        patch("scansort.pipeline.ocr_backfill.ocr_pdf_inplace", side_effect=fake_ocr),
        patch("scansort.pipeline.ocr_backfill.interprocess_file_lock", fake_lock),
        patch("scansort.pipeline.ocr_backfill.AuditLogger") as audit_cls,
    ):
        audit_cls.return_value.log_scan.side_effect = fake_log_scan
        result = run_ocr_backfill(cfg, app_dir)

    assert state["free_during_ocr"] is True
    assert state["held_during_audit"] is True
    assert result.processed == [pdf.resolve()]
    assert pdf.read_bytes() == b"%PDF-1.4 scan plus text layer"


def test_backfill_routes_failure_when_ocr_raises(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    pdf = _write_pdf(cfg.documents_root / "bill.pdf")
    app_dir = tmp_path / "app"

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", return_value=True),
        patch(
            "scansort.pipeline.ocr_backfill.ocr_pdf_inplace",
            side_effect=OcrError("engine error"),
        ),
        patch("scansort.pipeline.ocr_backfill.notify_filing_failed") as notify,
    ):
        result = run_ocr_backfill(cfg, app_dir)

    assert result.failed == [pdf.resolve()]
    assert not pdf.exists()
    assert (cfg.documents_root / "_Review_Needed" / "bill.pdf").exists()
    notify.assert_called_once()


def test_backfill_dry_run_does_not_route_failures(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    pdf = _write_pdf(cfg.documents_root / "corrupt.pdf")
    app_dir = tmp_path / "app"

    with patch(
        "scansort.pipeline.ocr_backfill.needs_ocr",
        side_effect=OcrError("unreadable"),
    ):
        result = run_ocr_backfill(cfg, app_dir, dry_run=True)

    assert result.failed == [pdf.resolve()]
    assert pdf.exists(), "dry run must never move files"
    assert not (cfg.documents_root / "_Review_Needed" / "corrupt.pdf").exists()


def test_backfill_swallows_route_failure_oserror(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    _write_pdf(cfg.documents_root / "corrupt.pdf")
    app_dir = tmp_path / "app"

    with (
        patch(
            "scansort.pipeline.ocr_backfill.needs_ocr",
            side_effect=OcrError("unreadable"),
        ),
        patch(
            "scansort.pipeline.ocr_backfill.shutil.move",
            side_effect=OSError("disk full"),
        ),
    ):
        result = run_ocr_backfill(cfg, app_dir)

    assert result.failed  # recorded, but the walk did not crash


def test_backfill_failure_route_cleans_partial_destination(tmp_path: Path):
    """A mid-copy failure during routing must not leave a corrupt destination."""
    cfg = _make_cfg(tmp_path)
    pdf = _write_pdf(cfg.documents_root / "corrupt.pdf")
    app_dir = tmp_path / "app"

    def fake_move(src, dst):
        Path(dst).write_bytes(b"%PDF-1.4 partial copy")
        raise OSError("interrupted")

    with (
        patch(
            "scansort.pipeline.ocr_backfill.needs_ocr",
            side_effect=OcrError("unreadable"),
        ),
        patch("scansort.pipeline.ocr_backfill.shutil.move", side_effect=fake_move),
    ):
        result = run_ocr_backfill(cfg, app_dir)

    review_dir = cfg.documents_root / "_Review_Needed"
    assert list(review_dir.glob("*.pdf")) == []
    assert result.failed == [pdf.resolve()]


def test_backfill_walk_skips_symlink_escaping_documents_root(tmp_path: Path):
    """An in-root file symlink pointing outside must never be rewritten."""
    cfg = _make_cfg(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.pdf"
    secret.write_bytes(b"%PDF-1.4 secret")
    review_dir = cfg.documents_root / "_Review_Needed"
    review_dir.mkdir()
    (review_dir / "pending.pdf").symlink_to(secret)
    app_dir = tmp_path / "app"

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr") as fake_needs,
        patch("scansort.pipeline.ocr_backfill.ocr_pdf_inplace") as fake_ocr,
    ):
        result = run_ocr_backfill(cfg, app_dir)

    fake_needs.assert_not_called()
    fake_ocr.assert_not_called()
    assert secret.read_bytes() == b"%PDF-1.4 secret"
    assert result.processed == []
    assert result.candidates == []


def test_backfill_external_target_records_empty_relative_folder(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    external = _write_pdf(tmp_path / "elsewhere" / "bill.pdf")
    app_dir = tmp_path / "app"

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", return_value=True),
        patch(
            "scansort.pipeline.ocr_backfill.ocr_pdf_inplace",
            side_effect=_write_ocr_output_80,
        ),
    ):
        result = run_ocr_backfill(cfg, app_dir, targets=[external])

    assert result.processed == [external.resolve()]
    record = _read_history(app_dir)[-1]
    assert record["destination_folder"] == ""


def test_backfill_root_level_target_records_empty_relative_folder(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    pdf = _write_pdf(cfg.documents_root / "bill.pdf")
    app_dir = tmp_path / "app"

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", return_value=True),
        patch(
            "scansort.pipeline.ocr_backfill.ocr_pdf_inplace",
            side_effect=_write_ocr_output_80,
        ),
    ):
        result = run_ocr_backfill(cfg, app_dir, targets=[pdf])

    assert result.processed == [pdf.resolve()]
    record = _read_history(app_dir)[-1]
    assert record["destination_folder"] == ""


def test_backfill_continues_after_ocr_oserror(tmp_path: Path):
    """A per-file OSError must not abort the walk (invariant U)."""
    cfg = _make_cfg(tmp_path)
    bad = _write_pdf(cfg.documents_root / "a.pdf")
    good = _write_pdf(cfg.documents_root / "b.pdf")
    app_dir = tmp_path / "app"

    def fake_ocr(path, language="eng", output_path=None):
        if path.name == "a.pdf":
            raise OSError("disk full")
        target = output_path or path
        target.write_bytes(b"%PDF-1.4 scan plus text")
        return target, 77.0

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", return_value=True),
        patch("scansort.pipeline.ocr_backfill.ocr_pdf_inplace", side_effect=fake_ocr),
        patch("scansort.pipeline.ocr_backfill.notify_filing_failed"),
    ):
        result = run_ocr_backfill(cfg, app_dir)

    assert result.failed == [bad.resolve()]
    assert result.processed == [good.resolve()]
    assert not bad.exists()
    assert (cfg.documents_root / "_Review_Needed" / "a.pdf").exists()


def test_backfill_continues_after_needs_ocr_oserror(tmp_path: Path):
    """A transient stat failure on one candidate must not abort the walk."""
    cfg = _make_cfg(tmp_path)
    bad = _write_pdf(cfg.documents_root / "a.pdf")
    good = _write_pdf(cfg.documents_root / "b.pdf")
    app_dir = tmp_path / "app"

    def fake_needs(path, *args, **kwargs):
        if path == bad.resolve():
            raise OSError("transient lock")
        return True

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", side_effect=fake_needs),
        patch(
            "scansort.pipeline.ocr_backfill.ocr_pdf_inplace",
            side_effect=_write_ocr_output,
        ),
        patch("scansort.pipeline.ocr_backfill.notify_filing_failed"),
    ):
        result = run_ocr_backfill(cfg, app_dir)

    assert result.failed == [bad.resolve()]
    assert result.processed == [good.resolve()]


def test_backfill_does_not_audit_when_no_text_embedded(tmp_path: Path):
    """A PDF where tesseract finds no words is left unchanged, not audited."""
    cfg = _make_cfg(tmp_path)
    pdf = _write_pdf(cfg.documents_root / "blank.pdf")
    app_dir = tmp_path / "app"
    printed: list[str] = []

    with (
        patch("scansort.pipeline.ocr_backfill.needs_ocr", return_value=True),
        patch(
            "scansort.pipeline.ocr_backfill.ocr_pdf_inplace",
            return_value=(pdf.resolve(), None),
        ),
    ):
        result = run_ocr_backfill(cfg, app_dir, progress=printed.append)

    assert result.processed == []
    assert result.failed == []
    assert not (app_dir / "history.jsonl").exists()
    assert pdf.read_bytes() == b"%PDF-1.4 scan"
    assert any("No searchable text" in line for line in printed)

"""End-to-End integration tests for ScanSort pipeline."""

import io
import json
import queue
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import APIError
from PIL import Image

from scansort.config import AppConfig
from scansort.models import DocumentClassification
from scansort.pipeline import ScanSortPipeline


@pytest.fixture(autouse=True)
def _silence_real_toasts():
    """Never construct the real WinRT toast backend during pipeline tests."""
    with patch("scansort.notifications.show_toast", return_value=True):
        yield


def _create_sample_scan(path: Path):
    img = Image.new("RGB", (200, 200), color="white")
    img.save(path, format="JPEG")


def test_pipeline_e2e_successful_flow(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs_root = tmp_path / "Documents"
    (docs_root / "Utilities" / "Electricity").mkdir(parents=True)

    log_dir = tmp_path / "appdata"
    cfg = AppConfig(
        watch_folder=inbox,
        documents_root=docs_root,
        dry_run=False,
    )

    # Mock classifier
    mock_classifier = MagicMock()
    mock_classifier.classify_document.return_value = DocumentClassification(
        document_date="260901",
        description="Origin_Energy_Bill",
        target_folder="Utilities/Electricity",
        confidence=0.95,
        orientation_correction=90,
        document_type="Invoice",
        summary="Quarterly electricity bill",
    )

    pipeline = ScanSortPipeline(config=cfg, app_dir=log_dir, classifier=mock_classifier)

    # Drop scanned file
    scan_file = inbox / "scan001.jpg"
    _create_sample_scan(scan_file)

    dest_file = pipeline.process_file(scan_file)

    assert dest_file is not None
    assert dest_file.exists()
    assert dest_file.name == "260901_Origin_Energy_Bill.pdf"
    assert dest_file.parent == docs_root / "Utilities" / "Electricity"
    assert not scan_file.exists()

    # Verify audit log
    history_file = log_dir / "history.jsonl"
    assert history_file.exists()
    records = [
        json.loads(line)
        for line in history_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["status"] == "SUCCESS"
    assert records[0]["new_filename"] == "260901_Origin_Energy_Bill.pdf"


def test_pipeline_e2e_duplicate_detection(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs_root = tmp_path / "Documents"
    (docs_root / "Utilities").mkdir(parents=True)

    log_dir = tmp_path / "appdata"
    cfg = AppConfig(watch_folder=inbox, documents_root=docs_root)

    mock_classifier = MagicMock()
    mock_classifier.classify_document.return_value = DocumentClassification(
        document_date="260901",
        description="Electricity_Bill",
        target_folder="Utilities",
        confidence=0.95,
    )

    pipeline = ScanSortPipeline(config=cfg, app_dir=log_dir, classifier=mock_classifier)

    # Process first time
    scan1 = inbox / "scan001.jpg"
    _create_sample_scan(scan1)
    pipeline.process_file(scan1)

    # Process same content second time (simulating duplicate scan)
    scan2 = inbox / "scan002.jpg"
    _create_sample_scan(scan2)
    duplicate_dest = pipeline.process_file(scan2)

    assert duplicate_dest is not None
    assert "_Review_Needed/Duplicates" in str(duplicate_dest).replace("\\", "/")
    assert duplicate_dest.exists()

    # Verify second record logged as DUPLICATE
    history_file = log_dir / "history.jsonl"
    records = [
        json.loads(line)
        for line in history_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 2
    assert records[1]["status"] == "DUPLICATE"


def test_pipeline_e2e_dry_run_mode(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs_root = tmp_path / "Documents"
    (docs_root / "Taxes").mkdir(parents=True)

    log_dir = tmp_path / "appdata"
    cfg = AppConfig(
        watch_folder=inbox,
        documents_root=docs_root,
        dry_run=True,
    )

    mock_classifier = MagicMock()
    mock_classifier.classify_document.return_value = DocumentClassification(
        document_date="260901",
        description="ATO_Notice",
        target_folder="Taxes",
        confidence=0.98,
    )

    pipeline = ScanSortPipeline(config=cfg, app_dir=log_dir, classifier=mock_classifier)

    scan_file = inbox / "scan_tax.jpg"
    _create_sample_scan(scan_file)

    simulated_dest = pipeline.process_file(scan_file)
    assert simulated_dest is not None

    # In dry-run mode, source file should remain untouched!
    assert scan_file.exists()
    # And target file should NOT exist on disk
    assert not (docs_root / "Taxes" / "260901_ATO_Notice.pdf").exists()


def test_pipeline_missing_file_returns_none(tmp_path: Path):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    pipeline = ScanSortPipeline(config=cfg, app_dir=tmp_path / "appdata")
    assert pipeline.process_file(tmp_path / "missing.pdf") is None


def test_pipeline_unstable_file_returns_none(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    unstable_file = inbox / "unstable.pdf"
    unstable_file.touch()

    cfg = AppConfig(watch_folder=inbox, documents_root=tmp_path / "Docs")
    pipeline = ScanSortPipeline(config=cfg, app_dir=tmp_path / "appdata")

    with patch("scansort.pipeline.wait_for_file_stability", return_value=False):
        assert pipeline.process_file(unstable_file) is None


def test_pipeline_conversion_error_returns_none(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    corrupt_file = inbox / "corrupt.jpg"
    corrupt_file.write_bytes(b"bad data")

    cfg = AppConfig(watch_folder=inbox, documents_root=tmp_path / "Docs")
    pipeline = ScanSortPipeline(config=cfg, app_dir=tmp_path / "appdata")

    with patch(
        "scansort.pipeline.convert_to_pdf", side_effect=ValueError("Corrupted image")
    ):
        assert pipeline.process_file(corrupt_file) is None


def test_pipeline_run_worker_processes_queue(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs = tmp_path / "Docs"
    docs.mkdir()

    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    pipeline = ScanSortPipeline(config=cfg, app_dir=tmp_path / "appdata")

    file_queue = queue.Queue()
    stop_event = threading.Event()

    test_file = inbox / "item.pdf"
    test_file.write_bytes(b"%PDF-1.4 test")
    file_queue.put(test_file)

    with patch.object(pipeline, "process_file") as mock_process:
        worker_thread = threading.Thread(
            target=pipeline.run_worker, args=(file_queue, stop_event)
        )
        worker_thread.start()

        # Wait for item to be processed
        file_queue.join()
        stop_event.set()
        worker_thread.join(timeout=2.0)

        mock_process.assert_called_once_with(test_file)


def test_dry_run_leaves_pdf_unmodified(tmp_path: Path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 raw scan content")
    orig = pdf.read_bytes()

    cfg = AppConfig(
        watch_folder=tmp_path / "inbox",
        documents_root=tmp_path / "docs",
        dry_run=True,
    )
    p = ScanSortPipeline(config=cfg, app_dir=tmp_path / "app")
    p.classifier.classify_document = MagicMock(
        return_value=DocumentClassification(
            target_folder="Tax",
            orientation_correction=180,
            description="Doc",
            summary="Sum",
            document_type="Tax",
            document_date="260901",
        )
    )
    p.process_file(pdf)
    assert pdf.read_bytes() == orig


def test_worker_thread_survives_api_error(tmp_path: Path):
    cfg = AppConfig(watch_folder=tmp_path / "inbox", documents_root=tmp_path / "docs")
    pipeline = ScanSortPipeline(config=cfg, app_dir=tmp_path / "app")
    pipeline.process_file = MagicMock(
        side_effect=APIError(429, {"error": {"message": "Quota exceeded"}})
    )
    q = queue.Queue()
    stop_event = threading.Event()
    q.put(tmp_path / "inbox" / "scan.pdf")
    t = threading.Thread(target=pipeline.run_worker, args=(q, stop_event))
    t.start()
    q.join()
    assert t.is_alive(), "Worker thread died on APIError!"
    stop_event.set()
    t.join(timeout=1.0)


def test_intermediate_pdf_in_temp_dir(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    app_dir = tmp_path / "app"

    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    pipeline = ScanSortPipeline(config=cfg, app_dir=app_dir)

    img_file = inbox / "scan.jpg"
    _create_sample_scan(img_file)

    mock_classification = DocumentClassification(
        document_date="260901",
        description="Test",
        target_folder="_Review_Needed",
        confidence=0.9,
    )
    pipeline.classifier.classify_document = MagicMock(return_value=mock_classification)

    filed = pipeline.process_file(img_file)
    assert filed is not None
    # Verify no .pdf was left in the inbox directory
    assert list(inbox.glob("*.pdf")) == []


def test_native_pdf_staged_in_temp_and_cleaned_up_on_error(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    app_dir = tmp_path / "app"

    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    pipeline = ScanSortPipeline(config=cfg, app_dir=app_dir)

    pdf_file = inbox / "native_scan.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 sample content")

    # Simulate classifier failing
    pipeline.classifier.classify_document = MagicMock(
        side_effect=RuntimeError("OCR failure")
    )

    result = pipeline.process_file(pdf_file)
    assert result is None
    # Failed scans are routed to the review folder with a FAILED audit record.
    assert not pdf_file.exists()
    review_dir = docs / "_Review_Needed"
    assert (review_dir / "native_scan.pdf").exists()
    history_lines = pipeline.audit_logger.jsonl_path.read_text().splitlines()
    assert any("FAILED" in line for line in history_lines)
    # And tmp_dir must be cleaned up (no leaked temporary PDFs)
    assert list(pipeline.tmp_dir.glob("*.pdf")) == []


def test_dry_run_duplicate_does_not_mutate_disk_or_history(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    app_dir = tmp_path / "app"

    cfg = AppConfig(watch_folder=inbox, documents_root=docs, dry_run=True)
    pipeline = ScanSortPipeline(config=cfg, app_dir=app_dir)

    # Pre-record a scan in history
    h = "hash12345678"
    pipeline.audit_logger.log_scan(
        {
            "sha256": h,
            "status": "SUCCESS",
            "new_filename": "prior.pdf",
        }
    )
    initial_history_lines = len(
        pipeline.audit_logger.jsonl_path.read_text().splitlines()
    )

    scan_file = inbox / "dup.pdf"
    scan_file.write_bytes(b"%PDF-1.4 duplicate")

    with patch("scansort.pipeline.compute_file_sha256", return_value=h):
        dup_result = pipeline.process_file(scan_file)

    assert dup_result is not None
    # In dry run, file must NOT be moved
    assert scan_file.exists()
    # Duplicates directory must NOT be created on disk
    dup_dir = docs / "_Review_Needed" / "Duplicates"
    assert not dup_dir.exists()
    # History must NOT have a DUPLICATE record logged
    current_history_lines = len(
        pipeline.audit_logger.jsonl_path.read_text().splitlines()
    )
    assert current_history_lines == initial_history_lines


def test_duplicate_routing_blocks_path_traversal(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    app_dir = tmp_path / "app"

    cfg = AppConfig(
        watch_folder=inbox,
        documents_root=docs,
        dry_run=False,
    )
    object.__setattr__(cfg, "fallback_folder", "../../Escaped_Fallback")
    pipeline = ScanSortPipeline(config=cfg, app_dir=app_dir)

    h = "hash999"
    pipeline.audit_logger.log_scan(
        {"sha256": h, "status": "SUCCESS", "new_filename": "first.pdf"}
    )

    scan_file = inbox / "dup.pdf"
    scan_file.write_bytes(b"%PDF-1.4 duplicate")

    with patch("scansort.pipeline.compute_file_sha256", return_value=h):
        result = pipeline.process_file(scan_file)

    assert result is not None
    assert result.resolve().is_relative_to(docs.resolve())
    assert "_Review_Needed" in str(result)


def test_source_unlink_error_does_not_abort_audit_logging(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    app_dir = tmp_path / "app"

    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    pipeline = ScanSortPipeline(config=cfg, app_dir=app_dir)

    scan_file = inbox / "scan.jpg"
    _create_sample_scan(scan_file)

    pipeline.classifier.classify_document = MagicMock(
        return_value=DocumentClassification(
            document_date="260901",
            description="Doc",
            target_folder="_Review_Needed",
            confidence=0.9,
        )
    )

    # Mock Path.unlink to raise OSError when unlinking the source scan_file
    orig_unlink = Path.unlink

    def mock_unlink(self, *args, **kwargs):
        if self.name == scan_file.name:
            raise OSError("File locked by scanner driver")
        return orig_unlink(self, *args, **kwargs)

    with patch.object(Path, "unlink", mock_unlink):
        dest = pipeline.process_file(scan_file)

    assert dest is not None
    assert dest.exists()
    # Audit log must still be recorded despite unlink error
    history_lines = pipeline.audit_logger.jsonl_path.read_text().splitlines()
    assert any("SUCCESS" in line for line in history_lines)


def test_process_file_waits_for_bursty_writer_to_finish(tmp_path: Path):
    """A writer pausing between bursts must not be dispatched mid-write."""
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs_root = tmp_path / "Documents"
    (docs_root / "Utilities").mkdir(parents=True)
    log_dir = tmp_path / "appdata"

    cfg = AppConfig(watch_folder=inbox, documents_root=docs_root)
    pipeline = ScanSortPipeline(config=cfg, app_dir=log_dir)
    pipeline.classifier.classify_document = MagicMock(
        return_value=DocumentClassification(
            document_date="260901",
            description="Bursty_Bill",
            target_folder="Utilities",
            confidence=0.95,
        )
    )

    scan_file = inbox / "bursty.jpg"
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color="white").save(buf, format="JPEG")
    data = buf.getvalue()
    chunk1_written = threading.Event()
    writer_done = threading.Event()

    def bursty_writer() -> None:
        with open(scan_file, "wb") as f:
            f.write(data[: len(data) // 2])
            f.flush()
            chunk1_written.set()
            time.sleep(0.6)
            f.write(data[len(data) // 2 :])
        writer_done.set()

    writer = threading.Thread(target=bursty_writer, daemon=True)
    writer.start()
    assert chunk1_written.wait(timeout=2.0)

    dest = pipeline.process_file(scan_file)

    assert writer_done.is_set(), "process_file dispatched before the writer finished"
    assert dest is not None
    assert dest.exists()
    assert not scan_file.exists()


def test_process_file_defers_when_source_changes_during_processing(tmp_path: Path):
    """A source that keeps growing after staging must not be filed."""
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs_root = tmp_path / "Documents"
    (docs_root / "Utilities").mkdir(parents=True)
    log_dir = tmp_path / "appdata"

    cfg = AppConfig(watch_folder=inbox, documents_root=docs_root)
    pipeline = ScanSortPipeline(config=cfg, app_dir=log_dir)

    scan_file = inbox / "late_writer.jpg"
    _create_sample_scan(scan_file)
    original_bytes = scan_file.read_bytes()

    def late_writing_classify(staging_pdf: Path):
        with open(scan_file, "ab") as f:
            f.write(b"tail-bytes")
        return DocumentClassification(
            document_date="260901",
            description="Late_Writer",
            target_folder="Utilities",
            confidence=0.95,
        )

    pipeline._classify_scan = late_writing_classify  # type: ignore[method-assign]

    dest = pipeline.process_file(scan_file)

    assert dest is None
    assert scan_file.read_bytes() == original_bytes + b"tail-bytes"
    assert not (docs_root / "Utilities" / "260901_Late_Writer.pdf").exists()
    assert not (log_dir / "history.jsonl").exists()


def test_process_file_routes_decompression_bomb_to_review(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    app_dir = tmp_path / "app"

    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    pipeline = ScanSortPipeline(config=cfg, app_dir=app_dir)

    scan_file = inbox / "giant.jpg"
    _create_sample_scan(scan_file)

    with patch("PIL.Image.MAX_IMAGE_PIXELS", 10):
        result = pipeline.process_file(scan_file)

    assert result is None
    assert not scan_file.exists()
    assert (docs / "_Review_Needed" / "giant.jpg").exists()
    history_lines = pipeline.audit_logger.jsonl_path.read_text().splitlines()
    assert any("FAILED" in line for line in history_lines)


def test_process_file_routes_corrupt_pdf_to_review(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    app_dir = tmp_path / "app"

    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    pipeline = ScanSortPipeline(config=cfg, app_dir=app_dir)
    pipeline.classifier.classify_document = MagicMock(
        return_value=DocumentClassification(
            document_date="260901",
            description="Corrupt",
            target_folder="Utilities",
            confidence=0.95,
        )
    )

    scan_file = inbox / "broken.pdf"
    scan_file.write_bytes(b"%PDF-1.4 broken")

    result = pipeline.process_file(scan_file)

    assert result is None
    assert not scan_file.exists()
    assert (docs / "_Review_Needed" / "broken.pdf").exists()
    history_lines = pipeline.audit_logger.jsonl_path.read_text().splitlines()
    assert any("FAILED" in line for line in history_lines)


def test_process_file_handles_hash_error_and_routes_to_review(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    app_dir = tmp_path / "app"

    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    pipeline = ScanSortPipeline(config=cfg, app_dir=app_dir)

    scan_file = inbox / "scan.pdf"
    scan_file.write_bytes(b"%PDF-1.4 data")

    with patch(
        "scansort.pipeline.compute_file_sha256", side_effect=OSError("I/O error")
    ):
        result = pipeline.process_file(scan_file)

    assert result is None
    assert not scan_file.exists()
    assert (docs / "_Review_Needed" / "scan.pdf").exists()
    history_lines = pipeline.audit_logger.jsonl_path.read_text().splitlines()
    assert any("FAILED" in line for line in history_lines)


def test_run_worker_drains_queue_after_stop(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()

    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    pipeline = ScanSortPipeline(config=cfg, app_dir=tmp_path / "appdata")

    file_queue = queue.Queue()
    stop_event = threading.Event()
    for i in range(3):
        item = inbox / f"item{i}.pdf"
        item.write_bytes(b"%PDF-1.4 test")
        file_queue.put(item)

    with patch.object(pipeline, "process_file") as mock_process:
        worker_thread = threading.Thread(
            target=pipeline.run_worker, args=(file_queue, stop_event)
        )
        worker_thread.start()
        stop_event.wait(0.2)
        stop_event.set()
        worker_thread.join(timeout=5.0)

    assert not worker_thread.is_alive()
    assert mock_process.call_count == 3
    assert file_queue.empty()


def test_pipeline_filed_toast_fired_with_destination(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs_root = tmp_path / "Documents"
    (docs_root / "Utilities" / "Electricity").mkdir(parents=True)

    mock_classifier = MagicMock()
    mock_classifier.classify_document.return_value = DocumentClassification(
        document_date="260901",
        description="Origin_Energy_Bill",
        target_folder="Utilities/Electricity",
        confidence=0.95,
        orientation_correction=0,
        document_type="Invoice",
        summary="Quarterly electricity bill",
    )
    pipeline = ScanSortPipeline(
        config=AppConfig(watch_folder=inbox, documents_root=docs_root),
        app_dir=tmp_path / "appdata",
        classifier=mock_classifier,
    )
    scan_file = inbox / "scan001.jpg"
    _create_sample_scan(scan_file)

    with patch("scansort.pipeline.notify_file_filed") as mock_notify:
        dest = pipeline.process_file(scan_file)
    assert dest is not None
    mock_notify.assert_called_once_with(
        "260901_Origin_Energy_Bill.pdf",
        "Utilities/Electricity",
        folder_path=dest.parent,
    )


def test_pipeline_failure_toast_when_routed_to_review(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs_root = tmp_path / "Documents"
    mock_classifier = MagicMock()
    mock_classifier.classify_document.side_effect = RuntimeError("rate limited 429")
    pipeline = ScanSortPipeline(
        config=AppConfig(watch_folder=inbox, documents_root=docs_root),
        app_dir=tmp_path / "appdata",
        classifier=mock_classifier,
    )
    scan_file = inbox / "scan001.jpg"
    _create_sample_scan(scan_file)

    with patch("scansort.pipeline.notify_filing_failed") as mock_notify:
        result = pipeline.process_file(scan_file)
    assert result is None
    assert not scan_file.exists()
    assert (docs_root / "_Review_Needed" / "scan001.jpg").exists()
    mock_notify.assert_called_once_with(
        "scan001.jpg",
        "_Review_Needed",
        "rate limited 429",
        folder_path=docs_root / "_Review_Needed",
        log_path=pipeline.app_dir / "scansort.log",
    )


def test_pipeline_stranded_toast_when_review_routing_fails(tmp_path: Path, monkeypatch):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs_root = tmp_path / "Documents"
    mock_classifier = MagicMock()
    mock_classifier.classify_document.side_effect = RuntimeError("boom")
    pipeline = ScanSortPipeline(
        config=AppConfig(watch_folder=inbox, documents_root=docs_root),
        app_dir=tmp_path / "appdata",
        classifier=mock_classifier,
    )
    scan_file = inbox / "scan001.jpg"
    _create_sample_scan(scan_file)

    monkeypatch.setattr(
        "scansort.pipeline.shutil.move",
        MagicMock(side_effect=OSError("file locked")),
    )
    with patch("scansort.pipeline.notify_scan_stranded") as mock_notify:
        result = pipeline.process_file(scan_file)
    assert result is None
    assert scan_file.exists()
    mock_notify.assert_called_once_with(
        "scan001.jpg",
        "_Review_Needed",
        folder_path=inbox,
        log_path=pipeline.app_dir / "scansort.log",
    )

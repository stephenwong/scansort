"""End-to-End integration tests for ScanSort pipeline."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from scansort.config import AppConfig
from scansort.gemini_client import DocumentClassification
from scansort.pipeline import ScanSortPipeline


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


import queue
import threading
import time
from unittest.mock import patch


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
        time.sleep(0.1)
        stop_event.set()
        worker_thread.join(timeout=1.0)

        mock_process.assert_called_once_with(test_file)


def test_dry_run_leaves_pdf_unmodified(tmp_path: Path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 raw scan content")
    orig = pdf.read_bytes()

    cfg = AppConfig(
        watch_folder=tmp_path, documents_root=tmp_path / "docs", dry_run=True
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
    from google.genai.errors import APIError

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
    # Source PDF should remain in inbox on failure
    assert pdf_file.exists()
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

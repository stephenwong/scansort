"""End-to-End integration tests for ScanSort pipeline (TDD Cycle 11)."""

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
    records = [json.loads(line) for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]
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
    records = [json.loads(line) for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]
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

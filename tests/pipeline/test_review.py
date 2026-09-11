"""Unit tests for scansort.pipeline.review module."""

import json
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from scansort.core.config import AppConfig
from scansort.core.constants import (
    HISTORY_CSV_NAME,
    HISTORY_JSONL_NAME,
)
from scansort.pipeline.review import (
    ReviewItem,
    dismiss_review_item,
    file_reviewed_item,
    get_review_queue,
)


def _create_dummy_pdf(path: Path, title: str = "Test") -> Path:
    """Create a minimal 1-page valid PDF on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": title})
    with open(path, "wb") as f:
        writer.write(f)
    return path


def test_review_item_dataclass(tmp_path: Path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    item = ReviewItem(
        file_path=p,
        filename="doc.pdf",
        file_size_bytes=p.stat().st_size,
        modified_time=p.stat().st_mtime,
        summary="A summary",
        confidence=0.65,
        suggested_folder="Health/Dental",
    )
    assert item.filename == "doc.pdf"
    assert item.suggested_folder == "Health/Dental"
    assert item.confidence == 0.65


def test_get_review_queue_empty(tmp_path: Path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    items = get_review_queue(docs_root=docs, fallback_folder="_Review_Needed")
    assert items == []


def test_get_review_queue_with_history_correlation(tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    pdf_path = _create_dummy_pdf(review_dir / "260815_Dental_Checkup.pdf")

    # Create history.jsonl
    history_file = tmp_path / HISTORY_JSONL_NAME
    record = {
        "timestamp": "2026-08-15T10:00:00Z",
        "sha256": "abc123hash",
        "original_filename": "scan_001.pdf",
        "new_filename": "260815_Dental_Checkup.pdf",
        "destination_folder": "_Review_Needed",
        "destination_path": str(pdf_path),
        "summary": "Checkup receipt from Drummoyne Dental",
        "document_type": "Receipt",
        "confidence": 0.62,
        "suggested_folder": "Health/Dental",
        "folder_reasoning": "Receipt matches dental service but no folder exists",
        "routing_rationale": "Confidence 0.62 below 0.70 threshold (suggested 'Health/Dental') -> routed to _Review_Needed.",
        "status": "SUCCESS",
    }
    history_file.write_text(json.dumps(record) + "\n", encoding="utf-8")

    items = get_review_queue(
        docs_root=docs,
        fallback_folder="_Review_Needed",
        history_path=history_file,
    )

    assert len(items) == 1
    item = items[0]
    assert item.filename == "260815_Dental_Checkup.pdf"
    assert item.summary == "Checkup receipt from Drummoyne Dental"
    assert item.confidence == 0.62
    assert item.suggested_folder == "Health/Dental"
    assert item.document_type == "Receipt"
    assert (
        item.folder_reasoning == "Receipt matches dental service but no folder exists"
    )
    assert item.document_date == "260815"
    assert item.description == "Dental_Checkup"


def test_get_review_queue_falls_back_to_regex_from_routing_rationale(tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    pdf_path = _create_dummy_pdf(review_dir / "260820_Electricity_Bill.pdf")

    history_file = tmp_path / HISTORY_JSONL_NAME
    # Legacy record lacking explicit suggested_folder field
    record = {
        "destination_path": str(pdf_path),
        "summary": "Electricity bill",
        "routing_rationale": "Confidence 0.55 below 0.70 threshold (suggested 'Utilities/Electricity') -> routed to _Review_Needed.",
        "status": "SUCCESS",
    }
    history_file.write_text(json.dumps(record) + "\n", encoding="utf-8")

    items = get_review_queue(
        docs_root=docs,
        fallback_folder="_Review_Needed",
        history_path=history_file,
    )
    assert len(items) == 1
    assert items[0].suggested_folder == "Utilities/Electricity"


def test_get_review_queue_excludes_duplicates_and_includes_subfolders(tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    dup_dir = review_dir / "Duplicates"
    sub_dir = review_dir / "CustomSub"
    dup_dir.mkdir(parents=True)
    sub_dir.mkdir(parents=True)

    _create_dummy_pdf(dup_dir / "scan_dup.pdf")
    _create_dummy_pdf(sub_dir / "sub_scan.pdf")
    _create_dummy_pdf(review_dir / "untracked_scan.pdf")

    items = get_review_queue(docs_root=docs, fallback_folder="_Review_Needed")
    assert len(items) == 2
    filenames = {i.filename for i in items}
    assert "scan_dup.pdf" not in filenames
    assert "sub_scan.pdf" in filenames
    assert "untracked_scan.pdf" in filenames


def test_file_reviewed_item_success(tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    source_pdf = _create_dummy_pdf(review_dir / "temp_scan.pdf")

    app_dir = tmp_path / "app_data"
    app_dir.mkdir(parents=True)
    hints_file = app_dir / "folder_hints.json"
    history_jsonl = app_dir / HISTORY_JSONL_NAME
    history_csv = app_dir / HISTORY_CSV_NAME
    lock_file = app_dir / "operations.lock"

    cfg = AppConfig(
        documents_root=docs,
        fallback_folder="_Review_Needed",
    )

    item = ReviewItem(
        file_path=source_pdf,
        filename=source_pdf.name,
        file_size_bytes=source_pdf.stat().st_size,
        modified_time=source_pdf.stat().st_mtime,
        sha256="abc123sha",
        summary="Dental consult invoice",
        document_type="Invoice",
    )

    dest = file_reviewed_item(
        item=item,
        target_folder="Health/Dental",
        document_date="260815",
        description="Drummoyne_Dental_Clinic",
        keyword_hint="drummoyne dental",
        config=cfg,
        hints_path=hints_file,
        history_jsonl=history_jsonl,
        history_csv=history_csv,
        lock_path=lock_file,
    )

    assert dest.exists()
    assert dest.parent == docs / "Health" / "Dental"
    assert dest.name == "260815_Drummoyne_Dental_Clinic.pdf"
    assert not source_pdf.exists()  # Moved out of review folder

    # Check PDF metadata was updated
    reader = PdfReader(str(dest))
    assert reader.metadata.get("/Title") == "Drummoyne_Dental_Clinic"
    assert reader.metadata.get("/Subject") == "Dental consult invoice"

    # Check hint was persisted
    hints_content = json.loads(hints_file.read_text(encoding="utf-8-sig"))
    assert "Health/Dental" in hints_content
    assert "drummoyne dental" in hints_content["Health/Dental"]

    # Check audit log was written with REVIEWED status
    lines = history_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["status"] == "REVIEWED"
    assert entry["destination_folder"] == "Health/Dental"
    assert entry["new_filename"] == "260815_Drummoyne_Dental_Clinic.pdf"


def test_file_reviewed_item_collision_resolution(tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    dest_dir = docs / "Utilities"
    dest_dir.mkdir(parents=True)
    # Pre-existing file
    _create_dummy_pdf(dest_dir / "260901_Power_Bill.pdf")

    source_pdf = _create_dummy_pdf(review_dir / "incoming.pdf")
    app_dir = tmp_path / "app_data"
    cfg = AppConfig(documents_root=docs)

    item = ReviewItem(
        file_path=source_pdf,
        filename=source_pdf.name,
        file_size_bytes=source_pdf.stat().st_size,
        modified_time=source_pdf.stat().st_mtime,
    )

    dest = file_reviewed_item(
        item=item,
        target_folder="Utilities",
        document_date="260901",
        description="Power_Bill",
        keyword_hint=None,
        config=cfg,
        hints_path=app_dir / "folder_hints.json",
        history_jsonl=app_dir / HISTORY_JSONL_NAME,
        history_csv=app_dir / HISTORY_CSV_NAME,
        lock_path=app_dir / "operations.lock",
    )

    # Must resolve collision to _1.pdf
    assert dest.name == "260901_Power_Bill_1.pdf"
    assert dest.exists()


def test_file_reviewed_item_rejects_path_traversal(tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    source_pdf = _create_dummy_pdf(review_dir / "scan.pdf")
    cfg = AppConfig(documents_root=docs)
    app_dir = tmp_path / "app_data"

    item = ReviewItem(
        file_path=source_pdf,
        filename=source_pdf.name,
        file_size_bytes=source_pdf.stat().st_size,
        modified_time=source_pdf.stat().st_mtime,
    )

    with pytest.raises(ValueError, match="Unsafe destination folder"):
        file_reviewed_item(
            item=item,
            target_folder="../Escaped",
            document_date="260901",
            description="Doc",
            config=cfg,
            hints_path=app_dir / "folder_hints.json",
            history_jsonl=app_dir / HISTORY_JSONL_NAME,
            history_csv=app_dir / HISTORY_CSV_NAME,
            lock_path=app_dir / "operations.lock",
        )


def test_dismiss_review_item(tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    source_pdf = _create_dummy_pdf(review_dir / "blank_scan.pdf")
    app_dir = tmp_path / "app_data"
    history_jsonl = app_dir / HISTORY_JSONL_NAME
    history_csv = app_dir / HISTORY_CSV_NAME
    lock_file = app_dir / "operations.lock"

    item = ReviewItem(
        file_path=source_pdf,
        filename=source_pdf.name,
        file_size_bytes=source_pdf.stat().st_size,
        modified_time=source_pdf.stat().st_mtime,
        sha256="blankhash",
        summary="Empty page",
    )

    dismiss_review_item(
        item=item,
        history_jsonl=history_jsonl,
        history_csv=history_csv,
        lock_path=lock_file,
    )

    assert not source_pdf.exists()
    lines = history_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "DISMISSED"


def test_file_reviewed_item_missing_source_raises(tmp_path: Path):
    docs = tmp_path / "Documents"
    cfg = AppConfig(documents_root=docs)
    app_dir = tmp_path / "app_data"

    item = ReviewItem(
        file_path=docs / "_Review_Needed" / "missing.pdf",
        filename="missing.pdf",
        file_size_bytes=0,
        modified_time=0.0,
    )

    with pytest.raises(FileNotFoundError):
        file_reviewed_item(
            item=item,
            target_folder="Health",
            document_date="260901",
            description="Doc",
            config=cfg,
            hints_path=app_dir / "folder_hints.json",
            history_jsonl=app_dir / HISTORY_JSONL_NAME,
            history_csv=app_dir / HISTORY_CSV_NAME,
            lock_path=app_dir / "operations.lock",
        )


def test_dismiss_review_item_already_missing(tmp_path: Path):
    app_dir = tmp_path / "app_data"
    history_jsonl = app_dir / HISTORY_JSONL_NAME
    history_csv = app_dir / HISTORY_CSV_NAME
    lock_file = app_dir / "operations.lock"

    item = ReviewItem(
        file_path=app_dir / "nonexistent.pdf",
        filename="nonexistent.pdf",
        file_size_bytes=0,
        modified_time=0.0,
    )
    # Should not raise
    dismiss_review_item(
        item=item,
        history_jsonl=history_jsonl,
        history_csv=history_csv,
        lock_path=lock_file,
    )
    assert history_jsonl.exists()


def test_get_review_queue_handles_malformed_history(tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    pdf = _create_dummy_pdf(review_dir / "scan1.pdf")

    history_file = tmp_path / HISTORY_JSONL_NAME
    history_file.write_text(
        "\n{invalid json\n"
        + json.dumps({"destination_path": str(pdf), "confidence": "bad_float"})
        + "\n",
        encoding="utf-8",
    )

    items = get_review_queue(
        docs_root=docs, fallback_folder="_Review_Needed", history_path=history_file
    )
    assert len(items) == 1
    assert items[0].confidence == 0.0


def test_extract_suggested_from_rationale_edge_cases():
    from scansort.pipeline.review import (
        _extract_date_and_desc,
        _extract_suggested_from_rationale,
    )

    assert _extract_suggested_from_rationale("") == ""
    assert _extract_suggested_from_rationale("No suggested folder here") == ""
    assert _extract_suggested_from_rationale("suggested '../escape'") == ""
    assert (
        _extract_suggested_from_rationale("suggested 'Utilities/Electricity'")
        == "Utilities/Electricity"
    )

    d, desc = _extract_date_and_desc("scan_001.pdf")
    assert desc == "Scan_001"


def test_get_review_queue_handles_errors(tmp_path: Path, monkeypatch):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    _create_dummy_pdf(review_dir / "scan.pdf")

    # Simulate rglob OSError
    def _mock_rglob(self, pattern):
        raise OSError("Access denied")

    monkeypatch.setattr(Path, "rglob", _mock_rglob)
    items = get_review_queue(docs_root=docs, fallback_folder="_Review_Needed")
    assert items == []


def test_file_reviewed_item_metadata_failure_swallowed(tmp_path: Path, monkeypatch):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    source_pdf = _create_dummy_pdf(review_dir / "doc.pdf")
    app_dir = tmp_path / "app_data"
    cfg = AppConfig(documents_root=docs)

    item = ReviewItem(
        file_path=source_pdf,
        filename=source_pdf.name,
        file_size_bytes=source_pdf.stat().st_size,
        modified_time=source_pdf.stat().st_mtime,
    )

    def _fail_metadata(**kwargs):
        raise ValueError("Corrupt PDF structure")

    monkeypatch.setattr(
        "scansort.pipeline.review.process_pdf_metadata_and_rotation", _fail_metadata
    )

    dest = file_reviewed_item(
        item=item,
        target_folder="Health",
        document_date="260901",
        description="Doc",
        config=cfg,
        hints_path=app_dir / "folder_hints.json",
        history_jsonl=app_dir / HISTORY_JSONL_NAME,
        history_csv=app_dir / HISTORY_CSV_NAME,
        lock_path=app_dir / "operations.lock",
    )
    assert dest.exists()


def test_file_reviewed_item_destination_escapes_docs_root(tmp_path: Path, monkeypatch):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    review_dir.mkdir(parents=True)
    source_pdf = _create_dummy_pdf(review_dir / "doc.pdf")
    app_dir = tmp_path / "app_data"
    cfg = AppConfig(documents_root=docs)

    item = ReviewItem(
        file_path=source_pdf,
        filename=source_pdf.name,
        file_size_bytes=source_pdf.stat().st_size,
        modified_time=source_pdf.stat().st_mtime,
    )

    # Mock resolve_destination_dir to return path outside docs
    monkeypatch.setattr(
        "scansort.pipeline.review.resolve_destination_dir",
        lambda docs_root, folder: tmp_path / "outside",
    )

    with pytest.raises(ValueError, match="escapes documents root"):
        file_reviewed_item(
            item=item,
            target_folder="Health",
            document_date="260901",
            description="Doc",
            config=cfg,
            hints_path=app_dir / "folder_hints.json",
            history_jsonl=app_dir / HISTORY_JSONL_NAME,
            history_csv=app_dir / HISTORY_CSV_NAME,
            lock_path=app_dir / "operations.lock",
        )

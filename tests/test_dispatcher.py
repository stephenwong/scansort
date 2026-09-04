"""Unit tests for scansort.dispatcher and audit_logger modules."""

import csv
import json
from pathlib import Path

from scansort.audit_logger import AuditLogger
from scansort.dispatcher import (
    dispatch_file,
    generate_target_filename,
    resolve_collision,
    undo_last_move,
)
from scansort.gemini_client import DocumentClassification


def test_generate_target_filename():
    meta = DocumentClassification(
        document_date="260901",
        description="Origin_Energy_Bill",
        target_folder="Utilities",
    )
    assert generate_target_filename(meta) == "260901_Origin_Energy_Bill.pdf"


def test_resolve_collision(tmp_path: Path):
    dest_folder = tmp_path / "Docs"
    dest_folder.mkdir()

    # Initial file
    file1 = dest_folder / "260901_Bill.pdf"
    file1.touch()

    resolved = resolve_collision(dest_folder, "260901_Bill.pdf")
    assert resolved == dest_folder / "260901_Bill_1.pdf"

    # Second file collision
    (dest_folder / "260901_Bill_1.pdf").touch()
    resolved2 = resolve_collision(dest_folder, "260901_Bill.pdf")
    assert resolved2 == dest_folder / "260901_Bill_2.pdf"


def test_dispatch_file_atomic_move(tmp_path: Path):
    source_dir = tmp_path / "Inbox"
    source_dir.mkdir()
    docs_root = tmp_path / "Documents"
    docs_root.mkdir()

    source_file = source_dir / "scan001.pdf"
    source_file.write_bytes(b"%PDF-1.4 test data")

    meta = DocumentClassification(
        document_date="260901",
        description="Origin_Energy_Bill",
        target_folder="Utilities/Electricity",
        confidence=0.95,
        summary="Electricity bill",
    )

    final_path = dispatch_file(
        source_path=source_file,
        docs_root=docs_root,
        classification=meta,
    )

    assert not source_file.exists()
    assert final_path.exists()
    assert (
        final_path
        == docs_root / "Utilities" / "Electricity" / "260901_Origin_Energy_Bill.pdf"
    )
    assert final_path.read_bytes() == b"%PDF-1.4 test data"


def test_audit_logger_records_jsonl_and_csv(tmp_path: Path):
    log_dir = tmp_path / "logs"
    jsonl_path = log_dir / "history.jsonl"
    csv_path = log_dir / "history.csv"
    mirror_csv = tmp_path / "Documents" / "_ScanSort_History.csv"

    logger = AuditLogger(
        jsonl_path=jsonl_path, csv_path=csv_path, mirror_csv_path=mirror_csv
    )

    entry = {
        "sha256": "abc1234567890",
        "original_filename": "scan001.pdf",
        "original_path": "/inbox/scan001.pdf",
        "new_filename": "260901_Origin_Energy_Bill.pdf",
        "destination_folder": "Utilities/Electricity",
        "destination_path": "/docs/Utilities/Electricity/260901_Origin_Energy_Bill.pdf",
        "summary": "Electricity bill",
        "status": "SUCCESS",
    }

    logger.log_scan(entry)

    assert jsonl_path.exists()
    assert csv_path.exists()
    assert mirror_csv.exists()

    # Verify JSONL
    line = jsonl_path.read_text(encoding="utf-8").strip()
    data = json.loads(line)
    assert data["sha256"] == "abc1234567890"
    assert data["new_filename"] == "260901_Origin_Energy_Bill.pdf"
    assert "timestamp" in data

    # Verify CSV
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["New Filename"] == "260901_Origin_Energy_Bill.pdf"
        assert rows[0]["Folder"] == "Utilities/Electricity"


def test_undo_last_move(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs = tmp_path / "Documents" / "Utilities"
    docs.mkdir(parents=True)

    moved_file = docs / "260901_Origin_Energy_Bill.pdf"
    moved_file.write_bytes(b"content")

    jsonl_path = tmp_path / "history.jsonl"
    original_inbox_file = inbox / "scan001.pdf"

    entry = {
        "timestamp": "2026-09-03T10:00:00Z",
        "sha256": "hash123",
        "original_filename": "scan001.pdf",
        "original_path": str(original_inbox_file),
        "new_filename": "260901_Origin_Energy_Bill.pdf",
        "destination_folder": "Utilities",
        "destination_path": str(moved_file),
        "summary": "Bill",
        "status": "SUCCESS",
    }
    jsonl_path.write_text(f"{json.dumps(entry)}\n", encoding="utf-8")

    undone_path = undo_last_move(jsonl_path)
    assert undone_path == original_inbox_file
    assert original_inbox_file.exists()
    assert not moved_file.exists()

    # Check status was updated
    last_line = jsonl_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert json.loads(last_line)["status"] == "UNDONE"


from unittest.mock import patch


def test_undo_nonexistent_history_file(tmp_path: Path):
    missing_file = tmp_path / "does_not_exist.jsonl"
    assert undo_last_move(missing_file) is None


def test_undo_empty_history_file(tmp_path: Path):
    empty_file = tmp_path / "empty.jsonl"
    empty_file.touch()
    assert undo_last_move(empty_file) is None


def test_undo_no_reversible_records(tmp_path: Path):
    no_rev_file = tmp_path / "no_rev.jsonl"
    no_rev_file.write_text('{"status": "DUPLICATE"}\n{invalid json\n', encoding="utf-8")
    assert undo_last_move(no_rev_file) is None


def test_undo_destination_file_missing(tmp_path: Path):
    hist_file = tmp_path / "hist.jsonl"
    entry = {
        "status": "SUCCESS",
        "destination_path": str(tmp_path / "ghost.pdf"),
        "original_path": str(tmp_path / "orig.pdf"),
    }
    hist_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    assert undo_last_move(hist_file) is None


def test_audit_logger_os_error_handling(tmp_path: Path):
    log_dir = tmp_path / "logs"
    logger = AuditLogger(jsonl_path=log_dir / "h.jsonl", csv_path=log_dir / "h.csv")
    with patch("builtins.open", side_effect=OSError("Disk full")):
        # Should not raise exception
        logger.log_scan({"status": "SUCCESS"})


def test_dispatch_blocks_path_traversal(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    docs_root.mkdir()
    src = tmp_path / "scan.pdf"
    src.write_bytes(b"%PDF-1.4")
    meta = DocumentClassification(
        document_date="260901",
        description="Escape",
        target_folder="_Review_Needed/../../Escaped",
    )
    dest = dispatch_file(src, docs_root, meta)
    assert dest.resolve().is_relative_to(docs_root.resolve())
    assert "_Review_Needed" in str(dest)


def test_undo_does_not_clobber_existing_file(tmp_path: Path):
    history_file = tmp_path / "history.jsonl"
    filed_pdf = tmp_path / "docs" / "260901_Bill.pdf"
    filed_pdf.parent.mkdir(parents=True)
    filed_pdf.write_bytes(b"OLD FILED BILL")
    drop_file = tmp_path / "inbox" / "scan.pdf"
    drop_file.parent.mkdir(parents=True)
    drop_file.write_bytes(b"NEW ARRIVING SCAN")
    record = {
        "status": "SUCCESS",
        "destination_path": str(filed_pdf),
        "original_path": str(drop_file),
        "new_filename": "260901_Bill.pdf",
    }
    history_file.write_text(json.dumps(record) + "\n")
    restored = undo_last_move(history_file)
    assert drop_file.read_bytes() == b"NEW ARRIVING SCAN"
    assert restored != drop_file
    assert restored.read_bytes() == b"OLD FILED BILL"


def test_undo_preserves_pdf_extension_for_converted_images(tmp_path: Path):
    history_file = tmp_path / "history.jsonl"
    dest_pdf = tmp_path / "docs" / "filed.pdf"
    dest_pdf.parent.mkdir(parents=True)
    dest_pdf.write_bytes(b"%PDF-1.4")
    orig_jpg = tmp_path / "inbox" / "scan.jpg"
    record = {
        "status": "SUCCESS",
        "destination_path": str(dest_pdf),
        "original_path": str(orig_jpg),
    }
    history_file.write_text(json.dumps(record) + "\n")
    restored = undo_last_move(history_file)
    assert restored.suffix == ".pdf"


def test_undo_multiple_moves(tmp_path: Path):
    hist = tmp_path / "history.jsonl"
    f1 = tmp_path / "d1.pdf"
    f1.touch()
    f2 = tmp_path / "d2.pdf"
    f2.touch()
    r1 = {
        "status": "SUCCESS",
        "destination_path": str(f1),
        "original_path": str(tmp_path / "o1.pdf"),
    }
    r2 = {
        "status": "SUCCESS",
        "destination_path": str(f2),
        "original_path": str(tmp_path / "o2.pdf"),
    }
    hist.write_text(f"{json.dumps(r1)}\n{json.dumps(r2)}\n")
    assert undo_last_move(hist) is not None
    assert undo_last_move(hist) is not None
    assert undo_last_move(hist) is None

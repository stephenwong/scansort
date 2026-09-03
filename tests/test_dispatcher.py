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
    assert final_path == docs_root / "Utilities" / "Electricity" / "260901_Origin_Energy_Bill.pdf"
    assert final_path.read_bytes() == b"%PDF-1.4 test data"


def test_audit_logger_records_jsonl_and_csv(tmp_path: Path):
    log_dir = tmp_path / "logs"
    jsonl_path = log_dir / "history.jsonl"
    csv_path = log_dir / "history.csv"
    mirror_csv = tmp_path / "Documents" / "_ScanSort_History.csv"

    logger = AuditLogger(jsonl_path=jsonl_path, csv_path=csv_path, mirror_csv_path=mirror_csv)

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

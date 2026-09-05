"""Unit tests for scansort.audit_logger module."""

import csv
import json
from pathlib import Path
from unittest.mock import patch

from scansort.audit_logger import AuditLogger


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


def test_audit_logger_ensure_csv_headers_atomic(tmp_path: Path):
    """Verify that _ensure_csv_headers creates headers if file doesn't exist."""
    csv_path = tmp_path / "history.csv"
    logger = AuditLogger(
        jsonl_path=tmp_path / "history.jsonl",
        csv_path=csv_path,
    )

    # First write should create headers
    entry = {
        "sha256": "hash1",
        "original_filename": "orig.pdf",
        "original_path": "/path/orig.pdf",
        "new_filename": "new.pdf",
        "destination_folder": "Docs",
        "destination_path": "/docs/new.pdf",
        "summary": "Summary",
        "status": "SUCCESS",
    }
    logger.log_scan(entry)

    with open(csv_path, newline="", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) == 2  # Header + 1 record
        assert "Timestamp" in lines[0]
        assert "New Filename" in lines[0]


def test_audit_logger_os_error_handling(tmp_path: Path):
    """Audit logger should survive OSError when writing files without crashing."""
    logger = AuditLogger(
        jsonl_path=tmp_path / "history.jsonl",
        csv_path=tmp_path / "history.csv",
    )
    with patch("pathlib.Path.open", side_effect=OSError("Read-only filesystem")):
        # Should not raise exception
        logger.log_scan({"status": "SUCCESS"})


def test_audit_logger_ensure_csv_headers_zero_byte_file(tmp_path: Path):
    """_ensure_csv_headers should write header if file exists but is 0 bytes."""
    csv_path = tmp_path / "history.csv"
    csv_path.touch()  # 0 bytes
    logger = AuditLogger(
        jsonl_path=tmp_path / "history.jsonl",
        csv_path=csv_path,
    )
    logger._ensure_csv_headers(csv_path)
    content = csv_path.read_text(encoding="utf-8")
    assert "Timestamp" in content


def test_audit_logger_ensure_csv_headers_os_error(tmp_path: Path):
    """_ensure_csv_headers should handle OSError gracefully."""
    logger = AuditLogger(
        jsonl_path=tmp_path / "history.jsonl",
        csv_path=tmp_path / "history.csv",
    )
    with patch("pathlib.Path.stat", side_effect=OSError("Disk error")):
        logger._ensure_csv_headers(tmp_path / "error.csv")

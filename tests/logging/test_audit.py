"""Unit tests for scansort.logging.audit module."""

import csv
import json
from datetime import datetime as _dt
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scansort.logging import AuditLogger
from scansort.logging import audit as audit_module


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
    with patch("builtins.open", side_effect=OSError("Read-only filesystem")):
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
    error_csv = tmp_path / "error.csv"
    error_csv.touch()
    logger = AuditLogger(
        jsonl_path=tmp_path / "history.jsonl",
        csv_path=tmp_path / "history.csv",
    )
    with patch.object(Path, "stat", side_effect=OSError("Disk error")):
        logger._ensure_csv_headers(error_csv)


def test_ensure_csv_headers_concurrent_creation_never_truncates(tmp_path: Path):
    """Header initialization must never truncate rows another process appended."""
    csv_path = tmp_path / "history.csv"
    logger = AuditLogger(
        jsonl_path=tmp_path / "history.jsonl",
        csv_path=csv_path,
    )

    orig_open = open

    def race_open(file, mode="r", *args, **kwargs):
        if str(file) == str(csv_path) and mode == "x":
            # Another process created the file and wrote a row
            with orig_open(csv_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["MUST_SURVIVE"])
            raise FileExistsError("File exists")
        return orig_open(file, mode, *args, **kwargs)

    with patch("scansort.logging.audit.open", race_open):
        logger._ensure_csv_headers(csv_path)

    content = csv_path.read_text(encoding="utf-8")
    assert "MUST_SURVIVE" in content


def test_log_scan_neutralizes_spreadsheet_formula_cells(tmp_path: Path):
    jsonl_path = tmp_path / "history.jsonl"
    csv_path = tmp_path / "history.csv"
    logger = AuditLogger(jsonl_path=jsonl_path, csv_path=csv_path)

    logger.log_scan(
        {
            "sha256": "hash1",
            "original_filename": '=HYPERLINK("http://evil")-x.pdf',
            "new_filename": "260901_Doc.pdf",
            "destination_folder": "Utilities",
            "destination_path": "/docs/Utilities/260901_Doc.pdf",
            "summary": "=cmd|'/C calc'!A0",
            "status": "SUCCESS",
        }
    )

    text = csv_path.read_text(encoding="utf-8")
    assert "'=cmd|'/C calc'!A0" in text
    assert "'=HYPERLINK" in text
    assert ",=cmd|" not in text
    assert ',"=cmd|' not in text

    # JSONL stays verbatim (source of truth).
    jsonl_text = jsonl_path.read_text(encoding="utf-8")
    assert "=cmd|'/C calc'!A0" in jsonl_text


def test_log_scan_survives_lone_surrogates(tmp_path: Path):
    jsonl_path = tmp_path / "history.jsonl"
    csv_path = tmp_path / "history.csv"
    logger = AuditLogger(jsonl_path=jsonl_path, csv_path=csv_path)

    # A lone surrogate is not encodable under strict UTF-8.
    logger.log_scan(
        {
            "sha256": "hash2",
            "original_filename": "scan.pdf",
            "new_filename": "260901_Doc.pdf",
            "destination_folder": "Utilities",
            "destination_path": "/docs/260901_Doc.pdf",
            "summary": "caf\udce9 content",
            "status": "SUCCESS",
        }
    )

    csv_text = csv_path.read_text(encoding="utf-8")
    assert "caf? content" in csv_text
    jsonl_text = jsonl_path.read_text(encoding="utf-8")
    assert json.loads(jsonl_text)["summary"] == "caf\udce9 content"


def test_log_scan_local_time_always_australia_sydney(tmp_path, monkeypatch):
    sydney_tz = ZoneInfo("Australia/Sydney")

    # 2026-01-31T13:30Z == 2026-02-01 00:30 Sydney (AEDT, UTC+11).
    frozen = _dt.fromisoformat("2026-01-31T13:30:00+00:00").astimezone(sydney_tz)
    monkeypatch.setattr(audit_module, "sydney_now", lambda: frozen)

    jsonl_path = tmp_path / "history.jsonl"
    logger = AuditLogger(jsonl_path=jsonl_path, csv_path=tmp_path / "history.csv")

    logger.log_scan({"status": "SUCCESS"})

    record = json.loads(jsonl_path.read_text(encoding="utf-8").strip())
    assert record["local_time"].startswith("2026-02-01 00:30")
    # The machine-independent UTC instant is preserved as an ISO +00:00 stamp.
    assert record["timestamp"].endswith("+00:00")

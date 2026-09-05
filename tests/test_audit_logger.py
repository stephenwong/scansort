"""Unit tests for scansort.audit_logger module."""

import csv
import json
import threading
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


def test_ensure_csv_headers_concurrent_creation_never_truncates(tmp_path: Path):
    """Header initialization must never truncate rows another process appended."""
    csv_path = tmp_path / "history.csv"
    logger = AuditLogger(
        jsonl_path=tmp_path / "history.jsonl",
        csv_path=csv_path,
    )

    orig_open = open
    entered = threading.Event()
    release = threading.Event()

    def guarded_open(file, mode="r", *args, **kwargs):
        name = getattr(file, "name", file)
        if str(name) == str(csv_path) and mode == "w":
            entered.set()
            release.wait(timeout=5)
        return orig_open(file, mode, *args, **kwargs)

    results: list[object] = []

    def initialize() -> None:
        try:
            logger._ensure_csv_headers(csv_path)
            results.append("ok")
        except BaseException as exc:  # noqa: BLE001 - test failure capture
            results.append(exc)

    thread = threading.Thread(target=initialize)
    with patch("builtins.open", guarded_open):
        thread.start()
        old_truncating_behavior = entered.wait(timeout=1.0)
        if old_truncating_behavior:
            # Old implementation is paused before its truncating open("w"):
            # append a row as the concurrent process would, then let it run.
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["MUST_SURVIVE"])
            release.set()
        thread.join(timeout=5)
        assert not thread.is_alive()
        if not old_truncating_behavior:
            # New implementation never opens "w"; simulate the concurrent append.
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["MUST_SURVIVE"])

    assert results == ["ok"]
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
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    from scansort import audit_logger as audit_module

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

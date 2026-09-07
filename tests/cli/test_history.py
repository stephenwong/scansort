"""Unit tests for scansort.cli.history module."""

import json
from pathlib import Path
from unittest.mock import patch

from scansort.cli.root import main_cli
from scansort.core.constants import HISTORY_JSONL_NAME


def _sample_records() -> list[dict]:
    return [
        {
            "timestamp": "2026-09-07T01:00:00Z",
            "local_time": "2026-09-07 11:00:00",
            "sha256": "aaaa1111",
            "original_filename": "scan_001.pdf",
            "new_filename": "260907_Electricity_Bill.pdf",
            "destination_folder": "Utilities",
            "destination_path": "/docs/Utilities/260907_Electricity_Bill.pdf",
            "summary": "Monthly electric utility statement",
            "status": "SUCCESS",
            "confidence": 0.95,
            "document_type": "Bill",
            "estimated_cost_usd": 0.00015,
        },
        {
            "timestamp": "2026-09-07T02:00:00Z",
            "local_time": "2026-09-07 12:00:00",
            "sha256": "bbbb2222",
            "original_filename": "scan_002.pdf",
            "new_filename": "scan_002.pdf",
            "destination_folder": "_Review_Needed/Duplicates",
            "destination_path": "/docs/_Review_Needed/Duplicates/scan_002.pdf",
            "summary": "Duplicate scan",
            "status": "DUPLICATE",
        },
        {
            "timestamp": "2026-09-07T03:00:00Z",
            "local_time": "2026-09-07 13:00:00",
            "sha256": "cccc3333",
            "original_filename": "tax_receipt.jpg",
            "new_filename": "260907_Donation_Receipt.pdf",
            "destination_folder": "Taxes/2026",
            "destination_path": "/docs/Taxes/2026/260907_Donation_Receipt.pdf",
            "summary": "Charity donation receipt",
            "status": "SUCCESS",
            "confidence": 0.88,
            "document_type": "Receipt",
            "estimated_cost_usd": 0.00021,
        },
        {
            "timestamp": "2026-09-07T04:00:00Z",
            "local_time": "2026-09-07 14:00:00",
            "sha256": "dddd4444",
            "original_filename": "corrupt.pdf",
            "new_filename": "corrupt.pdf",
            "destination_folder": "_Review_Needed",
            "destination_path": "/docs/_Review_Needed/corrupt.pdf",
            "summary": "Failed processing; unreadable scan.",
            "status": "FAILED",
        },
    ]


def test_history_no_file(tmp_path: Path, capsys):
    with patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["history"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No filing history found" in captured.out


def test_history_empty_file(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    history_file.write_text("", encoding="utf-8")

    with patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["history"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No filing history found" in captured.out


def test_history_default_display(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    records = _sample_records()
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    history_file.write_text(content, encoding="utf-8")

    with patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["history"])
        assert exit_code == 0
        captured = capsys.readouterr()
        # Default displays newest first
        assert "corrupt.pdf" in captured.out
        assert "260907_Electricity_Bill.pdf" in captured.out
        assert "SUCCESS" in captured.out
        assert "FAILED" in captured.out
        assert "DUPLICATE" in captured.out


def test_history_limit(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    records = _sample_records()
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    history_file.write_text(content, encoding="utf-8")

    with patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["history", "-n", "2"])
        assert exit_code == 0
        captured = capsys.readouterr()
        # Should include the two most recent records (corrupt.pdf and tax_receipt.jpg)
        assert "corrupt.pdf" in captured.out
        assert "Donation_Receipt" in captured.out
        # Older records should not be listed
        assert "Electricity_Bill" not in captured.out


def test_history_status_filter(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    records = _sample_records()
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    history_file.write_text(content, encoding="utf-8")

    with patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["history", "--status", "SUCCESS"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Electricity_Bill" in captured.out
        assert "Donation_Receipt" in captured.out
        assert "corrupt.pdf" not in captured.out
        assert "scan_002.pdf" not in captured.out


def test_history_search(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    records = _sample_records()
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    history_file.write_text(content, encoding="utf-8")

    with patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["history", "-q", "donation"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Donation_Receipt" in captured.out
        assert "Electricity_Bill" not in captured.out


def test_history_reverse(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    records = _sample_records()
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    history_file.write_text(content, encoding="utf-8")

    with patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["history", "--reverse"])
        assert exit_code == 0
        captured = capsys.readouterr()
        # Oldest first: Electricity_Bill should appear before corrupt.pdf
        elec_pos = captured.out.find("Electricity_Bill")
        corrupt_pos = captured.out.find("corrupt.pdf")
        assert elec_pos != -1
        assert corrupt_pos != -1
        assert elec_pos < corrupt_pos


def test_history_json_output(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    records = _sample_records()
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    history_file.write_text(content, encoding="utf-8")

    with patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["history", "--json", "--status", "SUCCESS"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) == 2
        assert all(item["status"] == "SUCCESS" for item in data)


def test_history_corrupt_lines_handled(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    history_file.write_text(
        '{"status": "SUCCESS", "original_filename": "good.pdf"}\n'
        "NOT_VALID_JSON\n"
        '{"status": "SUCCESS", "original_filename": "good2.pdf"}\n',
        encoding="utf-8",
    )

    with patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["history"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "good.pdf" in captured.out
        assert "good2.pdf" in captured.out


def test_history_no_matches_for_filter(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    history_file.write_text(
        '{"status": "SUCCESS", "original_filename": "bill.pdf"}\n', encoding="utf-8"
    )

    with patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["history", "--status", "FAILED"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No filing history records match" in captured.out


def test_history_read_os_error(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    history_file.write_text('{"status": "SUCCESS"}\n', encoding="utf-8")

    with (
        patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path),
        patch("builtins.open", side_effect=PermissionError("Cannot read history")),
    ):
        exit_code = main_cli(["history"])
        assert exit_code == 0
        assert "Error reading history file" in capsys.readouterr().err


def test_history_truncation_formatting(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    record = {
        "timestamp": "2026-09-07T12:34:56.789012Z",
        "original_filename": "an_extremely_long_original_scanned_filename_here.pdf",
        "new_filename": "an_equally_long_destination_classified_filename_20260907.pdf",
        "status": "FAILED",
        "summary": "Sample failure reason note",
    }
    history_file.write_text("\n\n" + json.dumps(record) + "\n", encoding="utf-8")

    with patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["history"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "..." in captured.out
        assert "Note: Sample failure reason note" in captured.out


def test_history_explicit_null_values(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    # JSON record with explicit null values
    record = {
        "timestamp": None,
        "local_time": None,
        "original_filename": None,
        "new_filename": None,
        "destination_folder": None,
        "summary": None,
        "status": None,
    }
    history_file.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with patch("scansort.cli.history.get_default_app_dir", return_value=tmp_path):
        # Searching for "none" should NOT match the record
        exit_code = main_cli(["history", "-q", "none"])
        assert exit_code == 0
        assert "No filing history records match" in capsys.readouterr().out

        # Regular display should not raise TypeError: object of type 'NoneType' has no len()
        exit_code = main_cli(["history"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Unknown" in captured.out
        assert "UNKNOWN" in captured.out

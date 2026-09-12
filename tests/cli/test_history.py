"""Unit tests for scansort.cli.history module."""

import json
from pathlib import Path
from unittest.mock import patch

from scansort.__main__ import main_cli
from scansort.core.constants import HISTORY_JSONL_NAME


def _write_history(app_dir: Path, records: list[dict]) -> Path:
    history_file = app_dir / HISTORY_JSONL_NAME
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    history_file.write_text(content, encoding="utf-8")
    return history_file


def test_history_no_file(mock_app_dir: Path, capsys):
    exit_code = main_cli(["history"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No filing history found" in captured.out


def test_history_empty_file(mock_app_dir: Path, capsys):
    history_file = mock_app_dir / HISTORY_JSONL_NAME
    history_file.write_text("", encoding="utf-8")

    exit_code = main_cli(["history"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No filing history found" in captured.out


def test_history_default_display(
    mock_app_dir: Path, sample_history_records: list[dict], capsys
):
    _write_history(mock_app_dir, sample_history_records)

    exit_code = main_cli(["history"])
    assert exit_code == 0
    captured = capsys.readouterr()
    # Default displays newest first
    assert "corrupt.pdf" in captured.out
    assert "260907_Electricity_Bill.pdf" in captured.out
    assert "SUCCESS" in captured.out
    assert "FAILED" in captured.out
    assert "DUPLICATE" in captured.out


def test_history_limit(mock_app_dir: Path, sample_history_records: list[dict], capsys):
    _write_history(mock_app_dir, sample_history_records)

    exit_code = main_cli(["history", "-n", "2"])
    assert exit_code == 0
    captured = capsys.readouterr()
    # Should include the two most recent records (corrupt.pdf and tax_receipt.jpg)
    assert "corrupt.pdf" in captured.out
    assert "Donation_Receipt" in captured.out
    # Older records should not be listed
    assert "Electricity_Bill" not in captured.out


def test_history_status_filter(
    mock_app_dir: Path, sample_history_records: list[dict], capsys
):
    _write_history(mock_app_dir, sample_history_records)

    exit_code = main_cli(["history", "--status", "SUCCESS"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Electricity_Bill" in captured.out
    assert "Donation_Receipt" in captured.out
    assert "corrupt.pdf" not in captured.out
    assert "scan_002.pdf" not in captured.out


def test_history_search(mock_app_dir: Path, sample_history_records: list[dict], capsys):
    _write_history(mock_app_dir, sample_history_records)

    exit_code = main_cli(["history", "-q", "donation"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Donation_Receipt" in captured.out
    assert "Electricity_Bill" not in captured.out


def test_history_reverse(
    mock_app_dir: Path, sample_history_records: list[dict], capsys
):
    _write_history(mock_app_dir, sample_history_records)

    exit_code = main_cli(["history", "--reverse"])
    assert exit_code == 0
    captured = capsys.readouterr()
    # Oldest first: Electricity_Bill should appear before corrupt.pdf
    elec_pos = captured.out.find("Electricity_Bill")
    corrupt_pos = captured.out.find("corrupt.pdf")
    assert elec_pos != -1
    assert corrupt_pos != -1
    assert elec_pos < corrupt_pos


def test_history_json_output(
    mock_app_dir: Path, sample_history_records: list[dict], capsys
):
    _write_history(mock_app_dir, sample_history_records)

    exit_code = main_cli(["history", "--json", "--status", "SUCCESS"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert len(data) == 2
    assert all(item["status"] == "SUCCESS" for item in data)


def test_history_corrupt_lines_handled(mock_app_dir: Path, capsys):
    history_file = mock_app_dir / HISTORY_JSONL_NAME
    history_file.write_text(
        '{"status": "SUCCESS", "original_filename": "good.pdf"}\n'
        "NOT_VALID_JSON\n"
        '{"status": "SUCCESS", "original_filename": "good2.pdf"}\n',
        encoding="utf-8",
    )

    exit_code = main_cli(["history"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "good.pdf" in captured.out
    assert "good2.pdf" in captured.out


def test_history_no_matches_for_filter(mock_app_dir: Path, capsys):
    history_file = mock_app_dir / HISTORY_JSONL_NAME
    history_file.write_text(
        '{"status": "SUCCESS", "original_filename": "bill.pdf"}\n', encoding="utf-8"
    )

    exit_code = main_cli(["history", "--status", "FAILED"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No filing history records match" in captured.out


def test_history_read_os_error(mock_app_dir: Path, capsys):
    history_file = mock_app_dir / HISTORY_JSONL_NAME
    history_file.write_text('{"dummy": 1}\n', encoding="utf-8")

    orig_open = open

    def guarded_open(file, *args, **kwargs):
        if str(file) == str(history_file):
            raise PermissionError("Cannot read history")
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", guarded_open):
        exit_code = main_cli(["history"])
        assert exit_code == 0
        assert "Error reading history file" in capsys.readouterr().err


def test_history_truncation_formatting(mock_app_dir: Path, capsys):
    history_file = mock_app_dir / HISTORY_JSONL_NAME
    record = {
        "timestamp": "2026-09-07T12:34:56.789012Z",
        "original_filename": "an_extremely_long_original_scanned_filename_here.pdf",
        "new_filename": "an_equally_long_destination_classified_filename_20260907.pdf",
        "status": "FAILED",
        "summary": "Sample failure reason note",
    }
    history_file.write_text("\n\n" + json.dumps(record) + "\n", encoding="utf-8")

    exit_code = main_cli(["history"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "..." in captured.out
    assert "Note: Sample failure reason note" in captured.out


def test_history_explicit_null_values(mock_app_dir: Path, capsys):
    history_file = mock_app_dir / HISTORY_JSONL_NAME
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


def test_load_history_records_skips_non_dict_lines(tmp_path):
    from scansort.cli.history import _load_history_records

    hist = tmp_path / "history.jsonl"
    hist.write_text('null\n[1,2]\n{"status": "SUCCESS"}\n', encoding="utf-8")
    records = _load_history_records(hist)
    assert records == [{"status": "SUCCESS"}]

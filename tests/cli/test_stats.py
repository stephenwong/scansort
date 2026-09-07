"""Unit tests for scansort.cli.stats module."""

import json
from pathlib import Path
from unittest.mock import patch

from scansort.cli.root import main_cli
from scansort.core.constants import HISTORY_JSONL_NAME


def _stats_sample_records() -> list[dict]:
    return [
        {
            "timestamp": "2026-09-07T01:00:00Z",
            "original_filename": "bill1.pdf",
            "new_filename": "260907_Electricity_Bill.pdf",
            "destination_folder": "Utilities",
            "status": "SUCCESS",
            "document_type": "Bill",
            "tokens": {"prompt": 1000, "candidates": 100, "total": 1100},
            "estimated_cost_usd": 0.000105,
        },
        {
            "timestamp": "2026-09-07T02:00:00Z",
            "original_filename": "bill2.pdf",
            "new_filename": "260907_Gas_Bill.pdf",
            "destination_folder": "Utilities",
            "status": "SUCCESS",
            "document_type": "Bill",
            "tokens": {"prompt": 1200, "candidates": 80, "total": 1280},
            "estimated_cost_usd": 0.000114,
        },
        {
            "timestamp": "2026-09-07T03:00:00Z",
            "original_filename": "receipt.jpg",
            "new_filename": "260907_Groceries_Receipt.pdf",
            "destination_folder": "Finances/Receipts",
            "status": "SUCCESS",
            "document_type": "Receipt",
            "tokens": {"prompt": 800, "candidates": 50, "total": 850},
            "estimated_cost_usd": 0.000075,
        },
        {
            "timestamp": "2026-09-07T04:00:00Z",
            "original_filename": "dup.pdf",
            "new_filename": "dup.pdf",
            "destination_folder": "_Review_Needed/Duplicates",
            "status": "DUPLICATE",
        },
        {
            "timestamp": "2026-09-07T05:00:00Z",
            "original_filename": "bad.pdf",
            "new_filename": "bad.pdf",
            "destination_folder": "_Review_Needed",
            "status": "FAILED",
        },
    ]


def test_stats_no_file(tmp_path: Path, capsys):
    with patch("scansort.cli.stats.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["stats"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No filing history found" in captured.out


def test_stats_empty_file(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    history_file.write_text("", encoding="utf-8")

    with patch("scansort.cli.stats.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["stats"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No filing history found" in captured.out


def test_stats_display(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    records = _stats_sample_records()
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    history_file.write_text(content, encoding="utf-8")

    with patch("scansort.cli.stats.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["stats"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Total Scans:        5" in captured.out
        assert "SUCCESS:" in captured.out
        assert "DUPLICATE:" in captured.out
        assert "FAILED:" in captured.out
        assert "Estimated Cost:" in captured.out
        assert "Total Tokens:" in captured.out
        assert "Utilities" in captured.out


def test_stats_fallback_cost_calculation(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    # Record has tokens and model, but no estimated_cost_usd field
    record = {
        "status": "SUCCESS",
        "gemini_model": "gemini-3.1-flash-lite",
        "tokens": {"prompt": 1000000, "candidates": 1000000, "total": 2000000},
    }
    history_file.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with patch("scansort.cli.stats.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["stats", "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        # Pricing: 0.075 + 0.30 = 0.375
        assert data["total_cost_usd"] == 0.375


def test_stats_json_output(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    records = _stats_sample_records()
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    history_file.write_text(content, encoding="utf-8")

    with patch("scansort.cli.stats.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["stats", "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total_scans"] == 5
        assert data["status_counts"]["SUCCESS"] == 3
        assert data["status_counts"]["DUPLICATE"] == 1
        assert data["status_counts"]["FAILED"] == 1
        assert data["success_rate_pct"] == 60.0
        assert data["tokens"]["total"] == 3230
        assert data["total_cost_usd"] > 0
        assert "Utilities" in data["top_folders"]


def test_stats_explicit_null_values(tmp_path: Path, capsys):
    history_file = tmp_path / HISTORY_JSONL_NAME
    # Record with explicit null for status, folder, doc_type, etc.
    records = [
        {
            "status": None,
            "destination_folder": None,
            "document_type": None,
            "tokens": None,
            "estimated_cost_usd": None,
        }
    ]
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    history_file.write_text(content, encoding="utf-8")

    with patch("scansort.cli.stats.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["stats", "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total_scans"] == 1
        assert data["status_counts"]["UNKNOWN"] == 1
        assert "NONE" not in data["status_counts"]

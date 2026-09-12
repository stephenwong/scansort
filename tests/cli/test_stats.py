"""Unit tests for scansort.cli.stats module."""

import json
from pathlib import Path

import pytest

from scansort.__main__ import main_cli
from scansort.core.constants import HISTORY_JSONL_NAME


def _write_stats_records(app_dir: Path, records: list[dict]) -> Path:
    history_file = app_dir / HISTORY_JSONL_NAME
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    history_file.write_text(content, encoding="utf-8")
    return history_file


@pytest.mark.parametrize("file_content", [None, ""])
def test_stats_missing_or_empty(mock_app_dir: Path, capsys, file_content: str | None):
    if file_content is not None:
        (mock_app_dir / HISTORY_JSONL_NAME).write_text(file_content, encoding="utf-8")

    exit_code = main_cli(["stats"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No filing history found" in captured.out


def test_stats_display(mock_app_dir: Path, sample_history_records: list[dict], capsys):
    _write_stats_records(mock_app_dir, sample_history_records)

    exit_code = main_cli(["stats"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Total Scans:        4" in captured.out
    assert "SUCCESS:" in captured.out
    assert "DUPLICATE:" in captured.out
    assert "FAILED:" in captured.out
    assert "Estimated Cost:" in captured.out
    assert "Total Tokens:" in captured.out
    assert "Utilities" in captured.out


def test_stats_fallback_cost_calculation(mock_app_dir: Path, capsys):
    record = {
        "status": "SUCCESS",
        "gemini_model": "gemini-3.1-flash-lite",
        "tokens": {"prompt": 1000000, "candidates": 1000000, "total": 2000000},
    }
    _write_stats_records(mock_app_dir, [record])

    exit_code = main_cli(["stats", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    # Pricing: 0.075 + 0.30 = 0.375
    assert data["total_cost_usd"] == 0.375


def test_stats_json_output(
    mock_app_dir: Path, sample_history_records: list[dict], capsys
):
    _write_stats_records(mock_app_dir, sample_history_records)

    exit_code = main_cli(["stats", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["total_scans"] == 4
    assert data["status_counts"]["SUCCESS"] == 2
    assert data["status_counts"]["DUPLICATE"] == 1
    assert data["status_counts"]["FAILED"] == 1
    assert data["success_rate_pct"] == 50.0
    assert data["tokens"]["total"] == 1950
    assert data["total_cost_usd"] > 0
    assert "Utilities" in data["top_folders"]


def test_stats_explicit_null_values(mock_app_dir: Path, capsys):
    records = [
        {
            "status": None,
            "destination_folder": None,
            "document_type": None,
            "tokens": None,
            "estimated_cost_usd": None,
        }
    ]
    _write_stats_records(mock_app_dir, records)

    exit_code = main_cli(["stats", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["total_scans"] == 1
    assert data["status_counts"]["UNKNOWN"] == 1
    assert "NONE" not in data["status_counts"]


def test_stats_excludes_review_folder_case_insensitively():
    """F26: review/fallback folders of any casing must not appear as destinations."""
    from scansort.cli.stats import _calculate_metrics

    records = [
        {"status": "FAILED", "destination_folder": "_review_needed"},
        {"status": "DUPLICATE", "destination_folder": "_REVIEW_NEEDED"},
        {"status": "SUCCESS", "destination_folder": "Utilities"},
    ]
    metrics = _calculate_metrics(records)
    assert metrics["top_folders"] == {"Utilities": 1}

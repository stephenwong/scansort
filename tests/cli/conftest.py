"""Shared pytest fixtures for the CLI test suites."""

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scansort.core.config import AppConfig


@contextmanager
def granted_instance_guard(*args, **kwargs):
    """Context manager simulating successfully acquired instance guard lock."""
    yield True


@contextmanager
def denied_instance_guard(*args, **kwargs):
    """Context manager simulating instance guard lock already held by another process."""
    yield False


@pytest.fixture
def mock_app_dir(tmp_path: Path, monkeypatch):
    """Hermetic app data directory fixture patching get_default_app_dir."""
    app_dir = tmp_path / "appdata"
    app_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("scansort.cli.history.get_default_app_dir", lambda: app_dir)
    monkeypatch.setattr("scansort.cli.logs.get_default_app_dir", lambda: app_dir)
    monkeypatch.setattr("scansort.cli.stats.get_default_app_dir", lambda: app_dir)
    return app_dir


@pytest.fixture
def sample_history_records() -> list[dict]:
    """Standardized history audit record dataset for history and stats CLI tests."""
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
            "tokens": {"prompt": 1000, "candidates": 100, "total": 1100},
            "estimated_cost_usd": 0.000105,
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
            "tokens": {"prompt": 0, "candidates": 0, "total": 0},
            "estimated_cost_usd": 0.0,
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
            "tokens": {"prompt": 800, "candidates": 50, "total": 850},
            "estimated_cost_usd": 0.000075,
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
            "tokens": {"prompt": 0, "candidates": 0, "total": 0},
            "estimated_cost_usd": 0.0,
        },
    ]


@pytest.fixture
def frozen_windows_env(monkeypatch, tmp_path: Path):
    """Simulate a frozen Windows executable environment."""
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe_path = tmp_path / "ScanSort" / "ScanSort.exe"
    exe_path.parent.mkdir(parents=True, exist_ok=True)
    exe_path.write_bytes(b"ScanSort")
    monkeypatch.setattr(sys, "executable", str(exe_path), raising=False)
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    app_dir = tmp_path / "appdata"
    app_dir.mkdir(parents=True, exist_ok=True)
    return cfg, app_dir, exe_path


@pytest.fixture
def mock_watch_stack(monkeypatch):
    """Composite mock for DropFolderWatcher, ScanSortPipeline, SystemTrayApp, and instance_guard."""
    mock_watcher = MagicMock()
    mock_pipeline = MagicMock()
    mock_tray = MagicMock()

    monkeypatch.setattr(
        "scansort.cli.watch.DropFolderWatcher", MagicMock(return_value=mock_watcher)
    )
    monkeypatch.setattr(
        "scansort.cli.watch.ScanSortPipeline", MagicMock(return_value=mock_pipeline)
    )
    monkeypatch.setattr(
        "scansort.cli.watch.SystemTrayApp", MagicMock(return_value=mock_tray)
    )
    monkeypatch.setattr("scansort.cli.watch.instance_guard", granted_instance_guard)
    return mock_watcher, mock_pipeline, mock_tray

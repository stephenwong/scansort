"""Unit tests for scansort.file_stabilizer module."""

import time
from pathlib import Path
from unittest.mock import patch

from scansort.file_stabilizer import is_file_locked, wait_for_file_stability


def test_wait_for_file_stability_immediate_for_static_file(tmp_path: Path):
    test_file = tmp_path / "sample.pdf"
    test_file.write_text("fixed content", encoding="utf-8")

    assert wait_for_file_stability(test_file, timeout=1.0, poll_interval=0.01, stable_count=2) is True


def test_wait_for_file_stability_nonexistent_file(tmp_path: Path):
    missing_file = tmp_path / "ghost.pdf"
    assert wait_for_file_stability(missing_file, timeout=0.1, poll_interval=0.01) is False


def test_wait_for_file_stability_zero_byte_file_waits_for_data(tmp_path: Path):
    zero_file = tmp_path / "empty.pdf"
    zero_file.touch()

    assert wait_for_file_stability(zero_file, timeout=0.1, poll_interval=0.02) is False


def test_wait_for_file_stability_waits_while_growing(tmp_path: Path):
    growing_file = tmp_path / "scan_in_progress.pdf"
    growing_file.write_bytes(b"initial")

    def simulate_scanner_appends():
        time.sleep(0.05)
        with open(growing_file, "ab") as f:
            f.write(b" more data")

    import threading

    writer = threading.Thread(target=simulate_scanner_appends)
    writer.start()

    assert (
        wait_for_file_stability(
            growing_file,
            timeout=2.0,
            poll_interval=0.05,
            stable_count=2,
        )
        is True
    )
    writer.join()


def test_is_file_locked(tmp_path: Path):
    test_file = tmp_path / "ready.pdf"
    test_file.write_text("content", encoding="utf-8")
    assert is_file_locked(test_file) is False


def test_is_file_locked_nonexistent(tmp_path: Path):
    missing_file = tmp_path / "nonexistent.pdf"
    assert is_file_locked(missing_file) is True


def test_wait_for_file_stability_stat_os_error(tmp_path: Path):
    test_file = tmp_path / "stat_err.pdf"
    test_file.write_text("data", encoding="utf-8")

    with patch.object(Path, "stat", side_effect=OSError("Read error")), patch.object(Path, "exists", return_value=True):
        assert wait_for_file_stability(test_file, timeout=0.05, poll_interval=0.01) is False

"""Unit tests for scansort.file_stabilizer module."""

import time
from pathlib import Path
from unittest.mock import patch

from scansort.file_stabilizer import is_file_locked, wait_for_file_stability


def test_wait_for_file_stability_immediate_for_static_file(tmp_path: Path):
    test_file = tmp_path / "scan.pdf"
    test_file.write_bytes(b"%PDF-1.4 test static pdf content")

    stable = wait_for_file_stability(test_file, timeout=2.0, poll_interval=0.05, stable_count=2)
    assert stable is True


def test_wait_for_file_stability_nonexistent_file(tmp_path: Path):
    missing_file = tmp_path / "missing.pdf"
    stable = wait_for_file_stability(missing_file, timeout=0.2, poll_interval=0.05)
    assert stable is False


def test_wait_for_file_stability_zero_byte_file_waits_for_data(tmp_path: Path):
    test_file = tmp_path / "incoming.tmp"
    test_file.touch()  # 0 bytes

    # Simulates timeout when file stays 0 bytes
    stable = wait_for_file_stability(test_file, timeout=0.2, poll_interval=0.05)
    assert stable is False


def test_wait_for_file_stability_waits_while_growing(tmp_path: Path):
    test_file = tmp_path / "growing.pdf"
    test_file.write_bytes(b"initial")

    def simulate_growth():
        time.sleep(0.08)
        with open(test_file, "ab") as f:
            f.write(b" more data written by scanner")

    import threading
    t = threading.Thread(target=simulate_growth)
    t.start()

    stable = wait_for_file_stability(test_file, timeout=2.0, poll_interval=0.05, stable_count=2)
    t.join()
    assert stable is True
    assert test_file.stat().st_size > len(b"initial")


def test_is_file_locked(tmp_path: Path):
    test_file = tmp_path / "check_lock.pdf"
    test_file.write_bytes(b"test")

    assert is_file_locked(test_file) is False

    with patch("scansort.file_stabilizer._try_open_exclusive", side_effect=OSError("Locked")):
        assert is_file_locked(test_file) is True

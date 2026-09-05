"""Unit tests for scansort.file_stabilizer module."""

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from scansort.file_stabilizer import is_file_locked, wait_for_file_stability


def test_wait_for_file_stability_immediate_for_static_file(tmp_path: Path):
    test_file = tmp_path / "sample.pdf"
    test_file.write_text("fixed content", encoding="utf-8")

    assert (
        wait_for_file_stability(
            test_file, timeout=1.0, poll_interval=0.01, stable_count=2
        )
        is True
    )


def test_wait_for_file_stability_nonexistent_file(tmp_path: Path):
    missing_file = tmp_path / "ghost.pdf"
    assert (
        wait_for_file_stability(missing_file, timeout=0.1, poll_interval=0.01) is False
    )


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

    with (
        patch.object(Path, "stat", side_effect=OSError("Read error")),
        patch.object(Path, "exists", return_value=True),
    ):
        assert (
            wait_for_file_stability(test_file, timeout=0.05, poll_interval=0.01)
            is False
        )


def test_is_file_locked_readonly_file(tmp_path: Path):
    ro_file = tmp_path / "readonly.pdf"
    ro_file.write_bytes(b"some scan data")
    ro_file.chmod(0o444)
    try:
        assert is_file_locked(ro_file) is False
    finally:
        ro_file.chmod(0o666)


def test_is_file_locked_windows_mock(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    test_file = tmp_path / "win_locked.pdf"
    test_file.write_bytes(b"content")

    mock_msvcrt = MagicMock()
    mock_msvcrt.locking.side_effect = OSError("Lock violation")
    with patch.dict("sys.modules", {"msvcrt": mock_msvcrt}):
        assert is_file_locked(test_file) is True

    # Windows unlocked branch
    mock_msvcrt_unlocked = MagicMock()
    with patch.dict("sys.modules", {"msvcrt": mock_msvcrt_unlocked}):
        assert is_file_locked(test_file) is False
        assert mock_msvcrt_unlocked.locking.call_count == 2


def test_is_file_locked_posix_flock_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    test_file = tmp_path / "posix_locked.pdf"
    test_file.write_bytes(b"content")

    # fcntl does not exist on Windows runners; inject a mock via sys.modules
    # so the POSIX branch can be exercised identically on every platform.
    mock_fcntl = MagicMock()
    mock_fcntl.flock.side_effect = OSError("Resource temporarily unavailable")
    with patch.dict("sys.modules", {"fcntl": mock_fcntl}):
        assert is_file_locked(test_file) is True

    # POSIX unlocked branch
    mock_fcntl_unlocked = MagicMock()
    with patch.dict("sys.modules", {"fcntl": mock_fcntl_unlocked}):
        assert is_file_locked(test_file) is False
        assert mock_fcntl_unlocked.flock.call_count == 2


def test_is_file_locked_permission_denied(tmp_path: Path):
    test_file = tmp_path / "perm_denied.pdf"
    test_file.write_bytes(b"content")

    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        assert is_file_locked(test_file) is True


def test_wait_for_file_stability_directory_fails_fast(tmp_path: Path):
    sub_dir = tmp_path / "sub_dir"
    sub_dir.mkdir()

    t0 = time.monotonic()
    # Should fail fast without waiting for the 2.0s timeout
    result = wait_for_file_stability(sub_dir, timeout=2.0, poll_interval=0.01)
    duration = time.monotonic() - t0

    assert result is False
    assert duration < 0.2


def test_is_file_locked_directory(tmp_path: Path):
    sub_dir = tmp_path / "sub_dir"
    sub_dir.mkdir()
    assert is_file_locked(sub_dir) is True


def test_wait_for_file_stability_resets_last_size_on_empty(tmp_path: Path):
    test_file = tmp_path / "delayed.pdf"
    test_file.touch()  # Starts empty (0 bytes)

    poll_count = 0

    def mock_stat(self, *args, **kwargs):
        nonlocal poll_count
        poll_count += 1
        stat_res = MagicMock()
        stat_res.st_mode = 0o100644
        if poll_count == 1:
            stat_res.st_size = 0  # First poll is 0 bytes
        elif poll_count == 2:
            stat_res.st_size = (
                100  # Second poll wrote 100 bytes (first time seeing 100)
            )
        else:
            stat_res.st_size = (
                100  # Third poll remains 100 bytes (second time seeing 100)
            )
        return stat_res

    with (
        patch.object(Path, "stat", mock_stat),
        patch.object(Path, "is_file", return_value=True),
        patch("scansort.file_stabilizer.is_file_locked", return_value=False),
    ):
        result = wait_for_file_stability(
            test_file, timeout=1.0, poll_interval=0.01, stable_count=2
        )
        assert result is True
        # Must have required 3 polls total (0 bytes, 100 bytes once, 100 bytes twice),
        # NOT declared stable on poll 2
        assert poll_count >= 3

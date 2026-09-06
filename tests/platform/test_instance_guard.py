"""Unit tests for the single-instance process guard."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scansort.platform.instance_guard import instance_guard


def test_instance_guard_acquired_contended_released(tmp_path: Path):
    lock_path = tmp_path / "instance.lock"
    with instance_guard(lock_path) as acquired:
        assert acquired is True
        assert lock_path.exists()
        with instance_guard(lock_path) as second:
            assert second is False
    with instance_guard(lock_path) as retry:
        assert retry is True


def test_instance_guard_windows_branch(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    mock_msvcrt = MagicMock()
    with (
        patch.dict("sys.modules", {"msvcrt": mock_msvcrt}),
        instance_guard(tmp_path / "instance2.lock") as acquired,
    ):
        assert acquired is True
    assert mock_msvcrt.locking.call_count == 2


def test_instance_guard_windows_contention_branch(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    mock_msvcrt = MagicMock()
    mock_msvcrt.locking.side_effect = [None, OSError("Lock violation"), None]
    with patch.dict("sys.modules", {"msvcrt": mock_msvcrt}):
        lock_path = tmp_path / "instance3.lock"
        with instance_guard(lock_path) as acquired:
            assert acquired is True
            with instance_guard(lock_path) as second:
                assert second is False

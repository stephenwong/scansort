"""Unit tests for process waiting, detached spawning, and self-update execution."""

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scansort.updater.process as proc
from scansort.updater.installer import UpdateError
from scansort.updater.process import (
    launch_installed_app,
    perform_self_update,
    spawn_update_helper,
    wait_for_process_exit,
)


def _make_tree(root: Path, name: str, marker: str) -> Path:
    tree = root / name
    tree.mkdir(parents=True)
    (tree / "ScanSort.exe").write_bytes(marker.encode("utf-8"))
    return tree


# ---------------------------------------------------------------------------
# Process waiting & process launching
# ---------------------------------------------------------------------------


def test_wait_for_process_exit_posix_live_and_exited(tmp_path: Path):
    if sys.platform == "win32":
        pytest.skip("Uses POSIX process semantics")
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert wait_for_process_exit(process.pid, timeout=0.2) is False
        process.terminate()
        process.wait(timeout=10)
        assert wait_for_process_exit(process.pid, timeout=5.0) is True
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_wait_for_process_exit_posix_missing_pid(tmp_path: Path):
    if sys.platform == "win32":
        pytest.skip("Uses POSIX process semantics")
    assert wait_for_process_exit(2**31 - 2, timeout=0.0) is True


def test_wait_for_process_exit_posix_continues_on_permission_error(
    tmp_path: Path, monkeypatch
):
    if sys.platform == "win32":
        pytest.skip("Uses POSIX process semantics")

    def denied_kill(pid, sig):
        raise PermissionError("exists but not ours")

    monkeypatch.setattr("scansort.updater.process.os.kill", denied_kill)
    assert wait_for_process_exit(2**31 - 2, timeout=0.0) is False


def test_wait_windows_process_exited_handle(monkeypatch):
    fake_ctypes = MagicMock()
    fake_kernel32 = fake_ctypes.WinDLL.return_value
    fake_kernel32.OpenProcess.return_value = 7
    fake_kernel32.WaitForSingleObject.return_value = 0
    monkeypatch.setattr("scansort.updater.process.ctypes", fake_ctypes)

    assert proc._wait_windows_process(1234, timeout=10.0) is True
    fake_kernel32.WaitForSingleObject.assert_called_once()
    fake_kernel32.CloseHandle.assert_called_once_with(7)


def test_wait_windows_process_open_failure_means_exited(monkeypatch):
    fake_ctypes = MagicMock()
    fake_kernel32 = fake_ctypes.WinDLL.return_value
    fake_kernel32.OpenProcess.return_value = 0
    fake_ctypes.get_last_error.return_value = 87  # ERROR_INVALID_PARAMETER
    monkeypatch.setattr("scansort.updater.process.ctypes", fake_ctypes)

    assert proc._wait_windows_process(9999, timeout=1.0) is True
    fake_kernel32.WaitForSingleObject.assert_not_called()


def test_wait_windows_process_polls_through_access_denied(monkeypatch):
    fake_ctypes = MagicMock()
    fake_kernel32 = fake_ctypes.WinDLL.return_value
    fake_kernel32.OpenProcess.return_value = 0
    fake_ctypes.get_last_error.side_effect = [5, 87]
    monkeypatch.setattr("scansort.updater.process.ctypes", fake_ctypes)

    assert proc._wait_windows_process(1234, timeout=2.0) is True
    assert fake_kernel32.OpenProcess.call_count == 2


def test_wait_windows_process_access_denied_timeout(monkeypatch):
    fake_ctypes = MagicMock()
    fake_kernel32 = fake_ctypes.WinDLL.return_value
    fake_kernel32.OpenProcess.return_value = 0
    fake_ctypes.get_last_error.return_value = 5  # Persistently ERROR_ACCESS_DENIED
    monkeypatch.setattr("scansort.updater.process.ctypes", fake_ctypes)

    assert proc._wait_windows_process(1234, timeout=0.01) is False


def test_wait_windows_process_timeout(monkeypatch):
    fake_ctypes = MagicMock()
    fake_kernel32 = fake_ctypes.WinDLL.return_value
    fake_kernel32.OpenProcess.return_value = 7
    fake_kernel32.WaitForSingleObject.return_value = 258  # WAIT_TIMEOUT
    monkeypatch.setattr("scansort.updater.process.ctypes", fake_ctypes)

    assert proc._wait_windows_process(1234, timeout=0.5) is False


def test_spawn_update_helper_windows_uses_detached_flags_and_cwd(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("sys.platform", "win32")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    with patch("scansort.updater.process.subprocess.Popen") as mock_popen:
        spawn_update_helper(install_dir, staged_dir, "0.2.0", parent_pid=4321)
    argv, kwargs = mock_popen.call_args
    assert argv[0] == [
        str(staged_dir / "ScanSort.exe"),
        "--self-update",
        "4321",
        str(install_dir),
        str(staged_dir),
        "0.2.0",
    ]
    assert kwargs["creationflags"] == (0x00000008 | 0x08000000)
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["cwd"] == str(install_dir.parent)


def test_spawn_update_helper_posix_no_creationflags(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    with patch("scansort.updater.process.subprocess.Popen") as mock_popen:
        spawn_update_helper(install_dir, staged_dir, "0.2.0", parent_pid=1)
    _, kwargs = mock_popen.call_args
    assert "creationflags" not in kwargs
    assert kwargs["cwd"] == str(install_dir.parent)


def test_spawn_update_helper_missing_exe_raises(tmp_path: Path):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    empty = tmp_path / "ScanSort.stage-0.2.0"
    empty.mkdir()
    with pytest.raises(UpdateError, match="ScanSort.exe"):
        spawn_update_helper(install_dir, empty, "0.2.0", parent_pid=1)


def test_spawn_update_helper_popen_failure_raises(tmp_path: Path, monkeypatch):
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    with (
        patch(
            "scansort.updater.process.subprocess.Popen",
            side_effect=OSError(13, "denied"),
        ) as mock_popen,
        pytest.raises(UpdateError, match="Could not launch helper process"),
    ):
        spawn_update_helper(install_dir, staged_dir, "0.2.0", parent_pid=1)
    mock_popen.assert_called_once()


def test_launch_installed_app_defaults_to_watch_minimized(tmp_path: Path, monkeypatch):
    install_dir = _make_tree(tmp_path, "ScanSort", "new")
    with patch("scansort.updater.process.subprocess.Popen") as mock_popen:
        launch_installed_app(install_dir)
    argv, kwargs = mock_popen.call_args
    assert argv[0] == [str(install_dir / "ScanSort.exe"), "watch", "--minimized"]
    assert kwargs["stdout"] == subprocess.DEVNULL


def test_launch_installed_app_custom_args_and_failure(tmp_path: Path, monkeypatch):
    install_dir = _make_tree(tmp_path, "ScanSort", "new")
    with patch("scansort.updater.process.subprocess.Popen") as mock_popen:
        launch_installed_app(install_dir, args=["--help"])
    argv, _ = mock_popen.call_args
    assert argv[0] == [str(install_dir / "ScanSort.exe"), "--help"]

    with (
        patch(
            "scansort.updater.process.subprocess.Popen",
            side_effect=OSError("cannot start"),
        ),
        pytest.raises(UpdateError, match="Could not launch helper process"),
    ):
        launch_installed_app(install_dir)


def test_launch_installed_app_requires_executable(tmp_path: Path):
    install_dir = tmp_path / "ScanSort"
    install_dir.mkdir()
    with pytest.raises(UpdateError, match="Installed ScanSort.exe not found"):
        launch_installed_app(install_dir)


def test_wait_for_process_exit_selects_windows_waiter(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    fake_waiter = MagicMock(return_value=True)
    monkeypatch.setattr("scansort.updater.process._wait_windows_process", fake_waiter)
    assert wait_for_process_exit(99, timeout=1.0) is True
    fake_waiter.assert_called_once_with(99, 1.0)


# ---------------------------------------------------------------------------
# perform_self_update orchestration
# ---------------------------------------------------------------------------


def test_perform_self_update_requires_frozen_windows_build():
    assert perform_self_update(1, "/tmp", "/tmp", "0.2.0") == 1


@patch.dict("sys.modules", {"msvcrt": MagicMock()})
def test_perform_self_update_full_success(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        "scansort.updater.process.wait_for_process_exit", lambda pid, timeout=60.0: True
    )
    monkeypatch.setattr("scansort.updater.process.launch_installed_app", MagicMock())
    mock_chdir = MagicMock()
    monkeypatch.setattr("os.chdir", mock_chdir)

    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    app_dir = tmp_path / "appdata"

    code = perform_self_update(1234, install_dir, staged_dir, "0.2.0", app_dir=app_dir)

    assert code == 0
    assert (install_dir / "ScanSort.exe").read_bytes() == b"new"
    state = json.loads((app_dir / "update_state.json").read_text(encoding="utf-8"))
    assert state["applied_version"] == "0.2.0"
    assert state["just_installed"] is True
    proc.launch_installed_app.assert_called_once_with(install_dir)
    mock_chdir.assert_called_with(install_dir.parent)
    monkeypatch.delattr(sys, "frozen", raising=False)


@patch.dict("sys.modules", {"msvcrt": MagicMock()})
def test_perform_self_update_without_relaunch(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        "scansort.updater.process.wait_for_process_exit", lambda pid, timeout=60.0: True
    )
    monkeypatch.setattr("scansort.updater.process.launch_installed_app", MagicMock())
    monkeypatch.setattr("os.chdir", MagicMock())

    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    app_dir = tmp_path / "appdata"

    code = perform_self_update(
        1234, install_dir, staged_dir, "0.2.0", app_dir=app_dir, relaunch=False
    )

    assert code == 0
    assert (install_dir / "ScanSort.exe").read_bytes() == b"new"
    proc.launch_installed_app.assert_not_called()
    monkeypatch.delattr(sys, "frozen", raising=False)


def test_perform_self_update_validates_staged_and_install(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("os.chdir", MagicMock())
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    empty = tmp_path / "ScanSort.stage-0.2.0"
    empty.mkdir()

    assert perform_self_update(1, install_dir, empty, "0.2.0") == 1
    assert perform_self_update(1, empty, install_dir, "0.2.0") == 1
    monkeypatch.delattr(sys, "frozen", raising=False)


def test_perform_self_update_aborts_when_old_process_still_running(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("os.chdir", MagicMock())
    monkeypatch.setattr(
        "scansort.updater.process.wait_for_process_exit",
        lambda pid, timeout=60.0: False,
    )
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")

    assert perform_self_update(1, install_dir, staged_dir, "0.2.0") == 1
    assert (install_dir / "ScanSort.exe").read_bytes() == b"old"
    monkeypatch.delattr(sys, "frozen", raising=False)


@patch.dict("sys.modules", {"msvcrt": MagicMock()})
def test_perform_self_update_defers_when_another_instance_runs(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("os.chdir", MagicMock())
    monkeypatch.setattr(
        "scansort.updater.process.wait_for_process_exit", lambda pid, timeout=60.0: True
    )

    @contextmanager
    def denied_guard(lock_path):
        yield False

    monkeypatch.setattr("scansort.updater.process.instance_guard", denied_guard)
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")

    assert perform_self_update(1, install_dir, staged_dir, "0.2.0") == 1
    assert (install_dir / "ScanSort.exe").read_bytes() == b"old"
    assert staged_dir.exists()
    monkeypatch.delattr(sys, "frozen", raising=False)


def test_perform_self_update_tolerates_chdir_oserror(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("os.chdir", MagicMock(side_effect=OSError("permission denied")))
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    empty = tmp_path / "ScanSort.stage-0.2.0"
    empty.mkdir()

    # Even if chdir fails, perform_self_update continues its checks gracefully
    assert perform_self_update(1, install_dir, empty, "0.2.0") == 1
    monkeypatch.delattr(sys, "frozen", raising=False)

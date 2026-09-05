"""Unit tests for the GitHub Releases self-updater."""

import hashlib
import io
import json
import subprocess
import sys
import time
import zipfile
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scansort.updater as updater
from scansort.updater import (
    ReleaseInfo,
    UpdateError,
    applied_version,
    available_update,
    cleanup_stale_updates,
    clear_applied_notification,
    download_and_stage,
    download_release,
    extract_bundle,
    fetch_latest_release,
    installed_version,
    launch_installed_app,
    load_state,
    parse_version,
    perform_self_update,
    record_applied_update,
    record_update_check,
    replace_install_dir,
    spawn_update_helper,
    update_is_due,
    wait_for_process_exit,
)

WINDOWS_ZIP = "ScanSort-v0.2.0-windows-x64.zip"


class _BytesResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _fake_urlopen(payload: bytes):
    def opener(request, timeout=None):
        return _BytesResponse(payload)

    return opener


def _release_zip_bytes(marker: bytes = b"new-exe") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ScanSort.exe", marker)
        archive.writestr("_internal/module.py", b"print('x')\n")
        archive.writestr("emptydir/", b"")
    return buffer.getvalue()


def _payload(
    tag: str = "v0.2.0",
    *,
    asset_name: str | None = None,
    digest: object = None,
    url: str = "https://example.com/ScanSort-v0.2.0-windows-x64.zip",
    size: int | None = 123,
) -> dict:
    return {
        "tag_name": tag,
        "assets": [
            {
                "name": asset_name or f"ScanSort-{tag}-windows-x64.zip",
                "browser_download_url": url,
                "size": size,
                "digest": digest,
            }
        ],
    }


# ---------------------------------------------------------------------------
# parse_version
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.1.0", (0, 1, 0)),
        ("v1.2.3", (1, 2, 3)),
        ("V2.0.0", (2, 0, 0)),
        (" 3.4.5 ", (3, 4, 5)),
    ],
)
def test_parse_version_valid(raw: str, expected):
    assert parse_version(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "1.2", "1.2.3.4", "1.2.3-rc1", "v1.2", "abc", "1.x.3", None, 12],
)
def test_parse_version_rejects_invalid(raw):
    assert parse_version(raw) is None


# ---------------------------------------------------------------------------
# Version baseline helpers
# ---------------------------------------------------------------------------


def test_installed_version_uses_package_version(monkeypatch):
    assert installed_version() == (0, 2, 1)
    monkeypatch.setattr("scansort.__version__", "9.8.7")
    assert installed_version() == (9, 8, 7)
    monkeypatch.setattr("scansort.__version__", "not-a-version")
    assert installed_version() is None


# ---------------------------------------------------------------------------
# Update state file helpers
# ---------------------------------------------------------------------------


def test_load_state_handles_missing_corrupt_and_non_dict(tmp_path: Path):
    state_path = tmp_path / "update_state.json"
    assert load_state(state_path) == {}
    state_path.write_text("{not json", encoding="utf-8")
    assert load_state(state_path) == {}
    state_path.write_text("[1, 2]", encoding="utf-8")
    assert load_state(state_path) == {}


def test_record_update_check_and_due_calculation(tmp_path: Path):
    state_path = tmp_path / "update_state.json"
    assert update_is_due(state_path, interval_days=1) is True

    when = datetime.now(UTC) - timedelta(days=5)
    record_update_check(state_path, when=when)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["checked_at"] == when.isoformat()
    assert update_is_due(state_path, interval_days=1) is True
    assert update_is_due(state_path, interval_days=10) is False


def test_update_is_due_treats_bad_or_naive_timestamps_as_due(tmp_path: Path):
    state_path = tmp_path / "update_state.json"
    state_path.write_text(json.dumps({"checked_at": "not-a-date"}), encoding="utf-8")
    assert update_is_due(state_path, 1) is True
    state_path.write_text(
        json.dumps({"checked_at": "2026-09-01T10:00:00"}), encoding="utf-8"
    )
    assert update_is_due(state_path, 1) is True
    state_path.write_text(json.dumps({"checked_at": 12345}), encoding="utf-8")
    assert update_is_due(state_path, 1) is True


def test_record_applied_update_and_notification_cycle(tmp_path: Path):
    state_path = tmp_path / "update_state.json"
    when = datetime.now(UTC)
    record_applied_update(state_path, "0.2.0", when=when)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["applied_version"] == "0.2.0"
    assert state["just_installed"] is True
    assert state["applied_at"] == when.isoformat()
    assert applied_version(state_path) == "0.2.0"

    clear_applied_notification(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state.get("just_installed") is False
    assert applied_version(state_path) == "0.2.0"


def test_applied_version_missing_returns_none(tmp_path: Path):
    assert applied_version(tmp_path / "missing.json") is None


def test_state_writes_tolerate_os_errors(tmp_path: Path, monkeypatch):
    state_path = tmp_path / "update_state.json"
    monkeypatch.setattr(
        "scansort.updater.atomic_write",
        MagicMock(side_effect=OSError("disk full")),
    )
    record_update_check(state_path)
    record_applied_update(state_path, "0.2.0")
    clear_applied_notification(state_path)
    assert not state_path.exists()


# ---------------------------------------------------------------------------
# Release feed parsing
# ---------------------------------------------------------------------------


def test_fetch_latest_release_parses_payload():
    payload = _payload()
    encoded = json.dumps(payload).encode("utf-8")
    seen: list = []

    def opener(request, timeout=None):
        seen.append((request, timeout))
        return _BytesResponse(encoded)

    assert fetch_latest_release(opener=opener) == payload
    request, timeout = seen[0]
    assert timeout == updater.REQUEST_TIMEOUT
    headers = {name.lower(): value for name, value in request.header_items()}
    assert "ScanSort" in headers["user-agent"]
    assert "github+json" in headers["accept"]


def test_fetch_latest_release_failures_raise_update_error():
    def broken_opener(request, timeout=None):
        raise OSError("connection reset")

    with pytest.raises(UpdateError, match="Update check failed"):
        fetch_latest_release(opener=broken_opener)

    with pytest.raises(UpdateError, match="Update check failed"):
        fetch_latest_release(opener=_fake_urlopen(b"{not json"))

    with pytest.raises(UpdateError, match="unexpected payload"):
        fetch_latest_release(opener=_fake_urlopen(b"[1, 2]"))


def test_available_update_returns_newer_release():
    info = available_update(_payload(digest="sha256:abcdef"), (0, 1, 0))
    assert info is not None
    assert info.version == "0.2.0"
    assert info.tag_name == "v0.2.0"
    assert info.asset_name == WINDOWS_ZIP
    assert info.sha256 == "abcdef"
    assert info.size_bytes == 123


def test_available_update_list_digest_form():
    digest = [{"algorithm": "sha256", "value": "deadbeef"}]
    payload = _payload(digest=digest)
    info = available_update(payload, (0, 1, 0))
    assert info is not None
    assert info.sha256 == "deadbeef"


def test_available_update_returns_none_for_equal_or_older():
    assert available_update(_payload(tag="v0.1.0"), (0, 1, 0)) is None
    assert available_update(_payload(tag="v0.0.9"), (0, 1, 0)) is None
    # A genuinely newer release still qualifies.
    assert available_update(_payload(tag="v0.1.9"), (0, 1, 0)) is not None


def test_available_update_respects_previously_applied_version():
    payload = _payload(tag="v0.2.0")
    assert available_update(payload, (0, 1, 0), applied_version="0.2.0") is None
    assert available_update(payload, (0, 1, 0), applied_version="0.1.0") is not None


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"tag_name": "not-a-version"},
        {"tag_name": "v0.2.0", "assets": []},
        {"tag_name": "v0.2.0", "assets": [{"name": "wrong-name.zip"}]},
        {"tag_name": "v0.2.0", "assets": "nope"},
    ],
)
def test_available_update_returns_none_for_unusable_payloads(payload):
    assert available_update(payload, (0, 1, 0)) is None


def test_available_update_returns_none_without_download_url():
    payload = _payload(url="")
    assert available_update(payload, (0, 1, 0)) is None


def test_available_update_drops_non_numeric_asset_size():
    payload = _payload(size="large")
    info = available_update(payload, (0, 1, 0))
    assert info is not None
    assert info.size_bytes is None


# ---------------------------------------------------------------------------
# Download & extraction
# ---------------------------------------------------------------------------


def test_download_release_streams_bytes_and_verifies_size(tmp_path: Path):
    data = _release_zip_bytes()
    info = ReleaseInfo(
        version="0.2.0",
        tag_name="v0.2.0",
        asset_name=WINDOWS_ZIP,
        download_url="https://example.com/a.zip",
        size_bytes=len(data),
        sha256=None,
        published_at=None,
    )
    dest = tmp_path / "dl.zip"
    download_release(info, dest, opener=_fake_urlopen(data))
    assert dest.read_bytes() == data


def test_download_release_rejects_size_mismatch(tmp_path: Path):
    info = ReleaseInfo(
        version="0.2.0",
        tag_name="v0.2.0",
        asset_name=WINDOWS_ZIP,
        download_url="https://example.com/a.zip",
        size_bytes=9999,
        sha256=None,
        published_at=None,
    )
    dest = tmp_path / "dl.zip"
    with pytest.raises(UpdateError, match="size mismatch"):
        download_release(info, dest, opener=_fake_urlopen(b"short"))
    assert not dest.exists()


def test_download_release_rejects_checksum_mismatch(tmp_path: Path):
    info = ReleaseInfo(
        version="0.2.0",
        tag_name="v0.2.0",
        asset_name=WINDOWS_ZIP,
        download_url="https://example.com/a.zip",
        size_bytes=None,
        sha256="0" * 64,
        published_at=None,
    )
    dest = tmp_path / "dl.zip"
    with pytest.raises(UpdateError, match="checksum mismatch"):
        download_release(info, dest, opener=_fake_urlopen(b"tampered"))
    assert not dest.exists()


def test_download_release_cleans_up_on_transport_error(tmp_path: Path):
    info = ReleaseInfo(
        version="0.2.0",
        tag_name="v0.2.0",
        asset_name=WINDOWS_ZIP,
        download_url="https://example.com/a.zip",
        size_bytes=None,
        sha256=None,
        published_at=None,
    )

    def broken_opener(request, timeout=None):
        raise OSError("timed out")

    dest = tmp_path / "dl.zip"
    dest.write_bytes(b"partial")
    with pytest.raises(UpdateError, match="Download failed"):
        download_release(info, dest, opener=broken_opener)
    assert not dest.exists()


def test_extract_bundle_materializes_release_files(tmp_path: Path):
    zip_path = tmp_path / "release.zip"
    zip_path.write_bytes(_release_zip_bytes())
    dest = tmp_path / "staged"
    extract_bundle(zip_path, dest)
    assert (dest / "ScanSort.exe").read_bytes() == b"new-exe"
    assert (dest / "_internal" / "module.py").read_bytes() == b"print('x')\n"
    assert (dest / "emptydir").is_dir()


@pytest.mark.parametrize(
    "entry", ["../evil.txt", "/abs.txt", "a/../../evil", "C:/evil.txt"]
)
def test_extract_bundle_rejects_unsafe_members(tmp_path: Path, entry: str):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(entry, b"boom")
    zip_path = tmp_path / "evil.zip"
    zip_path.write_bytes(buffer.getvalue())
    with pytest.raises(UpdateError, match="Unsafe archive entry"):
        extract_bundle(zip_path, tmp_path / "staged")


def test_extract_bundle_rejects_corrupt_archive_and_missing_exe(tmp_path: Path):
    zip_path = tmp_path / "corrupt.zip"
    zip_path.write_bytes(b"not a zip")
    with pytest.raises(UpdateError, match="corrupt"):
        extract_bundle(zip_path, tmp_path / "staged1")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", b"hello")
    zip_path.write_bytes(buffer.getvalue())
    with pytest.raises(UpdateError, match="ScanSort.exe"):
        extract_bundle(zip_path, tmp_path / "staged2")


# ---------------------------------------------------------------------------
# Staging & stale artifact cleanup
# ---------------------------------------------------------------------------


def _make_tree(root: Path, name: str, marker: str) -> Path:
    tree = root / name
    tree.mkdir(parents=True)
    (tree / "ScanSort.exe").write_bytes(marker.encode("utf-8"))
    return tree


def _stage_info(tmp_path: Path, marker: bytes = b"new-exe") -> ReleaseInfo:
    data = _release_zip_bytes(marker)
    return ReleaseInfo(
        version="0.2.0",
        tag_name="v0.2.0",
        asset_name=WINDOWS_ZIP,
        download_url="https://example.com/ScanSort-v0.2.0-windows-x64.zip",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        published_at=None,
    )


def test_cleanup_stale_updates_removes_old_stages_and_backups(tmp_path: Path):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    keep_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    stale_dir = _make_tree(tmp_path, "ScanSort.stage-0.1.0", "old")
    stale_old = _make_tree(tmp_path, "ScanSort.old-123", "old")
    (tmp_path / "ScanSort.stage-0.1.0-corrupt").write_text("junk", encoding="utf-8")

    cleanup_stale_updates(install_dir, keep=keep_dir)

    assert keep_dir.exists()
    assert not stale_dir.exists()
    assert not stale_old.exists()
    assert not (tmp_path / "ScanSort.stage-0.1.0-corrupt").exists()
    assert install_dir.exists()


def test_cleanup_stale_updates_tolerates_removal_errors(tmp_path: Path, monkeypatch):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    _make_tree(tmp_path, "ScanSort.stage-0.1.0", "old")
    monkeypatch.setattr(
        "scansort.updater.shutil.rmtree",
        MagicMock(side_effect=OSError("locked")),
    )
    cleanup_stale_updates(install_dir)
    assert (tmp_path / "ScanSort.stage-0.1.0").exists()


def test_download_and_stage_reuses_cached_archive(tmp_path: Path):
    info = _stage_info(tmp_path)
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    tmp_dir = tmp_path / "apptmp"
    calls: list = []

    def opener(request, timeout=None):
        calls.append(request)
        data = _release_zip_bytes()
        return _BytesResponse(data)

    first = download_and_stage(info, install_dir, tmp_dir, opener=opener)
    assert first.is_dir()
    assert (first / "ScanSort.exe").read_bytes() == b"new-exe"
    assert (tmp_dir / WINDOWS_ZIP).is_file()
    assert len(calls) == 1

    second = download_and_stage(info, install_dir, tmp_dir, opener=opener)
    assert second == first
    assert len(calls) == 1


def test_download_and_stage_redownloads_when_cache_is_stale(tmp_path: Path):
    info = _stage_info(tmp_path, marker=b"second")
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    tmp_dir = tmp_path / "apptmp"
    tmp_dir.mkdir()
    (tmp_dir / WINDOWS_ZIP).write_bytes(b"corrupted cache")

    seen = []
    data = _release_zip_bytes(b"second")

    def opener(request, timeout=None):
        seen.append(1)
        return _BytesResponse(data)

    stage = download_and_stage(info, install_dir, tmp_dir, opener=opener)
    assert seen == [1]
    assert (stage / "ScanSort.exe").read_bytes() == b"second"


def test_download_and_stage_prunes_old_archives_and_resets_stage(tmp_path: Path):
    info = _stage_info(tmp_path, marker=b"third")
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    tmp_dir = tmp_path / "apptmp"
    tmp_dir.mkdir(parents=True)
    (tmp_dir / "ScanSort-v0.1.0-windows-x64.zip").write_bytes(b"old archive")
    leftover = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "partial")
    (leftover / "junk").write_bytes(b"partial")

    def opener(request, timeout=None):
        return _BytesResponse(_release_zip_bytes(b"third"))

    stage = download_and_stage(info, install_dir, tmp_dir, opener=opener)
    assert (stage / "ScanSort.exe").read_bytes() == b"third"
    assert not (tmp_dir / "ScanSort-v0.1.0-windows-x64.zip").exists()
    assert not (leftover / "junk").exists()


# ---------------------------------------------------------------------------
# Swap / replace_install_dir
# ---------------------------------------------------------------------------


def test_replace_install_dir_swaps_trees_and_removes_backup(tmp_path: Path):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")

    replace_install_dir(install_dir, staged_dir)

    assert (install_dir / "ScanSort.exe").read_bytes() == b"new"
    assert not staged_dir.exists()
    assert not list(tmp_path.glob("ScanSort.old-*"))


def test_replace_install_dir_rolls_back_when_swap_fails(tmp_path: Path, monkeypatch):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    original_rename = Path.rename

    def failing_rename(self, target):
        if self == staged_dir:
            raise OSError(5, "access denied")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", failing_rename)

    with pytest.raises(UpdateError, match="restored"):
        replace_install_dir(install_dir, staged_dir)
    assert (install_dir / "ScanSort.exe").read_bytes() == b"old"
    assert staged_dir.exists()


def test_replace_install_dir_reports_unrecoverable_rollback(
    tmp_path: Path, monkeypatch
):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    backup_dir = install_dir.parent / f"{install_dir.name}.old-{int(time.time())}"
    original_rename = Path.rename

    def failing_rename(self, target):
        if self in (staged_dir, backup_dir):
            raise OSError(5, "access denied")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", failing_rename)

    with pytest.raises(UpdateError, match="preserved at"):
        replace_install_dir(install_dir, staged_dir)
    assert backup_dir.is_dir()


def test_replace_install_dir_tolerates_backup_removal_failure(
    tmp_path: Path, monkeypatch
):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")

    def locked_rmtree(path, ignore_errors=False):
        raise OSError(32, "file in use")

    monkeypatch.setattr("scansort.updater.shutil.rmtree", locked_rmtree)

    replace_install_dir(install_dir, staged_dir)
    assert (install_dir / "ScanSort.exe").read_bytes() == b"new"
    assert len(list(tmp_path.glob("ScanSort.old-*"))) == 1


def test_replace_install_dir_validates_both_trees(tmp_path: Path):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    empty_staged = tmp_path / "ScanSort.stage-0.2.0"
    empty_staged.mkdir()
    with pytest.raises(UpdateError, match="ScanSort.exe"):
        replace_install_dir(install_dir, empty_staged)

    broken_install = tmp_path / "Broken"
    broken_install.mkdir()
    good_staged = _make_tree(tmp_path, "ScanSort.stage-0.3.0", "new")
    with pytest.raises(UpdateError, match="ScanSort.exe"):
        replace_install_dir(broken_install, good_staged)


# ---------------------------------------------------------------------------
# Process waiting & process launching
# ---------------------------------------------------------------------------


def test_wait_for_process_exit_posix_live_and_exited(tmp_path: Path):
    if sys.platform == "win32":
        pytest.skip("Uses POSIX process semantics")
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert wait_for_process_exit(proc.pid, timeout=0.2) is False
        proc.terminate()
        proc.wait(timeout=10)
        assert wait_for_process_exit(proc.pid, timeout=5.0) is True
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


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

    monkeypatch.setattr("scansort.updater.os.kill", denied_kill)
    assert wait_for_process_exit(2**31 - 2, timeout=0.0) is False


def test_wait_windows_process_exited_handle(monkeypatch):
    fake_ctypes = MagicMock()
    fake_kernel32 = fake_ctypes.WinDLL.return_value
    fake_kernel32.OpenProcess.return_value = 7
    fake_kernel32.WaitForSingleObject.return_value = 0
    monkeypatch.setattr("scansort.updater.ctypes", fake_ctypes)

    assert updater._wait_windows_process(1234, timeout=10.0) is True
    fake_kernel32.WaitForSingleObject.assert_called_once_with(7, 10000)
    fake_kernel32.CloseHandle.assert_called_once_with(7)


def test_wait_windows_process_open_failure_means_exited(monkeypatch):
    fake_ctypes = MagicMock()
    fake_kernel32 = fake_ctypes.WinDLL.return_value
    fake_kernel32.OpenProcess.return_value = 0
    monkeypatch.setattr("scansort.updater.ctypes", fake_ctypes)

    assert updater._wait_windows_process(9999, timeout=1.0) is True
    fake_kernel32.WaitForSingleObject.assert_not_called()


def test_wait_windows_process_timeout(monkeypatch):
    fake_ctypes = MagicMock()
    fake_kernel32 = fake_ctypes.WinDLL.return_value
    fake_kernel32.OpenProcess.return_value = 7
    fake_kernel32.WaitForSingleObject.return_value = 258  # WAIT_TIMEOUT
    monkeypatch.setattr("scansort.updater.ctypes", fake_ctypes)

    assert updater._wait_windows_process(1234, timeout=0.5) is False


def test_spawn_update_helper_windows_uses_detached_flags(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    with patch("scansort.updater.subprocess.Popen") as mock_popen:
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


def test_spawn_update_helper_posix_no_creationflags(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    with patch("scansort.updater.subprocess.Popen") as mock_popen:
        spawn_update_helper(install_dir, staged_dir, "0.2.0", parent_pid=1)
    _, kwargs = mock_popen.call_args
    assert "creationflags" not in kwargs


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
            "scansort.updater.subprocess.Popen", side_effect=OSError(13, "denied")
        ) as mock_popen,
        pytest.raises(UpdateError, match="Could not launch helper process"),
    ):
        spawn_update_helper(install_dir, staged_dir, "0.2.0", parent_pid=1)
    mock_popen.assert_called_once()


def test_launch_installed_app_defaults_to_watch_minimized(tmp_path: Path, monkeypatch):
    install_dir = _make_tree(tmp_path, "ScanSort", "new")
    with patch("scansort.updater.subprocess.Popen") as mock_popen:
        launch_installed_app(install_dir)
    argv, kwargs = mock_popen.call_args
    assert argv[0] == [str(install_dir / "ScanSort.exe"), "watch", "--minimized"]
    assert kwargs["stdout"] == subprocess.DEVNULL


def test_launch_installed_app_custom_args_and_failure(tmp_path: Path, monkeypatch):
    install_dir = _make_tree(tmp_path, "ScanSort", "new")
    with patch("scansort.updater.subprocess.Popen") as mock_popen:
        launch_installed_app(install_dir, args=["--help"])
    argv, _ = mock_popen.call_args
    assert argv[0] == [str(install_dir / "ScanSort.exe"), "--help"]

    with (
        patch("scansort.updater.subprocess.Popen", side_effect=OSError("cannot start")),
        pytest.raises(UpdateError, match="Could not launch helper process"),
    ):
        launch_installed_app(install_dir)


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
        "scansort.updater.wait_for_process_exit", lambda pid, timeout=60.0: True
    )
    monkeypatch.setattr("scansort.updater.launch_installed_app", MagicMock())

    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    app_dir = tmp_path / "appdata"

    code = perform_self_update(1234, install_dir, staged_dir, "0.2.0", app_dir=app_dir)

    assert code == 0
    assert (install_dir / "ScanSort.exe").read_bytes() == b"new"
    state = json.loads(
        (app_dir / updater.UPDATE_STATE_FILENAME).read_text(encoding="utf-8")
    )
    assert state["applied_version"] == "0.2.0"
    assert state["just_installed"] is True
    updater.launch_installed_app.assert_called_once_with(install_dir)
    monkeypatch.delattr(sys, "frozen", raising=False)


@patch.dict("sys.modules", {"msvcrt": MagicMock()})
def test_perform_self_update_without_relaunch(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        "scansort.updater.wait_for_process_exit", lambda pid, timeout=60.0: True
    )
    monkeypatch.setattr("scansort.updater.launch_installed_app", MagicMock())

    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    app_dir = tmp_path / "appdata"

    code = perform_self_update(
        1234, install_dir, staged_dir, "0.2.0", app_dir=app_dir, relaunch=False
    )

    assert code == 0
    assert (install_dir / "ScanSort.exe").read_bytes() == b"new"
    updater.launch_installed_app.assert_not_called()
    monkeypatch.delattr(sys, "frozen", raising=False)


def test_perform_self_update_validates_staged_and_install(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
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
    monkeypatch.setattr(
        "scansort.updater.wait_for_process_exit", lambda pid, timeout=60.0: False
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
    monkeypatch.setattr(
        "scansort.updater.wait_for_process_exit", lambda pid, timeout=60.0: True
    )

    @contextmanager
    def denied_guard(lock_path):
        yield False

    monkeypatch.setattr("scansort.updater.instance_guard", denied_guard)
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")

    assert perform_self_update(1, install_dir, staged_dir, "0.2.0") == 1
    assert (install_dir / "ScanSort.exe").read_bytes() == b"old"
    assert staged_dir.exists()
    monkeypatch.delattr(sys, "frozen", raising=False)


def test_clear_applied_notification_tolerates_write_errors(tmp_path: Path, monkeypatch):
    state_path = tmp_path / "update_state.json"
    record_applied_update(state_path, "0.2.0")
    monkeypatch.setattr(
        "scansort.updater.atomic_write",
        MagicMock(side_effect=OSError("disk full")),
    )
    clear_applied_notification(state_path)


def test_available_update_ignores_non_sha256_digest():
    payload = _payload(digest="md5:abcdef")
    info = available_update(payload, (0, 1, 0))
    assert info is not None
    assert info.sha256 is None


def test_download_and_stage_cleans_partial_stage_on_corrupt_zip(tmp_path: Path):
    info = replace(_stage_info(tmp_path), sha256=None, size_bytes=None)
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    tmp_dir = tmp_path / "apptmp"
    with pytest.raises(UpdateError, match="corrupt"):
        download_and_stage(
            info, install_dir, tmp_dir, opener=_fake_urlopen(b"not a zip")
        )
    assert not (tmp_path / "ScanSort.stage-0.2.0").exists()


def test_download_and_stage_tolerates_old_archive_removal_failure(
    tmp_path: Path, monkeypatch
):
    info = _stage_info(tmp_path)
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    tmp_dir = tmp_path / "apptmp"
    tmp_dir.mkdir(parents=True)
    old_zip = tmp_dir / "ScanSort-v0.1.0-windows-x64.zip"
    old_zip.write_bytes(b"old archive")
    original_unlink = Path.unlink

    def denied_unlink(self, *args, **kwargs):
        if self == old_zip:
            raise OSError("file locked")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied_unlink)
    stage = download_and_stage(
        info, install_dir, tmp_dir, opener=_fake_urlopen(_release_zip_bytes())
    )
    assert (stage / "ScanSort.exe").is_file()
    assert old_zip.exists()


def test_replace_install_dir_reports_when_install_cannot_be_moved_aside(
    tmp_path: Path, monkeypatch
):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    original_rename = Path.rename

    def denied_rename(self, target):
        if self == install_dir:
            raise OSError(32, "file in use")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", denied_rename)
    with pytest.raises(UpdateError, match="aside"):
        replace_install_dir(install_dir, staged_dir)
    assert (install_dir / "ScanSort.exe").read_bytes() == b"old"
    assert staged_dir.exists()


def test_wait_for_process_exit_selects_windows_waiter(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    fake_waiter = MagicMock(return_value=True)
    monkeypatch.setattr("scansort.updater._wait_windows_process", fake_waiter)
    assert wait_for_process_exit(99, timeout=1.0) is True
    fake_waiter.assert_called_once_with(99, 1.0)


def test_launch_installed_app_requires_executable(tmp_path: Path):
    install_dir = tmp_path / "ScanSort"
    install_dir.mkdir()
    with pytest.raises(UpdateError, match="Installed ScanSort.exe not found"):
        launch_installed_app(install_dir)

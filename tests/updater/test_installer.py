"""Unit tests for the installation swap, retry loop, and stale artifact cleanup."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scansort.updater.installer as installer
from scansort.updater.installer import (
    UpdateError,
    cleanup_stale_updates,
    replace_install_dir,
)


@pytest.fixture(autouse=True)
def _speed_up_installer_retries(monkeypatch):
    """Keep test execution instantaneous by reducing retry intervals."""
    monkeypatch.setattr(installer, "SWAP_RETRY_TIMEOUT", 0.05)
    monkeypatch.setattr(installer, "SWAP_RETRY_INTERVAL", 0.005)


def _make_tree(root: Path, name: str, marker: str) -> Path:
    tree = root / name
    tree.mkdir(parents=True)
    (tree / "ScanSort.exe").write_bytes(marker.encode("utf-8"))
    return tree


# ---------------------------------------------------------------------------
# Stale artifact cleanup
# ---------------------------------------------------------------------------


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
        "scansort.updater.installer.shutil.rmtree",
        MagicMock(side_effect=OSError("locked")),
    )
    cleanup_stale_updates(install_dir)
    assert (tmp_path / "ScanSort.stage-0.1.0").exists()


# ---------------------------------------------------------------------------
# Swap / replace_install_dir & transient lock retries
# ---------------------------------------------------------------------------


def test_replace_install_dir_swaps_trees_and_removes_backup(tmp_path: Path):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")

    replace_install_dir(install_dir, staged_dir)

    assert (install_dir / "ScanSort.exe").read_bytes() == b"new"
    assert not staged_dir.exists()
    assert not list(tmp_path.glob("ScanSort.old-*"))


def test_replace_install_dir_retries_and_recovers_from_transient_lock(
    tmp_path: Path, monkeypatch
):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")
    original_rename = Path.rename
    attempts = [0]

    def flaky_rename(self, target):
        if self == install_dir and attempts[0] < 2:
            attempts[0] += 1
            raise OSError(
                32,
                "The process cannot access the file because it is being used by another process",
            )
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)

    replace_install_dir(install_dir, staged_dir, timeout=0.5, interval=0.01)

    assert attempts[0] == 2
    assert (install_dir / "ScanSort.exe").read_bytes() == b"new"
    assert not staged_dir.exists()


def test_replace_install_dir_handles_backup_dir_collision(tmp_path: Path):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")

    now_ts = int(time.time())
    colliding = tmp_path / f"ScanSort.old-{now_ts}"
    colliding.mkdir(parents=True)
    (colliding / "marker.txt").write_text("existing", encoding="utf-8")

    with patch("time.time", return_value=float(now_ts)):
        replace_install_dir(install_dir, staged_dir)

    assert (install_dir / "ScanSort.exe").read_bytes() == b"new"
    assert (colliding / "marker.txt").read_text(encoding="utf-8") == "existing"


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
    original_rename = Path.rename

    def failing_rename(self, target):
        if self == staged_dir or "ScanSort.old-" in str(self):
            raise OSError(5, "access denied")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", failing_rename)

    with pytest.raises(UpdateError, match="preserved at"):
        replace_install_dir(install_dir, staged_dir)


def test_replace_install_dir_tolerates_backup_removal_failure(
    tmp_path: Path, monkeypatch
):
    install_dir = _make_tree(tmp_path, "ScanSort", "old")
    staged_dir = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "new")

    def locked_rmtree(path, ignore_errors=False):
        raise OSError(32, "file in use")

    monkeypatch.setattr("scansort.updater.installer.shutil.rmtree", locked_rmtree)

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

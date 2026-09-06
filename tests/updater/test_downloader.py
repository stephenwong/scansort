"""Unit tests for the release download, verification, and staging engine."""

import hashlib
import io
from dataclasses import replace
from pathlib import Path

import pytest

from scansort.updater.downloader import (
    download_and_stage,
    download_release,
    extract_bundle,
)
from scansort.updater.feed import (
    WINDOWS_ASSET_PREFIX,
    WINDOWS_ASSET_SUFFIX,
    ReleaseInfo,
)
from scansort.updater.installer import UpdateError

WINDOWS_ZIP = f"{WINDOWS_ASSET_PREFIX}v0.2.0{WINDOWS_ASSET_SUFFIX}"


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
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ScanSort.exe", marker)
        archive.writestr("_internal/module.py", b"print('x')\n")
        archive.writestr("emptydir/", b"")
    return buffer.getvalue()


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
        download_url=f"https://example.com/{WINDOWS_ZIP}",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        published_at=None,
    )


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
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(entry, b"boom")
    zip_path = tmp_path / "evil.zip"
    zip_path.write_bytes(buffer.getvalue())
    with pytest.raises(UpdateError, match="Unsafe archive entry"):
        extract_bundle(zip_path, tmp_path / "staged")


def test_extract_bundle_rejects_corrupt_archive_and_missing_exe(tmp_path: Path):
    import zipfile

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
    (tmp_dir / f"{WINDOWS_ASSET_PREFIX}v0.1.0{WINDOWS_ASSET_SUFFIX}").write_bytes(
        b"old archive"
    )
    leftover = _make_tree(tmp_path, "ScanSort.stage-0.2.0", "partial")
    (leftover / "junk").write_bytes(b"partial")

    def opener(request, timeout=None):
        return _BytesResponse(_release_zip_bytes(b"third"))

    stage = download_and_stage(info, install_dir, tmp_dir, opener=opener)
    assert (stage / "ScanSort.exe").read_bytes() == b"third"
    assert not (
        tmp_dir / f"{WINDOWS_ASSET_PREFIX}v0.1.0{WINDOWS_ASSET_SUFFIX}"
    ).exists()
    assert not (leftover / "junk").exists()


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
    old_zip = tmp_dir / f"{WINDOWS_ASSET_PREFIX}v0.1.0{WINDOWS_ASSET_SUFFIX}"
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

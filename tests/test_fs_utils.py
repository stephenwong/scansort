"""Unit tests for scansort.fs_utils module."""

from unittest.mock import patch

import pytest

from scansort.fs_utils import atomic_write, relative_folder_is_safe


def test_atomic_write_text_creates_file(tmp_path):
    target = tmp_path / "nested" / "out.json"
    atomic_write(target, '{"a": 1}')
    assert target.read_text(encoding="utf-8") == '{"a": 1}'


def test_atomic_write_bytes_creates_file(tmp_path):
    target = tmp_path / "data.bin"
    atomic_write(target, b"\x00\x01\xff")
    assert target.read_bytes() == b"\x00\x01\xff"


def test_atomic_write_overwrites_existing_file(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("old", encoding="utf-8")
    atomic_write(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_atomic_write_cleans_up_temp_file_on_replace_error(tmp_path):
    target = tmp_path / "file.txt"
    with (
        patch.object(type(target), "replace", side_effect=OSError("Read-only fs")),
        pytest.raises(OSError),
    ):
        atomic_write(target, "data")
    assert not target.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_error_propagates_and_no_temp_leak(tmp_path):
    target = tmp_path / "file.txt"
    with (
        patch("tempfile.NamedTemporaryFile", side_effect=OSError("Disk full")),
        pytest.raises(OSError),
    ):
        atomic_write(target, "data")
    assert list(tmp_path.glob("*.tmp")) == []


def test_relative_folder_is_safe_accepts_plain_paths():
    assert relative_folder_is_safe("Finances")
    assert relative_folder_is_safe("Finances/Banking/ANZ")
    assert relative_folder_is_safe("Finances\\Banking")
    assert relative_folder_is_safe(".")


def test_relative_folder_is_safe_rejects_absolutes_and_traversal():
    assert not relative_folder_is_safe("/absolute/path")
    assert not relative_folder_is_safe("\\absolute\\path")
    assert not relative_folder_is_safe("C:/Drive")
    assert not relative_folder_is_safe("C:\\Drive")
    assert not relative_folder_is_safe("../Escaped")
    assert not relative_folder_is_safe("Finances/../../Escaped")
    assert not relative_folder_is_safe("")
    assert not relative_folder_is_safe("   ")

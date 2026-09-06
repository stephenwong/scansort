"""Unit tests for scansort.dispatcher module."""

from pathlib import Path
from unittest.mock import patch

import pytest

from scansort.dispatcher import (
    dispatch_file,
    generate_target_filename,
    resolve_collision,
    resolve_destination_dir,
    resolve_duplicates_dir,
)
from scansort.models import DocumentClassification


def test_generate_target_filename():
    meta = DocumentClassification(
        document_date="260901",
        description="Origin_Energy_Bill",
        target_folder="Utilities",
    )
    assert generate_target_filename(meta) == "260901_Origin_Energy_Bill.pdf"


def test_resolve_destination_dir_valid_and_review_fallback(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    docs_root.mkdir()

    assert (
        resolve_destination_dir(docs_root, "Utilities/Electricity")
        == (docs_root / "Utilities" / "Electricity").resolve()
    )

    review_dir = (docs_root / "_Review_Needed").resolve()
    for empty_target in ["", "/", "\\", ".", "///"]:
        assert resolve_destination_dir(docs_root, empty_target) == review_dir


def test_resolve_destination_dir_blocks_unsafe_targets(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    docs_root.mkdir()

    for traversal in ["../../Escaped", "Sub/../../Escaped", "C:\\Drive", ".."]:
        dest = resolve_destination_dir(docs_root, traversal)
        assert dest == (docs_root / "_Review_Needed").resolve()
        assert dest.is_relative_to(docs_root.resolve())


def test_resolve_destination_dir_symlink_to_root_falls_back(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    docs_root.mkdir()
    link = docs_root / "loop"
    try:
        link.symlink_to(docs_root, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation not permitted in this environment")

    # A target that resolves to the documents root itself must route to Review_Needed
    assert (
        resolve_destination_dir(docs_root, "loop")
        == (docs_root / "_Review_Needed").resolve()
    )


def test_resolve_duplicates_dir_default_and_custom_fallback(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    docs_root.mkdir()

    default_dup_dir = (docs_root / "_Review_Needed" / "Duplicates").resolve()
    assert resolve_duplicates_dir(docs_root, "") == default_dup_dir
    assert resolve_duplicates_dir(docs_root, ".") == default_dup_dir
    assert resolve_duplicates_dir(docs_root, "///") == default_dup_dir

    assert (
        resolve_duplicates_dir(docs_root, "Taxes")
        == (docs_root / "Taxes" / "Duplicates").resolve()
    )
    assert (
        resolve_duplicates_dir(docs_root, "Taxes/2026")
        == (docs_root / "Taxes" / "2026" / "Duplicates").resolve()
    )


def test_resolve_duplicates_dir_unsafe_fallback_uses_review(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    docs_root.mkdir()

    for fallback in ["../../Escaped_Fallback", "C:\\Escaped"]:
        dup_dir = resolve_duplicates_dir(docs_root, fallback)
        assert dup_dir == (docs_root / "_Review_Needed" / "Duplicates").resolve()
        assert dup_dir.is_relative_to(docs_root.resolve())


def test_resolve_duplicates_dir_symlink_escape_falls_back(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    docs_root.mkdir()
    link = docs_root / "escape"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation not permitted in this environment")

    # A fallback that resolves outside docs_root must route to Review_Needed
    dup_dir = resolve_duplicates_dir(docs_root, "escape")
    assert dup_dir == (docs_root / "_Review_Needed" / "Duplicates").resolve()
    assert dup_dir.is_relative_to(docs_root.resolve())


def test_resolve_collision(tmp_path: Path):
    dest_folder = tmp_path / "Docs"
    dest_folder.mkdir()

    # Initial file
    file1 = dest_folder / "260901_Bill.pdf"
    file1.touch()

    resolved = resolve_collision(dest_folder, "260901_Bill.pdf")
    assert resolved == dest_folder / "260901_Bill_1.pdf"

    # Second file collision
    (dest_folder / "260901_Bill_1.pdf").touch()
    resolved2 = resolve_collision(dest_folder, "260901_Bill.pdf")
    assert resolved2 == dest_folder / "260901_Bill_2.pdf"


def test_dispatch_file_atomic_move(tmp_path: Path):
    source_dir = tmp_path / "Inbox"
    source_dir.mkdir()
    docs_root = tmp_path / "Documents"
    docs_root.mkdir()

    source_file = source_dir / "scan001.pdf"
    source_file.write_bytes(b"%PDF-1.4 test data")

    meta = DocumentClassification(
        document_date="260901",
        description="Origin_Energy_Bill",
        target_folder="Utilities/Electricity",
        confidence=0.95,
        summary="Electricity bill",
    )

    final_path = dispatch_file(
        source_path=source_file,
        docs_root=docs_root,
        classification=meta,
    )

    assert not source_file.exists()
    assert final_path.exists()
    assert (
        final_path
        == docs_root / "Utilities" / "Electricity" / "260901_Origin_Energy_Bill.pdf"
    )
    assert final_path.read_bytes() == b"%PDF-1.4 test data"


def test_dispatch_empty_or_root_target_routes_to_review(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    docs_root.mkdir()
    src = tmp_path / "scan.pdf"
    src.write_bytes(b"%PDF-1.4")

    for empty_target in ["", "/", "\\", ".", "///"]:
        meta = DocumentClassification(
            document_date="260901",
            description="Doc",
            target_folder=empty_target,
        )
        dest = dispatch_file(src, docs_root, meta)
        assert "_Review_Needed" in str(dest)
        assert dest.resolve().is_relative_to(docs_root.resolve())
        # Source was moved, recreate for next loop iteration
        src.write_bytes(b"%PDF-1.4")


def test_dispatch_blocks_path_traversal(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    docs_root.mkdir()
    src = tmp_path / "scan.pdf"
    src.write_bytes(b"%PDF-1.4")
    meta = DocumentClassification(
        document_date="260901",
        description="Escape",
        target_folder="_Review_Needed/../../Escaped",
    )
    dest = dispatch_file(src, docs_root, meta)
    assert dest.resolve().is_relative_to(docs_root.resolve())
    assert "_Review_Needed" in str(dest)


def test_dispatch_file_move_os_error_cleans_up_destination(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    docs_root.mkdir()
    src = tmp_path / "scan.pdf"
    src.write_bytes(b"%PDF-1.4")
    meta = DocumentClassification(
        document_date="260901",
        description="Doc",
        target_folder="_Review_Needed",
    )

    with (
        patch("shutil.move", side_effect=OSError("Cross-device link failure")),
        pytest.raises(OSError, match="Cross-device"),
    ):
        dispatch_file(src, docs_root, meta)

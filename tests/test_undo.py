"""Unit tests for scansort.undo module."""

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import scansort.dispatcher as dispatcher
from scansort.logging import AuditLogger
from scansort.undo import undo_last_move


def _create_undo_entry(original_path: Path, destination_path: Path) -> dict:
    return {
        "status": "SUCCESS",
        "original_filename": original_path.name,
        "new_filename": destination_path.name,
        "original_path": str(original_path),
        "destination_path": str(destination_path),
        "target_folder": "Utilities",
        "confidence": 0.95,
        "summary": "Bill",
        "sha256": "fakehash",
    }


def test_undo_last_move_success(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs = tmp_path / "Documents" / "Utilities"
    docs.mkdir(parents=True)

    moved_file = docs / "260901_Origin_Energy_Bill.pdf"
    moved_file.write_bytes(b"content")

    jsonl_path = tmp_path / "history.jsonl"
    original_inbox_file = inbox / "scan001.pdf"

    entry = _create_undo_entry(original_inbox_file, moved_file)
    jsonl_path.write_text(f"{json.dumps(entry)}\n", encoding="utf-8")

    undone_path = undo_last_move(jsonl_path)
    assert undone_path == inbox / f"_undone_{original_inbox_file.name}"
    assert undone_path.exists()
    assert not moved_file.exists()

    # Check status was updated
    last_line = jsonl_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert json.loads(last_line)["status"] == "UNDONE"


def test_undo_updates_csv_audit_log(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs = tmp_path / "Documents" / "Utilities"
    docs.mkdir(parents=True)

    moved_file = docs / "260901_Bill.pdf"
    moved_file.write_bytes(b"content")

    jsonl_path = tmp_path / "history.jsonl"
    csv_path = tmp_path / "history.csv"
    orig_file = inbox / "bill.pdf"

    logger = AuditLogger(jsonl_path=jsonl_path, csv_path=csv_path)
    logger.log_scan(_create_undo_entry(orig_file, moved_file))

    restored = undo_last_move(jsonl_path)
    assert restored is not None

    # Verify CSV has UNDONE status recorded
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert rows[-1]["Status"] == "UNDONE"


def test_undo_updates_mirror_csv_audit_log(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs = tmp_path / "Documents" / "Utilities"
    docs.mkdir(parents=True)

    moved_file = docs / "260901_Bill.pdf"
    moved_file.write_bytes(b"content")

    jsonl_path = tmp_path / "history.jsonl"
    csv_path = tmp_path / "history.csv"
    mirror_csv = tmp_path / "Documents" / "_ScanSort_History.csv"
    orig_file = inbox / "bill.pdf"

    AuditLogger(
        jsonl_path=jsonl_path, csv_path=csv_path, mirror_csv_path=mirror_csv
    ).log_scan(_create_undo_entry(orig_file, moved_file))

    restored = undo_last_move(jsonl_path, csv_path=csv_path, mirror_csv_path=mirror_csv)
    assert restored is not None

    # Verify both the primary and mirrored CSV logs recorded the UNDONE status
    for csv_target in [csv_path, mirror_csv]:
        with open(csv_target, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            assert len(rows) == 2
            assert rows[-1]["Status"] == "UNDONE"


def test_undo_skips_missing_destination_and_restores_earlier(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs = tmp_path / "Documents" / "Utilities"
    docs.mkdir(parents=True)

    # Earlier file exists
    f1 = docs / "260901_Older.pdf"
    f1.write_bytes(b"older")
    # Later file does not exist (was deleted manually by user)
    f2 = docs / "260902_Newer.pdf"

    jsonl_path = tmp_path / "history.jsonl"
    r1 = {
        "status": "SUCCESS",
        "destination_path": str(f1),
        "original_path": str(inbox / "older.pdf"),
    }
    r2 = {
        "status": "SUCCESS",
        "destination_path": str(f2),
        "original_path": str(inbox / "newer.pdf"),
    }
    jsonl_path.write_text(f"{json.dumps(r1)}\n{json.dumps(r2)}\n", encoding="utf-8")

    # Should skip missing f2 and restore f1
    restored = undo_last_move(jsonl_path)
    assert restored is not None
    assert restored == inbox / "_undone_older.pdf"
    assert restored.exists()
    assert not f1.exists()


def test_undo_permission_error_handled_cleanly(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    f = docs / "locked.pdf"
    f.touch()

    jsonl_path = tmp_path / "history.jsonl"
    r = {
        "status": "SUCCESS",
        "destination_path": str(f),
        "original_path": str(tmp_path / "inbox" / "scan.pdf"),
    }
    jsonl_path.write_text(json.dumps(r) + "\n", encoding="utf-8")

    with (
        patch("shutil.move", side_effect=PermissionError("[WinError 32] File locked")),
        pytest.raises(PermissionError, match="File locked"),
    ):
        undo_last_move(jsonl_path)

    # Ensure no UNDONE status was recorded in history
    last_line = jsonl_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert json.loads(last_line)["status"] == "SUCCESS"


def test_undo_skips_record_missing_original_path(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs = tmp_path / "Documents" / "Utilities"
    docs.mkdir(parents=True)

    older = docs / "260901_Older.pdf"
    older.write_bytes(b"older")
    newer = docs / "260902_Newer.pdf"
    newer.write_bytes(b"newer")

    jsonl_path = tmp_path / "history.jsonl"
    malformed = {
        "status": "SUCCESS",
        "destination_path": str(newer),  # existing, but missing original_path
    }
    valid = {
        "status": "SUCCESS",
        "destination_path": str(older),
        "original_path": str(inbox / "older.pdf"),
    }
    jsonl_path.write_text(f"{json.dumps(malformed)}\n{json.dumps(valid)}\n")

    restored = undo_last_move(jsonl_path)
    assert restored is not None
    assert restored == inbox / "_undone_older.pdf"
    assert not older.exists()


def test_undo_skips_directory_at_recorded_destination(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs = tmp_path / "Documents"
    docs.mkdir(parents=True)

    # The recorded "file" destination is now a populated directory.
    folder_dest = docs / "260901_Bill.pdf"
    folder_dest.mkdir()
    (folder_dest / "child.txt").write_text("user data")

    jsonl_path = tmp_path / "history.jsonl"
    r = {
        "status": "SUCCESS",
        "destination_path": str(folder_dest),
        "original_path": str(inbox / "scan.pdf"),
    }
    jsonl_path.write_text(json.dumps(r) + "\n")

    assert undo_last_move(jsonl_path) is None
    assert folder_dest.is_dir()
    assert (folder_dest / "child.txt").exists()
    assert not (inbox / "_undone_scan.pdf").exists()


def test_undo_nonexistent_history_file(tmp_path: Path):
    missing_file = tmp_path / "does_not_exist.jsonl"
    assert undo_last_move(missing_file) is None


def test_undo_empty_history_file(tmp_path: Path):
    empty_file = tmp_path / "empty.jsonl"
    empty_file.touch()
    assert undo_last_move(empty_file) is None


def test_undo_no_reversible_records(tmp_path: Path):
    no_rev_file = tmp_path / "no_rev.jsonl"
    no_rev_file.write_text('{"status": "DUPLICATE"}\n{invalid json\n', encoding="utf-8")
    assert undo_last_move(no_rev_file) is None


def test_undo_destination_file_missing(tmp_path: Path):
    hist_file = tmp_path / "hist.jsonl"
    entry = {
        "status": "SUCCESS",
        "destination_path": str(tmp_path / "ghost.pdf"),
        "original_path": str(tmp_path / "orig.pdf"),
    }
    hist_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    assert undo_last_move(hist_file) is None


def test_undo_does_not_clobber_existing_file(tmp_path: Path):
    history_file = tmp_path / "history.jsonl"
    filed_pdf = tmp_path / "docs" / "260901_Bill.pdf"
    filed_pdf.parent.mkdir(parents=True)
    filed_pdf.write_bytes(b"OLD FILED BILL")
    drop_file = tmp_path / "inbox" / "_undone_scan.pdf"
    drop_file.parent.mkdir(parents=True)
    drop_file.write_bytes(b"NEW ARRIVING SCAN")
    record = {
        "status": "SUCCESS",
        "destination_path": str(filed_pdf),
        "original_path": str(tmp_path / "inbox" / "scan.pdf"),
        "new_filename": "260901_Bill.pdf",
    }
    history_file.write_text(json.dumps(record) + "\n")
    restored = undo_last_move(history_file)
    assert drop_file.read_bytes() == b"NEW ARRIVING SCAN"
    assert restored != drop_file
    assert restored.read_bytes() == b"OLD FILED BILL"


def test_undo_preserves_pdf_extension_for_converted_images(tmp_path: Path):
    history_file = tmp_path / "history.jsonl"
    dest_pdf = tmp_path / "docs" / "filed.pdf"
    dest_pdf.parent.mkdir(parents=True)
    dest_pdf.write_bytes(b"%PDF-1.4")
    orig_jpg = tmp_path / "inbox" / "scan.jpg"
    record = {
        "status": "SUCCESS",
        "destination_path": str(dest_pdf),
        "original_path": str(orig_jpg),
    }
    history_file.write_text(json.dumps(record) + "\n")
    restored = undo_last_move(history_file)
    assert restored.suffix == ".pdf"


def test_undo_multiple_moves(tmp_path: Path):
    hist = tmp_path / "history.jsonl"
    f1 = tmp_path / "d1.pdf"
    f1.touch()
    f2 = tmp_path / "d2.pdf"
    f2.touch()
    r1 = {
        "status": "SUCCESS",
        "destination_path": str(f1),
        "original_path": str(tmp_path / "o1.pdf"),
    }
    r2 = {
        "status": "SUCCESS",
        "destination_path": str(f2),
        "original_path": str(tmp_path / "o2.pdf"),
    }
    hist.write_text(f"{json.dumps(r1)}\n{json.dumps(r2)}\n")
    assert undo_last_move(hist) is not None
    assert undo_last_move(hist) is not None
    assert undo_last_move(hist) is None


def test_undo_log_write_os_error(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()

    f = docs / "doc.pdf"
    f.touch()

    jsonl_path = tmp_path / "hist.jsonl"
    r = {
        "status": "SUCCESS",
        "destination_path": str(f),
        "original_path": str(inbox / "scan.pdf"),
    }
    jsonl_path.write_text(json.dumps(r) + "\n")

    orig_open = open

    def mock_open_append(file, mode="r", *args, **kwargs):
        if str(file) == str(jsonl_path) and "a" in mode:
            raise OSError("Read-only filesystem")
        return orig_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open_append):
        # Even if appending to jsonl fails, undo restores the file
        restored = undo_last_move(jsonl_path)
        assert restored is not None


def test_undo_csv_write_os_error(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()

    f = docs / "doc.pdf"
    f.touch()

    jsonl_path = tmp_path / "hist.jsonl"
    csv_path = tmp_path / "hist.csv"
    csv_path.touch()

    r = {
        "status": "SUCCESS",
        "destination_path": str(f),
        "original_path": str(inbox / "scan.pdf"),
    }
    jsonl_path.write_text(json.dumps(r) + "\n")

    orig_open = open

    def mock_open_csv_fail(file, mode="r", *args, **kwargs):
        if str(file) == str(csv_path) and "a" in mode:
            raise OSError("CSV locked")
        return orig_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open_csv_fail):
        restored = undo_last_move(jsonl_path)
        assert restored is not None


def test_undo_read_os_error(tmp_path: Path):
    jsonl_path = tmp_path / "history.jsonl"
    jsonl_path.write_text('{"status": "SUCCESS"}\n', encoding="utf-8")

    with patch.object(Path, "read_text", side_effect=OSError("Disk unreadable")):
        assert undo_last_move(jsonl_path) is None


def test_undo_skips_non_dict_and_blank_lines(tmp_path: Path):
    jsonl_path = tmp_path / "history.jsonl"
    jsonl_path.write_text('\n\n12345\n   \n"just a string"\n', encoding="utf-8")
    assert undo_last_move(jsonl_path) is None


def test_dispatcher_re_exports_undo_last_move():
    assert dispatcher.undo_last_move is undo_last_move

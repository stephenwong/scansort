"""Unit tests for scansort.hasher module (TDD Cycle 4)."""

import hashlib
import json
from pathlib import Path

from scansort.hasher import check_duplicate, compute_file_sha256


def test_compute_file_sha256(tmp_path: Path):
    test_file = tmp_path / "document.pdf"
    content = b"PDF Document binary stream contents for hashing"
    test_file.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    actual_hash = compute_file_sha256(test_file)
    assert actual_hash == expected_hash


def test_check_duplicate_not_found(tmp_path: Path):
    history_file = tmp_path / "history.jsonl"
    history_file.write_text('{"sha256": "aaaa1111", "new_filename": "doc1.pdf"}\n', encoding="utf-8")

    result = check_duplicate("bbbb2222", history_file)
    assert result is None


def test_check_duplicate_found(tmp_path: Path):
    history_file = tmp_path / "history.jsonl"
    record1 = {"sha256": "aaaa1111", "new_filename": "260901_Origin_Energy.pdf", "status": "SUCCESS"}
    record2 = {"sha256": "cccc3333", "new_filename": "260902_Tax_Notice.pdf", "status": "SUCCESS"}
    history_file.write_text(
        f"{json.dumps(record1)}\n{json.dumps(record2)}\n", encoding="utf-8"
    )

    found = check_duplicate("aaaa1111", history_file)
    assert found is not None
    assert found["new_filename"] == "260901_Origin_Energy.pdf"


def test_check_duplicate_missing_history_file(tmp_path: Path):
    missing_history = tmp_path / "no_history.jsonl"
    assert check_duplicate("somehash", missing_history) is None

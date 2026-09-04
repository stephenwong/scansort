"""Unit tests for scansort.hasher module."""

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
    history_file.write_text(
        '{"sha256": "aaaa1111", "new_filename": "doc1.pdf"}\n', encoding="utf-8"
    )

    result = check_duplicate("bbbb2222", history_file)
    assert result is None


def test_check_duplicate_found(tmp_path: Path):
    history_file = tmp_path / "history.jsonl"
    record1 = {
        "sha256": "aaaa1111",
        "new_filename": "260901_Origin_Energy.pdf",
        "status": "SUCCESS",
    }
    record2 = {
        "sha256": "cccc3333",
        "new_filename": "260902_Tax_Notice.pdf",
        "status": "SUCCESS",
    }
    history_file.write_text(
        f"{json.dumps(record1)}\n{json.dumps(record2)}\n", encoding="utf-8"
    )

    found = check_duplicate("aaaa1111", history_file)
    assert found is not None
    assert found["new_filename"] == "260901_Origin_Energy.pdf"


def test_check_duplicate_missing_history_file(tmp_path: Path):
    missing_history = tmp_path / "no_history.jsonl"
    assert check_duplicate("somehash", missing_history) is None


from unittest.mock import patch


def test_check_duplicate_skips_empty_and_corrupt_lines(tmp_path: Path):
    history_file = tmp_path / "history.jsonl"
    content = (
        "\n\n{invalid json target_hash\n"
        + json.dumps({"sha256": "target_hash", "new_filename": "found.pdf"})
        + "\n"
    )
    history_file.write_text(content, encoding="utf-8")

    result = check_duplicate("target_hash", history_file)
    assert result is not None
    assert result["new_filename"] == "found.pdf"


def test_check_duplicate_handles_os_error(tmp_path: Path):
    history_file = tmp_path / "history.jsonl"
    history_file.touch()
    with patch("builtins.open", side_effect=OSError("Read error")):
        assert check_duplicate("somehash", history_file) is None


def test_check_duplicate_ignores_undone(tmp_path: Path):
    hist = tmp_path / "history.jsonl"
    h = "a" * 64
    r1 = {"sha256": h, "status": "SUCCESS"}
    r2 = {"sha256": h, "status": "UNDONE"}
    hist.write_text(f"{json.dumps(r1)}\n{json.dumps(r2)}\n")
    assert check_duplicate(h, hist) is None


def test_compute_file_sha256_invalid_chunk_size(tmp_path: Path):
    import pytest

    test_file = tmp_path / "doc.pdf"
    test_file.write_bytes(b"content")

    with pytest.raises(ValueError, match="chunk_size must be greater than 0"):
        compute_file_sha256(test_file, chunk_size=0)

    with pytest.raises(ValueError, match="chunk_size must be greater than 0"):
        compute_file_sha256(test_file, chunk_size=-1024)


def test_check_duplicate_mid_stream_os_error_returns_none(tmp_path: Path):
    hist = tmp_path / "history.jsonl"
    h = "a" * 64
    r1 = {"sha256": h, "status": "SUCCESS"}
    hist.write_text(f"{json.dumps(r1)}\n")

    class FaultyFile:
        def __init__(self):
            self.lines = [json.dumps(r1) + "\n"]
            self.iterated = 0

        def __iter__(self):
            return self

        def __next__(self):
            if self.iterated == 0:
                self.iterated += 1
                return self.lines[0]
            raise OSError("I/O device detached mid-read")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("builtins.open", return_value=FaultyFile()):
        # Mid-stream error must return None, not r1
        assert check_duplicate(h, hist) is None

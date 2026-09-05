"""Unit tests for scansort.folder_hints module."""

import json
from pathlib import Path

from scansort.folder_hints import get_default_hints_path, load_folder_hints


def test_get_default_hints_path():
    path = get_default_hints_path()
    assert path.name == "folder_hints.json"


def test_load_folder_hints_nonexistent_returns_empty(tmp_path: Path):
    hints_file = tmp_path / "hints.json"
    assert load_folder_hints(hints_file) == {}


def test_load_folder_hints_valid(tmp_path: Path):
    hints_file = tmp_path / "folder_hints.json"
    data = {
        "Health/Dental": ["dentist", "teeth", "bupa"],
        "Utilities\\Electricity": ["energy", "origin"],
    }
    hints_file.write_text(json.dumps(data), encoding="utf-8")

    hints = load_folder_hints(hints_file)
    assert "Health/Dental" in hints
    assert hints["Health/Dental"] == ["dentist", "teeth", "bupa"]
    # Verify path normalization (backslashes converted to forward slashes)
    assert "Utilities/Electricity" in hints
    assert hints["Utilities/Electricity"] == ["energy", "origin"]


def test_load_folder_hints_invalid_format(tmp_path: Path):
    invalid_file = tmp_path / "hints.json"
    invalid_file.write_text('["not", "a", "dict"]', encoding="utf-8")
    assert load_folder_hints(invalid_file) == {}


def test_load_folder_hints_corrupt(tmp_path: Path):
    corrupt_file = tmp_path / "corrupt_hints.json"
    corrupt_file.write_text("{bad json", encoding="utf-8")
    assert load_folder_hints(corrupt_file) == {}


def test_folder_hints_ignores_none_and_non_strings(tmp_path: Path):
    hints_file = tmp_path / "hints_with_null.json"
    data = {"Finances": ["tax", None, 123, "invoice"]}
    hints_file.write_text(json.dumps(data), encoding="utf-8")
    hints = load_folder_hints(hints_file)
    assert hints["Finances"] == ["tax", "invoice"]
    assert "none" not in hints["Finances"]
    assert "123" not in hints["Finances"]


def test_load_folder_hints_utf8_bom(tmp_path: Path):
    hints_file = tmp_path / "hints_bom.json"
    data = '{"Tax/2026": ["ato", "return"]}'
    hints_file.write_bytes(b"\xef\xbb\xbf" + data.encode("utf-8"))
    hints = load_folder_hints(hints_file)
    assert "Tax/2026" in hints
    assert hints["Tax/2026"] == ["ato", "return"]

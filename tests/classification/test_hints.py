"""Unit tests for scansort.folder_hints module."""

import json
from pathlib import Path

from scansort.classification.hints import get_default_hints_path, load_folder_hints


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


def test_save_folder_hints_writes_atomically_and_sorted(tmp_path: Path):
    from scansort.classification.hints import save_folder_hints

    hints_file = tmp_path / "folder_hints.json"
    hints = {
        "Utilities/Power": ["electricity", "origin"],
        "Health/Dental": ["dentist", "teeth"],
    }
    save_folder_hints(hints, hints_path=hints_file)

    assert hints_file.exists()
    content = hints_file.read_text(encoding="utf-8-sig")
    loaded = json.loads(content)
    assert loaded == hints
    # Ensure keys are sorted deterministically
    keys = list(loaded.keys())
    assert keys == ["Health/Dental", "Utilities/Power"]


def test_add_folder_hint_creates_and_updates_mappings(tmp_path: Path):
    from scansort.classification.hints import add_folder_hint

    hints_file = tmp_path / "folder_hints.json"

    # Add single keyword to new folder
    res = add_folder_hint("Health\\Dental", "Dentist", hints_path=hints_file)
    assert "Health/Dental" in res
    assert res["Health/Dental"] == ["dentist"]

    # Add multiple keywords including duplicates and uppercase
    res = add_folder_hint(
        "Health/Dental",
        ["teeth", "DENTIST", "Bupa Dental", "  "],
        hints_path=hints_file,
    )
    assert res["Health/Dental"] == ["dentist", "teeth", "bupa dental"]

    # Re-adding identical keywords is a no-op (file mtime unchanged)
    mtime_before = hints_file.stat().st_mtime_ns
    res_noop = add_folder_hint(
        "Health/Dental",
        ["teeth", "dentist"],
        hints_path=hints_file,
    )
    assert res_noop == res
    assert hints_file.stat().st_mtime_ns == mtime_before

    # Verify on-disk persistence
    disk_hints = load_folder_hints(hints_file)
    assert disk_hints == res

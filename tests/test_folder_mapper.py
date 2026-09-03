"""Unit tests for scansort.folder_mapper module (TDD Cycle 3)."""

import json
from pathlib import Path

from scansort.folder_mapper import (
    FolderMapper,
    format_taxonomy_for_prompt,
    scan_documents_folders,
)


def test_scan_folders_empty_directory(tmp_path: Path):
    docs_dir = tmp_path / "Documents"
    docs_dir.mkdir()
    folders = scan_documents_folders(docs_dir)
    assert folders == []


def test_scan_folders_discovers_nested_hierarchy(tmp_path: Path):
    docs_dir = tmp_path / "Documents"
    (docs_dir / "Finances" / "Banking" / "ANZ").mkdir(parents=True)
    (docs_dir / "Finances" / "Taxes").mkdir(parents=True)
    (docs_dir / "Health" / "Dental").mkdir(parents=True)
    (docs_dir / "Utilities").mkdir(parents=True)

    folders = scan_documents_folders(docs_dir, max_depth=3)
    assert "Finances" in folders
    assert "Finances/Banking" in folders
    assert "Finances/Banking/ANZ" in folders
    assert "Finances/Taxes" in folders
    assert "Health/Dental" in folders
    assert "Utilities" in folders


def test_scan_folders_filters_noise_and_dotfolders(tmp_path: Path):
    docs_dir = tmp_path / "Documents"
    (docs_dir / "Finances" / "Invoices").mkdir(parents=True)
    (docs_dir / "My Games" / "Saves").mkdir(parents=True)
    (docs_dir / "Zoom" / "2026-01-01").mkdir(parents=True)
    (docs_dir / ".git" / "refs").mkdir(parents=True)
    (docs_dir / ".vscode").mkdir(parents=True)
    (docs_dir / "Custom Office Templates").mkdir(parents=True)

    folders = scan_documents_folders(docs_dir)
    assert "Finances/Invoices" in folders
    assert "Finances" in folders

    for folder in folders:
        assert not folder.startswith(".")
        assert "My Games" not in folder
        assert "Zoom" not in folder
        assert "Custom Office Templates" not in folder


def test_scan_folders_respects_max_depth(tmp_path: Path):
    docs_dir = tmp_path / "Documents"
    (docs_dir / "L1" / "L2" / "L3" / "L4").mkdir(parents=True)

    folders_d2 = scan_documents_folders(docs_dir, max_depth=2)
    assert "L1" in folders_d2
    assert "L1/L2" in folders_d2
    assert "L1/L2/L3" not in folders_d2

    folders_d3 = scan_documents_folders(docs_dir, max_depth=3)
    assert "L1/L2/L3" in folders_d3
    assert "L1/L2/L3/L4" not in folders_d3


def test_scan_folders_ignores_fallback_review_folder(tmp_path: Path):
    docs_dir = tmp_path / "Documents"
    (docs_dir / "Receipts").mkdir(parents=True)
    (docs_dir / "_Review_Needed" / "Duplicates").mkdir(parents=True)

    folders = scan_documents_folders(docs_dir, fallback_folder="_Review_Needed")
    assert "Receipts" in folders
    for f in folders:
        assert not f.startswith("_Review_Needed")


def test_format_taxonomy_for_prompt():
    folders = ["Finances/Banking/ANZ", "Health/Dental", "Utilities/Electricity"]
    hints = {
        "Health/Dental": ["dentist", "bupa"],
        "Utilities/Electricity": ["energy", "origin"],
    }
    prompt_str = format_taxonomy_for_prompt(folders, hints)
    assert "Finances/Banking/ANZ" in prompt_str
    assert "Health/Dental (Hints: dentist, bupa)" in prompt_str
    assert "Utilities/Electricity (Hints: energy, origin)" in prompt_str


def test_folder_mapper_class_caching(tmp_path: Path):
    docs_dir = tmp_path / "Documents"
    cache_file = tmp_path / "folder_map.json"
    (docs_dir / "Work" / "Contracts").mkdir(parents=True)

    mapper = FolderMapper(docs_root=docs_dir, cache_path=cache_file)
    discovered = mapper.refresh()
    assert "Work/Contracts" in discovered
    assert cache_file.exists()

    # Load from cache
    saved_data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "Work/Contracts" in saved_data["folders"]

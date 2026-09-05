"""Unit tests for scansort.folder_mapper module."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_scan_nonexistent_directory(tmp_path: Path):
    missing_dir = tmp_path / "missing_dir"
    assert scan_documents_folders(missing_dir) == []


def test_scan_handles_permission_error(tmp_path: Path):
    docs_dir = tmp_path / "Docs"
    (docs_dir / "Allowed").mkdir(parents=True)
    with patch.object(Path, "iterdir", side_effect=PermissionError("Denied")):
        assert scan_documents_folders(docs_dir) == []


def test_format_taxonomy_empty():
    assert format_taxonomy_for_prompt([]) == "No pre-existing folders detected."


def test_folder_mapper_load_from_cache_and_prompt_string(tmp_path: Path):
    docs_dir = tmp_path / "Docs"
    (docs_dir / "Finances").mkdir(parents=True)
    cache_file = tmp_path / "cache.json"

    mapper = FolderMapper(docs_root=docs_dir, cache_path=cache_file)
    assert mapper.get_prompt_string() is not None

    # Test loading from cache on new instance
    mapper2 = FolderMapper(docs_root=docs_dir, cache_path=cache_file)
    assert "Finances" in mapper2.get_taxonomy()
    # Call again to test if _cached_folders already populated
    assert "Finances" in mapper2.get_taxonomy()


def test_folder_mapper_cache_write_error(tmp_path: Path):
    docs_dir = tmp_path / "Docs"
    docs_dir.mkdir()
    cache_file = tmp_path / "cache.json"
    mapper = FolderMapper(docs_root=docs_dir, cache_path=cache_file)
    with patch.object(Path, "replace", side_effect=OSError("Read-only filesystem")):
        # Should not raise exception
        folders = mapper.refresh()
        assert folders == []


def test_scan_folders_case_insensitive_fallback(tmp_path: Path):
    docs_dir = tmp_path / "Documents"
    (docs_dir / "Receipts").mkdir(parents=True)
    (docs_dir / "_review_needed").mkdir(parents=True)

    folders = scan_documents_folders(docs_dir, fallback_folder="_Review_Needed")
    assert "Receipts" in folders
    assert "_review_needed" not in folders


def test_format_taxonomy_case_insensitive_hints():
    folders = ["Health/Dental"]
    hints = {"health/dental": ["teeth", "dentist"]}
    prompt = format_taxonomy_for_prompt(folders, hints)
    assert "Health/Dental (Hints: teeth, dentist)" in prompt


def test_cache_invalidation_on_docs_root_change(tmp_path: Path):
    dir_a = tmp_path / "DocsA"
    dir_b = tmp_path / "DocsB"
    (dir_a / "FolderA").mkdir(parents=True)
    (dir_b / "FolderB").mkdir(parents=True)
    cache_file = tmp_path / "cache.json"

    mapper_a = FolderMapper(docs_root=dir_a, cache_path=cache_file)
    mapper_a.refresh()

    mapper_b = FolderMapper(docs_root=dir_b, cache_path=cache_file)
    tax_b = mapper_b.get_taxonomy()
    assert "FolderB" in tax_b
    assert "FolderA" not in tax_b


def test_cache_corrupt_format_list_handling(tmp_path: Path):
    docs_dir = tmp_path / "Docs"
    (docs_dir / "Bills").mkdir(parents=True)
    cache_file = tmp_path / "cache.json"
    cache_file.write_text('["not", "a", "dict"]', encoding="utf-8")

    mapper = FolderMapper(docs_root=docs_dir, cache_path=cache_file)
    tax = mapper.get_taxonomy()
    assert "Bills" in tax


def test_empty_taxonomy_memory_caching(tmp_path: Path):
    docs_dir = tmp_path / "EmptyDocs"
    docs_dir.mkdir()
    mapper = FolderMapper(docs_root=docs_dir, cache_path=tmp_path / "cache.json")
    assert mapper.get_taxonomy() == []
    # Verify second call returns the cached empty list
    assert mapper._cached_folders == []
    assert mapper.get_taxonomy() == []


def test_scan_folders_trailing_slash_fallback(tmp_path: Path):
    docs_dir = tmp_path / "Documents"
    (docs_dir / "Bills").mkdir(parents=True)
    (docs_dir / "_Review_Needed" / "Duplicates").mkdir(parents=True)

    folders = scan_documents_folders(docs_dir, fallback_folder="_Review_Needed/")
    assert "Bills" in folders
    for f in folders:
        assert not f.startswith("_Review_Needed")


def test_scan_folders_inaccessible_sibling_does_not_drop_others(tmp_path: Path):
    docs_dir = tmp_path / "Documents"
    good1 = docs_dir / "Alpha"
    bad = docs_dir / "Restricted"
    good2 = docs_dir / "Beta"
    good1.mkdir(parents=True)
    bad.mkdir(parents=True)
    good2.mkdir(parents=True)

    orig_is_dir = Path.is_dir

    def mock_is_dir(self):
        if self.name == "Restricted":
            raise PermissionError("Access Denied")
        return orig_is_dir(self)

    with patch.object(Path, "is_dir", side_effect=mock_is_dir, autospec=True):
        folders = scan_documents_folders(docs_dir)
        assert "Alpha" in folders
        assert "Beta" in folders
        assert "Restricted" not in folders


def test_folder_mapper_external_cache_mtime_update_reloads(tmp_path: Path):
    docs_dir = tmp_path / "Documents"
    (docs_dir / "Alpha").mkdir(parents=True)
    cache_file = tmp_path / "folder_map.json"

    mapper = FolderMapper(docs_root=docs_dir, cache_path=cache_file)
    assert mapper.get_taxonomy() == ["Alpha"]

    # External modification (simulating another process running rescan)
    (docs_dir / "Beta").mkdir()
    new_data = {"documents_root": str(docs_dir), "folders": ["Alpha", "Beta"]}
    cache_file.write_text(json.dumps(new_data), encoding="utf-8")
    mtime = cache_file.stat().st_mtime + 5.0
    os.utime(cache_file, (mtime, mtime))

    assert mapper.get_taxonomy() == ["Alpha", "Beta"]


def test_format_taxonomy_unnormalized_backslashes_in_hints():
    folders = ["Tax/2026"]
    hints = {"Tax\\2026": ["ato"]}
    prompt = format_taxonomy_for_prompt(folders, hints)
    assert "Tax/2026 (Hints: ato)" in prompt


def test_folder_mapper_docs_root_resolved_cache_hit(tmp_path: Path):
    docs_dir = tmp_path / "Documents"
    (docs_dir / "Folder").mkdir(parents=True)
    cache_file = tmp_path / "cache.json"

    new_data = {"documents_root": str(docs_dir) + "/.", "folders": ["Folder"]}
    cache_file.write_text(json.dumps(new_data), encoding="utf-8")

    mapper = FolderMapper(docs_root=docs_dir, cache_path=cache_file)
    assert mapper.get_taxonomy() == ["Folder"]
    assert mapper._cached_folders == ["Folder"]


def test_cache_invalid_json_fallback(tmp_path: Path):
    docs_dir = tmp_path / "Docs"
    (docs_dir / "Bills").mkdir(parents=True)
    cache_file = tmp_path / "cache.json"
    cache_file.write_text("{bad json syntax", encoding="utf-8")

    mapper = FolderMapper(docs_root=docs_dir, cache_path=cache_file)
    tax = mapper.get_taxonomy()
    assert "Bills" in tax


def test_cache_mtime_stat_oserror(tmp_path: Path):
    docs_dir = tmp_path / "Docs"
    (docs_dir / "Alpha").mkdir(parents=True)
    cache_file = tmp_path / "cache.json"

    mapper = FolderMapper(docs_root=docs_dir, cache_path=cache_file)
    assert mapper.get_taxonomy() == ["Alpha"]

    # When stat raises OSError
    with patch.object(Path, "stat", side_effect=OSError("Disk error")):
        # Should cleanly return in-memory cached folders without crashing
        assert mapper.get_taxonomy() == ["Alpha"]


def test_folder_mapper_ttl_picks_up_new_folders(tmp_path: Path, monkeypatch):
    docs_root = tmp_path / "Documents"
    (docs_root / "Alpha").mkdir(parents=True)
    mapper = FolderMapper(
        docs_root=docs_root,
        cache_path=tmp_path / "folder_map.json",
    )
    mapper.refresh()
    assert mapper.get_taxonomy() == ["Alpha"]

    # A folder created after the cached scan must be picked up once stale.
    (docs_root / "Beta").mkdir()
    monkeypatch.setattr("scansort.folder_mapper.TAXONOMY_CACHE_MAX_AGE_SECONDS", 0.0)
    taxonomy = mapper.get_taxonomy()
    assert "Beta" in taxonomy
    assert "Alpha" in taxonomy


def test_folder_mapper_ttl_drops_deleted_folders(tmp_path: Path, monkeypatch):
    docs_root = tmp_path / "Documents"
    (docs_root / "Gamma").mkdir(parents=True)
    mapper = FolderMapper(
        docs_root=docs_root,
        cache_path=tmp_path / "folder_map.json",
    )
    mapper.refresh()
    assert mapper.get_taxonomy() == ["Gamma"]

    import shutil

    shutil.rmtree(docs_root / "Gamma")
    monkeypatch.setattr("scansort.folder_mapper.TAXONOMY_CACHE_MAX_AGE_SECONDS", 0.0)
    assert mapper.get_taxonomy() == []


def test_folder_mapper_load_prunes_deleted_folders(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    (docs_root / "Keep").mkdir(parents=True)
    (docs_root / "Ghost").mkdir(parents=True)
    cache_path = tmp_path / "folder_map.json"

    first = FolderMapper(docs_root=docs_root, cache_path=cache_path)
    first.refresh()

    import shutil

    shutil.rmtree(docs_root / "Ghost")

    second = FolderMapper(docs_root=docs_root, cache_path=cache_path)
    assert second.get_taxonomy() == ["Keep"]


def test_scan_folders_skips_symlinked_directories(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    (docs_root / "Real").mkdir(parents=True)
    external = tmp_path / "ExternalData"
    (external / "SecretProject").mkdir(parents=True)
    try:
        (docs_root / "Linked").symlink_to(external, target_is_directory=True)
    except OSError, NotImplementedError:
        import pytest as _pytest

        _pytest.skip("Symlinks unavailable on this platform")

    result = scan_documents_folders(docs_root)
    assert result == ["Real"]
    assert not any("SecretProject" in folder for folder in result)


def test_scan_folders_skips_windows_hidden_attribute(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    docs_root = tmp_path / "Documents"
    (docs_root / "Private").mkdir(parents=True)
    (docs_root / "Visible").mkdir(parents=True)

    import os as _os
    import types

    import scansort.folder_mapper as folder_mapper

    def fake_stat(path, *args, **kwargs):
        if str(path).endswith("Private"):
            fake = MagicMock()
            fake.st_file_attributes = 0x2  # FILE_ATTRIBUTE_HIDDEN
            return fake
        return _os.stat(path, *args, **kwargs)

    # Swap only folder_mapper's own os binding so pathlib internals stay real.
    monkeypatch.setattr(folder_mapper, "os", types.SimpleNamespace(stat=fake_stat))

    result = scan_documents_folders(docs_root)
    assert result == ["Visible"]

    monkeypatch.setattr("sys.platform", "linux")
    assert scan_documents_folders(docs_root) == ["Private", "Visible"]

"""Unit tests for scansort.core.config module."""

import json
from pathlib import Path

import pytest

from scansort.core.config import (
    AppConfig,
    get_default_app_dir,
    get_default_config_path,
    load_config,
    save_config,
)
from scansort.core.constants import DEFAULT_GEMINI_MODEL


def test_default_config():
    cfg = AppConfig()
    assert cfg.gemini_model == DEFAULT_GEMINI_MODEL
    assert cfg.fallback_folder == "_Review_Needed"
    assert cfg.start_on_boot is True
    assert cfg.max_folder_depth == 3
    assert cfg.dry_run is False
    assert cfg.mirror_log_to_documents is False
    assert cfg.watch_folder is not None
    assert cfg.documents_root is not None


def test_save_and_load_config(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    custom_watch = tmp_path / "IncomingScans"
    custom_docs = tmp_path / "MyDocs"

    original_cfg = AppConfig(
        watch_folder=custom_watch,
        documents_root=custom_docs,
        gemini_model="gemini-3.5-flash-lite",
        fallback_folder="Unsorted",
        start_on_boot=False,
        max_folder_depth=5,
        dry_run=True,
        mirror_log_to_documents=True,
    )

    save_config(original_cfg, cfg_file)
    assert cfg_file.exists()

    loaded_cfg = load_config(cfg_file)
    assert loaded_cfg.watch_folder == custom_watch.resolve()
    assert loaded_cfg.documents_root == custom_docs.resolve()
    assert loaded_cfg.gemini_model == "gemini-3.5-flash-lite"
    assert loaded_cfg.fallback_folder == "Unsorted"
    assert loaded_cfg.start_on_boot is False
    assert loaded_cfg.max_folder_depth == 5
    assert loaded_cfg.dry_run is True
    assert loaded_cfg.mirror_log_to_documents is True


def test_config_never_serializes_api_keys(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    cfg = AppConfig()
    save_config(cfg, cfg_file)

    content = cfg_file.read_text(encoding="utf-8")
    assert "api_key" not in content
    assert "gemini_api_key" not in content
    assert "AIza" not in content


def test_ensure_directories_creates_missing(tmp_path: Path):
    watch_dir = tmp_path / "drop"
    docs_dir = tmp_path / "docs"

    assert not watch_dir.exists()
    assert not docs_dir.exists()

    cfg = AppConfig(watch_folder=watch_dir, documents_root=docs_dir)
    cfg.ensure_directories()

    assert watch_dir.is_dir()
    assert docs_dir.is_dir()
    assert (docs_dir / "_Review_Needed").is_dir()


def test_load_nonexistent_config_returns_default(tmp_path: Path):
    missing_file = tmp_path / "does_not_exist.json"
    cfg = load_config(missing_file)
    assert isinstance(cfg, AppConfig)


def test_get_default_config_path():
    path = get_default_config_path()
    assert path.name == "config.json"
    assert "ScanSort" in str(path) or "scansort" in str(path)


def test_get_default_app_dir_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("APPDATA", "C:\\Users\\Test\\AppData\\Roaming")

    app_dir = get_default_app_dir()
    assert "ScanSort" in str(app_dir)
    assert "AppData" in str(app_dir)


def test_load_config_corrupt_json_fallback(tmp_path: Path):
    corrupt_file = tmp_path / "corrupt_config.json"
    corrupt_file.write_text("{invalid json", encoding="utf-8")
    cfg = load_config(corrupt_file)
    assert isinstance(cfg, AppConfig)
    assert cfg.gemini_model == DEFAULT_GEMINI_MODEL


def test_config_gemini_model_validation():
    assert AppConfig(gemini_model="").gemini_model == DEFAULT_GEMINI_MODEL
    assert AppConfig(gemini_model="   ").gemini_model == DEFAULT_GEMINI_MODEL
    assert AppConfig(gemini_model=None).gemini_model == DEFAULT_GEMINI_MODEL
    assert (
        AppConfig(gemini_model="gemini-3.5-flash-lite").gemini_model
        == "gemini-3.5-flash-lite"
    )
    assert (
        AppConfig(gemini_model="gemini-3.1-flash-lite-001").gemini_model
        == "gemini-3.1-flash-lite-001"
    )

    with pytest.raises(ValueError, match="gemini_model must be one of"):
        AppConfig(gemini_model="gemini-2.5-flash")

    with pytest.raises(ValueError, match="gemini_model must be one of"):
        AppConfig(gemini_model="unsupported-model")


def test_fallback_folder_validation():
    with pytest.raises(ValueError, match="fallback_folder cannot contain absolute"):
        AppConfig(fallback_folder="/absolute/path")

    with pytest.raises(ValueError, match="fallback_folder cannot contain absolute"):
        AppConfig(fallback_folder="../../escaped")

    with pytest.raises(ValueError, match="fallback_folder cannot be empty"):
        AppConfig(fallback_folder="   ")


def test_load_config_type_error_handling(tmp_path: Path):
    null_file = tmp_path / "null_config.json"
    null_file.write_text("null", encoding="utf-8")
    cfg = load_config(null_file)
    assert isinstance(cfg, AppConfig)

    list_file = tmp_path / "list_config.json"
    list_file.write_text("[]", encoding="utf-8")
    cfg = load_config(list_file)
    assert isinstance(cfg, AppConfig)

    bad_field_file = tmp_path / "bad_field.json"
    bad_field_file.write_text(
        '{"watch_folder": null, "documents_root": null}', encoding="utf-8"
    )
    cfg = load_config(bad_field_file)
    assert isinstance(cfg, AppConfig)


def test_fallback_folder_windows_drive_traversal_rejected():
    with pytest.raises(ValueError, match="cannot contain absolute paths"):
        AppConfig(fallback_folder="C:\\escaped")

    with pytest.raises(ValueError, match="cannot contain absolute paths"):
        AppConfig(fallback_folder="D:/Review")


def test_fallback_folder_trailing_slash_trimmed():
    cfg = AppConfig(fallback_folder="_Review_Needed/")
    assert cfg.fallback_folder == "_Review_Needed"

    cfg2 = AppConfig(fallback_folder="_Review_Needed\\")
    assert cfg2.fallback_folder == "_Review_Needed"


def test_config_rejects_identical_watch_and_docs_root(tmp_path: Path):
    folder = tmp_path / "SharedFolder"
    with pytest.raises(ValueError, match="cannot be the same directory"):
        AppConfig(watch_folder=folder, documents_root=folder)


def test_config_max_folder_depth_bounds():
    with pytest.raises(ValueError):
        AppConfig(max_folder_depth=0)

    with pytest.raises(ValueError):
        AppConfig(max_folder_depth=-1)

    with pytest.raises(ValueError):
        AppConfig(max_folder_depth=11)

    assert AppConfig(max_folder_depth=1).max_folder_depth == 1
    assert AppConfig(max_folder_depth=10).max_folder_depth == 10


def test_load_config_utf8_bom(tmp_path: Path):
    cfg_file = tmp_path / "config_bom.json"
    content = '{\n  "fallback_folder": "_BOM_Review"\n}'
    cfg_file.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
    cfg = load_config(cfg_file)
    assert cfg.fallback_folder == "_BOM_Review"


def test_config_rejects_regular_file(tmp_path: Path):
    dummy_file = tmp_path / "file.txt"
    dummy_file.write_text("not a directory")

    with pytest.raises(ValueError, match="watch_folder cannot be a regular file"):
        AppConfig(watch_folder=dummy_file, documents_root=tmp_path / "docs")

    with pytest.raises(ValueError, match="documents_root cannot be a regular file"):
        AppConfig(watch_folder=tmp_path / "watch", documents_root=dummy_file)


def test_config_rejects_path_under_regular_file(tmp_path: Path):
    blocker = tmp_path / "blocker.txt"
    blocker.write_text("a file, not a directory")
    broken_path = blocker / "Inbox"

    with pytest.raises(ValueError, match="watch_folder cannot be a regular file"):
        AppConfig(watch_folder=broken_path, documents_root=tmp_path / "docs")

    with pytest.raises(ValueError, match="documents_root cannot be a regular file"):
        AppConfig(watch_folder=tmp_path / "watch", documents_root=broken_path)


def test_config_rejects_nested_watch_folder(tmp_path: Path):
    docs_root = tmp_path / "Documents"
    nested_watch = docs_root / "Scans" / "Inbox"

    with pytest.raises(ValueError, match="cannot be the same directory or contain"):
        AppConfig(watch_folder=nested_watch, documents_root=docs_root)

    # And containment in the opposite direction is rejected too.
    with pytest.raises(ValueError, match="cannot be the same directory or contain"):
        AppConfig(watch_folder=docs_root, documents_root=nested_watch)


def test_load_config_semantic_invalid_raises(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "documents_root": str(tmp_path / "Docs"),
                "watch_folder": str(tmp_path / "Inbox"),
                "max_folder_depth": 99,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="max_folder_depth"):
        load_config(cfg_file)

    # Unreadable / undecodable files still fall back to defaults.
    cfg_file.write_text("{broken", encoding="utf-8")
    assert isinstance(load_config(cfg_file), AppConfig)


def test_config_assignment_validation(tmp_path: Path):
    cfg = AppConfig(watch_folder=tmp_path / "watch", documents_root=tmp_path / "docs")

    # Assignment validation should catch invalid values
    with pytest.raises(ValueError):
        cfg.max_folder_depth = 99


def test_config_auto_update_defaults():
    cfg = AppConfig()
    assert cfg.auto_update is True
    assert cfg.update_check_interval_days == 0


def test_config_update_interval_bounds():
    with pytest.raises(ValueError):
        AppConfig(update_check_interval_days=-1)
    with pytest.raises(ValueError):
        AppConfig(update_check_interval_days=61)
    assert AppConfig(update_check_interval_days=0).update_check_interval_days == 0
    assert AppConfig(update_check_interval_days=30).update_check_interval_days == 30
    assert AppConfig(auto_update=False).auto_update is False


def test_config_auto_update_fields_round_trip(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    watch_dir = tmp_path / "watch"
    docs_dir = tmp_path / "docs"
    original = AppConfig(
        watch_folder=watch_dir,
        documents_root=docs_dir,
        auto_update=False,
        update_check_interval_days=7,
    )
    save_config(original, cfg_file)
    loaded = load_config(cfg_file)
    assert loaded.auto_update is False
    assert loaded.update_check_interval_days == 7


def test_load_config_rejects_invalid_update_interval(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "watch_folder": str(tmp_path / "Watch"),
                "documents_root": str(tmp_path / "Docs"),
                "update_check_interval_days": -1,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="update_check_interval_days"):
        load_config(cfg_file)


def test_config_backward_compatible_without_update_fields(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "watch_folder": str(tmp_path / "Watch"),
                "documents_root": str(tmp_path / "Docs"),
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.auto_update is True
    assert cfg.update_check_interval_days == 0

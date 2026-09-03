"""Unit tests for scansort.config and folder_hints modules (TDD Cycle 2)."""

import json
from pathlib import Path

from scansort.config import AppConfig, get_default_config_path, load_config, save_config
from scansort.folder_hints import load_folder_hints


def test_default_config():
    cfg = AppConfig()
    assert cfg.gemini_model == "gemini-2.5-flash"
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
        gemini_model="gemini-2.5-flash-lite",
        dry_run=True,
    )

    save_config(original_cfg, cfg_file)
    assert cfg_file.exists()

    loaded_cfg = load_config(cfg_file)
    assert loaded_cfg.watch_folder == custom_watch
    assert loaded_cfg.documents_root == custom_docs
    assert loaded_cfg.gemini_model == "gemini-2.5-flash-lite"
    assert loaded_cfg.dry_run is True


def test_config_never_serializes_api_keys(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    cfg = AppConfig()
    save_config(cfg, cfg_file)

    content = cfg_file.read_text(encoding="utf-8")
    parsed = json.loads(content)
    assert "api_key" not in parsed
    assert "gemini_api_key" not in parsed
    assert "key" not in parsed


def test_ensure_directories_creates_missing(tmp_path: Path):
    watch_dir = tmp_path / "created_watch"
    docs_dir = tmp_path / "created_docs"
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


def test_get_default_config_path():
    path = get_default_config_path()
    assert path.name == "config.json"
    assert "ScanSort" in str(path) or "scansort" in str(path)


def test_get_default_app_dir_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("APPDATA", "C:\\Users\\Test\\AppData\\Roaming")
    from scansort.config import get_default_app_dir
    app_dir = get_default_app_dir()
    assert "ScanSort" in str(app_dir)
    assert "AppData" in str(app_dir)


def test_load_config_corrupt_json_fallback(tmp_path: Path):
    corrupt_file = tmp_path / "corrupt_config.json"
    corrupt_file.write_text("{invalid json", encoding="utf-8")
    cfg = load_config(corrupt_file)
    assert isinstance(cfg, AppConfig)
    assert cfg.gemini_model == "gemini-2.5-flash"


def test_get_default_hints_path():
    from scansort.folder_hints import get_default_hints_path
    path = get_default_hints_path()
    assert path.name == "folder_hints.json"


def test_load_folder_hints_invalid_format(tmp_path: Path):
    invalid_file = tmp_path / "hints.json"
    invalid_file.write_text('["not", "a", "dict"]', encoding="utf-8")
    assert load_folder_hints(invalid_file) == {}


def test_load_folder_hints_corrupt(tmp_path: Path):
    corrupt_file = tmp_path / "corrupt_hints.json"
    corrupt_file.write_text("{bad json", encoding="utf-8")
    assert load_folder_hints(corrupt_file) == {}

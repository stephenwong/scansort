"""Undo wiring tests for RAG memory invalidation."""

import json
from pathlib import Path

from scansort.classification.memory import MemoryStore, memory_db_path_for
from scansort.core.config import AppConfig
from scansort.pipeline.undo import run_undo, undo_last_move


def _write_history(jsonl_path: Path, entry: dict) -> None:
    jsonl_path.write_text(f"{json.dumps(entry)}\n", encoding="utf-8")


def _setup_undo(tmp_path: Path, sha: str = "a" * 64):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs = tmp_path / "Documents" / "Utilities"
    docs.mkdir(parents=True)
    moved_file = docs / "260901_Origin_Energy_Bill.pdf"
    moved_file.write_bytes(b"content")
    original = inbox / "scan001.pdf"
    entry = {
        "status": "SUCCESS",
        "original_filename": original.name,
        "new_filename": moved_file.name,
        "original_path": str(original),
        "destination_path": str(moved_file),
        "destination_folder": "Utilities",
        "confidence": 0.95,
        "summary": "Origin Energy electricity bill",
        "sha256": sha,
    }
    jsonl_path = tmp_path / "history.jsonl"
    _write_history(jsonl_path, entry)
    return jsonl_path, sha


def _indexed_store(base_dir: Path, sha: str) -> MemoryStore:
    store = MemoryStore(memory_db_path_for(base_dir))
    assert (
        store.index_record(
            {
                "sha256": sha,
                "status": "SUCCESS",
                "destination_folder": "Utilities",
                "summary": "Origin Energy electricity bill",
            }
        )
        is True
    )
    return store


def test_undo_removes_misfiled_vector(tmp_path: Path):
    jsonl_path, sha = _setup_undo(tmp_path)
    store = _indexed_store(tmp_path, sha)
    assert store.count() == 1
    assert undo_last_move(jsonl_path) is not None
    assert MemoryStore(memory_db_path_for(tmp_path)).count() == 0


def test_undo_disabled_keeps_vector(tmp_path: Path):
    jsonl_path, sha = _setup_undo(tmp_path)
    _indexed_store(tmp_path, sha)
    assert undo_last_move(jsonl_path, memory_enabled=False) is not None
    assert MemoryStore(memory_db_path_for(tmp_path)).count() == 1


def test_undo_without_memory_db_succeeds_and_creates_nothing(tmp_path: Path):
    jsonl_path, _ = _setup_undo(tmp_path)
    assert undo_last_move(jsonl_path) is not None
    assert not (tmp_path / "vectors").exists()


def test_undo_without_sha_skips_memory(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs = tmp_path / "Documents" / "Utilities"
    docs.mkdir(parents=True)
    moved_file = docs / "doc.pdf"
    moved_file.write_bytes(b"content")
    original = inbox / "scan.pdf"
    jsonl_path = tmp_path / "history.jsonl"
    _write_history(
        jsonl_path,
        {
            "status": "SUCCESS",
            "original_path": str(original),
            "destination_path": str(moved_file),
            "destination_folder": "Utilities",
            "summary": "Bill",
        },
    )
    assert undo_last_move(jsonl_path) is not None


def test_run_undo_honours_disabled_flag(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs = tmp_path / "Documents" / "Utilities"
    docs.mkdir(parents=True)
    moved_file = docs / "doc.pdf"
    moved_file.write_bytes(b"content")
    original = inbox / "scan.pdf"
    sha = "b" * 64
    (app_dir / "history.jsonl").write_text(
        json.dumps(
            {
                "status": "SUCCESS",
                "original_path": str(original),
                "destination_path": str(moved_file),
                "destination_folder": "Utilities",
                "summary": "Bill",
                "sha256": sha,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _indexed_store(app_dir, sha)
    cfg = AppConfig(
        watch_folder=inbox,
        documents_root=tmp_path / "Documents",
        rag_memory_enabled=False,
    )
    result = run_undo(cfg, app_dir=app_dir)
    assert result.success is True
    assert MemoryStore(memory_db_path_for(app_dir)).count() == 1


def test_run_undo_removes_vector_when_enabled(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    docs = tmp_path / "Documents" / "Utilities"
    docs.mkdir(parents=True)
    moved_file = docs / "doc.pdf"
    moved_file.write_bytes(b"content")
    original = inbox / "scan.pdf"
    sha = "c" * 64
    (app_dir / "history.jsonl").write_text(
        json.dumps(
            {
                "status": "SUCCESS",
                "original_path": str(original),
                "destination_path": str(moved_file),
                "destination_folder": "Utilities",
                "summary": "Bill",
                "sha256": sha,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _indexed_store(app_dir, sha)
    cfg = AppConfig(watch_folder=inbox, documents_root=tmp_path / "Documents")
    result = run_undo(cfg, app_dir=app_dir)
    assert result.success is True
    assert MemoryStore(memory_db_path_for(app_dir)).count() == 0

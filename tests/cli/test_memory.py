"""Unit tests for scansort.cli.memory subcommand."""

import json
from pathlib import Path
from unittest.mock import patch

from scansort.__main__ import main_cli
from scansort.classification.memory import MemoryStore
from scansort.core.constants import HISTORY_JSONL_NAME


def _seed_store(app_dir: Path) -> None:
    from scansort.classification.memory import memory_db_path_for

    store = MemoryStore(memory_db_path_for(app_dir))
    store.index_record(
        {
            "sha256": "a" * 64,
            "status": "SUCCESS",
            "destination_folder": "Finances/Utilities",
            "summary": "Origin Energy bill July",
            "document_type": "Invoice",
            "timestamp": "2026-09-13T14:22:00",
        }
    )
    store.index_record(
        {
            "sha256": "b" * 64,
            "status": "SUCCESS",
            "destination_folder": "Health/Dental",
            "summary": "Dental checkup invoice",
            "document_type": "Receipt",
            "timestamp": "2026-09-13T15:00:00",
        }
    )


def test_memory_summary_output(mock_app_dir: Path, capsys):
    _seed_store(mock_app_dir)
    assert main_cli(["memory"]) == 0
    out = capsys.readouterr().out
    assert "Filing Memory:" in out
    assert "Examples Learned: 2" in out
    assert "Store:" in out


def test_memory_list_output(mock_app_dir: Path, capsys):
    _seed_store(mock_app_dir)
    assert main_cli(["memory", "--list"]) == 0
    out = capsys.readouterr().out
    assert "Finances/Utilities" in out
    assert "Health/Dental" in out


def test_memory_forget_folder(mock_app_dir: Path, capsys):
    _seed_store(mock_app_dir)
    assert main_cli(["memory", "--forget-folder", "Finances/Utilities"]) == 0
    out = capsys.readouterr().out
    assert "Forgot 1 examples for 'Finances/Utilities'." in out


def test_memory_clear_requires_confirmation(mock_app_dir: Path, monkeypatch, capsys):
    _seed_store(mock_app_dir)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    assert main_cli(["memory", "--clear"]) == 0
    assert "Clear cancelled." in capsys.readouterr().out
    from scansort.classification.memory import memory_db_path_for

    assert MemoryStore(memory_db_path_for(mock_app_dir)).count() == 2

    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    assert main_cli(["memory", "--clear"]) == 0
    assert "Cleared filing memory." in capsys.readouterr().out
    assert MemoryStore(memory_db_path_for(mock_app_dir)).count() == 0


def test_memory_rebuild(mock_app_dir: Path, capsys):
    history = mock_app_dir / HISTORY_JSONL_NAME
    history.write_text(
        json.dumps(
            {
                "sha256": "c" * 64,
                "status": "SUCCESS",
                "destination_folder": "Finances/Utilities",
                "summary": "Origin Energy bill August",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert main_cli(["memory", "--rebuild"]) == 0
    assert "Rebuilt filing memory: 1 examples from history." in capsys.readouterr().out


def test_memory_json_output(mock_app_dir: Path, capsys):
    _seed_store(mock_app_dir)
    assert main_cli(["memory", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["examples"] == 2
    assert "db_path" in data


def test_memory_failure_degrades_gracefully(mock_app_dir: Path, capsys):
    with patch(
        "scansort.classification.memory.memory_summary",
        side_effect=RuntimeError("boom"),
    ):
        assert main_cli(["memory"]) == 0
        assert "Filing Memory:" in capsys.readouterr().out


def test_memory_status_unknown_on_invalid_config(mock_app_dir: Path, capsys):
    with patch("scansort.cli.memory.load_config", side_effect=ValueError("bad")):
        assert main_cli(["memory"]) == 0
    assert "Status:           Unknown" in capsys.readouterr().out


def test_memory_forget_folder_mutates_store_and_json(mock_app_dir: Path, capsys):
    _seed_store(mock_app_dir)
    assert main_cli(["memory", "--forget-folder", "Finances/Utilities", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"folder": "Finances/Utilities", "forgot": 1}
    from scansort.classification.memory import memory_db_path_for

    assert MemoryStore(memory_db_path_for(mock_app_dir)).count() == 1


def test_memory_forget_error_returns_one(mock_app_dir: Path, capsys):
    with patch.object(MemoryStore, "forget_folder", side_effect=RuntimeError("locked")):
        assert main_cli(["memory", "--forget-folder", "Finances/Utilities"]) == 1
    assert "Error forgetting folder" in capsys.readouterr().err


def test_memory_clear_json(mock_app_dir: Path, monkeypatch, capsys):
    _seed_store(mock_app_dir)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    assert main_cli(["memory", "--clear", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"cleared": True}


def test_memory_clear_when_nothing_stored(mock_app_dir: Path, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    assert main_cli(["memory", "--clear"]) == 0
    assert "Nothing to clear." in capsys.readouterr().out

    assert main_cli(["memory", "--clear", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"cleared": False}


def test_memory_clear_error_returns_one(mock_app_dir: Path, monkeypatch, capsys):
    _seed_store(mock_app_dir)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    with patch.object(MemoryStore, "clear", side_effect=RuntimeError("disk full")):
        assert main_cli(["memory", "--clear"]) == 1
    assert "Error clearing memory" in capsys.readouterr().err


def test_memory_clear_eof_cancels(mock_app_dir: Path, monkeypatch, capsys):
    _seed_store(mock_app_dir)

    def _raise(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)
    assert main_cli(["memory", "--clear"]) == 0
    assert "Clear cancelled." in capsys.readouterr().out


def test_memory_rebuild_mutates_store_and_json(mock_app_dir: Path, capsys):
    history = mock_app_dir / HISTORY_JSONL_NAME
    history.write_text(
        json.dumps(
            {
                "sha256": "c" * 64,
                "status": "SUCCESS",
                "destination_folder": "Finances/Utilities",
                "summary": "Origin Energy bill August",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert main_cli(["memory", "--rebuild", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"rebuilt": 1}
    from scansort.classification.memory import memory_db_path_for

    assert MemoryStore(memory_db_path_for(mock_app_dir)).count() == 1


def test_memory_rebuild_error_returns_one(mock_app_dir: Path, capsys):
    with patch(
        "scansort.classification.memory.rebuild_memory",
        side_effect=RuntimeError("locked"),
    ):
        assert main_cli(["memory", "--rebuild"]) == 1
    assert "Error rebuilding memory" in capsys.readouterr().err


def test_memory_list_json_and_empty(mock_app_dir: Path, capsys):
    _seed_store(mock_app_dir)
    assert main_cli(["memory", "--list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 2

    from scansort.classification.memory import memory_db_path_for

    MemoryStore(memory_db_path_for(mock_app_dir)).clear()
    assert main_cli(["memory", "--list"]) == 0
    assert "No learned examples." in capsys.readouterr().out


def test_memory_list_error_returns_one(mock_app_dir: Path, capsys):
    with patch.object(MemoryStore, "list_examples", side_effect=RuntimeError("locked")):
        assert main_cli(["memory", "--list"]) == 1
    assert "Error listing memory" in capsys.readouterr().err


def test_memory_direct_guard_rejects_multiple_actions(capsys):
    """Direct handler calls (non-CLI) are still guarded against combinations."""
    from scansort.cli.memory import handle_memory
    from scansort.cli.parser import build_parser

    parsed = build_parser().parse_args(["memory"])
    parsed.memory_list = True
    parsed.memory_clear = True
    assert handle_memory(parsed) == 1
    assert "mutually exclusive" in capsys.readouterr().err

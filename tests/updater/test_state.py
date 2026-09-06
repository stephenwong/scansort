"""Unit tests for update state persistence and check interval tracking."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from scansort.updater.state import (
    applied_version,
    clear_applied_notification,
    load_state,
    record_applied_update,
    record_update_check,
    update_is_due,
)


def test_load_state_handles_missing_corrupt_and_non_dict(tmp_path: Path):
    state_path = tmp_path / "update_state.json"
    assert load_state(state_path) == {}
    state_path.write_text("{not json", encoding="utf-8")
    assert load_state(state_path) == {}
    state_path.write_text("[1, 2]", encoding="utf-8")
    assert load_state(state_path) == {}


def test_record_update_check_and_due_calculation(tmp_path: Path):
    state_path = tmp_path / "update_state.json"
    assert update_is_due(state_path, interval_days=1) is True

    when = datetime.now(UTC) - timedelta(days=5)
    record_update_check(state_path, when=when)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["checked_at"] == when.isoformat()
    assert update_is_due(state_path, interval_days=1) is True
    assert update_is_due(state_path, interval_days=10) is False


def test_update_is_due_treats_bad_or_naive_timestamps_as_due(tmp_path: Path):
    state_path = tmp_path / "update_state.json"
    state_path.write_text(json.dumps({"checked_at": "not-a-date"}), encoding="utf-8")
    assert update_is_due(state_path, 1) is True
    state_path.write_text(
        json.dumps({"checked_at": "2026-09-01T10:00:00"}), encoding="utf-8"
    )
    assert update_is_due(state_path, 1) is True
    state_path.write_text(json.dumps({"checked_at": 12345}), encoding="utf-8")
    assert update_is_due(state_path, 1) is True


def test_update_is_due_zero_or_negative_always_true(tmp_path: Path):
    state_file = tmp_path / "update_state.json"
    record_update_check(state_file)
    assert update_is_due(state_file, 0) is True
    assert update_is_due(state_file, -1) is True


def test_record_applied_update_and_notification_cycle(tmp_path: Path):
    state_path = tmp_path / "update_state.json"
    when = datetime.now(UTC)
    record_applied_update(state_path, "0.2.0", when=when)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["applied_version"] == "0.2.0"
    assert state["just_installed"] is True
    assert state["applied_at"] == when.isoformat()
    assert applied_version(state_path) == "0.2.0"

    clear_applied_notification(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state.get("just_installed") is False
    assert applied_version(state_path) == "0.2.0"


def test_applied_version_missing_returns_none(tmp_path: Path):
    assert applied_version(tmp_path / "missing.json") is None


def test_state_writes_tolerate_os_errors(tmp_path: Path, monkeypatch):
    state_path = tmp_path / "update_state.json"
    state_path.write_text(json.dumps({"just_installed": True}), encoding="utf-8")
    monkeypatch.setattr(
        "scansort.updater.state.atomic_write",
        MagicMock(side_effect=OSError("disk full")),
    )
    record_update_check(state_path)
    record_applied_update(state_path, "0.2.0")
    clear_applied_notification(state_path)

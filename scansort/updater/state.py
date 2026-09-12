"""Update state tracking and check interval evaluation.

Persists and reads update check timestamps and applied release versions
in %APPDATA%/ScanSort/update_state.json.
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scansort.core.fs import atomic_write

logger = logging.getLogger(__name__)


def load_state(state_path: Path) -> dict:
    """Read the update state file, returning {} when missing or malformed."""
    try:
        content = Path(state_path).read_text(encoding="utf-8-sig")
    except OSError, UnicodeError:
        return {}
    try:
        data = json.loads(content)
    except json.JSONDecodeError, TypeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _save_state(state_path: Path, state: dict) -> None:
    atomic_write(state_path, json.dumps(state, indent=2))


def _mutate_state(
    state_path: Path, mutate: Callable[[dict], bool], warning: str
) -> None:
    """Load state, apply *mutate*, and best-effort persist.

    ``mutate`` returns False to suppress the save when nothing changed.
    """
    state = load_state(state_path)
    if not mutate(state):
        return
    try:
        _save_state(state_path, state)
    except OSError as e:
        logger.warning("%s: %s", warning, e)


def record_update_check(state_path: Path, when: datetime | None = None) -> None:
    """Persist the timestamp of a completed update check (best effort)."""

    def _apply(state: dict) -> bool:
        state["checked_at"] = (when or datetime.now(UTC)).isoformat()
        return True

    _mutate_state(state_path, _apply, "Could not record update check time")


def update_is_due(state_path: Path, interval_days: int) -> bool:
    """Return True when the last completed check is older than the interval.

    An interval of 0 (or negative) means check on every launch.
    Missing, malformed, or timezone-naive timestamps count as due so a corrupt
    state file can never suppress an update check.
    """
    if interval_days <= 0:
        return True
    state = load_state(state_path)
    raw = state.get("checked_at")
    if not raw or not isinstance(raw, str):
        return True
    try:
        checked = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if checked.tzinfo is None:
        return True
    return datetime.now(UTC) - checked >= timedelta(days=interval_days)


def record_applied_update(
    state_path: Path, version: str, when: datetime | None = None
) -> None:
    """Mark a release as installed and arm the post-install toast marker."""

    def _apply(state: dict) -> bool:
        state["applied_version"] = version
        state["applied_at"] = (when or datetime.now(UTC)).isoformat()
        state["just_installed"] = True
        return True

    _mutate_state(state_path, _apply, "Could not record applied update")


def clear_applied_notification(state_path: Path) -> None:
    """Disarm the post-install toast marker after it has been shown."""

    def _apply(state: dict) -> bool:
        if "just_installed" not in state:
            return False
        state["just_installed"] = False
        return True

    _mutate_state(state_path, _apply, "Could not clear update notification marker")


def applied_version(state_path: Path) -> str | None:
    """Return the version of the last applied release, if recorded."""
    value = load_state(state_path).get("applied_version")
    return value if isinstance(value, str) and value else None


__all__ = [
    "applied_version",
    "clear_applied_notification",
    "load_state",
    "record_applied_update",
    "record_update_check",
    "update_is_due",
]

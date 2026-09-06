"""Update check and self-update CLI command handlers."""

import argparse
import contextlib
import logging
import os
import sys
from pathlib import Path

from scansort import __version__
from scansort.core.config import AppConfig, get_default_app_dir
from scansort.core.constants import UPDATE_STATE_FILENAME
from scansort.platform.toasts import show_toast
from scansort.updater import (
    UpdateError,
    applied_version,
    available_update,
    clear_applied_notification,
    download_and_stage,
    fetch_latest_release,
    installed_version,
    load_state,
    perform_self_update,
    record_update_check,
    spawn_update_helper,
    update_is_due,
)

logger = logging.getLogger(__name__)


def announce_applied_update(app_dir: Path) -> None:
    """Toast once that a self-installed update is now running, then disarm."""
    state_path = app_dir / UPDATE_STATE_FILENAME
    state = load_state(state_path)
    if not state.get("just_installed"):
        return
    version = state.get("applied_version")
    label = (
        f"Version {version}"
        if isinstance(version, str) and version
        else "A new version"
    )
    show_toast("ScanSort updated", f"{label} was installed successfully.")
    clear_applied_notification(state_path)


_announce_applied_update = announce_applied_update


def maybe_apply_auto_update(cfg: AppConfig, app_dir: Path) -> bool:
    """Download and hand off a newer release, returning True when applied.

    Runs only in frozen Windows builds with auto-update enabled and the check
    interval elapsed. Every failure mode (offline, rate-limited, download or
    spawn errors) logs a warning and returns False so normal watch startup
    always proceeds. The check timestamp is only recorded once a decision is
    made or an install is handed off, so a failed install retries next launch.
    """
    if not cfg.auto_update:
        logger.debug(
            "Auto-update check skipped: auto_update is disabled in configuration."
        )
        return False
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        logger.debug(
            "Auto-update check skipped: running in non-frozen/development environment (%s, frozen=%s).",
            sys.platform,
            getattr(sys, "frozen", False),
        )
        return False
    state_path = app_dir / UPDATE_STATE_FILENAME
    try:
        if not update_is_due(state_path, cfg.update_check_interval_days):
            logger.debug(
                "Auto-update check skipped: check interval (%d days) has not elapsed.",
                cfg.update_check_interval_days,
            )
            return False
        payload = fetch_latest_release()
        release = available_update(
            payload,
            installed_version(),
            applied_version(state_path),
        )
        if release is None:
            record_update_check(state_path)
            return False
        install_dir = Path(sys.executable).parent
        staged_dir = download_and_stage(release, install_dir, app_dir / "tmp")
        show_toast(
            "ScanSort update available",
            f"Version {release.version} downloaded. Restarting to install it.",
        )
        logger.info(
            "Restarting application to apply update %s via helper...",
            release.version,
        )
        with contextlib.suppress(OSError):
            os.chdir(install_dir.parent)
        spawn_update_helper(install_dir, staged_dir, release.version, os.getpid())
        record_update_check(state_path)
        return True
    except UpdateError as e:
        logger.warning("Automatic update skipped: %s", e)
        return False


_maybe_apply_auto_update = maybe_apply_auto_update


def handle_self_update(values: list[str]) -> int:
    """Handle the hidden '--self-update' helper invocation from a staged build."""
    try:
        pid = int(values[0])
    except ValueError as e:
        print(f"Invalid --self-update arguments: {e}", file=sys.stderr)
        return 1
    return perform_self_update(pid, values[1], values[2], values[3])


def handle_check_update(parsed: argparse.Namespace) -> int:
    """Check GitHub Releases for newer ScanSort versions and display findings."""
    print(f"Checking for updates (current version: {__version__})...")
    app_dir = get_default_app_dir()
    state_path = app_dir / UPDATE_STATE_FILENAME
    try:
        payload = fetch_latest_release()
        release = available_update(
            payload,
            installed_version(),
            applied_version(state_path),
        )
        if release is None:
            print(
                f"ScanSort is up to date (version {__version__}). No new updates available."
            )
        else:
            print(
                f"Update available: version {release.version} (current: {__version__})"
            )
            print(f"Release asset:  {release.asset_name}")
            print(f"Download URL:   {release.download_url}")
            if release.size_bytes:
                print(f"Asset size:     {release.size_bytes:,} bytes")
        return 0
    except UpdateError as e:
        print(f"Update check failed: {e}", file=sys.stderr)
        return 1

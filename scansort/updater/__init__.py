"""Self-update engine for ScanSort.

Provides GitHub Releases checking, background streaming downloads,
checksum verification, rollback-safe directory swaps, and process orchestration.
"""

from scansort.updater.downloader import (
    DOWNLOAD_CHUNK_SIZE,
    download_and_stage,
    download_release,
    extract_bundle,
)
from scansort.updater.feed import (
    GITHUB_REPO,
    RELEASE_API_URL,
    REQUEST_TIMEOUT,
    USER_AGENT,
    WINDOWS_ASSET_PREFIX,
    WINDOWS_ASSET_SUFFIX,
    ReleaseInfo,
    available_update,
    fetch_latest_release,
    installed_version,
    parse_version,
)
from scansort.updater.installer import (
    EXECUTABLE_NAME,
    SWAP_RETRY_INTERVAL,
    SWAP_RETRY_TIMEOUT,
    UpdateError,
    cleanup_stale_updates,
    replace_install_dir,
)
from scansort.updater.process import (
    launch_installed_app,
    perform_self_update,
    spawn_update_helper,
    wait_for_process_exit,
)
from scansort.updater.state import (
    applied_version,
    clear_applied_notification,
    load_state,
    record_applied_update,
    record_update_check,
    update_is_due,
)

__all__ = [
    "DOWNLOAD_CHUNK_SIZE",
    "EXECUTABLE_NAME",
    "GITHUB_REPO",
    "RELEASE_API_URL",
    "REQUEST_TIMEOUT",
    "SWAP_RETRY_INTERVAL",
    "SWAP_RETRY_TIMEOUT",
    "USER_AGENT",
    "WINDOWS_ASSET_PREFIX",
    "WINDOWS_ASSET_SUFFIX",
    "ReleaseInfo",
    "UpdateError",
    "applied_version",
    "available_update",
    "cleanup_stale_updates",
    "clear_applied_notification",
    "download_and_stage",
    "download_release",
    "extract_bundle",
    "fetch_latest_release",
    "installed_version",
    "launch_installed_app",
    "load_state",
    "parse_version",
    "perform_self_update",
    "record_applied_update",
    "record_update_check",
    "replace_install_dir",
    "spawn_update_helper",
    "update_is_due",
    "wait_for_process_exit",
]

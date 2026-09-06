"""GitHub Releases self-updater for frozen Windows builds of ScanSort.

Design invariants
-----------------
- Version feed: the public ``stephenwong/scansort`` GitHub Releases page.
  The asset must be named ``ScanSort-<tag>-windows-x64.zip`` (the exact name
  the release workflow publishes) and its tag must be strictly newer than both
  the embedded ``__version__`` and any previously applied release recorded in
  the update state file, preventing perpetual re-install loops.
- A running Windows executable cannot be overwritten, so the current process
  spawns the *staged* new build as a detached helper (``--self-update``). The
  helper waits for the old process to exit, then swaps directories under the
  cross-process update lock and the single-instance guard.
- Swap ordering is rollback-safe: the current install is renamed aside first,
  the staged tree is renamed into place, and only then is the backup removed.
  Any failure between the two renames restores the backup, so the auto-start
  path never points at a missing executable.
- Staging lives in a sibling directory of the install directory (same volume)
  so the final swap is an atomic rename rather than a cross-volume copy.
"""

import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from scansort.config import get_default_app_dir
from scansort.constants import (
    INSTANCE_LOCK_FILENAME,
    UPDATE_LOCK_FILENAME,
    UPDATE_STATE_FILENAME,
)
from scansort.fs_utils import atomic_write, interprocess_file_lock
from scansort.hasher import compute_file_sha256
from scansort.instance_guard import instance_guard

logger = logging.getLogger(__name__)

GITHUB_REPO = "stephenwong/scansort"
RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
WINDOWS_ASSET_PREFIX = "ScanSort-"
WINDOWS_ASSET_SUFFIX = "-windows-x64.zip"
EXECUTABLE_NAME = "ScanSort.exe"
REQUEST_TIMEOUT = 5.0
USER_AGENT = "ScanSort-Self-Update"

DOWNLOAD_CHUNK_SIZE = 64 * 1024

# Detached, console-less child: the helper must outlive its parent and never
# flash a terminal window (the app itself is built with console=False).
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000

_ARCHIVE_GLOB = f"{WINDOWS_ASSET_PREFIX}*-{WINDOWS_ASSET_SUFFIX.lstrip('-')}"
WAIT_POLL_INTERVAL = 0.25


class UpdateError(Exception):
    """Raised when an update check, download, or install step fails."""


@dataclass(frozen=True)
class ReleaseInfo:
    """A downloadable release bundle and its verification metadata."""

    version: str
    tag_name: str
    asset_name: str
    download_url: str
    size_bytes: int | None
    sha256: str | None
    published_at: str | None


def parse_version(value: str) -> tuple[int, int, int] | None:
    """Parse a ``v?MAJOR.MINOR.PATCH`` version string into a comparable tuple.

    Returns None for pre-release suffixes, missing segments, or non-numeric
    content so unreleasable tags are never treated as update candidates.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text.startswith("v"):
        text = text[1:]
    parts = text.split(".")
    if len(parts) != 3:
        return None
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    return tuple(numbers)  # type: ignore[return-value]


def installed_version() -> tuple[int, int, int] | None:
    """Parse the embedded package version as a comparable tuple."""
    from scansort import __version__  # imported lazily so tests can patch it

    return parse_version(__version__)


# ---------------------------------------------------------------------------
# Update state file (last check / last applied release)
# ---------------------------------------------------------------------------


def load_state(state_path: Path) -> dict:
    """Read the update state file, returning {} when missing or malformed."""
    try:
        content = Path(state_path).read_text(encoding="utf-8-sig")
    except OSError:
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


def record_update_check(state_path: Path, when: datetime | None = None) -> None:
    """Persist the timestamp of a completed update check (best effort)."""
    state = load_state(state_path)
    state["checked_at"] = (when or datetime.now(UTC)).isoformat()
    try:
        _save_state(state_path, state)
    except OSError as e:
        logger.warning("Could not record update check time: %s", e)


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
    state = load_state(state_path)
    state["applied_version"] = version
    state["applied_at"] = (when or datetime.now(UTC)).isoformat()
    state["just_installed"] = True
    try:
        _save_state(state_path, state)
    except OSError as e:
        logger.warning("Could not record applied update: %s", e)


def clear_applied_notification(state_path: Path) -> None:
    """Disarm the post-install toast marker after it has been shown."""
    state = load_state(state_path)
    if "just_installed" not in state:
        return
    state["just_installed"] = False
    try:
        _save_state(state_path, state)
    except OSError as e:
        logger.warning("Could not clear update notification marker: %s", e)


def applied_version(state_path: Path) -> str | None:
    """Return the version of the last applied release, if recorded."""
    value = load_state(state_path).get("applied_version")
    return value if isinstance(value, str) and value else None


# ---------------------------------------------------------------------------
# Release feed querying
# ---------------------------------------------------------------------------


def fetch_latest_release(
    url: str | None = None,
    opener=urllib.request.urlopen,
    timeout: float = REQUEST_TIMEOUT,
    user_agent: str = USER_AGENT,
) -> dict:
    """Fetch and decode the latest GitHub release payload.

    Raises:
        UpdateError: On transport errors, undecodable bodies, or payloads
            that are not JSON objects.
    """
    target_url = url or RELEASE_API_URL
    logger.info("Checking for updates from %s...", target_url)
    request = urllib.request.Request(
        target_url,
        headers={"User-Agent": user_agent, "Accept": "application/vnd.github+json"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (OSError, ValueError) as e:
        raise UpdateError(f"Update check failed: {e}") from e
    if not isinstance(payload, dict):
        raise UpdateError("Update check returned an unexpected payload.")
    return payload


def _asset_sha256(asset: dict) -> str | None:
    """Extract a lowercase SHA-256 hex digest from a release asset if present."""
    digest = asset.get("digest")
    if isinstance(digest, str):
        if digest.startswith("sha256:"):
            return digest.split(":", 1)[1].strip().lower()
        return None
    if isinstance(digest, list):
        for item in digest:
            if (
                isinstance(item, dict)
                and isinstance(item.get("algorithm"), str)
                and item["algorithm"].lower() == "sha256"
                and isinstance(item.get("value"), str)
            ):
                return item["value"].strip().lower()
    return None


def available_update(
    payload: dict | None,
    current_version: tuple[int, int, int] | None,
    applied_version: str | None = None,
) -> ReleaseInfo | None:
    """Return the newest downloadable release, or None when nothing qualifies.

    The release tag must parse as a clean three-part version, the asset must be
    named exactly ``ScanSort-<tag>-windows-x64.zip``, and the version must be
    strictly newer than both the embedded version and any version already
    applied (so an unbumped ``__version__`` cannot cause re-install loops).
    """
    if not isinstance(payload, dict):
        return None
    tag_name = payload.get("tag_name")
    if not isinstance(tag_name, str) or not tag_name:
        return None
    tag_version = parse_version(tag_name)
    if tag_version is None:
        return None
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return None

    expected_name = f"{WINDOWS_ASSET_PREFIX}{tag_name}{WINDOWS_ASSET_SUFFIX}"
    asset: dict | None = None
    for candidate in assets:
        if isinstance(candidate, dict) and candidate.get("name") == expected_name:
            asset = candidate
            break
    if asset is None:
        return None
    if current_version is not None and tag_version <= current_version:
        logger.info(
            "ScanSort is up to date (installed: %s, latest release: %s).",
            ".".join(str(part) for part in current_version),
            tag_name,
        )
        return None
    if applied_version is not None:
        applied = parse_version(applied_version)
        if applied is not None and tag_version <= applied:
            logger.info(
                "ScanSort update %s was already applied previously.",
                tag_name,
            )
            return None

    download_url = asset.get("browser_download_url")
    if not isinstance(download_url, str) or not download_url:
        return None
    size = asset.get("size")
    size_bytes = size if isinstance(size, int) and size > 0 else None
    published_at = payload.get("published_at")
    rel_info = ReleaseInfo(
        version=".".join(str(part) for part in tag_version),
        tag_name=tag_name,
        asset_name=expected_name,
        download_url=download_url,
        size_bytes=size_bytes,
        sha256=_asset_sha256(asset),
        published_at=published_at if isinstance(published_at, str) else None,
    )
    logger.info(
        "Update available: %s (installed: %s). Asset: %s (%s bytes).",
        tag_name,
        ".".join(str(p) for p in current_version) if current_version else "unknown",
        expected_name,
        size_bytes or "unknown",
    )
    return rel_info


# ---------------------------------------------------------------------------
# Download & extraction
# ---------------------------------------------------------------------------


def download_release(
    info: ReleaseInfo,
    dest_path: Path,
    opener=urllib.request.urlopen,
    timeout: float = REQUEST_TIMEOUT,
    user_agent: str = USER_AGENT,
) -> Path:
    """Stream a release asset to ``dest_path`` and verify its integrity.

    The declared byte count is always checked; a SHA-256 digest is verified
    when GitHub provides one. Any failure removes the partial file.

    Raises:
        UpdateError: On transport errors, size mismatches, or checksum errors.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Downloading release asset %s from %s...", info.asset_name, info.download_url
    )
    request = urllib.request.Request(
        info.download_url, headers={"User-Agent": user_agent}
    )
    total = 0
    try:
        with (
            opener(request, timeout=timeout) as response,
            dest_path.open("wb") as out_file,
        ):
            while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
                out_file.write(chunk)
                total += len(chunk)
    except OSError as e:
        dest_path.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {e}") from e

    if info.size_bytes is not None and total != info.size_bytes:
        dest_path.unlink(missing_ok=True)
        raise UpdateError(
            f"Downloaded file size mismatch: expected {info.size_bytes}, got {total}."
        )
    if info.sha256:
        actual = compute_file_sha256(dest_path)
        if actual != info.sha256:
            dest_path.unlink(missing_ok=True)
            raise UpdateError("Downloaded file checksum mismatch.")
    logger.info(
        "Downloaded release asset %s (%d bytes) successfully.", info.asset_name, total
    )
    return dest_path


def _member_target(dest_dir: Path, name: str) -> Path:
    """Map an archive member name onto a path strictly inside ``dest_dir``."""
    clean = name.replace("\\", "/")
    path = PurePosixPath(clean)
    parts = path.parts
    unsafe = not parts or any(part in {"..", ""} or ":" in part for part in parts)
    if path.is_absolute() or unsafe:
        raise UpdateError(f"Unsafe archive entry: {name}")
    return dest_dir.joinpath(*parts)


def extract_bundle(zip_path: Path, dest_dir: Path) -> Path:
    """Extract a release bundle, rejecting traversal members and corrupt zips.

    Raises:
        UpdateError: If the archive is corrupt, contains unsafe paths, or does
            not contain ``ScanSort.exe`` at its root.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Extracting release bundle %s into %s...", zip_path.name, dest_dir)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                target = _member_target(dest_dir, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as out_file:
                    shutil.copyfileobj(source, out_file)
    except zipfile.BadZipFile as e:
        raise UpdateError("Release archive is corrupt.") from e
    if not (dest_dir / EXECUTABLE_NAME).is_file():
        raise UpdateError("Release bundle does not contain ScanSort.exe.")
    logger.info("Extracted release bundle %s successfully.", zip_path.name)
    return dest_dir


# ---------------------------------------------------------------------------
# Staging & stale artifact cleanup
# ---------------------------------------------------------------------------


def _stage_dir_for(install_dir: Path, version: str) -> Path:
    return install_dir.parent / f"{install_dir.name}.stage-{version}"


def cleanup_stale_updates(install_dir: Path, keep: Path | None = None) -> None:
    """Remove leftover stage and backup siblings from earlier attempts.

    Deletion failures (e.g. a file still held open by another process) are
    tolerated and deferred to the next update run.
    """
    install_dir = Path(install_dir)
    for pattern in (
        f"{install_dir.name}.stage-*",
        f"{install_dir.name}.old-*",
    ):
        for entry in install_dir.parent.glob(pattern):
            if keep is not None and entry == keep:
                continue
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink(missing_ok=True)
            except OSError as e:
                logger.warning(
                    "Could not remove stale update artifact %s: %s", entry, e
                )


def _prune_old_archives(tmp_dir: Path, keep_name: str) -> None:
    """Remove cached release zips for versions other than ``keep_name``."""
    for entry in tmp_dir.glob(_ARCHIVE_GLOB):
        if entry.name != keep_name:
            try:
                entry.unlink(missing_ok=True)
            except OSError as e:
                logger.warning("Could not remove old archive %s: %s", entry, e)


def download_and_stage(
    info: ReleaseInfo,
    install_dir: Path,
    tmp_dir: Path,
    opener=urllib.request.urlopen,
    timeout: float = REQUEST_TIMEOUT,
    user_agent: str = USER_AGENT,
) -> Path:
    """Download and extract a release into a fresh sibling staging directory.

    A cached zip with a matching checksum is reused instead of re-downloaded.
    Staging next to the install directory keeps the final swap on one volume.
    """
    install_dir = Path(install_dir)
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    install_dir.parent.mkdir(parents=True, exist_ok=True)

    stage_dir = _stage_dir_for(install_dir, info.version)
    logger.info("Staging update %s into %s...", info.version, stage_dir)
    cleanup_stale_updates(install_dir, keep=stage_dir)

    zip_path = tmp_dir / info.asset_name
    cached_valid = (
        info.sha256 is not None
        and zip_path.is_file()
        and compute_file_sha256(zip_path) == info.sha256
    )
    if cached_valid:
        logger.info("Reusing cached release archive %s", zip_path)
    else:
        download_release(
            info, zip_path, opener=opener, timeout=timeout, user_agent=user_agent
        )
    _prune_old_archives(tmp_dir, keep_name=zip_path.name)

    if stage_dir.exists():
        shutil.rmtree(stage_dir, ignore_errors=True)
    try:
        extract_bundle(zip_path, stage_dir)
    except UpdateError:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise
    logger.info("Update %s successfully staged into %s.", info.version, stage_dir)
    return stage_dir


# ---------------------------------------------------------------------------
# Rollback-safe install swap
# ---------------------------------------------------------------------------


def replace_install_dir(install_dir: Path, staged_dir: Path) -> None:
    """Swap the staged tree into the install directory with rollback.

    Ordering: rename the current install to a backup, rename the staged tree
    into place, then delete the backup. If the second rename fails the backup
    is renamed back before the error propagates, so the auto-start target is
    never left pointing at a missing directory.

    Raises:
        UpdateError: If either directory lacks ``ScanSort.exe``, the initial
            rename fails, or the swap fails and cannot be rolled back.
    """
    install_dir = Path(install_dir)
    staged_dir = Path(staged_dir)
    if not (staged_dir / EXECUTABLE_NAME).is_file():
        raise UpdateError("Staged update does not contain ScanSort.exe.")
    if not (install_dir / EXECUTABLE_NAME).is_file():
        raise UpdateError("Install directory does not contain ScanSort.exe.")

    backup_dir = install_dir.parent / f"{install_dir.name}.old-{int(time.time())}"
    try:
        install_dir.rename(backup_dir)
    except OSError as e:
        raise UpdateError(f"Could not move the current installation aside: {e}") from e

    try:
        staged_dir.rename(install_dir)
    except OSError as e:
        try:
            backup_dir.rename(install_dir)
        except OSError as rollback_error:
            raise UpdateError(
                "Update swap failed and rollback failed; the previous install "
                f"is preserved at {backup_dir}: {rollback_error}"
            ) from rollback_error
        raise UpdateError(
            f"Update swap failed; the previous installation was restored: {e}"
        ) from e

    try:
        shutil.rmtree(backup_dir)
    except OSError as e:
        logger.warning(
            "Could not remove backup %s; it will be cleaned on a later run: %s",
            backup_dir,
            e,
        )


# ---------------------------------------------------------------------------
# Process waiting & launching
# ---------------------------------------------------------------------------


def _wait_posix_process(pid: int, timeout: float) -> bool:
    """Poll a PID with ``os.kill(pid, 0)`` until it disappears or times out.

    ``os.kill`` is only a valid liveness probe on POSIX; the Windows build uses
    ``_wait_windows_process`` instead (on Windows ``os.kill`` maps to console
    events or TerminateProcess and can never probe existence).
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            pass  # e.g. permission denied: the process still exists
        if time.monotonic() >= deadline:
            return False
        time.sleep(WAIT_POLL_INTERVAL)


def _wait_windows_process(pid: int, timeout: float) -> bool:
    """Wait on a native process handle for termination.

    The handle is opened once (with SYNCHRONIZE) so PID recycling cannot make
    the wait target a different process. A failed open means the PID is already
    gone.
    """
    process_query_limited = 0x1000
    synchronize = 0x00100000
    wait_object_0 = 0

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)

    handle = kernel32.OpenProcess(process_query_limited | synchronize, False, pid)
    if not handle:
        return True
    try:
        result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        return result == wait_object_0
    finally:
        kernel32.CloseHandle(handle)


def wait_for_process_exit(pid: int, timeout: float = 60.0, impl=None) -> bool:
    """Return True when the process exits within ``timeout`` seconds.

    ``impl`` is an optional waiter override used by tests; it defaults to the
    native waiter for the current platform.
    """
    if impl is None:
        if sys.platform == "win32":
            impl = _wait_windows_process
        else:
            impl = _wait_posix_process
    return bool(impl(pid, timeout))


def _popen_detached(argv: list[str]) -> None:
    """Launch a console-less detached child, raising UpdateError on failure."""
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NO_WINDOW
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except OSError as e:
        raise UpdateError(f"Could not launch helper process: {e}") from e


def spawn_update_helper(
    install_dir: Path, staged_dir: Path, version: str, parent_pid: int
) -> None:
    """Spawn the staged build as the detached ``--self-update`` helper.

    The old process must exit right after this returns so the helper can take
    over the instance lock and swap the install directory.

    Raises:
        UpdateError: If the staged executable is missing or cannot be launched.
    """
    executable = Path(staged_dir) / EXECUTABLE_NAME
    if not executable.is_file():
        raise UpdateError("Staged update does not contain ScanSort.exe.")
    logger.info(
        "Spawning self-update helper (PID: %d, version: %s)...", parent_pid, version
    )
    _popen_detached(
        [
            str(executable),
            "--self-update",
            str(parent_pid),
            str(install_dir),
            str(staged_dir),
            version,
        ]
    )


def launch_installed_app(install_dir: Path, args: list[str] | None = None) -> None:
    """Relaunch the freshly installed executable in background watch mode."""
    executable = Path(install_dir) / EXECUTABLE_NAME
    if not executable.is_file():
        raise UpdateError("Installed ScanSort.exe not found.")
    argv = [str(executable), *(args if args is not None else ["watch", "--minimized"])]
    _popen_detached(argv)


# ---------------------------------------------------------------------------
# Helper entry point (runs inside the staged, new build)
# ---------------------------------------------------------------------------


def perform_self_update(
    pid: int,
    install_dir: Path | str,
    staged_dir: Path | str,
    version: str,
    *,
    app_dir: Path | None = None,
    relaunch: bool = True,
) -> int:
    """Wait for the old process, swap the install, and relaunch the new build.

    Returns a process exit code: 0 on success, 1 on any failure (the previous
    install is preserved or restored in every failure path).
    """
    install_dir = Path(install_dir)
    staged_dir = Path(staged_dir)
    logger.info(
        "Self-update helper launched for version %s (waiting for parent PID %d)...",
        version,
        pid,
    )
    try:
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            raise UpdateError(
                "The --self-update helper requires a frozen Windows build."
            )
        if not (staged_dir / EXECUTABLE_NAME).is_file():
            raise UpdateError("Staged update does not contain ScanSort.exe.")
        if not (install_dir / EXECUTABLE_NAME).is_file():
            raise UpdateError("Installed ScanSort.exe not found.")

        app_dir = Path(app_dir) if app_dir is not None else get_default_app_dir()
        app_dir.mkdir(parents=True, exist_ok=True)

        if not wait_for_process_exit(pid):
            raise UpdateError(
                "Timed out waiting for the previous ScanSort instance to exit."
            )
        with (
            interprocess_file_lock(app_dir / UPDATE_LOCK_FILENAME),
            instance_guard(app_dir / INSTANCE_LOCK_FILENAME) as acquired,
        ):
            if not acquired:
                raise UpdateError(
                    "Another ScanSort instance is running; "
                    "the update will apply on a later start."
                )
            logger.info(
                "Acquired instance and update locks. Swapping installation %s with staged %s...",
                install_dir,
                staged_dir,
            )
            replace_install_dir(install_dir, staged_dir)

        record_applied_update(app_dir / UPDATE_STATE_FILENAME, version)
        cleanup_stale_updates(install_dir)
        logger.info(
            "Update to version %s installed successfully. Relaunching application...",
            version,
        )
        if relaunch:
            launch_installed_app(install_dir)
        return 0
    except UpdateError as e:
        logger.error("Update installation failed: %s", e)
        return 1

"""Release asset download, verification, archive extraction, and staging."""

import logging
import shutil
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from scansort.hasher import compute_file_sha256
from scansort.updater.feed import (
    REQUEST_TIMEOUT,
    USER_AGENT,
    WINDOWS_ASSET_PREFIX,
    WINDOWS_ASSET_SUFFIX,
    ReleaseInfo,
)
from scansort.updater.installer import (
    EXECUTABLE_NAME,
    UpdateError,
    cleanup_stale_updates,
)

logger = logging.getLogger(__name__)

DOWNLOAD_CHUNK_SIZE = 64 * 1024
_ARCHIVE_GLOB = f"{WINDOWS_ASSET_PREFIX}*-{WINDOWS_ASSET_SUFFIX.lstrip('-')}"


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


def _stage_dir_for(install_dir: Path, version: str) -> Path:
    return install_dir.parent / f"{install_dir.name}.stage-{version}"


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


__all__ = [
    "DOWNLOAD_CHUNK_SIZE",
    "download_and_stage",
    "download_release",
    "extract_bundle",
]

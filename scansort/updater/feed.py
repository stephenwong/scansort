"""GitHub Releases feed query, version parsing, and candidate evaluation."""

import http.client
import json
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from scansort.updater.installer import UpdateError

logger = logging.getLogger(__name__)

GITHUB_REPO = "stephenwong/scansort"
RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
WINDOWS_ASSET_PREFIX = "ScanSort-"
WINDOWS_ASSET_SUFFIX = "-windows-x64.zip"
REQUEST_TIMEOUT = 5.0
USER_AGENT = "ScanSort-Self-Update"


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
        if not part.isdecimal():
            return None
        numbers.append(int(part))
    return tuple(numbers)  # type: ignore[return-value]


def _format_version(parts: tuple[int, int, int]) -> str:
    """Render a parsed version tuple back to ``MAJOR.MINOR.PATCH``."""
    return ".".join(str(part) for part in parts)


def installed_version() -> tuple[int, int, int] | None:
    """Parse the embedded package version as a comparable tuple."""
    from scansort import __version__  # imported lazily so tests can patch it

    return parse_version(__version__)


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
    except (OSError, http.client.HTTPException, ValueError) as e:
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
            _format_version(current_version),
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
    expected_prefix = f"https://github.com/{GITHUB_REPO}/releases/download/{tag_name}/"
    if not download_url.startswith(expected_prefix):
        logger.warning(
            "Ignoring release asset with unexpected download URL: %s", download_url
        )
        return None
    size = asset.get("size")
    size_bytes = size if isinstance(size, int) and size > 0 else None
    published_at = payload.get("published_at")
    rel_info = ReleaseInfo(
        version=_format_version(tag_version),
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
        _format_version(current_version) if current_version else "unknown",
        expected_name,
        size_bytes or "unknown",
    )
    return rel_info


def check_for_updates(
    app_dir=None,
    fetch_fn=None,
    available_fn=None,
) -> tuple[ReleaseInfo | None, str | None]:
    """Check GitHub Releases for newer ScanSort versions.

    Returns:
        tuple[ReleaseInfo | None, str | None]: (release_info, error_message)
    """
    from scansort.core.config import get_default_app_dir
    from scansort.core.constants import UPDATE_STATE_FILENAME
    from scansort.updater.state import applied_version

    active_app_dir = Path(app_dir) if app_dir else get_default_app_dir()
    state_path = active_app_dir / UPDATE_STATE_FILENAME
    fetcher = fetch_fn or fetch_latest_release
    evaluator = available_fn or available_update
    try:
        payload = fetcher()
        release = evaluator(
            payload,
            installed_version(),
            applied_version(state_path),
        )
        return release, None
    except UpdateError as e:
        return None, str(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("Unexpected error during update check")
        return None, f"Unexpected error: {e}"


__all__ = [
    "GITHUB_REPO",
    "RELEASE_API_URL",
    "REQUEST_TIMEOUT",
    "USER_AGENT",
    "WINDOWS_ASSET_PREFIX",
    "WINDOWS_ASSET_SUFFIX",
    "ReleaseInfo",
    "available_update",
    "check_for_updates",
    "fetch_latest_release",
    "installed_version",
    "parse_version",
]

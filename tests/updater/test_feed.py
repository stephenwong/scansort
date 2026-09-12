"""Unit tests for the GitHub Releases release feed and version parser."""

import io
import json
from pathlib import Path

import pytest

from scansort import __version__
from scansort.updater.feed import (
    GITHUB_REPO,
    REQUEST_TIMEOUT,
    WINDOWS_ASSET_PREFIX,
    WINDOWS_ASSET_SUFFIX,
    available_update,
    fetch_latest_release,
    installed_version,
    parse_version,
)
from scansort.updater.installer import UpdateError

WINDOWS_ZIP = f"{WINDOWS_ASSET_PREFIX}v{__version__}{WINDOWS_ASSET_SUFFIX}"

_current_v = parse_version(__version__) or (1, 0, 0)
NEXT_VERSION = f"{_current_v[0] + 1}.0.0"
NEXT_TAG = f"v{NEXT_VERSION}"
NEXT_ZIP = f"{WINDOWS_ASSET_PREFIX}{NEXT_TAG}{WINDOWS_ASSET_SUFFIX}"


class _BytesResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _fake_urlopen(payload: bytes):
    def opener(request, timeout=None):
        return _BytesResponse(payload)

    return opener


def _payload(
    tag: str = f"v{__version__}",
    *,
    asset_name: str | None = None,
    digest: object = None,
    url: str | None = None,
    size: int | None = 123,
) -> dict:
    if url is None:
        url = (
            f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/"
            f"{WINDOWS_ASSET_PREFIX}{tag}{WINDOWS_ASSET_SUFFIX}"
        )
    return {
        "tag_name": tag,
        "assets": [
            {
                "name": asset_name
                or f"{WINDOWS_ASSET_PREFIX}{tag}{WINDOWS_ASSET_SUFFIX}",
                "browser_download_url": url,
                "size": size,
                "digest": digest,
            }
        ],
    }


# ---------------------------------------------------------------------------
# parse_version
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (__version__, parse_version(__version__)),
        (f"v{__version__}", parse_version(__version__)),
        ("0.1.0", (0, 1, 0)),
        ("v1.2.3", (1, 2, 3)),
        (" 3.4.5 ", (3, 4, 5)),
    ],
)
def test_parse_version_valid(raw: str, expected):
    assert parse_version(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "1.2", "1.2.3.4", "1.2.3-rc1", "v1.2", "abc", "1.x.3", None, 12, "1.2.\u00b2"],
)
def test_parse_version_rejects_invalid(raw):
    assert parse_version(raw) is None


# ---------------------------------------------------------------------------
# Version baseline helpers
# ---------------------------------------------------------------------------


def test_installed_version_uses_package_version(monkeypatch):
    from scansort import __version__

    assert installed_version() == parse_version(__version__)
    monkeypatch.setattr("scansort.__version__", "9.8.7")
    assert installed_version() == (9, 8, 7)
    monkeypatch.setattr("scansort.__version__", "not-a-version")
    assert installed_version() is None


# ---------------------------------------------------------------------------
# Release feed parsing
# ---------------------------------------------------------------------------


def test_fetch_latest_release_parses_payload():
    payload = _payload()
    encoded = json.dumps(payload).encode("utf-8")
    seen: list = []

    def opener(request, timeout=None):
        seen.append((request, timeout))
        return _BytesResponse(encoded)

    assert fetch_latest_release(opener=opener) == payload
    request, timeout = seen[0]
    assert timeout == REQUEST_TIMEOUT
    headers = {name.lower(): value for name, value in request.header_items()}
    assert "ScanSort" in headers["user-agent"]
    assert "github+json" in headers["accept"]


def test_fetch_latest_release_failures_raise_update_error():
    def broken_opener(request, timeout=None):
        raise OSError("connection reset")

    with pytest.raises(UpdateError, match="Update check failed"):
        fetch_latest_release(opener=broken_opener)

    with pytest.raises(UpdateError, match="Update check failed"):
        fetch_latest_release(opener=_fake_urlopen(b"{not json"))

    with pytest.raises(UpdateError, match="unexpected payload"):
        fetch_latest_release(opener=_fake_urlopen(b"[1, 2]"))


def test_fetch_latest_release_maps_http_exception_to_update_error():
    """F52: mid-body HTTPException must surface as an UpdateError."""
    import http.client

    class _BrokenResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            raise http.client.IncompleteRead(b"partial", 100)

    def opener(request, timeout=None):
        return _BrokenResponse()

    with pytest.raises(UpdateError, match="Update check failed"):
        fetch_latest_release(opener=opener)


def test_available_update_rejects_non_github_download_url():
    """F53: only the expected GitHub release host/path may be downloaded."""
    assert (
        available_update(_payload(url="http://evil.example/x.zip"), (0, 0, 1)) is None
    )
    assert (
        available_update(
            _payload(url="https://github.com/attacker/repo/releases/download/vX/x.zip"),
            (0, 0, 1),
        )
        is None
    )


def test_available_update_returns_newer_release():
    info = available_update(_payload(digest="sha256:abcdef"), (0, 0, 1))
    assert info is not None
    assert info.version == __version__
    assert info.tag_name == f"v{__version__}"
    assert info.asset_name == WINDOWS_ZIP
    assert info.sha256 == "abcdef"
    assert info.size_bytes == 123


def test_available_update_list_digest_form():
    digest = [{"algorithm": "sha256", "value": "deadbeef"}]
    payload = _payload(digest=digest)
    info = available_update(payload, (0, 0, 1))
    assert info is not None
    assert info.sha256 == "deadbeef"


def test_available_update_returns_none_for_equal_or_older():
    assert available_update(_payload(tag="v0.1.0"), (0, 1, 0)) is None
    assert available_update(_payload(tag="v0.0.9"), (0, 1, 0)) is None
    # A genuinely newer release still qualifies.
    assert available_update(_payload(tag="v0.1.9"), (0, 1, 0)) is not None


def test_available_update_respects_previously_applied_version():
    payload = _payload()
    assert available_update(payload, (0, 0, 1), applied_version=__version__) is None
    assert available_update(payload, (0, 0, 1), applied_version="0.0.1") is not None


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"tag_name": "not-a-version"},
        {"tag_name": f"v{__version__}", "assets": []},
        {"tag_name": f"v{__version__}", "assets": [{"name": "wrong-name.zip"}]},
        {"tag_name": f"v{__version__}", "assets": "nope"},
    ],
)
def test_available_update_returns_none_for_unusable_payloads(payload):
    assert available_update(payload, (0, 0, 1)) is None


def test_available_update_returns_none_without_download_url():
    payload = _payload(url="")
    assert available_update(payload, (0, 0, 1)) is None


def test_available_update_drops_non_numeric_asset_size():
    payload = _payload(size="large")
    info = available_update(payload, (0, 0, 1))
    assert info is not None
    assert info.size_bytes is None


def test_available_update_ignores_non_sha256_digest():
    payload = _payload(digest="md5:abcdef")
    info = available_update(payload, (0, 0, 1))
    assert info is not None
    assert info.sha256 is None


def test_updater_emits_lifecycle_logs(caplog):
    caplog.set_level("INFO")
    payload = {
        "tag_name": NEXT_TAG,
        "assets": [
            {
                "name": NEXT_ZIP,
                "browser_download_url": (
                    f"https://github.com/{GITHUB_REPO}/releases/download/{NEXT_TAG}/{NEXT_ZIP}"
                ),
                "size": 100,
            }
        ],
    }
    # Available update log
    rel = available_update(payload, current_version=installed_version())
    assert rel is not None
    assert f"Update available: {NEXT_TAG}" in caplog.text

    # Up to date log
    caplog.clear()
    up_to_date = available_update(payload, current_version=parse_version(NEXT_VERSION))
    assert up_to_date is None
    assert "ScanSort is up to date" in caplog.text


def test_check_for_updates_available(tmp_path: Path):
    from unittest.mock import patch

    from scansort.updater.feed import ReleaseInfo, check_for_updates

    fake_release = ReleaseInfo(
        version=NEXT_VERSION,
        tag_name=NEXT_TAG,
        asset_name=NEXT_ZIP,
        download_url="https://example.com/dl.zip",
        size_bytes=100,
        sha256="abc",
        published_at=None,
    )
    with (
        patch("scansort.updater.feed.fetch_latest_release", return_value={}),
        patch("scansort.updater.feed.available_update", return_value=fake_release),
    ):
        rel, err = check_for_updates(tmp_path)
        assert rel == fake_release
        assert err is None


def test_check_for_updates_none_available(tmp_path: Path):
    from unittest.mock import patch

    from scansort.updater.feed import check_for_updates

    with (
        patch("scansort.updater.feed.fetch_latest_release", return_value={}),
        patch("scansort.updater.feed.available_update", return_value=None),
    ):
        rel, err = check_for_updates(tmp_path)
        assert rel is None
        assert err is None


def test_check_for_updates_error(tmp_path: Path):
    from unittest.mock import patch

    from scansort.updater.feed import UpdateError, check_for_updates

    with patch(
        "scansort.updater.feed.fetch_latest_release",
        side_effect=UpdateError("Network down"),
    ):
        rel, err = check_for_updates(tmp_path)
        assert rel is None
        assert err == "Network down"

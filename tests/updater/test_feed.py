"""Unit tests for the GitHub Releases release feed and version parser."""

import io
import json

import pytest

import scansort.updater as updater
from scansort.updater.feed import (
    REQUEST_TIMEOUT,
    WINDOWS_ASSET_PREFIX,
    WINDOWS_ASSET_SUFFIX,
    available_update,
    fetch_latest_release,
    installed_version,
    parse_version,
)
from scansort.updater.installer import UpdateError

WINDOWS_ZIP = f"{WINDOWS_ASSET_PREFIX}v0.2.0{WINDOWS_ASSET_SUFFIX}"


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
    tag: str = "v0.2.0",
    *,
    asset_name: str | None = None,
    digest: object = None,
    url: str = f"https://example.com/{WINDOWS_ASSET_PREFIX}v0.2.0{WINDOWS_ASSET_SUFFIX}",
    size: int | None = 123,
) -> dict:
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
        ("0.1.0", (0, 1, 0)),
        ("v1.2.3", (1, 2, 3)),
        ("V2.0.0", (2, 0, 0)),
        (" 3.4.5 ", (3, 4, 5)),
    ],
)
def test_parse_version_valid(raw: str, expected):
    assert parse_version(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "1.2", "1.2.3.4", "1.2.3-rc1", "v1.2", "abc", "1.x.3", None, 12],
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


def test_available_update_returns_newer_release():
    info = available_update(_payload(digest="sha256:abcdef"), (0, 1, 0))
    assert info is not None
    assert info.version == "0.2.0"
    assert info.tag_name == "v0.2.0"
    assert info.asset_name == WINDOWS_ZIP
    assert info.sha256 == "abcdef"
    assert info.size_bytes == 123


def test_available_update_list_digest_form():
    digest = [{"algorithm": "sha256", "value": "deadbeef"}]
    payload = _payload(digest=digest)
    info = available_update(payload, (0, 1, 0))
    assert info is not None
    assert info.sha256 == "deadbeef"


def test_available_update_returns_none_for_equal_or_older():
    assert available_update(_payload(tag="v0.1.0"), (0, 1, 0)) is None
    assert available_update(_payload(tag="v0.0.9"), (0, 1, 0)) is None
    # A genuinely newer release still qualifies.
    assert available_update(_payload(tag="v0.1.9"), (0, 1, 0)) is not None


def test_available_update_respects_previously_applied_version():
    payload = _payload(tag="v0.2.0")
    assert available_update(payload, (0, 1, 0), applied_version="0.2.0") is None
    assert available_update(payload, (0, 1, 0), applied_version="0.1.0") is not None


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"tag_name": "not-a-version"},
        {"tag_name": "v0.2.0", "assets": []},
        {"tag_name": "v0.2.0", "assets": [{"name": "wrong-name.zip"}]},
        {"tag_name": "v0.2.0", "assets": "nope"},
    ],
)
def test_available_update_returns_none_for_unusable_payloads(payload):
    assert available_update(payload, (0, 1, 0)) is None


def test_available_update_returns_none_without_download_url():
    payload = _payload(url="")
    assert available_update(payload, (0, 1, 0)) is None


def test_available_update_drops_non_numeric_asset_size():
    payload = _payload(size="large")
    info = available_update(payload, (0, 1, 0))
    assert info is not None
    assert info.size_bytes is None


def test_available_update_ignores_non_sha256_digest():
    payload = _payload(digest="md5:abcdef")
    info = available_update(payload, (0, 1, 0))
    assert info is not None
    assert info.sha256 is None


def test_updater_emits_lifecycle_logs(caplog):
    caplog.set_level("INFO")
    payload = {
        "tag_name": "v9.9.9",
        "assets": [
            {
                "name": "ScanSort-v9.9.9-windows-x64.zip",
                "browser_download_url": "https://example.com/dl.zip",
                "size": 100,
            }
        ],
    }
    # Available update log
    rel = available_update(payload, current_version=(1, 0, 0))
    assert rel is not None
    assert "Update available: v9.9.9" in caplog.text

    # Up to date log
    caplog.clear()
    up_to_date = available_update(payload, current_version=(9, 9, 9))
    assert up_to_date is None
    assert "ScanSort is up to date" in caplog.text


def test_updater_re_exports_symbols():
    from scansort.updater.installer import (
        cleanup_stale_updates,
        replace_install_dir,
    )
    from scansort.updater.process import (
        launch_installed_app,
        perform_self_update,
        spawn_update_helper,
        wait_for_process_exit,
    )

    assert updater.cleanup_stale_updates is cleanup_stale_updates
    assert updater.launch_installed_app is launch_installed_app
    assert updater.perform_self_update is perform_self_update
    assert updater.replace_install_dir is replace_install_dir
    assert updater.spawn_update_helper is spawn_update_helper
    assert updater.wait_for_process_exit is wait_for_process_exit

"""Fixed timezone helpers: ScanSort always operates on Australia/Sydney time."""

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo

SYDNEY_TZ: tzinfo = ZoneInfo("Australia/Sydney")


def sydney_now() -> datetime:
    """Return the current wall-clock time in Australia/Sydney (aware)."""
    return datetime.now(UTC).astimezone(SYDNEY_TZ)

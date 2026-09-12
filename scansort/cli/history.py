"""Filing history and audit inspection CLI subcommand handler."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scansort.cli.args import CliArgs
from scansort.core.config import get_default_app_dir
from scansort.core.constants import HISTORY_JSONL_NAME


def load_history_records(history_path: Path) -> list[dict[str, Any]] | None:
    """Load and parse JSONL records, tolerating empty files or malformed lines.

    Returns ``None`` when the file exists but cannot be read (I/O failure), so
    callers can distinguish a genuine read error from an empty history (F23).
    """
    records: list[dict[str, Any]] = []
    try:
        if not history_path.exists() or history_path.stat().st_size == 0:
            return []
        with open(history_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                clean = line.strip()
                if not clean:
                    continue
                try:
                    parsed = json.loads(clean)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    records.append(parsed)
    except FileNotFoundError:
        return []
    except OSError as e:
        print(f"Error reading history file: {e}", file=sys.stderr)
        return None

    return records


def safe_str(val: Any, default: str = "") -> str:
    """Return string representation or default if val is None or empty."""
    if val is None:
        return default
    s = str(val).strip()
    return s if s else default


def _truncate_column(value: str, width: int) -> str:
    """Ellipsis-truncate *value* so it fits within *width* characters."""
    return value[: width - 3] + "..." if len(value) > width else value


def handle_history(parsed: argparse.Namespace) -> int:
    """Handle 'history' command to view, filter, or export filing records."""
    args = CliArgs.from_namespace(parsed)
    app_dir = get_default_app_dir()
    history_file = app_dir / HISTORY_JSONL_NAME

    records = load_history_records(history_file)
    if records is None:
        return 1
    if not records:
        print("No filing history found.")
        return 0

    # Filter by status
    status_filter = args.status
    if status_filter:
        clean_status = status_filter.strip().upper()
        records = [
            r for r in records if safe_str(r.get("status")).upper() == clean_status
        ]

    # Filter by search term
    search_term = args.search
    if search_term:
        q = search_term.strip().lower()
        records = [
            r
            for r in records
            if q in safe_str(r.get("original_filename")).lower()
            or q in safe_str(r.get("new_filename")).lower()
            or q in safe_str(r.get("summary")).lower()
            or q in safe_str(r.get("destination_folder")).lower()
        ]

    # Ordering: default newest-first unless --reverse is passed
    reverse = args.reverse
    if not reverse:
        records = list(reversed(records))

    # Apply limit
    limit = args.limit if args.limit is not None else 20
    if limit is not None and limit > 0:
        records = records[:limit]

    if args.json:
        print(json.dumps(records, indent=2))
        return 0

    if not records:
        print("No filing history records match the specified filter criteria.")
        return 0

    print(
        "================================ ScanSort Filing History ================================"
    )
    header = f"{'Local Time':<20} {'Status':<12} {'Original File':<22} {'Filed As / Destination':<35}"
    print(header)
    print("-" * len(header))

    for r in records:
        time_str = (
            safe_str(r.get("local_time")) or safe_str(r.get("timestamp")) or "Unknown"
        )
        if len(time_str) > 19:
            time_str = time_str[:19]
        status_str = safe_str(r.get("status"), default="UNKNOWN")
        orig = _truncate_column(
            safe_str(r.get("original_filename"), default="Unknown"), 20
        )
        dest = _truncate_column(
            safe_str(r.get("new_filename"))
            or safe_str(r.get("destination_folder"))
            or "Unknown",
            34,
        )

        row = f"{time_str:<20} {status_str:<12} {orig:<22} {dest:<35}"
        print(row)
        summary = safe_str(r.get("summary"))
        if summary and status_str != "SUCCESS":
            print(f"  └─ Note: {summary}")

    print(
        "========================================================================================="
    )
    return 0

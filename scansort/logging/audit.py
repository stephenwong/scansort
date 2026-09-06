"""Audit logger maintaining dual JSONL and CSV execution logs for all processed scans."""

import csv
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scansort.core.config import get_default_app_dir
from scansort.core.constants import HISTORY_CSV_NAME, HISTORY_JSONL_NAME
from scansort.core.timeutil import sydney_now

logger = logging.getLogger(__name__)

CSV_FIELD_MAPPING: list[tuple[str, str]] = [
    ("Timestamp", "timestamp"),
    ("Local Time", "local_time"),
    ("Original File", "original_filename"),
    ("New Filename", "new_filename"),
    ("Folder", "destination_folder"),
    ("Destination Path", "destination_path"),
    ("SHA256", "sha256"),
    ("Summary", "summary"),
    ("Status", "status"),
]

CSV_HEADERS: list[str] = [header for header, _ in CSV_FIELD_MAPPING]

_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r", "\n")


def _sanitize_csv_cell(value: object) -> str:
    """Neutralize spreadsheet formula prefixes and undecodable surrogates in CSV cells."""
    cell = str(value).encode("utf-8", "replace").decode("utf-8")
    if cell.startswith(_FORMULA_PREFIXES):
        cell = "'" + cell
    return cell


class AuditLogger:
    """Manages appending audit logs in JSONL and CSV formats."""

    def __init__(
        self,
        jsonl_path: Path | None = None,
        csv_path: Path | None = None,
        mirror_csv_path: Path | None = None,
    ) -> None:
        app_dir = get_default_app_dir()
        self.jsonl_path = jsonl_path or (app_dir / HISTORY_JSONL_NAME)
        self.csv_path = csv_path or (app_dir / HISTORY_CSV_NAME)
        self.mirror_csv_path = mirror_csv_path

    def _ensure_csv_headers(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if path.stat().st_size > 0:
                    return
                # Zero-byte file: append the header only while still empty so a
                # concurrent process's appends are never truncated.
                with open(path, "a", newline="", encoding="utf-8") as f:
                    if os.fstat(f.fileno()).st_size == 0:
                        csv.writer(f).writerow(CSV_HEADERS)
                return
            with open(path, "x", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(CSV_HEADERS)
        except FileExistsError:
            pass  # A concurrent process created the file first; never truncate.
        except OSError as e:
            logger.error("Failed to initialize CSV header at %s: %s", path, e)

    def log_scan(self, entry: dict[str, Any]) -> None:
        """Record a scan event to JSONL and CSV log files.

        Args:
            entry: Log record dictionary.
        """
        record = dict(entry)
        now_utc = datetime.now(UTC)
        record.setdefault("timestamp", now_utc.isoformat())
        record.setdefault("local_time", sydney_now().strftime("%Y-%m-%d %H:%M:%S"))

        # Write to JSONL
        try:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except (OSError, UnicodeError) as e:
            logger.error("Failed to append to history.jsonl: %s", e)

        # Write to CSV
        csv_row = [
            _sanitize_csv_cell(record.get(field_key, ""))
            for _, field_key in CSV_FIELD_MAPPING
        ]

        for target_csv in [self.csv_path, self.mirror_csv_path]:
            if target_csv:
                try:
                    self._ensure_csv_headers(target_csv)
                    with open(target_csv, "a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow(csv_row)
                except (OSError, UnicodeError) as e:
                    logger.error("Failed to append to %s: %s", target_csv, e)

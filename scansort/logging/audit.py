"""Audit logger maintaining dual JSONL and CSV execution logs for all processed scans."""

import csv
import io
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scansort.core.config import get_default_app_dir
from scansort.core.constants import HISTORY_CSV_NAME, HISTORY_JSONL_NAME
from scansort.core.fs import atomic_write, interprocess_file_lock
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
    ("Ocr Engine", "ocr_engine"),
    ("Ocr Confidence", "ocr_confidence"),
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
        self._migration_attempted: set[Path] = set()

    def _ensure_csv_headers(self, path: Path) -> None:
        # Serialize header initialization across processes: without a lock two
        # writers can both observe a zero-byte file and emit duplicate headers.
        lock_path = path.parent / (path.name + ".lock")
        try:
            with interprocess_file_lock(lock_path):
                path.parent.mkdir(parents=True, exist_ok=True)
                # Append-only open never truncates a file another process
                # populated; the added row is only written for an empty file.
                with open(path, "a", newline="", encoding="utf-8") as f:
                    if os.fstat(f.fileno()).st_size == 0:
                        csv.writer(f).writerow(CSV_HEADERS)
                        f.flush()
                        return
                self._migrate_csv_header(path)
        except OSError as e:
            logger.error("Failed to initialize CSV header at %s: %s", path, e)

    def _migrate_csv_header(self, path: Path) -> None:
        """Pad a legacy short-header CSV up to the canonical column schema.

        Only a strict prefix of the canonical header (a trailing column append)
        is migrated; unrecognized shapes are left untouched.
        """
        if path in self._migration_attempted:
            return
        self._migration_attempted.add(path)
        try:
            with open(path, newline="", encoding="utf-8") as f:
                first_line = f.readline()
        except (OSError, UnicodeError) as e:
            logger.error("Failed to inspect CSV header at %s: %s", path, e)
            return
        existing = next(csv.reader([first_line]), []) if first_line else []
        if not existing or existing == CSV_HEADERS:
            return
        if existing != CSV_HEADERS[: len(existing)]:
            return

        try:
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
        except (OSError, UnicodeError, csv.Error) as e:
            logger.error("Failed to read legacy CSV at %s: %s", path, e)
            return

        width = len(CSV_HEADERS)
        migrated = [CSV_HEADERS]
        migrated.extend((row + [""] * width)[:width] for row in rows[1:])
        buffer = io.StringIO()
        csv.writer(buffer).writerows(migrated)
        try:
            atomic_write(path, buffer.getvalue())
        except OSError as e:
            logger.error("Failed to migrate CSV header at %s: %s", path, e)

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
                f.write(json.dumps(record, default=str) + "\n")
        except (OSError, UnicodeError, TypeError, ValueError) as e:
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

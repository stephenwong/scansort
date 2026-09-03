"""Audit logger maintaining dual JSONL and CSV execution logs for all processed scans."""

import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scansort.config import get_default_app_dir

logger = logging.getLogger(__name__)

CSV_HEADERS = [
    "Timestamp",
    "Local Time",
    "Original File",
    "New Filename",
    "Folder",
    "Destination Path",
    "SHA256",
    "Summary",
    "Status",
]


class AuditLogger:
    """Manages appending audit logs in JSONL and CSV formats."""

    def __init__(
        self,
        jsonl_path: Path | None = None,
        csv_path: Path | None = None,
        mirror_csv_path: Path | None = None,
    ) -> None:
        app_dir = get_default_app_dir()
        self.jsonl_path = jsonl_path or (app_dir / "history.jsonl")
        self.csv_path = csv_path or (app_dir / "history.csv")
        self.mirror_csv_path = mirror_csv_path

    def _ensure_csv_headers(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size == 0:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_HEADERS)

    def log_scan(self, entry: dict[str, Any]) -> None:
        """Record a scan event to JSONL and CSV log files.

        Args:
            entry: Log record dictionary.
        """
        record = dict(entry)
        now_utc = datetime.now(UTC)
        record.setdefault("timestamp", now_utc.isoformat())
        record.setdefault(
            "local_time", now_utc.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        )

        # Write to JSONL
        try:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as e:
            logger.error("Failed to append to history.jsonl: %s", e)

        # Write to CSV
        csv_row = [
            record.get("timestamp", ""),
            record.get("local_time", ""),
            record.get("original_filename", ""),
            record.get("new_filename", ""),
            record.get("destination_folder", ""),
            record.get("destination_path", ""),
            record.get("sha256", ""),
            record.get("summary", ""),
            record.get("status", ""),
        ]

        for target_csv in [self.csv_path, self.mirror_csv_path]:
            if target_csv:
                try:
                    self._ensure_csv_headers(target_csv)
                    with open(target_csv, "a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow(csv_row)
                except OSError as e:
                    logger.error("Failed to append to %s: %s", target_csv, e)

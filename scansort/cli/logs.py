"""Log inspection, streaming, and maintenance CLI subcommand handler."""

import argparse
import os
import sys
import time
from pathlib import Path

from scansort.cli.args import CliArgs
from scansort.core.config import get_default_app_dir
from scansort.core.constants import LOG_FILENAME

_LEVEL_SEVERITY = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "WARN": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

_LEVEL_SUBSTRINGS: tuple[tuple[str, int], ...] = (
    ("CRITICAL", 50),
    ("ERROR", 40),
    ("WARNING", 30),
    ("WARN", 30),
    ("INFO", 20),
    ("DEBUG", 10),
)


def _extract_line_severity(line: str) -> int | None:
    """Attempt to extract standard logging level from a formatted log line."""
    tokens = line.split(maxsplit=4)
    if len(tokens) >= 3:
        candidate = tokens[2].upper()
        if candidate in _LEVEL_SEVERITY:
            return _LEVEL_SEVERITY[candidate]
    # Continuation lines (tracebacks) inherit the previous line's severity.
    if line[:1].isspace():
        return None
    # Fallback to token search in first 50 chars
    upper_head = line[:50].upper()
    for lvl, sev in _LEVEL_SUBSTRINGS:
        if lvl in upper_head:
            return sev
    return None


def _line_passes(
    line: str, min_severity: int | None, last_matched: bool
) -> tuple[bool, bool]:
    """Return ``(updated_last_matched, should_emit)`` for a log-level filter."""
    if min_severity is None:
        return last_matched, True
    severity = _extract_line_severity(line)
    if severity is not None:
        last_matched = severity >= min_severity
    return last_matched, last_matched


def _follow_log(log_file: Path, min_severity: int | None) -> None:
    """Stream appended log lines, following across rotations/truncation.

    The file handle is opened only for the duration of each read and closed
    before the poll sleep: on Windows an open handle blocks the writer's
    ``RotatingFileHandler`` rename (WinError 32), which would defeat log
    rotation for as long as the follower runs (F24).
    """
    last_matched = False
    inode: int | None = None
    position = 0
    first_iteration = True
    while True:
        try:
            stat = os.stat(log_file)
        except OSError:
            if first_iteration:
                raise
            time.sleep(0.2)
            continue

        if inode is None or stat.st_ino != inode or stat.st_size < position:
            # Fresh file, rotation, or truncation: read from the beginning.
            inode = stat.st_ino
            position = 0

        try:
            with open(log_file, encoding="utf-8", errors="replace") as f:
                f.seek(position)
                while True:
                    line = f.readline()
                    if not line:
                        break
                    last_matched, emit = _line_passes(line, min_severity, last_matched)
                    if emit:
                        print(line, end="")
                        sys.stdout.flush()
                    position = f.tell()
        except OSError:
            if first_iteration:
                raise
        first_iteration = False
        time.sleep(0.2)


def handle_logs(parsed: argparse.Namespace) -> int:
    """Handle 'logs' command to view, filter, tail, or clear scansort.log."""
    args = CliArgs.from_namespace(parsed)
    app_dir = get_default_app_dir()
    log_file = app_dir / LOG_FILENAME

    if args.clear:
        if not log_file.exists():
            print(f"Log file does not exist: {log_file}")
            return 0
        try:
            with open(log_file, "w", encoding="utf-8"):
                pass
            print(f"Log file cleared: {log_file}")
            return 0
        except OSError as e:
            print(f"Error clearing log file: {e}", file=sys.stderr)
            return 1

    if not log_file.exists():
        print(f"No log file found at: {log_file}")
        return 0

    target_level_str = args.level
    min_severity = (
        _LEVEL_SEVERITY.get(target_level_str.upper()) if target_level_str else None
    )

    if args.follow:
        try:
            _follow_log(log_file, min_severity)
        except KeyboardInterrupt:
            return 0
        except OSError as e:
            print(f"Error reading log file: {e}", file=sys.stderr)
            return 1

    try:
        with open(log_file, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        print(f"Error reading log file: {e}", file=sys.stderr)
        return 1

    if min_severity is not None:
        filtered = []
        last_matched = False
        for line in lines:
            last_matched, emit = _line_passes(line, min_severity, last_matched)
            if emit:
                filtered.append(line)
        lines = filtered

    count = args.lines
    display_lines = lines[-count:] if count > 0 else []
    for line in display_lines:
        print(line, end="")
    sys.stdout.flush()

    return 0

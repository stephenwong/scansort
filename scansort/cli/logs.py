"""Log inspection, streaming, and maintenance CLI subcommand handler."""

import argparse
import os
import sys
import time

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


def handle_logs(parsed: argparse.Namespace) -> int:
    """Handle 'logs' command to view, filter, tail, or clear scansort.log."""
    app_dir = get_default_app_dir()
    log_file = app_dir / LOG_FILENAME

    if getattr(parsed, "clear", False):
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

    target_level_str = getattr(parsed, "level", None)
    min_severity = (
        _LEVEL_SEVERITY.get(target_level_str.upper()) if target_level_str else None
    )

    if getattr(parsed, "follow", False):
        try:
            last_matched = False
            while True:
                rotated = False
                with open(log_file, encoding="utf-8", errors="replace") as f:
                    last_inode = os.fstat(f.fileno()).st_ino
                    # Print content already present (empty on a fresh rotation).
                    for line in f:
                        if min_severity is not None:
                            sev = _extract_line_severity(line)
                            if sev is not None:
                                last_matched = sev >= min_severity
                            if not last_matched:
                                continue
                        print(line, end="")
                        sys.stdout.flush()

                    # Poll for appended lines, detecting log rotation/truncation.
                    while True:
                        try:
                            current_inode = os.stat(log_file).st_ino
                        except OSError:
                            current_inode = last_inode
                        if current_inode != last_inode:
                            rotated = True
                            break
                        line = f.readline()
                        if line:
                            if min_severity is not None:
                                sev = _extract_line_severity(line)
                                if sev is not None:
                                    last_matched = sev >= min_severity
                                if not last_matched:
                                    continue
                            print(line, end="")
                            sys.stdout.flush()
                        else:
                            time.sleep(0.2)
                if not rotated:
                    break
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
            sev = _extract_line_severity(line)
            if sev is not None:
                last_matched = sev >= min_severity
            if last_matched:
                filtered.append(line)
        lines = filtered

    count = getattr(parsed, "lines", 50)
    display_lines = lines[-count:] if count > 0 else []
    for line in display_lines:
        print(line, end="")
    sys.stdout.flush()

    return 0

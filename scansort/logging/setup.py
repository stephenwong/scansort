"""Persistent rotating file and console logging configuration for ScanSort."""

import logging
import logging.handlers
from pathlib import Path

from scansort.config import get_default_app_dir
from scansort.constants import LOG_FILENAME

_LOG_MAX_BYTES = 1_048_576
_LOG_BACKUP_COUNT = 3
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_CONSOLE_MARKER = "_scansort_console_handler"


def _root_file_handlers(log_dir: Path) -> list[logging.Handler]:
    """Return root-logger file handlers already bound to ``log_dir``'s file."""
    target = (log_dir / LOG_FILENAME).resolve()
    return [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
        and Path(handler.baseFilename).resolve() == target
    ]


def _root_console_handlers() -> list[logging.Handler]:
    """Return the stderr console handlers previously attached by this module."""
    return [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.StreamHandler)
        and getattr(handler, _CONSOLE_MARKER, False)
    ]


def configure_file_logging(
    log_dir: Path | None = None,
    level: int = logging.INFO,
) -> logging.Handler | None:
    """Attach persistent rotating file and stderr console handlers to the root logger.

    Messages matching ``level`` (default INFO) from every ``scansort.*`` logger
    are written to ``scansort.log`` in ``log_dir`` (rotating at 1 MB, 3 backups);
    WARNING-and-above (or DEBUG if verbose) messages flow to stderr. Calling
    again for the same directory updates or reuses the existing handlers.
    Best-effort: returns None if the log directory cannot be prepared.

    Args:
        log_dir: Target directory for the log file (defaults to app data dir).
        level: Minimum logging level for root logger and file handler (e.g. logging.INFO or logging.DEBUG).

    Returns:
        The active RotatingFileHandler, or None on I/O failure.
    """
    directory = log_dir or get_default_app_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    existing_file_handlers = _root_file_handlers(directory)
    if not existing_file_handlers:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                directory / LOG_FILENAME,
                maxBytes=_LOG_MAX_BYTES,
                backupCount=_LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        except OSError:
            return None
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logging.getLogger().addHandler(file_handler)
        existing_file_handlers = [file_handler]
    else:
        existing_file_handlers[0].setLevel(level)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    console_handlers = _root_console_handlers()
    console_level = logging.DEBUG if level == logging.DEBUG else logging.WARNING
    if not console_handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        setattr(console_handler, _CONSOLE_MARKER, True)
        logging.getLogger().addHandler(console_handler)
    else:
        console_handlers[0].setLevel(console_level)

    return existing_file_handlers[0]

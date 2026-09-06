"""Persistent rotating file logging for ScanSort.

Diagnostics (e.g. redacted Gemini API failures) are otherwise only visible on
stderr, which the packaged GUI executable discards unless it was launched from
a console. This module attaches a rotating ``scansort.log`` handler in the app
data directory so warnings and errors survive background tray operation.
"""

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


def configure_file_logging(log_dir: Path | None = None) -> logging.Handler | None:
    """Attach persistent rotating file and stderr console handlers to the root logger.

    INFO-and-above messages from every ``scansort.*`` logger are written to
    ``scansort.log`` in ``log_dir`` (rotating at 1 MB, 3 backups); WARNING-and-
    above messages also keep flowing to stderr so terminal launches behave as
    before. Calling again for the same directory reuses the existing handlers.
    Best-effort by design: returns ``None`` instead of raising when the log
    directory or file cannot be created, so background operation never fails
    because logging is unavailable.
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
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logging.getLogger().addHandler(file_handler)
        existing_file_handlers = [file_handler]

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if not _root_console_handlers():
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        setattr(console_handler, _CONSOLE_MARKER, True)
        logging.getLogger().addHandler(console_handler)

    return existing_file_handlers[0]

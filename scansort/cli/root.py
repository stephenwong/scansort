"""Main CLI router, logging initialization, and parent console attachment."""

import logging

from scansort.cli.config import handle_config
from scansort.cli.parser import build_parser
from scansort.cli.rescan import handle_rescan
from scansort.cli.undo import handle_undo
from scansort.cli.update import handle_check_update, handle_self_update
from scansort.cli.watch import handle_watch
from scansort.logging import configure_file_logging
from scansort.platform.console import attach_parent_console

# Backward compatibility alias
_attach_parent_console = attach_parent_console


def main_cli(args: list[str] | None = None) -> int:
    """Main CLI execution router."""
    attach_parent_console()
    parser = build_parser()
    parsed = parser.parse_args(args)
    log_level = logging.DEBUG if getattr(parsed, "verbose", False) else logging.INFO
    configure_file_logging(level=log_level)

    if getattr(parsed, "self_update", None):
        return handle_self_update(parsed.self_update)

    command = parsed.command or "watch"
    handlers = {
        "watch": handle_watch,
        "config": handle_config,
        "undo": handle_undo,
        "rescan": handle_rescan,
        "check-update": handle_check_update,
    }
    handler = handlers.get(command, handle_watch)
    return handler(parsed)

"""Main CLI router, logging initialization, and parent console attachment."""

import logging

from scansort.cli.args import CliArgs
from scansort.cli.completion import handle_completion
from scansort.cli.config import handle_config
from scansort.cli.file_cmd import handle_file
from scansort.cli.help import handle_help
from scansort.cli.history import handle_history
from scansort.cli.logs import handle_logs
from scansort.cli.parser import build_parser
from scansort.cli.rescan import handle_rescan
from scansort.cli.review import handle_review
from scansort.cli.stats import handle_stats
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
    cli_args = CliArgs.from_namespace(parsed)
    log_level = logging.DEBUG if cli_args.verbose else logging.INFO
    configure_file_logging(level=log_level)

    if cli_args.self_update:
        return handle_self_update(cli_args.self_update)

    command = cli_args.command or "watch"
    if command == "help":
        return handle_help(parsed, parser=parser)

    handlers = {
        "watch": handle_watch,
        "file": handle_file,
        "config": handle_config,
        "undo": handle_undo,
        "review": handle_review,
        "rescan": handle_rescan,
        "check-update": handle_check_update,
        "logs": handle_logs,
        "history": handle_history,
        "stats": handle_stats,
        "completion": handle_completion,
    }
    handler = handlers.get(command, handle_watch)
    return handler(parsed)

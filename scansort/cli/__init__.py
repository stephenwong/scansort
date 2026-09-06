"""Command-line interface and subcommand routers for ScanSort."""

from scansort.cli.config import handle_config
from scansort.cli.parser import build_parser
from scansort.cli.rescan import handle_rescan
from scansort.cli.root import _attach_parent_console, main_cli
from scansort.cli.undo import handle_undo
from scansort.cli.update import handle_check_update, handle_self_update
from scansort.cli.watch import handle_watch

__all__ = [
    "main_cli",
    "build_parser",
    "handle_watch",
    "handle_config",
    "handle_undo",
    "handle_rescan",
    "handle_check_update",
    "handle_self_update",
    "_attach_parent_console",
]

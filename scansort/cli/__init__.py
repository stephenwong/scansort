from scansort.cli.completion import handle_completion
from scansort.cli.config import handle_config
from scansort.cli.file_cmd import handle_file
from scansort.cli.help import handle_help
from scansort.cli.history import handle_history
from scansort.cli.logs import handle_logs
from scansort.cli.ocr import handle_ocr_backfill
from scansort.cli.parser import build_parser
from scansort.cli.rescan import handle_rescan
from scansort.cli.review import handle_review
from scansort.cli.root import _attach_parent_console, main_cli
from scansort.cli.stats import handle_stats
from scansort.cli.undo import handle_undo
from scansort.cli.update import handle_check_update, handle_self_update
from scansort.cli.watch import handle_watch

__all__ = [
    "main_cli",
    "build_parser",
    "handle_watch",
    "handle_file",
    "handle_config",
    "handle_undo",
    "handle_review",
    "handle_rescan",
    "handle_ocr_backfill",
    "handle_check_update",
    "handle_self_update",
    "handle_logs",
    "handle_history",
    "handle_stats",
    "handle_help",
    "handle_completion",
    "_attach_parent_console",
]

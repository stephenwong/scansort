"""Undo CLI subcommand handler."""

import argparse
import sys

from scansort.cli.args import CliArgs
from scansort.cli.config import _load_config_or_exit
from scansort.core.config import get_default_app_dir
from scansort.pipeline.undo import run_undo, undo_last_move


def handle_undo(parsed: argparse.Namespace) -> int:
    """Handle 'undo' command to reverse the most recent file move."""
    args = CliArgs.from_namespace(parsed)
    cfg = _load_config_or_exit()
    if cfg is None:
        return 1
    if args.dry_run or cfg.dry_run:
        print("Dry-run mode: would reverse the last move. No files were changed.")
        return 0
    app_dir = get_default_app_dir()
    result = run_undo(cfg, undo_fn=undo_last_move, app_dir=app_dir)
    if result.success or result.no_action:
        print(result.message)
        return 0
    print(result.message, file=sys.stderr)
    return 1

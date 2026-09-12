"""Undo CLI subcommand handler."""

import argparse
import sys

from scansort.cli.config import _load_config_or_exit
from scansort.core.config import get_default_app_dir
from scansort.pipeline.undo import run_undo, undo_last_move


def handle_undo(parsed: argparse.Namespace) -> int:
    """Handle 'undo' command to reverse the most recent file move."""
    cfg = _load_config_or_exit()
    if cfg is None:
        return 1
    if getattr(parsed, "dry_run", False) or cfg.dry_run:
        print("Dry-run mode: would reverse the last move. No files were changed.")
        return 0
    app_dir = get_default_app_dir()
    success, message, restored = run_undo(cfg, undo_fn=undo_last_move, app_dir=app_dir)
    if success:
        print(message)
        return 0
    if restored is None and "No reversible" in message:
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 1

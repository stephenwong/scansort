"""Undo CLI subcommand handler."""

import argparse
import sys

from scansort.cli.config import _load_config_or_exit
from scansort.core.config import get_default_app_dir
from scansort.core.constants import HISTORY_JSONL_NAME
from scansort.pipeline.undo import undo_last_move


def handle_undo(parsed: argparse.Namespace) -> int:
    """Handle 'undo' command to reverse the most recent file move."""
    cfg = _load_config_or_exit()
    if cfg is None:
        return 1
    jsonl_path = get_default_app_dir() / HISTORY_JSONL_NAME
    try:
        restored = undo_last_move(jsonl_path, mirror_csv_path=cfg.mirror_csv_path)
        if restored:
            print(f"Successfully reversed move. File restored to: {restored}")
        else:
            print("No reversible document filing action found in history.")
        return 0
    except OSError as e:
        print(f"Error reversing last move: {e}", file=sys.stderr)
        return 1

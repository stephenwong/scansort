"""CLI entry point and command router for ScanSort."""

import sys

from scansort.cli import _attach_parent_console, build_parser, main_cli
from scansort.logging import configure_file_logging

__all__ = [
    "main_cli",
    "build_parser",
    "_attach_parent_console",
    "configure_file_logging",
]

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main_cli())

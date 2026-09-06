"""CLI argument parser construction for ScanSort."""

import argparse
from pathlib import Path

from scansort import __version__


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser."""
    verbose_parser = argparse.ArgumentParser(add_help=False)
    verbose_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Enable verbose debug logging",
    )

    parser = argparse.ArgumentParser(
        prog="scansort",
        description="ScanSort: Intelligent automated desktop document filer powered by Google Gemini.",
        parents=[verbose_parser],
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program's version number and exit",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Start minimized to tray",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Simulate actions without moving files",
    )
    parser.add_argument(
        "--self-update",
        nargs=4,
        metavar=("PID", "INSTALL_DIR", "STAGED_DIR", "VERSION"),
        help=argparse.SUPPRESS,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # watch command
    watch_p = subparsers.add_parser(
        "watch",
        parents=[verbose_parser],
        help="Start background drop folder monitor",
    )
    watch_p.add_argument("--watch-folder", type=Path, help="Override drop folder")
    watch_p.add_argument("--documents-root", type=Path, help="Override documents root")
    watch_p.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Simulate actions without moving files",
    )
    watch_p.add_argument(
        "--minimized",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Start minimized to tray",
    )

    # undo command
    subparsers.add_parser(
        "undo",
        parents=[verbose_parser],
        help="Reverse the last filed document move",
    )

    # rescan command
    subparsers.add_parser(
        "rescan",
        parents=[verbose_parser],
        help="Rescan and display Documents folder taxonomy",
    )

    # check-update command
    subparsers.add_parser(
        "check-update",
        parents=[verbose_parser],
        help="Check GitHub Releases for newer ScanSort versions",
    )

    # config command
    cfg_p = subparsers.add_parser(
        "config",
        parents=[verbose_parser],
        help="Manage application settings and secrets",
    )
    cfg_p.add_argument(
        "--show", action="store_true", help="Display current configuration"
    )
    cfg_p.add_argument(
        "--set-key", type=str, help="Store Gemini API key securely in credential vault"
    )
    cfg_p.add_argument(
        "--watch-folder", type=Path, help="Set default scanner drop folder"
    )
    cfg_p.add_argument(
        "--documents-folder", type=Path, help="Set default documents destination folder"
    )
    cfg_p.add_argument(
        "--autostart", choices=["enable", "disable"], help="Toggle auto-start on boot"
    )

    return parser

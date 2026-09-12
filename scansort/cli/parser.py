"""CLI argument parser construction for ScanSort."""

import argparse
from pathlib import Path

from scansort import __version__
from scansort.core.constants import FILING_STATUSES, SUPPORTED_GEMINI_MODELS


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

    # file command
    file_p = subparsers.add_parser(
        "file",
        parents=[verbose_parser],
        help="Directly process and file specified document(s)",
    )
    file_p.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="Path(s) to document file(s) to file",
    )
    file_p.add_argument(
        "--copy",
        "-c",
        action="store_true",
        help="Preserve original file(s) instead of moving them",
    )
    file_p.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Simulate filing actions without moving files",
    )

    # undo command
    subparsers.add_parser(
        "undo",
        parents=[verbose_parser],
        help="Reverse the last filed document move",
    )

    # review command
    review_p = subparsers.add_parser(
        "review",
        parents=[verbose_parser],
        help="Review and manually file ambiguous scans from _Review_Needed",
    )
    review_p.add_argument(
        "--gui",
        "-g",
        action="store_true",
        help="Launch the visual review dialog window",
    )
    review_p.add_argument(
        "--cli",
        "-c",
        action="store_true",
        help="Force interactive terminal review session",
    )
    review_p.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Limit number of documents to review",
    )

    # rescan command
    rescan_p = subparsers.add_parser(
        "rescan",
        parents=[verbose_parser],
        help="Rescan and display Documents folder taxonomy",
    )
    rescan_p.add_argument(
        "--json",
        action="store_true",
        help="Output discovered taxonomy as a JSON array",
    )

    # check-update command
    check_p = subparsers.add_parser(
        "check-update",
        parents=[verbose_parser],
        help="Check GitHub Releases for newer ScanSort versions",
    )
    check_p.add_argument(
        "--json",
        action="store_true",
        help="Output update availability information as JSON",
    )

    # logs command
    logs_p = subparsers.add_parser(
        "logs",
        parents=[verbose_parser],
        help="View, filter, or tail application execution logs",
    )
    logs_p.add_argument(
        "-n",
        "--lines",
        type=int,
        default=50,
        help="Number of log lines to show (default: 50)",
    )
    logs_p.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="Follow log output in real-time",
    )
    logs_p.add_argument(
        "--level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Minimum log severity level filter",
    )
    logs_p.add_argument(
        "--clear",
        action="store_true",
        help="Clear / truncate the application log file",
    )

    # history command
    hist_p = subparsers.add_parser(
        "history",
        parents=[verbose_parser],
        help="View and search document filing history and audit trail",
    )
    hist_p.add_argument(
        "-n",
        "--limit",
        type=int,
        default=20,
        help="Maximum records to display (0 for all, default: 20)",
    )
    hist_p.add_argument(
        "--status",
        choices=list(FILING_STATUSES),
        help="Filter records by filing status",
    )
    hist_p.add_argument(
        "-q",
        "--search",
        type=str,
        help="Search query matching filename, folder, or summary",
    )
    hist_p.add_argument(
        "--reverse",
        action="store_true",
        help="Display records in chronological order (oldest first)",
    )
    hist_p.add_argument(
        "--json",
        action="store_true",
        help="Output history records as JSON array",
    )

    # stats command
    stats_p = subparsers.add_parser(
        "stats",
        parents=[verbose_parser],
        help="Display aggregate filing statistics, token consumption, and estimated cost",
    )
    stats_p.add_argument(
        "--json",
        action="store_true",
        help="Output statistics as JSON",
    )

    # help command
    help_p = subparsers.add_parser(
        "help",
        parents=[verbose_parser],
        help="Show help for ScanSort or a specific command",
    )
    help_p.add_argument(
        "command_name",
        nargs="?",
        help="Subcommand name to display detailed help for",
    )

    # completion command
    comp_p = subparsers.add_parser(
        "completion",
        parents=[verbose_parser],
        help="Generate shell completion scripts (bash, zsh, fish, powershell)",
    )
    comp_p.add_argument(
        "shell",
        choices=["bash", "zsh", "fish", "powershell"],
        help="Target shell for autocomplete script",
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
        "--json", action="store_true", help="Output configuration as JSON"
    )
    cfg_p.add_argument(
        "--path", action="store_true", help="Print path to configuration file and exit"
    )
    cfg_p.add_argument(
        "--get",
        type=str,
        metavar="KEY",
        help="Inspect a specific configuration property",
    )
    cfg_p.add_argument(
        "--set",
        nargs=2,
        metavar=("KEY", "VALUE"),
        help="Set a specific configuration property",
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
        "--gemini-model",
        choices=list(SUPPORTED_GEMINI_MODELS),
        help="Set default Gemini classification model",
    )
    cfg_p.add_argument(
        "--fallback-folder", type=str, help="Set fallback review folder name"
    )
    cfg_p.add_argument(
        "--max-depth", type=int, help="Set maximum folder scanning depth (1-10)"
    )
    cfg_p.add_argument(
        "--mirror-csv",
        choices=["enable", "disable"],
        help="Toggle mirroring audit history CSV to Documents folder",
    )
    cfg_p.add_argument(
        "--auto-update",
        choices=["enable", "disable"],
        help="Toggle automated self-updates",
    )
    cfg_p.add_argument(
        "--update-check-interval",
        type=int,
        help="Set update check frequency in days (0-60)",
    )
    cfg_p.add_argument(
        "--dry-run", choices=["enable", "disable"], help="Toggle dry-run mode"
    )
    cfg_p.add_argument(
        "--autostart", choices=["enable", "disable"], help="Toggle auto-start on boot"
    )
    cfg_p.add_argument(
        "--context-menu",
        choices=["enable", "disable"],
        help="Toggle Windows Explorer right-click 'File with ScanSort' context menu",
    )

    return parser

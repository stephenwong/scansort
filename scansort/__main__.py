"""CLI entry point and command router for ScanSort."""

import argparse
import logging
import queue
import sys
import threading
from pathlib import Path

import keyring.errors

from scansort.autorun import disable_autorun, enable_autorun, is_autorun_enabled
from scansort.config import get_default_config_path, load_config, save_config
from scansort.dispatcher import undo_last_move
from scansort.folder_mapper import FolderMapper
from scansort.pipeline import ScanSortPipeline
from scansort.secrets import (
    get_api_key,
    mask_api_key,
    redact_secrets_from_text,
    set_api_key,
)
from scansort.watcher import DropFolderWatcher

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="scansort",
        description="ScanSort: Intelligent automated desktop document filer powered by Gemini 2.5 Flash.",
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
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # watch command
    watch_p = subparsers.add_parser(
        "watch", help="Start background drop folder monitor"
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
    subparsers.add_parser("undo", help="Reverse the last filed document move")

    # rescan command
    subparsers.add_parser("rescan", help="Rescan and display Documents folder taxonomy")

    # config command
    cfg_p = subparsers.add_parser(
        "config", help="Manage application settings and secrets"
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


def main_cli(args: list[str] | None = None) -> int:
    """Main CLI execution router."""
    parser = build_parser()
    parsed = parser.parse_args(args)

    if not parsed.command or parsed.command == "watch":
        cfg = load_config()
        if getattr(parsed, "watch_folder", None):
            cfg.watch_folder = parsed.watch_folder.resolve()
        if getattr(parsed, "documents_root", None):
            cfg.documents_root = parsed.documents_root.resolve()
        if getattr(parsed, "dry_run", False):
            cfg.dry_run = True

        cfg.ensure_directories()

        if not getattr(parsed, "minimized", False):
            print(f"Starting ScanSort monitor on: {cfg.watch_folder}")
            print(f"Destination Documents root: {cfg.documents_root}")
            if cfg.dry_run:
                print("[DRY-RUN MODE ACTIVE: No files will be moved]")

        file_queue: queue.Queue = queue.Queue()
        stop_event = threading.Event()
        pipeline = ScanSortPipeline(config=cfg)
        watcher = DropFolderWatcher(
            watch_folder=cfg.watch_folder, file_queue=file_queue
        )

        worker_thread = threading.Thread(
            target=pipeline.run_worker,
            args=(file_queue, stop_event),
            daemon=True,
        )
        worker_thread.start()

        try:
            watcher.start()
        except KeyboardInterrupt:
            pass
        finally:
            watcher.stop()
            stop_event.set()
            worker_thread.join(timeout=20.0)
            if worker_thread.is_alive():
                logger.warning("Worker thread did not terminate within 20 seconds.")

        return 0

    if parsed.command == "config":
        cfg = load_config()

        if parsed.set_key:
            try:
                set_api_key(parsed.set_key)
                print(
                    "Successfully saved Gemini API key to secure OS credential vault."
                )
            except (ValueError, keyring.errors.KeyringError, OSError) as e:
                redacted = redact_secrets_from_text(str(e), parsed.set_key)
                print(f"Error saving Gemini API key: {redacted}", file=sys.stderr)
                return 1

        if parsed.watch_folder:
            target = parsed.watch_folder.resolve()
            if target.is_file():
                print(
                    f"Error: Watch folder cannot be a regular file: {target}",
                    file=sys.stderr,
                )
                return 1
            if target == cfg.documents_root.resolve():
                print(
                    "Error: Watch folder and documents root cannot be the same directory.",
                    file=sys.stderr,
                )
                return 1
            cfg.watch_folder = target
            try:
                save_config(cfg)
            except OSError as e:
                print(f"Error saving configuration: {e}", file=sys.stderr)
                return 1
            print(f"Updated watch folder to: {cfg.watch_folder}")

        if parsed.documents_folder:
            target = parsed.documents_folder.resolve()
            if target.is_file():
                print(
                    f"Error: Documents folder cannot be a regular file: {target}",
                    file=sys.stderr,
                )
                return 1
            if target == cfg.watch_folder.resolve():
                print(
                    "Error: Watch folder and documents root cannot be the same directory.",
                    file=sys.stderr,
                )
                return 1
            cfg.documents_root = target
            try:
                save_config(cfg)
            except OSError as e:
                print(f"Error saving configuration: {e}", file=sys.stderr)
                return 1
            print(f"Updated documents folder to: {cfg.documents_root}")

        if parsed.autostart:
            if parsed.autostart == "enable":
                if not enable_autorun():
                    print(
                        "Error: Failed to enable auto-start on boot.", file=sys.stderr
                    )
                    return 1
                cfg.start_on_boot = True
                try:
                    save_config(cfg)
                except OSError as e:
                    print(f"Error saving configuration: {e}", file=sys.stderr)
                    return 1
                print("Auto-start on boot: ENABLED")
            else:
                if not disable_autorun():
                    print(
                        "Error: Failed to disable auto-start on boot.", file=sys.stderr
                    )
                    return 1
                cfg.start_on_boot = False
                try:
                    save_config(cfg)
                except OSError as e:
                    print(f"Error saving configuration: {e}", file=sys.stderr)
                    return 1
                print("Auto-start on boot: DISABLED")

        if parsed.show or (
            not parsed.set_key
            and not parsed.watch_folder
            and not parsed.documents_folder
            and not parsed.autostart
        ):
            api_key = get_api_key()
            masked = mask_api_key(api_key)
            autorun_status = "Enabled" if is_autorun_enabled() else "Disabled"

            print("================ ScanSort Configuration ================")
            print(f"Config File:       {get_default_config_path()}")
            print(f"Watch Folder:      {cfg.watch_folder}")
            print(f"Documents Root:    {cfg.documents_root}")
            print(f"Fallback Folder:   {cfg.fallback_folder}")
            print(f"Gemini Model:      {cfg.gemini_model}")
            print(f"Start on Boot:     {autorun_status}")
            print(f"Dry Run Mode:      {cfg.dry_run}")
            print(f"Gemini API Key:    {masked}")
            print("=========================================================")

        return 0

    if parsed.command == "undo":
        cfg_path = get_default_config_path().parent / "history.jsonl"
        try:
            restored = undo_last_move(cfg_path)
            if restored:
                print(f"Successfully reversed move. File restored to: {restored}")
            else:
                print("No reversible document filing action found in history.")
            return 0
        except OSError as e:
            print(f"Error reversing last move: {e}", file=sys.stderr)
            return 1

    if parsed.command == "rescan":
        cfg = load_config()
        mapper = FolderMapper(
            docs_root=cfg.documents_root,
            max_depth=cfg.max_folder_depth,
            fallback_folder=cfg.fallback_folder,
        )
        taxonomy = mapper.refresh()
        print(
            f"Discovered {len(taxonomy)} destination folders in {cfg.documents_root}:"
        )
        for f in taxonomy:
            print(f"  - {f}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main_cli())

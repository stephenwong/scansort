"""CLI entry point and command router for ScanSort."""

import argparse
import logging
import queue
import sys
import threading
from pathlib import Path

from scansort.autorun import disable_autorun, enable_autorun, is_autorun_enabled
from scansort.config import (
    AppConfig,
    get_default_app_dir,
    get_default_config_path,
    load_config,
    save_config,
)
from scansort.constants import HISTORY_JSONL_NAME
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
        description="ScanSort: Intelligent automated desktop document filer powered by Google Gemini.",
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


def _try_save_config(cfg: AppConfig) -> bool:
    """Persist configuration, printing user-friendly error on failure."""
    try:
        save_config(cfg)
        return True
    except OSError as e:
        print(f"Error saving configuration: {e}", file=sys.stderr)
        return False


def _load_config_or_exit() -> AppConfig | None:
    """Load configuration, printing a diagnostic and returning None on failure."""
    try:
        return load_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return None


def _handle_watch(parsed: argparse.Namespace) -> int:
    """Handle 'watch' command to start monitoring the drop folder."""
    cfg = _load_config_or_exit()
    if cfg is None:
        return 1
    new_watch = (
        parsed.watch_folder.resolve()
        if getattr(parsed, "watch_folder", None)
        else cfg.watch_folder
    )
    new_docs = (
        parsed.documents_root.resolve()
        if getattr(parsed, "documents_root", None)
        else cfg.documents_root
    )
    dry_run = getattr(parsed, "dry_run", False) or cfg.dry_run

    try:
        updated_dict = cfg.model_dump()
        updated_dict["watch_folder"] = new_watch
        updated_dict["documents_root"] = new_docs
        updated_dict["dry_run"] = dry_run
        cfg = AppConfig(**updated_dict)
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    try:
        cfg.ensure_directories()
    except OSError as e:
        print(f"Error preparing directories: {e}", file=sys.stderr)
        return 1

    if not getattr(parsed, "minimized", False):
        print(f"Starting ScanSort monitor on: {cfg.watch_folder}")
        print(f"Destination Documents root: {cfg.documents_root}")
        if cfg.dry_run:
            print("[DRY-RUN MODE ACTIVE: No files will be moved]")

    file_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()
    try:
        pipeline = ScanSortPipeline(config=cfg)
    except OSError as e:
        print(f"Error preparing application directories: {e}", file=sys.stderr)
        return 1
    watcher = DropFolderWatcher(watch_folder=cfg.watch_folder, file_queue=file_queue)

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


def _handle_config(parsed: argparse.Namespace) -> int:
    """Handle 'config' command to view or modify settings."""
    cfg = _load_config_or_exit()
    if cfg is None:
        return 1

    if parsed.set_key:
        try:
            set_api_key(parsed.set_key)
            print("Successfully saved Gemini API key to secure OS credential vault.")
        except (ValueError, OSError) as e:
            redacted = redact_secrets_from_text(str(e), parsed.set_key)
            print(f"Error saving Gemini API key: {redacted}", file=sys.stderr)
            return 1

    if parsed.watch_folder or parsed.documents_folder:
        new_watch = (
            parsed.watch_folder.resolve() if parsed.watch_folder else cfg.watch_folder
        )
        new_docs = (
            parsed.documents_folder.resolve()
            if parsed.documents_folder
            else cfg.documents_root
        )

        if parsed.watch_folder and parsed.watch_folder.resolve().is_file():
            print(
                f"Error: Watch folder cannot be a regular file: {parsed.watch_folder.resolve()}",
                file=sys.stderr,
            )
            return 1
        if parsed.documents_folder and parsed.documents_folder.resolve().is_file():
            print(
                f"Error: Documents folder cannot be a regular file: {parsed.documents_folder.resolve()}",
                file=sys.stderr,
            )
            return 1
        if new_watch.resolve() == new_docs.resolve():
            print(
                "Error: Watch folder and documents root cannot be the same directory.",
                file=sys.stderr,
            )
            return 1

        try:
            updated_dict = cfg.model_dump()
            updated_dict["watch_folder"] = new_watch
            updated_dict["documents_root"] = new_docs
            cfg = AppConfig(**updated_dict)
        except ValueError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            return 1

        if not _try_save_config(cfg):
            return 1

        if parsed.watch_folder:
            print(f"Updated watch folder to: {new_watch}")
        if parsed.documents_folder:
            print(f"Updated documents folder to: {new_docs}")

    if parsed.autostart:
        enable = parsed.autostart == "enable"
        action_fn = enable_autorun if enable else disable_autorun
        action_name = "enable" if enable else "disable"
        status_str = "ENABLED" if enable else "DISABLED"

        if not action_fn():
            print(
                f"Error: Failed to {action_name} auto-start on boot.", file=sys.stderr
            )
            return 1
        cfg.start_on_boot = enable
        if not _try_save_config(cfg):
            return 1
        print(f"Auto-start on boot: {status_str}")

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


def _handle_undo(parsed: argparse.Namespace) -> int:
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


def _handle_rescan(parsed: argparse.Namespace) -> int:
    """Handle 'rescan' command to discover and display taxonomy."""
    cfg = _load_config_or_exit()
    if cfg is None:
        return 1
    mapper = FolderMapper(
        docs_root=cfg.documents_root,
        max_depth=cfg.max_folder_depth,
        fallback_folder=cfg.fallback_folder,
    )
    taxonomy = mapper.refresh()
    print(f"Discovered {len(taxonomy)} destination folders in {cfg.documents_root}:")
    for f in taxonomy:
        print(f"  - {f}")
    return 0


def main_cli(args: list[str] | None = None) -> int:
    """Main CLI execution router."""
    parser = build_parser()
    parsed = parser.parse_args(args)

    command = parsed.command or "watch"
    handlers = {
        "watch": _handle_watch,
        "config": _handle_config,
        "undo": _handle_undo,
        "rescan": _handle_rescan,
    }
    handler = handlers.get(command, _handle_watch)
    return handler(parsed)


if __name__ == "__main__":
    sys.exit(main_cli())

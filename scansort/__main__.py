"""CLI entry point and command router for ScanSort."""

import argparse
import sys
from pathlib import Path

from scansort.autorun import disable_autorun, enable_autorun, is_autorun_enabled
from scansort.config import get_default_config_path, load_config, save_config
from scansort.dispatcher import undo_last_move
from scansort.folder_mapper import FolderMapper
from scansort.secrets import get_api_key, mask_api_key, set_api_key


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="scansort",
        description="ScanSort: Intelligent automated desktop document filer powered by Gemini 2.5 Flash.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # watch command
    watch_p = subparsers.add_parser("watch", help="Start background drop folder monitor")
    watch_p.add_argument("--watch-folder", type=Path, help="Override drop folder")
    watch_p.add_argument("--documents-root", type=Path, help="Override documents root")
    watch_p.add_argument("--dry-run", action="store_true", help="Simulate actions without moving files")
    watch_p.add_argument("--minimized", action="store_true", help="Start minimized to tray")

    # undo command
    subparsers.add_parser("undo", help="Reverse the last filed document move")

    # rescan command
    subparsers.add_parser("rescan", help="Rescan and display Documents folder taxonomy")

    # config command
    cfg_p = subparsers.add_parser("config", help="Manage application settings and secrets")
    cfg_p.add_argument("--show", action="store_true", help="Display current configuration")
    cfg_p.add_argument("--set-key", type=str, help="Store Gemini API key securely in credential vault")
    cfg_p.add_argument("--watch-folder", type=Path, help="Set default scanner drop folder")
    cfg_p.add_argument("--documents-folder", type=Path, help="Set default documents destination folder")
    cfg_p.add_argument("--autostart", choices=["enable", "disable"], help="Toggle auto-start on boot")

    return parser


def main_cli(args: list[str] | None = None) -> int:
    """Main CLI execution router."""
    parser = build_parser()
    parsed = parser.parse_args(args)

    if not parsed.command or parsed.command == "watch":
        cfg = load_config()
        if parsed.command == "watch":
            if parsed.watch_folder:
                cfg.watch_folder = parsed.watch_folder
            if parsed.documents_root:
                cfg.documents_root = parsed.documents_root
            if parsed.dry_run:
                cfg.dry_run = True

        print(f"Starting ScanSort monitor on: {cfg.watch_folder}")
        print(f"Destination Documents root: {cfg.documents_root}")
        if cfg.dry_run:
            print("[DRY-RUN MODE ACTIVE: No files will be moved]")
        return 0

    if parsed.command == "config":
        cfg = load_config()

        if parsed.set_key:
            set_api_key(parsed.set_key)
            print("Successfully saved Gemini API key to secure OS credential vault.")

        if parsed.watch_folder:
            cfg.watch_folder = parsed.watch_folder
            save_config(cfg)
            print(f"Updated watch folder to: {cfg.watch_folder}")

        if parsed.documents_folder:
            cfg.documents_root = parsed.documents_folder
            save_config(cfg)
            print(f"Updated documents folder to: {cfg.documents_root}")

        if parsed.autostart:
            if parsed.autostart == "enable":
                enable_autorun()
                cfg.start_on_boot = True
                save_config(cfg)
                print("Auto-start on boot: ENABLED")
            else:
                disable_autorun()
                cfg.start_on_boot = False
                save_config(cfg)
                print("Auto-start on boot: DISABLED")

        if parsed.show or (not parsed.set_key and not parsed.watch_folder and not parsed.documents_folder and not parsed.autostart):
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
        restored = undo_last_move(cfg_path)
        if restored:
            print(f"Successfully reversed move. File restored to: {restored}")
        else:
            print("No reversible document filing action found in history.")
        return 0

    if parsed.command == "rescan":
        cfg = load_config()
        mapper = FolderMapper(docs_root=cfg.documents_root)
        taxonomy = mapper.refresh()
        print(f"Discovered {len(taxonomy)} destination folders in {cfg.documents_root}:")
        for f in taxonomy:
            print(f"  - {f}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main_cli())

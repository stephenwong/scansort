"""Configuration viewing and modification CLI subcommand handler."""

import argparse
import sys

from scansort import __version__
from scansort.core.config import (
    AppConfig,
    get_default_config_path,
    load_config,
    save_config,
)
from scansort.platform.autorun import (
    disable_autorun,
    enable_autorun,
    is_autorun_enabled,
)
from scansort.platform.secrets import (
    get_api_key,
    mask_api_key,
    redact_secrets_from_text,
    set_api_key,
)


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


def handle_config(parsed: argparse.Namespace) -> int:
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
        print(f"Version:           {__version__}")
        print(f"Config File:       {get_default_config_path()}")
        print(f"Watch Folder:      {cfg.watch_folder}")
        print(f"Documents Root:    {cfg.documents_root}")
        print(f"Fallback Folder:   {cfg.fallback_folder}")
        print(f"Gemini Model:      {cfg.gemini_model}")
        print(f"Start on Boot:     {autorun_status}")
        print(f"Dry Run Mode:      {cfg.dry_run}")
        auto_update = "Enabled" if cfg.auto_update else "Disabled"
        print(f"Auto Update:       {auto_update}")
        print(f"Update Check:      every {cfg.update_check_interval_days} day(s)")
        print(f"Gemini API Key:    {masked}")
        print("=========================================================")

    return 0

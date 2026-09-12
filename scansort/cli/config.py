"""Configuration viewing and modification CLI subcommand handler."""

import argparse
import sys
from pathlib import Path

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
from scansort.platform.context_menu import (
    disable_context_menu,
    enable_context_menu,
    is_context_menu_enabled,
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
    if getattr(parsed, "path", False):
        print(get_default_config_path())
        return 0

    cfg = _load_config_or_exit()
    if cfg is None:
        return 1

    if getattr(parsed, "get", None):
        field_query = parsed.get.strip().lower()
        if field_query in ("gemini_key", "api_key", "gemini_api_key"):
            api_key = get_api_key()
            print(mask_api_key(api_key))
            return 0
        if hasattr(cfg, field_query):
            print(getattr(cfg, field_query))
            return 0
        print(f"Unknown configuration field: {parsed.get}", file=sys.stderr)
        return 1

    if getattr(parsed, "set", None):
        field_name = parsed.set[0].strip().lower()
        raw_val = parsed.set[1].strip()
        if not hasattr(cfg, field_name):
            print(f"Unknown configuration field: {parsed.set[0]}", file=sys.stderr)
            return 1
        updated_dict = cfg.model_dump()
        current_val = getattr(cfg, field_name)
        if isinstance(current_val, bool):
            updated_dict[field_name] = raw_val.lower() in (
                "true",
                "1",
                "yes",
                "enable",
                "enabled",
            )
        elif isinstance(current_val, int):
            try:
                updated_dict[field_name] = int(raw_val)
            except ValueError:
                print(
                    f"Invalid integer value for {field_name}: {raw_val}",
                    file=sys.stderr,
                )
                return 1
        elif isinstance(current_val, Path):
            updated_dict[field_name] = Path(raw_val).resolve()
        else:
            updated_dict[field_name] = raw_val

        try:
            cfg = AppConfig(**updated_dict)
        except ValueError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            return 1
        if not _try_save_config(cfg):
            return 1
        print(f"Updated {field_name} to: {getattr(cfg, field_name)}")
        return 0

    has_mutation = False

    if getattr(parsed, "set_key", None):
        has_mutation = True
        try:
            set_api_key(parsed.set_key)
            print("Successfully saved Gemini API key to secure OS credential vault.")
        except (ValueError, OSError) as e:
            redacted = redact_secrets_from_text(str(e), parsed.set_key)
            print(f"Error saving Gemini API key: {redacted}", file=sys.stderr)
            return 1

    # Check for direct flag mutations
    direct_fields_changed = False
    updated_dict = cfg.model_dump()

    if getattr(parsed, "watch_folder", None) or getattr(
        parsed, "documents_folder", None
    ):
        has_mutation = True
        direct_fields_changed = True
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
        updated_dict["watch_folder"] = new_watch
        updated_dict["documents_root"] = new_docs

    if getattr(parsed, "gemini_model", None):
        has_mutation = True
        direct_fields_changed = True
        updated_dict["gemini_model"] = parsed.gemini_model

    if getattr(parsed, "fallback_folder", None):
        has_mutation = True
        direct_fields_changed = True
        updated_dict["fallback_folder"] = parsed.fallback_folder

    if getattr(parsed, "max_depth", None) is not None:
        has_mutation = True
        direct_fields_changed = True
        updated_dict["max_folder_depth"] = parsed.max_depth

    if getattr(parsed, "mirror_csv", None):
        has_mutation = True
        direct_fields_changed = True
        updated_dict["mirror_log_to_documents"] = parsed.mirror_csv == "enable"

    if getattr(parsed, "auto_update", None):
        has_mutation = True
        direct_fields_changed = True
        updated_dict["auto_update"] = parsed.auto_update == "enable"

    if getattr(parsed, "update_check_interval", None) is not None:
        has_mutation = True
        direct_fields_changed = True
        updated_dict["update_check_interval_days"] = parsed.update_check_interval

    if getattr(parsed, "dry_run", None):
        has_mutation = True
        direct_fields_changed = True
        updated_dict["dry_run"] = parsed.dry_run == "enable"

    if direct_fields_changed:
        try:
            cfg = AppConfig(**updated_dict)
        except ValueError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            return 1
        if not _try_save_config(cfg):
            return 1

        if getattr(parsed, "watch_folder", None):
            print(f"Updated watch folder to: {cfg.watch_folder}")
        if getattr(parsed, "documents_folder", None):
            print(f"Updated documents folder to: {cfg.documents_root}")
        if getattr(parsed, "gemini_model", None):
            print(f"Updated Gemini model to: {cfg.gemini_model}")
        if getattr(parsed, "fallback_folder", None):
            print(f"Updated fallback folder to: {cfg.fallback_folder}")
        if getattr(parsed, "max_depth", None) is not None:
            print(f"Updated max folder depth to: {cfg.max_folder_depth}")
        if getattr(parsed, "mirror_csv", None):
            print(f"Mirror history CSV to Documents: {cfg.mirror_log_to_documents}")
        if getattr(parsed, "auto_update", None):
            print(f"Auto-update: {cfg.auto_update}")
        if getattr(parsed, "update_check_interval", None) is not None:
            print(f"Update check interval: {cfg.update_check_interval_days} day(s)")
        if getattr(parsed, "dry_run", None):
            print(f"Dry run mode: {cfg.dry_run}")

    if getattr(parsed, "autostart", None):
        has_mutation = True
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

    if getattr(parsed, "context_menu", None):
        has_mutation = True
        enable = parsed.context_menu == "enable"
        action_fn = enable_context_menu if enable else disable_context_menu
        action_name = "enable" if enable else "disable"
        status_str = "ENABLED" if enable else "DISABLED"

        if not action_fn():
            print(
                f"Error: Failed to {action_name} Windows Explorer context menu.",
                file=sys.stderr,
            )
            return 1
        print(f"Windows Explorer context menu: {status_str}")

    show_config = getattr(parsed, "show", False) or not has_mutation
    if show_config:
        api_key = get_api_key()
        masked = mask_api_key(api_key)
        autorun_status = "Enabled" if is_autorun_enabled() else "Disabled"
        context_menu_status = "Enabled" if is_context_menu_enabled() else "Disabled"

        if getattr(parsed, "json", False):
            import json

            cfg_dict = {
                "version": __version__,
                "config_file": str(get_default_config_path()),
                "watch_folder": str(cfg.watch_folder),
                "documents_root": str(cfg.documents_root),
                "fallback_folder": cfg.fallback_folder,
                "gemini_model": cfg.gemini_model,
                "start_on_boot": is_autorun_enabled(),
                "context_menu": is_context_menu_enabled(),
                "dry_run": cfg.dry_run,
                "max_folder_depth": cfg.max_folder_depth,
                "mirror_log_to_documents": cfg.mirror_log_to_documents,
                "auto_update": cfg.auto_update,
                "update_check_interval_days": cfg.update_check_interval_days,
                "gemini_api_key": masked,
            }
            print(json.dumps(cfg_dict, indent=2))
            return 0

        print("================ ScanSort Configuration ================")
        print(f"Version:           {__version__}")
        print(f"Config File:       {get_default_config_path()}")
        print(f"Watch Folder:      {cfg.watch_folder}")
        print(f"Documents Root:    {cfg.documents_root}")
        print(f"Fallback Folder:   {cfg.fallback_folder}")
        print(f"Gemini Model:      {cfg.gemini_model}")
        print(f"Start on Boot:     {autorun_status}")
        print(f"Context Menu:      {context_menu_status}")
        print(f"Dry Run Mode:      {cfg.dry_run}")
        auto_update = "Enabled" if cfg.auto_update else "Disabled"
        print(f"Auto Update:       {auto_update}")
        print(f"Update Check:      every {cfg.update_check_interval_days} day(s)")
        print(f"Gemini API Key:    {masked}")
        print("=========================================================")

    return 0

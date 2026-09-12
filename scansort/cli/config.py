"""Configuration viewing and modification CLI subcommand handler."""

import argparse
import sys
from pathlib import Path
from typing import Any

from scansort import __version__
from scansort.cli.args import CliArgs
from scansort.core.config import (
    AppConfig,
    get_default_app_dir,
    get_default_config_path,
    load_config,
    save_config,
)
from scansort.core.constants import OPERATIONS_LOCK_FILENAME
from scansort.core.fs import interprocess_file_lock
from scansort.platform.autorun import (
    disable_autorun,
    enable_autorun,
    is_autorun_enabled,
)
from scansort.platform.context_menu import (
    disable_context_menu,
    disable_ocr_menu,
    enable_context_menu,
    enable_ocr_menu,
    is_context_menu_enabled,
    is_ocr_menu_enabled,
)
from scansort.platform.secrets import (
    get_api_key,
    mask_api_key,
    redact_secrets_from_text,
    set_api_key,
)

_TRUTHY_TOKENS = frozenset({"true", "1", "yes", "enable", "enabled"})
_FALSY_TOKENS = frozenset({"false", "0", "no", "disable", "disabled"})

# Flags that mutate persisted state; combining them with --set/--get is rejected
# rather than silently applying only one.
_MUTATION_FLAGS = (
    "set_key",
    "watch_folder",
    "documents_folder",
    "gemini_model",
    "fallback_folder",
    "max_depth",
    "mirror_csv",
    "auto_update",
    "update_check_interval",
    "dry_run",
    "autostart",
    "context_menu",
    "ocr",
    "ocr_menu",
)


def _has_other_mutations(args: CliArgs, exclude: str | None = None) -> bool:
    """Return True when a mutation flag other than ``exclude`` is present."""
    return any(
        attr != exclude and getattr(args, attr, None) is not None
        for attr in _MUTATION_FLAGS
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


def _with_overrides(cfg: AppConfig, **overrides: Any) -> AppConfig | None:
    """Return *cfg* with *overrides* applied and re-validated, or None on failure."""
    try:
        return AppConfig(**{**cfg.model_dump(), **overrides})
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return None


def _handle_get(args: CliArgs, cfg: AppConfig) -> int | None:
    """Handle the ``--get`` query; returns None when it was not requested."""
    if not args.get:
        return None
    if _has_other_mutations(args) or args.set is not None:
        print(
            "Error: --get cannot be combined with mutation flags.",
            file=sys.stderr,
        )
        return 1
    field_query = args.get.strip().lower()
    if field_query in ("gemini_key", "api_key", "gemini_api_key"):
        api_key = get_api_key()
        print(mask_api_key(api_key))
        return 0
    if field_query in AppConfig.model_fields:
        print(getattr(cfg, field_query))
        return 0
    print(f"Unknown configuration field: {args.get}", file=sys.stderr)
    return 1


def _handle_set(args: CliArgs, cfg: AppConfig) -> int | None:
    """Handle the ``--set FIELD VALUE`` mutation; returns None when not requested."""
    if not args.set:
        return None
    field_name = args.set[0].strip().lower()
    raw_val = args.set[1].strip()
    if field_name not in AppConfig.model_fields:
        print(f"Unknown configuration field: {args.set[0]}", file=sys.stderr)
        return 1
    if _has_other_mutations(args):
        print(
            "Error: --set cannot be combined with other mutation flags.",
            file=sys.stderr,
        )
        return 1
    updated_dict = cfg.model_dump()
    current_val = getattr(cfg, field_name)
    if isinstance(current_val, bool):
        token = raw_val.lower()
        if token in _TRUTHY_TOKENS:
            updated_dict[field_name] = True
        elif token in _FALSY_TOKENS:
            updated_dict[field_name] = False
        else:
            print(
                f"Invalid boolean value for {field_name}: {raw_val}",
                file=sys.stderr,
            )
            return 1
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

    new_cfg = _with_overrides(cfg, **updated_dict)
    if new_cfg is None:
        return 1
    cfg = new_cfg
    if not _try_save_config(cfg):
        return 1
    print(f"Updated {field_name} to: {getattr(cfg, field_name)}")
    return 0


def _apply_mutations(
    args: CliArgs, cfg: AppConfig
) -> tuple[AppConfig, bool, int | None]:
    """Apply set-key, direct-field, and platform-toggle mutations.

    Returns ``(cfg, has_mutation, exit_code)``; a non-None ``exit_code`` means
    the caller must return it immediately.
    """
    has_mutation = False

    # Defer the irreversible vault write until every other mutation input has
    # been validated: a failed sibling flag must never leave a key persisted
    # while the command reports failure (F18).
    pending_set_key = args.set_key
    if pending_set_key is not None:
        has_mutation = True

    # Check for direct flag mutations
    direct_fields_changed = False
    updated_dict = cfg.model_dump()

    if args.watch_folder or args.documents_folder:
        has_mutation = True
        direct_fields_changed = True
        new_watch = (
            args.watch_folder.resolve() if args.watch_folder else cfg.watch_folder
        )
        new_docs = (
            args.documents_folder.resolve()
            if args.documents_folder
            else cfg.documents_root
        )

        if args.watch_folder and args.watch_folder.resolve().is_file():
            print(
                f"Error: Watch folder cannot be a regular file: {args.watch_folder.resolve()}",
                file=sys.stderr,
            )
            return cfg, has_mutation, 1
        if args.documents_folder and args.documents_folder.resolve().is_file():
            print(
                f"Error: Documents folder cannot be a regular file: {args.documents_folder.resolve()}",
                file=sys.stderr,
            )
            return cfg, has_mutation, 1
        if new_watch.resolve() == new_docs.resolve():
            print(
                "Error: Watch folder and documents root cannot be the same directory.",
                file=sys.stderr,
            )
            return cfg, has_mutation, 1
        updated_dict["watch_folder"] = new_watch
        updated_dict["documents_root"] = new_docs

    if args.gemini_model:
        has_mutation = True
        direct_fields_changed = True
        updated_dict["gemini_model"] = args.gemini_model

    if args.fallback_folder:
        has_mutation = True
        direct_fields_changed = True
        updated_dict["fallback_folder"] = args.fallback_folder

    if args.max_depth is not None:
        has_mutation = True
        direct_fields_changed = True
        updated_dict["max_folder_depth"] = args.max_depth

    if args.mirror_csv:
        has_mutation = True
        direct_fields_changed = True
        updated_dict["mirror_log_to_documents"] = args.mirror_csv == "enable"

    if args.auto_update:
        has_mutation = True
        direct_fields_changed = True
        updated_dict["auto_update"] = args.auto_update == "enable"

    if args.update_check_interval is not None:
        has_mutation = True
        direct_fields_changed = True
        updated_dict["update_check_interval_days"] = args.update_check_interval

    if args.dry_run:
        has_mutation = True
        direct_fields_changed = True
        updated_dict["dry_run"] = args.dry_run == "enable"

    if args.ocr:
        has_mutation = True
        direct_fields_changed = True
        updated_dict["ocr_enabled"] = args.ocr == "enable"

    if direct_fields_changed:
        new_cfg = _with_overrides(cfg, **updated_dict)
        if new_cfg is None:
            return cfg, has_mutation, 1
        cfg = new_cfg
        if not _try_save_config(cfg):
            return cfg, has_mutation, 1

        if args.watch_folder:
            print(f"Updated watch folder to: {cfg.watch_folder}")
        if args.documents_folder:
            print(f"Updated documents folder to: {cfg.documents_root}")
        if args.gemini_model:
            print(f"Updated Gemini model to: {cfg.gemini_model}")
        if args.fallback_folder:
            print(f"Updated fallback folder to: {cfg.fallback_folder}")
        if args.max_depth is not None:
            print(f"Updated max folder depth to: {cfg.max_folder_depth}")
        if args.mirror_csv:
            print(f"Mirror history CSV to Documents: {cfg.mirror_log_to_documents}")
        if args.auto_update:
            print(f"Auto-update: {cfg.auto_update}")
        if args.update_check_interval is not None:
            print(f"Update check interval: {cfg.update_check_interval_days} day(s)")
        if args.dry_run:
            print(f"Dry run mode: {cfg.dry_run}")
        if args.ocr:
            print(f"OCR text layer: {cfg.ocr_enabled}")

    if args.autostart:
        has_mutation = True
        enable = args.autostart == "enable"
        action_fn = enable_autorun if enable else disable_autorun
        action_name = "enable" if enable else "disable"
        status_str = "ENABLED" if enable else "DISABLED"

        if not action_fn():
            print(
                f"Error: Failed to {action_name} auto-start on boot.", file=sys.stderr
            )
            return cfg, has_mutation, 1
        cfg.start_on_boot = enable
        if not _try_save_config(cfg):
            return cfg, has_mutation, 1
        print(f"Auto-start on boot: {status_str}")

    if args.context_menu:
        has_mutation = True
        enable = args.context_menu == "enable"
        action_fn = enable_context_menu if enable else disable_context_menu
        action_name = "enable" if enable else "disable"
        status_str = "ENABLED" if enable else "DISABLED"

        if not action_fn():
            print(
                f"Error: Failed to {action_name} Windows Explorer context menu.",
                file=sys.stderr,
            )
            return cfg, has_mutation, 1
        print(f"Windows Explorer context menu: {status_str}")

    if args.ocr_menu:
        has_mutation = True
        enable = args.ocr_menu == "enable"
        ocr_action_fn = enable_ocr_menu if enable else disable_ocr_menu
        ocr_action_name = "enable" if enable else "disable"
        ocr_status_str = "ENABLED" if enable else "DISABLED"

        if not ocr_action_fn():
            print(
                f"Error: Failed to {ocr_action_name} 'Make searchable' context menu.",
                file=sys.stderr,
            )
            return cfg, has_mutation, 1
        print(f"'Make searchable' context menu: {ocr_status_str}")

    # All sibling mutations validated and applied; now persist the API key.
    if pending_set_key is not None:
        try:
            set_api_key(pending_set_key)
            print("Successfully saved Gemini API key to secure OS credential vault.")
        except (ValueError, OSError) as e:
            redacted = redact_secrets_from_text(str(e), pending_set_key)
            print(f"Error saving Gemini API key: {redacted}", file=sys.stderr)
            return cfg, has_mutation, 1

    return cfg, has_mutation, None


def _config_display_payload(cfg: AppConfig) -> dict[str, object]:
    """Return the canonical configuration display mapping (JSON and text panels)."""
    return {
        "version": __version__,
        "config_file": str(get_default_config_path()),
        "watch_folder": str(cfg.watch_folder),
        "documents_root": str(cfg.documents_root),
        "fallback_folder": cfg.fallback_folder,
        "gemini_model": cfg.gemini_model,
        "start_on_boot": is_autorun_enabled(),
        "context_menu": is_context_menu_enabled(),
        "ocr_menu": is_ocr_menu_enabled(),
        "dry_run": cfg.dry_run,
        "max_folder_depth": cfg.max_folder_depth,
        "mirror_log_to_documents": cfg.mirror_log_to_documents,
        "auto_update": cfg.auto_update,
        "update_check_interval_days": cfg.update_check_interval_days,
        "ocr_enabled": cfg.ocr_enabled,
        "ocr_language": cfg.ocr_language,
        "gemini_api_key": mask_api_key(get_api_key()),
    }


def _show_config(args: CliArgs, cfg: AppConfig) -> None:
    """Render the full configuration as JSON or a human-readable panel."""
    payload = _config_display_payload(cfg)

    if args.json:
        import json

        print(json.dumps(payload, indent=2))
        return

    autorun_status = "Enabled" if payload["start_on_boot"] else "Disabled"
    context_menu_status = "Enabled" if payload["context_menu"] else "Disabled"
    ocr_menu_status = "Enabled" if payload["ocr_menu"] else "Disabled"
    auto_update = "Enabled" if payload["auto_update"] else "Disabled"

    print("================ ScanSort Configuration ================")
    print(f"Version:           {payload['version']}")
    print(f"Config File:       {payload['config_file']}")
    print(f"Watch Folder:      {payload['watch_folder']}")
    print(f"Documents Root:    {payload['documents_root']}")
    print(f"Fallback Folder:   {payload['fallback_folder']}")
    print(f"Gemini Model:      {payload['gemini_model']}")
    print(f"Start on Boot:     {autorun_status}")
    print(f"Context Menu:      {context_menu_status}")
    print(f"OCR Menu:          {ocr_menu_status}")
    print(f"OCR Text Layer:    {'Enabled' if payload['ocr_enabled'] else 'Disabled'}")
    print(f"OCR Language:      {payload['ocr_language']}")
    print(f"Dry Run Mode:      {payload['dry_run']}")
    print(f"Auto Update:       {auto_update}")
    print(f"Update Check:      every {payload['update_check_interval_days']} day(s)")
    print(f"Gemini API Key:    {payload['gemini_api_key']}")
    print("=========================================================")


def handle_config(parsed: argparse.Namespace) -> int:
    """Handle 'config' command to view or modify settings."""
    args = CliArgs.from_namespace(parsed)
    if args.path:
        print(get_default_config_path())
        return 0

    cfg = _load_config_or_exit()
    if cfg is None:
        return 1

    get_code = _handle_get(args, cfg)
    if get_code is not None:
        return get_code

    # Serialize the whole load-modify-save span so concurrent writers (CLI and
    # the tray Settings dialog) cannot silently drop each other's changes (F19).
    op_lock = get_default_app_dir() / OPERATIONS_LOCK_FILENAME
    with interprocess_file_lock(op_lock):
        cfg = _load_config_or_exit()
        if cfg is None:
            return 1

        set_code = _handle_set(args, cfg)
        if set_code is not None:
            return set_code

        cfg, has_mutation, mutation_code = _apply_mutations(args, cfg)
        if mutation_code is not None:
            return mutation_code

        if args.show or not has_mutation:
            _show_config(args, cfg)

    return 0

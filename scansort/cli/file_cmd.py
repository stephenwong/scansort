"""Direct document filing CLI subcommand handler."""

import argparse
import logging
import sys
from pathlib import Path

from scansort.cli.config import _load_config_or_exit
from scansort.core.config import AppConfig
from scansort.core.constants import SUPPORTED_EXTENSIONS
from scansort.pipeline.coordinator import ScanSortPipeline
from scansort.platform.secrets import get_api_key

logger = logging.getLogger(__name__)


def handle_file(parsed: argparse.Namespace) -> int:
    """Handle 'file' command to process and file specified document(s) directly."""
    cfg = _load_config_or_exit()
    if cfg is None:
        return 1

    api_key = get_api_key()
    if not api_key or not api_key.strip():
        print(
            "Error: Gemini API key not configured. Run 'scansort config --set-key <API_KEY>' first.",
            file=sys.stderr,
        )
        return 1

    dry_run = getattr(parsed, "dry_run", False) or cfg.dry_run
    if dry_run != cfg.dry_run:
        updated_dict = cfg.model_dump()
        updated_dict["dry_run"] = dry_run
        cfg = AppConfig(**updated_dict)

    copy_source = getattr(parsed, "copy", False)
    files: list[Path] = getattr(parsed, "files", [])
    if not files:
        print("Error: No files specified to file.", file=sys.stderr)
        return 1

    try:
        pipeline = ScanSortPipeline(config=cfg)
    except OSError as e:
        print(f"Error preparing application directories: {e}", file=sys.stderr)
        return 1
    any_failure = False

    for target_path in files:
        resolved = target_path.resolve()
        if resolved.is_dir():
            print(
                f"Error: Expected a file but got a directory: {target_path.name}",
                file=sys.stderr,
            )
            any_failure = True
            continue
        if not resolved.is_file():
            print(f"Error: File not found: {target_path.name}", file=sys.stderr)
            any_failure = True
            continue

        if resolved.suffix.lower() not in SUPPORTED_EXTENSIONS:
            allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            print(
                f"Error: Unsupported file type: {resolved.suffix} for '{target_path.name}' (supported: {allowed})",
                file=sys.stderr,
            )
            any_failure = True
            continue

        prefix = "[DRY RUN] Would file" if dry_run else "Filing"
        print(f"{prefix}: {target_path.name}...")
        dest = pipeline.process_file(resolved, preserve_source=copy_source)
        if dest is not None:
            if dry_run:
                print(f"[DRY RUN] Simulated destination for {target_path.name}: {dest}")
            else:
                action_desc = (
                    "Preserved original; filed copy" if copy_source else "Filed"
                )
                print(f"{action_desc}: {target_path.name} -> {dest}")
        else:
            print(f"Error: Failed to file: {target_path.name}", file=sys.stderr)
            any_failure = True

    return 1 if any_failure else 0

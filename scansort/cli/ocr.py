"""OCR backfill CLI subcommand handler."""

import argparse
import logging
import sys
from pathlib import Path

from scansort.cli.args import CliArgs
from scansort.cli.config import _load_config_or_exit
from scansort.core.config import get_default_app_dir, normalize_ocr_language
from scansort.document.ocr import has_ocr_support
from scansort.pipeline.ocr_backfill import run_ocr_backfill

logger = logging.getLogger(__name__)


def _validate_targets(targets: list[Path]) -> str | None:
    """Return an error message when any explicit target is missing or not a PDF."""
    for target in targets:
        resolved = target.resolve()
        if not resolved.exists():
            return f"Error: path not found: {target}"
        if resolved.is_file() and resolved.suffix.lower() != ".pdf":
            return f"Error: not a PDF file: {target}"
    return None


def handle_ocr_backfill(parsed: argparse.Namespace) -> int:
    """Handle 'ocr-backfill' to retrofit searchable text layers into filed PDFs."""
    args = CliArgs.from_namespace(parsed)
    cfg = _load_config_or_exit()
    if cfg is None:
        return 1

    dry_run = bool(args.dry_run) or cfg.dry_run
    if not dry_run and not has_ocr_support():
        print(
            "Error: OCR requires the tesseract binary, which was not found. "
            "Use the official ScanSort build or install tesseract.",
            file=sys.stderr,
        )
        return 1

    targets = [Path(target) for target in args.targets]
    error = _validate_targets(targets)
    if error is not None:
        print(error, file=sys.stderr)
        return 1

    language = args.language
    if language:
        try:
            language = normalize_ocr_language(language)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    try:
        result = run_ocr_backfill(
            cfg,
            get_default_app_dir(),
            targets=targets,
            dry_run=dry_run,
            limit=args.limit,
            language=language,
            progress=print,
        )
    except (OSError, ValueError) as exc:
        print(f"Error: OCR backfill failed: {exc}", file=sys.stderr)
        return 1

    if dry_run:
        print(
            f"Dry run: {len(result.candidates)} PDF(s) need OCR, "
            f"{len(result.failed)} failed, {result.skipped} already searchable."
        )
    else:
        print(
            f"Backfill complete: {len(result.processed)} made searchable, "
            f"{len(result.failed)} failed, {result.skipped} already searchable."
        )
    return 1 if result.failed else 0

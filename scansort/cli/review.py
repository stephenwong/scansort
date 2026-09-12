"""Review and self-learning CLI subcommand handler."""

import argparse
import os
import sys

from scansort.cli.args import CliArgs
from scansort.cli.config import _load_config_or_exit
from scansort.core.config import AppConfig, get_default_app_dir
from scansort.core.constants import (
    HINTS_FILENAME,
    HISTORY_CSV_NAME,
    HISTORY_JSONL_NAME,
)
from scansort.core.fs import open_in_file_manager
from scansort.pipeline.dispatcher import OPERATIONS_LOCK_FILENAME
from scansort.pipeline.review import (
    ReviewItem,
    dismiss_review_item,
    file_reviewed_item,
    get_review_queue,
)


def _has_gui_display() -> bool:
    """Check if a graphical display environment is available."""
    if sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _print_review_item(item: ReviewItem, idx: int, total: int) -> None:
    """Print the diagnostic card for a single review item."""
    print("=" * 64)
    print(f"[{idx}/{total}] {item.filename} ({item.file_size_bytes / 1024:.1f} KB)")
    if item.summary:
        print(f"Summary: {item.summary}")
    if item.confidence:
        print(f"Type: {item.document_type} | Confidence: {int(item.confidence * 100)}%")
    if item.suggested_folder:
        print(f"AI Suggestion: {item.suggested_folder}")
    if item.folder_reasoning:
        print(f"Reasoning: {item.folder_reasoning}")
    print("=" * 64)


def _input_or_cancel(prompt: str) -> str | None:
    """Read a line of input, returning None when the user cancels (EOF/interrupt)."""
    try:
        return input(prompt)
    except EOFError, KeyboardInterrupt:
        return None


def _confirm_duplicate(record: dict) -> bool:
    """Prompt whether to file content identical to a previous filing."""
    previous = record.get("new_filename") or "a previously filed document"
    answer = _input_or_cancel(
        f"Duplicate of '{previous}' detected. File anyway? [y/N]: "
    )
    return bool(answer) and answer.strip().lower() in {"y", "yes"}


def _run_cli_review(
    items: list[ReviewItem],
    config: AppConfig,
    limit: int | None = None,
) -> int:
    queue = items[:limit] if limit is not None and limit > 0 else items
    total = len(queue)
    app_dir = get_default_app_dir()
    hints_path = app_dir / HINTS_FILENAME
    history_jsonl = app_dir / HISTORY_JSONL_NAME
    history_csv = app_dir / HISTORY_CSV_NAME
    lock_path = app_dir / OPERATIONS_LOCK_FILENAME

    print(
        f"\nStarting interactive review session ({total} document{'s' if total != 1 else ''} to review)...\n"
    )

    for idx, item in enumerate(queue, start=1):
        _print_review_item(item, idx, total)

        while True:
            print("Actions:")
            if item.suggested_folder:
                print(f"  [1] Accept AI suggestion ('{item.suggested_folder}')")
            else:
                print("  [1] Enter destination folder")
            print("  [2] Enter destination folder")
            print("  [3] Open document in default viewer")
            print("  [4] Skip for now")
            print("  [5] Dismiss (delete file)")
            print("  [q] Quit review")

            default_choice = "1" if item.suggested_folder else "2"
            raw_choice = _input_or_cancel(f"Choice [{default_choice}]: ")
            if raw_choice is None:
                print("\nReview session cancelled.")
                return 0
            choice = raw_choice.strip() or default_choice

            if choice.lower() == "q":
                print("\nReview session ended.")
                return 0

            if choice == "3":
                if open_in_file_manager(item.file_path):
                    print(f"Opened {item.filename} in default viewer.\n")
                else:
                    print(
                        f"Could not open {item.filename} in a viewer.", file=sys.stderr
                    )
                continue

            if choice == "4":
                print(f"Skipped {item.filename}.\n")
                break

            if choice == "5":
                raw_confirm = _input_or_cancel(f"Delete {item.filename}? [y/N]: ")
                if raw_confirm is None:
                    return 0
                if raw_confirm.strip().lower() == "y":
                    try:
                        dismiss_review_item(
                            item,
                            history_jsonl=history_jsonl,
                            history_csv=history_csv,
                            lock_path=lock_path,
                            mirror_csv_path=config.mirror_csv_path,
                            docs_root=config.documents_root,
                        )
                        print(f"Dismissed {item.filename}.\n")
                    except (OSError, ValueError) as e:
                        print(f"Error dismissing document: {e}\n", file=sys.stderr)
                else:
                    print("Dismiss cancelled.\n")
                break

            target_folder = ""
            if choice == "1":
                if item.suggested_folder:
                    target_folder = item.suggested_folder
                else:
                    raw_target = _input_or_cancel(
                        "Target folder (e.g. Utilities/Electricity): "
                    )
                    if raw_target is None:
                        return 0
                    target_folder = raw_target.strip()
            elif choice == "2":
                raw_target = _input_or_cancel(
                    "Target folder (e.g. Utilities/Electricity): "
                )
                if raw_target is None:
                    return 0
                target_folder = raw_target.strip()
            else:
                print(
                    f"Error: Invalid choice '{choice}'. Please select a valid option.\n"
                )
                continue

            if not target_folder:
                print("Error: Target folder cannot be empty.\n")
                continue

            raw_date = _input_or_cancel(f"Document date [{item.document_date}]: ")
            if raw_date is None:
                print("\nReview session cancelled.")
                return 0
            in_date = raw_date.strip() or item.document_date

            raw_desc = _input_or_cancel(f"Description [{item.description}]: ")
            if raw_desc is None:
                print("\nReview session cancelled.")
                return 0
            in_desc = raw_desc.strip() or item.description

            suggested_kw = item.description.replace("_", " ").lower()
            hint_prompt = f"Add keyword hint for '{target_folder}'? [{suggested_kw}] (Enter to accept, type custom, or 'n' to skip): "
            raw_hint = _input_or_cancel(hint_prompt)
            if raw_hint is None:
                print("\nReview session cancelled.")
                return 0
            in_hint = raw_hint.strip()
            hint_to_save: str | None = None
            if in_hint.lower() != "n":
                hint_to_save = in_hint or suggested_kw

            try:
                dest = file_reviewed_item(
                    item=item,
                    target_folder=target_folder,
                    document_date=in_date,
                    description=in_desc,
                    config=config,
                    keyword_hint=hint_to_save,
                    hints_path=hints_path,
                    history_jsonl=history_jsonl,
                    history_csv=history_csv,
                    lock_path=lock_path,
                    on_duplicate=_confirm_duplicate,
                )
                print(f"Successfully filed to {dest.name} in '{target_folder}'.\n")
                break
            except (OSError, ValueError) as e:
                print(f"Error filing document: {e}\n")
                continue

    print("Review session complete.")
    return 0


def handle_review(parsed: argparse.Namespace) -> int:
    """Handle review subcommand execution."""
    args = CliArgs.from_namespace(parsed)
    config = _load_config_or_exit()
    if config is None:
        return 1
    items = get_review_queue(config.documents_root, config.fallback_folder)
    if not items:
        print(f"No documents currently require review in '{config.fallback_folder}'.")
        return 0

    use_gui = args.gui
    use_cli = args.cli

    if use_gui or (not use_cli and _has_gui_display()):
        import tkinter as tk

        from scansort.ui.review import open_review_dialog

        limit = args.limit
        if limit:
            print(
                "Note: --limit applies to the CLI review session only; "
                "the GUI shows the full queue.",
                file=sys.stderr,
            )
        try:
            dialog = open_review_dialog(config)
            dialog.mainloop()
            return 0
        except tk.TclError as e:
            # A stale/unreachable display must degrade to the terminal session
            # rather than crashing with an unhandled traceback (F25).
            print(
                f"GUI unavailable ({e}); falling back to terminal review.",
                file=sys.stderr,
            )

    return _run_cli_review(items, config, limit=args.limit)

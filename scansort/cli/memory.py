"""Filing-memory inspection and control CLI subcommand handler."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scansort.cli.args import CliArgs
from scansort.core.config import get_default_app_dir, load_config
from scansort.core.constants import HISTORY_JSONL_NAME


def _resolve_paths() -> tuple[Path, Path, Path, Path]:
    """Return ``(app_dir, db_path, history_path, lock_path)`` for memory ops."""
    from scansort.classification.memory import (
        memory_db_path_for,
        memory_lock_path_for,
    )

    app_dir = get_default_app_dir()
    return (
        app_dir,
        memory_db_path_for(app_dir),
        app_dir / HISTORY_JSONL_NAME,
        memory_lock_path_for(app_dir),
    )


def _memory_status() -> str:
    """Return Enabled/Disabled/Unknown best-effort; never raises."""
    try:
        return "Enabled" if load_config().rag_memory_enabled else "Disabled"
    except ValueError:
        return "Unknown"
    except Exception:  # noqa: BLE001 - memory CLI never crashes on config
        return "Unknown"


def _summary_best_effort() -> dict[str, Any]:
    """Return :func:`memory_summary` output, zeroed on failure; never raises."""
    from scansort.classification.memory import memory_db_path_for, memory_summary

    app_dir = get_default_app_dir()
    try:
        return memory_summary(memory_db_path_for(app_dir), app_dir / HISTORY_JSONL_NAME)
    except Exception:  # noqa: BLE001 - best-effort
        return {
            "examples": 0,
            "calibrated_folders": {},
            "last_learned": None,
            "db_path": str(memory_db_path_for(app_dir)),
        }


def _confirm(prompt: str) -> bool:
    """Prompt for y/N confirmation; False on EOF/interrupt or non-affirmative."""
    try:
        answer = input(prompt)
    except EOFError, KeyboardInterrupt:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _print_summary(summary: dict[str, Any], status: str) -> None:
    examples = int(summary.get("examples", 0) or 0)
    calibrated = summary.get("calibrated_folders", {}) or {}
    parts = [f"{name} {float(value):.2f}" for name, value in sorted(calibrated.items())]
    calibrated_str = f"{len(parts)} ({', '.join(parts)})" if parts else "0"
    last = summary.get("last_learned") or "—"
    if isinstance(last, str) and "T" in last:
        last = last.replace("T", " ")[:16]
    print("Filing Memory:")
    print(f"  Status:           {status}")
    print(f"  Examples Learned: {examples}")
    print(f"  Calibrated Folders: {calibrated_str}")
    print(f"  Last Learned:     {last}")
    print(f"  Store: {summary.get('db_path', '')}")


def handle_memory(parsed: argparse.Namespace) -> int:
    """Handle 'memory' command to inspect and control filing memory."""
    args = CliArgs.from_namespace(parsed)
    ops = [
        bool(args.memory_list),
        args.memory_forget_folder is not None,
        bool(args.memory_clear),
        bool(args.memory_rebuild),
    ]
    if sum(ops) > 1:
        print(
            "Error: --list, --forget-folder, --clear, and --rebuild are mutually exclusive.",
            file=sys.stderr,
        )
        return 1

    _app_dir, db_path, history_path, lock_path = _resolve_paths()
    status = _memory_status()

    if args.memory_forget_folder is not None:
        from scansort.classification.memory import MemoryStore

        try:
            removed = MemoryStore(db_path).forget_folder(args.memory_forget_folder)
        except Exception as e:  # noqa: BLE001 - best-effort
            print(f"Error forgetting folder: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    {"folder": args.memory_forget_folder, "forgot": removed}, indent=2
                )
            )
            return 0
        print(f"Forgot {removed} examples for '{args.memory_forget_folder}'.")
        return 0

    if args.memory_clear:
        if not _confirm(
            "Clear all learned examples? ScanSort will re-learn from filing "
            "history on the next scan unless memory is turned off. [y/N]: "
        ):
            print("Clear cancelled.")
            return 0
        from scansort.classification.memory import MemoryStore

        try:
            cleared = MemoryStore(db_path).clear()
        except Exception as e:  # noqa: BLE001 - best-effort
            print(f"Error clearing memory: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"cleared": bool(cleared)}, indent=2))
            return 0
        print("Cleared filing memory." if cleared else "Nothing to clear.")
        return 0

    if args.memory_rebuild:
        from scansort.classification.memory import rebuild_memory

        try:
            count = rebuild_memory(db_path, history_path, lock_path)
        except Exception as e:  # noqa: BLE001 - best-effort
            print(f"Error rebuilding memory: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"rebuilt": count}, indent=2))
            return 0
        print(f"Rebuilt filing memory: {count} examples from history.")
        return 0

    if args.memory_list:
        from scansort.classification.memory import MemoryStore

        try:
            limit = args.limit if args.limit is not None else 20
            rows = MemoryStore(db_path).list_examples(limit=limit)
        except Exception as e:  # noqa: BLE001 - best-effort
            print(f"Error listing memory: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            print("No learned examples.")
            return 0
        print(f"{'Folder':<30} {'Summary':<40} {'Learned':<16} {'Status':<12}")
        print("-" * 100)
        for row in rows:
            folder = str(row.get("folder", ""))[:28]
            summary = str(row.get("summary", ""))[:38]
            learned = str(row.get("timestamp", ""))[:16].replace("T", " ")
            state = str(row.get("status", ""))
            print(f"{folder:<30} {summary:<40} {learned:<16} {state:<12}")
        return 0

    summary = _summary_best_effort()
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    _print_summary(summary, status)
    return 0

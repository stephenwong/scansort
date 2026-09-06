"""Watch CLI subcommand handler and background monitoring runner."""

import argparse
import logging
import queue
import sys
import threading

from scansort.cli.config import _load_config_or_exit
from scansort.cli.update import (
    announce_applied_update,
    maybe_apply_auto_update,
)
from scansort.core.config import AppConfig, get_default_app_dir
from scansort.core.constants import INSTANCE_LOCK_FILENAME
from scansort.pipeline.coordinator import ScanSortPipeline
from scansort.pipeline.watcher import DropFolderWatcher
from scansort.platform.instance_guard import instance_guard

logger = logging.getLogger(__name__)

_announce_applied_update = announce_applied_update
_maybe_apply_auto_update = maybe_apply_auto_update


def _run_monitor(cfg: AppConfig) -> int:
    """Run the drop folder watcher and its pipeline worker until stopped."""
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


def handle_watch(parsed: argparse.Namespace) -> int:
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

    app_dir = get_default_app_dir()
    try:
        with instance_guard(app_dir / INSTANCE_LOCK_FILENAME) as acquired:
            if not acquired:
                print("Another ScanSort instance is already running.", file=sys.stderr)
                return 0
            announce_applied_update(app_dir)
            if maybe_apply_auto_update(cfg, app_dir):
                return 0
            return _run_monitor(cfg)
    except OSError as e:
        print(f"Error acquiring instance lock: {e}", file=sys.stderr)
        return 1

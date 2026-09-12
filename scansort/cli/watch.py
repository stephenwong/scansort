"""Watch CLI subcommand handler and background monitoring runner."""

import argparse
import logging
import queue
import sys
import threading

from scansort.cli.args import CliArgs
from scansort.cli.config import _load_config_or_exit, _with_overrides
from scansort.cli.update import (
    announce_applied_update,
    maybe_apply_auto_update,
)
from scansort.core.config import AppConfig, get_default_app_dir
from scansort.core.constants import INSTANCE_LOCK_FILENAME
from scansort.pipeline.coordinator import ScanSortPipeline
from scansort.pipeline.watcher import DropFolderWatcher
from scansort.platform.instance_guard import instance_guard
from scansort.ui import SystemTrayApp

logger = logging.getLogger(__name__)


def _run_monitor(cfg: AppConfig, start_tray: bool = True) -> int:
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

    tray_app: SystemTrayApp | None = None
    if start_tray:
        try:
            tray_app = SystemTrayApp(
                config=cfg,
                watcher=watcher,
                pipeline=pipeline,
                stop_event=stop_event,
            )
            tray_app.start()
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not initialize system tray: %s", e)

    try:
        watcher.start()
    except KeyboardInterrupt:
        pass
    finally:
        if tray_app is not None:
            try:
                tray_app.stop()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Error stopping system tray; continuing shutdown.", exc_info=True
                )
        watcher.stop()
        stop_event.set()
        worker_thread.join(timeout=20.0)
        if worker_thread.is_alive():
            logger.warning("Worker thread did not terminate within 20 seconds.")

    return 0


def handle_watch(parsed: argparse.Namespace) -> int:
    """Handle 'watch' command to start monitoring the drop folder."""
    args = CliArgs.from_namespace(parsed)
    cfg = _load_config_or_exit()
    if cfg is None:
        return 1
    new_watch = args.watch_folder.resolve() if args.watch_folder else cfg.watch_folder
    new_docs = (
        args.documents_root.resolve() if args.documents_root else cfg.documents_root
    )
    dry_run = args.dry_run or cfg.dry_run

    new_cfg = _with_overrides(
        cfg, watch_folder=new_watch, documents_root=new_docs, dry_run=dry_run
    )
    if new_cfg is None:
        return 1
    cfg = new_cfg

    try:
        cfg.ensure_directories()
    except OSError as e:
        print(f"Error preparing directories: {e}", file=sys.stderr)
        return 1

    if not args.minimized:
        print(f"Starting ScanSort monitor on: {cfg.watch_folder}")
        print(f"Destination Documents root: {cfg.documents_root}")
        if cfg.dry_run:
            print("[DRY-RUN MODE ACTIVE: No files will be moved]")

    app_dir = get_default_app_dir()
    try:
        guard = instance_guard(app_dir / INSTANCE_LOCK_FILENAME)
        acquired = guard.__enter__()
    except OSError as e:
        print(f"Error acquiring instance lock: {e}", file=sys.stderr)
        return 1
    try:
        if not acquired:
            print("Another ScanSort instance is already running.", file=sys.stderr)
            return 0
        announce_applied_update(app_dir)
        if maybe_apply_auto_update(cfg, app_dir):
            return 0
        try:
            return _run_monitor(cfg)
        except OSError as e:
            print(f"Error during monitoring: {e}", file=sys.stderr)
            return 1
    finally:
        guard.__exit__(None, None, None)

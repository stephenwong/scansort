"""Filesystem drop folder monitor utilizing Rust-powered watchfiles with native debouncing."""

import logging
import queue
import threading
from pathlib import Path

from watchfiles import Change, watch

from scansort.constants import IGNORED_PREFIXES, TEMPORARY_EXTENSIONS
from scansort.image_converter import is_supported_format

logger = logging.getLogger(__name__)


def should_process_path(path: Path) -> bool:
    """Determine whether a detected filesystem entry should be processed.

    Filters out directories, dotfiles, temporary/swap files, and unsupported formats.

    Args:
        path: Path to the candidate file.

    Returns:
        True if the file is a candidate for scan processing, False otherwise.
    """
    if path.is_dir():
        return False

    name = path.name
    lower_name = name.lower()
    if name.startswith(IGNORED_PREFIXES) or lower_name.endswith(TEMPORARY_EXTENSIONS):
        return False

    return is_supported_format(path)


class DropFolderWatcher:
    """Monitors scanner drop directory and pushes stabilized incoming files to a worker queue."""

    def __init__(
        self,
        watch_folder: Path,
        file_queue: queue.Queue,
        debounce_ms: int = 1500,
    ) -> None:
        self.watch_folder = watch_folder
        self.file_queue = file_queue
        self.debounce_ms = debounce_ms

        self._stop_event = threading.Event()
        self._restart_event = threading.Event()
        self._cycle_stop_event: threading.Event | None = None
        self._running = False
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        """Check if watcher is currently active."""
        return self._running

    def _interrupt_cycle(self) -> None:
        """Interrupt the current watchfiles cycle."""
        self._restart_event.set()
        if self._cycle_stop_event is not None:
            self._cycle_stop_event.set()

    def switch_folder(self, new_folder: Path) -> None:
        """Dynamically update the monitored directory and restart the watcher loop."""
        with self._lock:
            if self.watch_folder == new_folder:
                return
            logger.info(
                "Switching monitored folder from %s to %s",
                self.watch_folder,
                new_folder,
            )
            self.watch_folder = new_folder
            self._interrupt_cycle()

    def _handle_changes(self, changes) -> None:
        """Process a batch of debounced change events from watchfiles."""
        seen_paths: set[Path] = set()
        for change_type, path_str in changes:
            if change_type in {Change.added, Change.modified}:
                candidate = Path(path_str)
                if candidate not in seen_paths and should_process_path(candidate):
                    seen_paths.add(candidate)
                    logger.info("Detected incoming scan: %s", candidate.name)
                    self.file_queue.put(candidate)

    def _run_watch_cycle(self, folder: Path, cycle_stop_event: threading.Event) -> None:
        """Run a single monitoring cycle on folder using cycle_stop_event."""
        folder.mkdir(parents=True, exist_ok=True)
        logger.info(
            "DropFolderWatcher listening on %s (debounce: %dms)",
            folder,
            self.debounce_ms,
        )

        for changes in watch(
            folder,
            debounce=self.debounce_ms,
            stop_event=cycle_stop_event,
            recursive=False,
        ):
            self._handle_changes(changes)
            if self._stop_event.is_set() or self._restart_event.is_set():
                break

    def start(self) -> None:
        """Run the blocking watchfiles event loop until stop() is called."""
        self._running = True
        self._stop_event.clear()

        try:
            while not self._stop_event.is_set():
                with self._lock:
                    self._restart_event.clear()
                    self._cycle_stop_event = threading.Event()
                    current_folder = self.watch_folder
                    cycle_stop = self._cycle_stop_event

                try:
                    self._run_watch_cycle(current_folder, cycle_stop)
                except (OSError, RuntimeError) as e:
                    if not self._stop_event.is_set():
                        logger.warning(
                            "Watcher encountered error on %s: %s", current_folder, e
                        )
                        self._stop_event.wait(2.0)
        finally:
            self._running = False
            logger.info("DropFolderWatcher stopped.")

    def stop(self) -> None:
        """Signal the watcher to exit immediately."""
        with self._lock:
            self._stop_event.set()
            self._interrupt_cycle()

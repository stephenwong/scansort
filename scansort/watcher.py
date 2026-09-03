"""Filesystem drop folder monitor utilizing Rust-powered watchfiles with native debouncing."""

import logging
import queue
import threading
from pathlib import Path

from watchfiles import Change, watch

from scansort.image_converter import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


def should_process_path(path: Path) -> bool:
    """Determine whether a detected filesystem entry should be processed.

    Filters out dotfiles, temporary/swap files, and unsupported formats.

    Args:
        path: Path to the candidate file.

    Returns:
        True if the file is a candidate for scan processing, False otherwise.
    """
    name = path.name
    if name.startswith((".", "~")) or ".crdownload" in name or ".part" in name:
        return False

    return path.suffix.lower() in SUPPORTED_EXTENSIONS


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
        self._running = False
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        """Check if watcher is currently active."""
        return self._running

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
            self._restart_event.set()

    def _handle_changes(self, changes) -> None:
        """Process a batch of debounced change events from watchfiles."""
        for change_type, path_str in changes:
            if change_type in {Change.added, Change.modified}:
                candidate = Path(path_str)
                if should_process_path(candidate):
                    logger.info("Detected incoming scan: %s", candidate.name)
                    self.file_queue.put(candidate)

    def start(self) -> None:
        """Run the blocking watchfiles event loop until stop() is called."""
        self._running = True
        self._stop_event.clear()

        try:
            while not self._stop_event.is_set():
                self._restart_event.clear()
                with self._lock:
                    current_folder = self.watch_folder

                current_folder.mkdir(parents=True, exist_ok=True)
                logger.info(
                    "DropFolderWatcher listening on %s (debounce: %dms)",
                    current_folder,
                    self.debounce_ms,
                )

                try:
                    for changes in watch(
                        current_folder,
                        debounce=self.debounce_ms,
                        stop_event=self._stop_event,
                        recursive=False,
                    ):
                        if self._stop_event.is_set():
                            break
                        if self._restart_event.is_set():
                            logger.debug("Restarting watcher for new folder.")
                            break

                        self._handle_changes(changes)

                except (OSError, RuntimeError) as e:
                    if not self._stop_event.is_set():
                        logger.warning(
                            "Watcher encountered error on %s: %s", current_folder, e
                        )
        finally:
            self._running = False
            logger.info("DropFolderWatcher stopped.")

    def stop(self) -> None:
        """Signal the watcher to exit immediately."""
        self._stop_event.set()
        self._restart_event.set()

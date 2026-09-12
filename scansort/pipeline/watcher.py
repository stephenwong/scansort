"""Filesystem drop folder monitor utilizing Rust-powered watchfiles with native debouncing."""

import logging
import queue
import threading
from pathlib import Path

from watchfiles import Change, watch

from scansort.core.constants import (
    DEFAULT_WATCH_DEBOUNCE_MS,
    IGNORED_PREFIXES,
    TEMPORARY_EXTENSIONS,
    WATCHER_ERROR_BACKOFF_S,
)
from scansort.document.converter import is_supported_format

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
    if name.startswith(IGNORED_PREFIXES):
        logger.debug("Ignoring prefixed path in drop folder: %s", name)
        return False
    if lower_name.endswith(TEMPORARY_EXTENSIONS):
        logger.debug("Ignoring temporary file in drop folder: %s", name)
        return False

    supported = is_supported_format(path)
    if not supported:
        logger.debug("Ignoring unsupported file in drop folder: %s", name)
        return False
    return True


class DropFolderWatcher:
    """Monitors scanner drop directory and pushes stabilized incoming files to a worker queue."""

    def __init__(
        self,
        watch_folder: Path,
        file_queue: queue.Queue,
        debounce_ms: int = DEFAULT_WATCH_DEBOUNCE_MS,
    ) -> None:
        self.watch_folder = watch_folder
        self.file_queue = file_queue
        self.debounce_ms = debounce_ms

        self._stop_event = threading.Event()
        self._restart_event = threading.Event()
        self._cycle_stop_event: threading.Event | None = None
        self._running = False
        self._paused = False
        self._lock = threading.Lock()
        # Shared path -> mtime_ns dedup registry: the resume sweep, cycle
        # sweeps, and live event batches must agree on what has been queued so a
        # file is not enqueued twice (F03). Keying on mtime lets a file that is
        # still growing be re-queued after a stabilization timeout (F07) while
        # an unchanged file is skipped.
        self._swept: dict[Path, int] = {}

    def is_running(self) -> bool:
        """Check if watcher is currently active."""
        return self._running

    def is_paused(self) -> bool:
        """Check if watcher ingestion is currently paused."""
        with self._lock:
            return self._paused

    def pause(self) -> None:
        """Pause watcher ingestion: new scan events are ignored until resumed."""
        with self._lock:
            self._paused = True
            logger.info("DropFolderWatcher paused.")

    def resume(self) -> None:
        """Resume watcher ingestion and sweep any files dropped during the pause."""
        with self._lock:
            if not self._paused:
                return
            self._paused = False
            logger.info("DropFolderWatcher resumed.")
            current_folder = self.watch_folder
        self._sweep_preexisting_files(current_folder)

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

    def _handle_changes(
        self, changes, seen_paths: dict[Path, int] | None = None
    ) -> None:
        """Process a batch of debounced change events from watchfiles."""
        seen = seen_paths if seen_paths is not None else self._swept
        for change_type, path_str in changes:
            if change_type in {Change.added, Change.modified}:
                self._enqueue_candidate(Path(path_str), seen, "Detected incoming scan")

    def _enqueue_candidate(
        self, candidate: Path, seen: dict[Path, int], reason: str
    ) -> bool:
        """Queue *candidate* once if it is a supported, not-yet-seen drop file.

        Re-checks the paused flag under the lock so a batch that raced ``pause()``
        cannot slip an item through (F04), and dedups on ``(path, mtime_ns)`` so a
        file still being written is re-queued after a stabilization timeout (F07).
        """
        with self._lock:
            if self._paused:
                logger.debug(
                    "Watcher is paused; ignoring candidate %s.", candidate.name
                )
                return False
            if not should_process_path(candidate):
                return False
            try:
                mtime_ns = candidate.stat().st_mtime_ns
            except OSError:
                return False
            if seen.get(candidate) == mtime_ns:
                return False
            seen[candidate] = mtime_ns
        logger.info("%s: %s", reason, candidate.name)
        self.file_queue.put(candidate)
        return True

    def _run_watch_cycle(self, folder: Path, cycle_stop_event: threading.Event) -> None:
        """Run a single monitoring cycle on folder using cycle_stop_event."""
        folder.mkdir(parents=True, exist_ok=True)
        logger.info(
            "DropFolderWatcher listening on %s (debounce: %dms)",
            folder,
            self.debounce_ms,
        )

        with self._lock:
            is_paused = self._paused
        if not is_paused:
            self._sweep_preexisting_files(folder)

        first_wake = True
        for changes in watch(
            folder,
            debounce=self.debounce_ms,
            stop_event=cycle_stop_event,
            recursive=False,
            yield_on_timeout=True,
        ):
            if first_wake:
                # watchfiles has registered its baseline by this first wake, so
                # any file created between the initial sweep and registration is
                # now visible; sweep again (deduped by mtime) to close the gap
                # and to retry any file that grew after a failed stabilization.
                self._handle_changes(changes)
                if not is_paused:
                    self._sweep_preexisting_files(folder)
                first_wake = False
            else:
                self._handle_changes(changes)
            if self._stop_event.is_set() or self._restart_event.is_set():
                break

    def _sweep_preexisting_files(
        self, folder: Path, seen: dict[Path, int] | None = None
    ) -> None:
        """Enqueue supported files already present when a watch cycle starts.

        watchfiles only reports changes after registration, so scans that arrived
        while the app was stopped (or were left queued at shutdown) would otherwise
        never be filed. The shared ``(path, mtime_ns)`` registry prevents
        re-enqueuing across resume/cycle sweeps while still retrying files that
        changed since the last sweep.
        """
        persistent = seen is None
        registry = self._swept if persistent else seen
        present: set[Path] = set()
        try:
            for candidate in sorted(folder.iterdir()):
                present.add(candidate)
                self._enqueue_candidate(
                    candidate, registry, "Queuing pre-existing scan"
                )
        except OSError as e:
            logger.warning("Could not enumerate watch folder %s: %s", folder, e)
        if persistent:
            # Bound the registry to files still present in the drop folder.
            for stale in list(registry):
                if stale not in present:
                    del registry[stale]

    def start(self) -> None:
        """Run the blocking watchfiles event loop until stop() is called."""
        with self._lock:
            # Honor a stop() that landed before start(): do not erase the signal.
            if self._stop_event.is_set():
                logger.info("DropFolderWatcher.start() ignored: already stopped.")
                return
            self._running = True

        try:
            while True:
                with self._lock:
                    # Re-check the stop signal under the lock: a stop() that
                    # completed while this thread was between iterations must
                    # not be lost to a freshly re-armed cycle event.
                    if self._stop_event.is_set():
                        break
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
                        self._stop_event.wait(WATCHER_ERROR_BACKOFF_S)
        finally:
            self._running = False
            logger.info("DropFolderWatcher stopped.")

    def stop(self) -> None:
        """Signal the watcher to exit immediately."""
        with self._lock:
            self._stop_event.set()
            self._interrupt_cycle()

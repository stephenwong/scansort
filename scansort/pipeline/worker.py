"""Sequential queue worker with rate limiting and shutdown draining."""

import logging
import queue
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run_pipeline_worker(
    process_fn: Callable[[Path], Any],
    file_queue: queue.Queue,
    stop_event: threading.Event,
) -> None:
    """Sequential background worker processing items from the queue with rate-limiting.

    On shutdown the worker drains everything still queued before exiting so
    no dropped scan is silently skipped.
    """
    logger.info("ScanSort pipeline worker started.")
    while True:
        try:
            item = file_queue.get(timeout=0.5)
        except queue.Empty:
            if stop_event.is_set():
                break
            continue

        try:
            process_fn(item)
        except Exception as e:  # noqa: BLE001 - Worker loop must survive unexpected task errors
            logger.error("Unexpected error processing %s: %s", item, e)
        finally:
            file_queue.task_done()
            stop_event.wait(1.0)  # Gentle spacing for API rate limits

    logger.info("ScanSort pipeline worker stopped.")

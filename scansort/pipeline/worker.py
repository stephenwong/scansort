"""Sequential queue worker with rate limiting and shutdown draining."""

import logging
import queue
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scansort.core.constants import DEFAULT_RATE_LIMIT_DELAY_S

logger = logging.getLogger(__name__)


def run_pipeline_worker(
    process_fn: Callable[[Path], Any],
    file_queue: queue.Queue,
    stop_event: threading.Event,
    rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY_S,
) -> None:
    """Sequential background worker processing items from the queue with rate-limiting.

    On shutdown the worker drains everything still queued before exiting so
    no dropped scan is silently skipped.
    """
    logger.info("ScanSort pipeline worker started.")
    while True:
        if stop_event.is_set() and file_queue.empty():
            break

        try:
            item = file_queue.get(timeout=0.5)
        except queue.Empty:
            # Re-check emptiness: an item may have been enqueued concurrently
            # with the timeout, and shutdown must drain rather than drop it.
            if stop_event.is_set() and file_queue.empty():
                break
            continue

        try:
            process_fn(item)
        except Exception as e:  # noqa: BLE001 - Worker loop must survive unexpected task errors
            logger.error("Unexpected error processing %s: %s", item, e)
        finally:
            file_queue.task_done()
            if rate_limit_delay > 0:
                stop_event.wait(rate_limit_delay)  # Gentle spacing for API rate limits

    logger.info("ScanSort pipeline worker stopped.")

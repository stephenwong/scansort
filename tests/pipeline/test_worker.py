"""Unit tests for scansort.pipeline.worker module."""

import queue
import threading
from pathlib import Path
from unittest.mock import MagicMock

from scansort.pipeline.worker import run_pipeline_worker


def test_worker_processes_items_sequentially(tmp_path: Path):
    file_queue = queue.Queue()
    stop_event = threading.Event()

    processed = []

    def mock_process(item: Path):
        processed.append(item.name)

    for i in range(3):
        p = tmp_path / f"file_{i}.pdf"
        p.touch()
        file_queue.put(p)

    worker_thread = threading.Thread(
        target=run_pipeline_worker,
        args=(mock_process, file_queue, stop_event),
        kwargs={"rate_limit_delay": 0.0},
    )
    worker_thread.start()

    # Give worker time to process and stop it
    file_queue.join()
    stop_event.set()
    worker_thread.join(timeout=5.0)

    assert not worker_thread.is_alive()
    assert processed == ["file_0.pdf", "file_1.pdf", "file_2.pdf"]
    assert file_queue.empty()


def test_worker_survives_process_exception(tmp_path: Path):
    file_queue = queue.Queue()
    stop_event = threading.Event()

    calls = []

    def mock_process(item: Path):
        calls.append(item.name)
        if item.name == "bad.pdf":
            raise RuntimeError("Unexpected failure")

    file_queue.put(tmp_path / "bad.pdf")
    file_queue.put(tmp_path / "good.pdf")

    worker_thread = threading.Thread(
        target=run_pipeline_worker,
        args=(mock_process, file_queue, stop_event),
        kwargs={"rate_limit_delay": 0.0},
    )
    worker_thread.start()

    file_queue.join()
    stop_event.set()
    worker_thread.join(timeout=5.0)

    assert not worker_thread.is_alive()
    assert "bad.pdf" in calls
    assert "good.pdf" in calls
    assert file_queue.empty()


def test_worker_exits_immediately_when_stop_event_set_on_empty_queue():
    file_queue = queue.Queue()
    stop_event = threading.Event()
    stop_event.set()

    mock_process = MagicMock()
    run_pipeline_worker(mock_process, file_queue, stop_event)
    mock_process.assert_not_called()


def test_worker_drains_item_enqueued_during_final_timeout():
    """An item that arrives as get() times out must still be processed on shutdown."""
    import queue as _queue

    class RacyQueue:
        def __init__(self):
            self.calls = 0

        def get(self, block=True, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise _queue.Empty
            if self.calls == 2:
                return "late"
            raise _queue.Empty

        def empty(self):
            return self.calls >= 2

        def task_done(self):
            pass

    q = RacyQueue()
    stop = threading.Event()
    processed = []

    def process(item):
        processed.append(item)

    stop.set()
    t = threading.Thread(
        target=run_pipeline_worker,
        args=(process, q, stop),
        kwargs={"rate_limit_delay": 0.0},
    )
    t.start()
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert processed == ["late"]

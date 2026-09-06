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
    )
    worker_thread.start()

    # Give worker time to process and stop it
    stop_event.wait(0.2)
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
    )
    worker_thread.start()

    stop_event.wait(0.2)
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

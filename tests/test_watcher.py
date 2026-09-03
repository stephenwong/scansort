"""Unit tests for scansort.watcher module."""

import queue
import threading
import time
from pathlib import Path
from unittest.mock import patch

from watchfiles import Change

from scansort.watcher import DropFolderWatcher, should_process_path


def test_should_process_path():
    assert should_process_path(Path("C:/Scans/scan001.pdf")) is True
    assert should_process_path(Path("C:/Scans/scan001.jpg")) is True
    assert should_process_path(Path("C:/Scans/scan001.PNG")) is True
    assert should_process_path(Path("C:/Scans/scan001.tmp")) is False
    assert should_process_path(Path("C:/Scans/~scan001.pdf")) is False
    assert should_process_path(Path("C:/Scans/.hidden.pdf")) is False
    assert should_process_path(Path("C:/Scans/subfolder")) is False


def test_watcher_enqueue(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()

    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)

    test_file = inbox / "scan001.pdf"
    test_file.touch()

    # Simulate event notification
    watcher._handle_changes([(Change.added, str(test_file))])

    assert not file_queue.empty()
    queued_path = file_queue.get_nowait()
    assert queued_path == test_file


def test_watcher_ignores_temporary_and_unsupported(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()

    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)

    tmp_file = inbox / "scanner_buffer.tmp"
    tmp_file.touch()
    txt_file = inbox / "notes.txt"
    txt_file.touch()

    watcher._handle_changes([
        (Change.added, str(tmp_file)),
        (Change.modified, str(txt_file)),
    ])

    assert file_queue.empty()


def test_watcher_hot_switch_folder(tmp_path: Path):
    folder_a = tmp_path / "FolderA"
    folder_b = tmp_path / "FolderB"
    folder_a.mkdir()
    folder_b.mkdir()

    watcher = DropFolderWatcher(watch_folder=folder_a, file_queue=queue.Queue())
    assert watcher.watch_folder == folder_a

    watcher.switch_folder(folder_b)
    assert watcher.watch_folder == folder_b


def test_watcher_start_and_stop_cleanly(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()

    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)

    # Mock watchfiles.watch as a generator
    def mock_watch(*args, **kwargs):
        while not watcher._stop_event.is_set():
            time.sleep(0.01)
            yield []

    with patch("scansort.watcher.watch", side_effect=mock_watch):
        thread = threading.Thread(target=watcher.start)
        thread.start()

        time.sleep(0.05)
        assert watcher.is_running() is True

        watcher.stop()
        thread.join(timeout=1.0)
        assert not thread.is_alive()
        assert watcher.is_running() is False

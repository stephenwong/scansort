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
    # S2-05: multipart file names like scan.part1.pdf should be allowed
    assert should_process_path(Path("C:/Scans/scan.part1.pdf")) is True
    assert should_process_path(Path("C:/Scans/doc.part2.jpg")) is True
    # S2-05: actual partial downloads should be rejected
    assert should_process_path(Path("C:/Scans/scan.pdf.part")) is False
    assert should_process_path(Path("C:/Scans/scan.pdf.crdownload")) is False
    # S1-07: undone restored files should be ignored to prevent re-ingestion loops
    assert should_process_path(Path("C:/Scans/_undone_scan001.pdf")) is False


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

    watcher._handle_changes(
        [
            (Change.added, str(tmp_file)),
            (Change.modified, str(txt_file)),
        ]
    )

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


def test_watcher_switch_same_folder(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=queue.Queue())
    watcher.switch_folder(inbox)
    assert watcher.watch_folder == inbox


def test_watcher_handles_error_in_watch(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=queue.Queue())

    calls = 0

    def mock_watch_error(*args, **kwargs):
        nonlocal calls
        calls += 1
        watcher.stop()
        raise OSError("Disk disconnected")

    with patch("scansort.watcher.watch", side_effect=mock_watch_error):
        watcher.start()
        assert calls == 1


def test_should_process_path_directory(tmp_path: Path):
    pdf_dir = tmp_path / "SubFolder.pdf"
    pdf_dir.mkdir()
    assert should_process_path(pdf_dir) is False


def test_watcher_batch_deduplication(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    scan = inbox / "scan.pdf"
    scan.touch()

    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)
    watcher._handle_changes(
        [
            (Change.added, str(scan)),
            (Change.modified, str(scan)),
        ]
    )
    assert file_queue.qsize() == 1


def test_switch_folder_unblocks_watch(tmp_path: Path):
    folder_a = tmp_path / "A"
    folder_b = tmp_path / "B"
    folder_a.mkdir()
    folder_b.mkdir()

    w = DropFolderWatcher(watch_folder=folder_a, file_queue=queue.Queue())
    watched = []

    def mock_watch(folder, *args, **kwargs):
        watched.append(folder)
        stop_event = kwargs.get("stop_event")
        while not (stop_event and stop_event.is_set()):
            time.sleep(0.01)
        yield []

    with patch("scansort.watcher.watch", side_effect=mock_watch):
        t = threading.Thread(target=w.start)
        t.start()
        time.sleep(0.05)
        w.switch_folder(folder_b)
        time.sleep(0.05)
        w.stop()
        t.join(timeout=1.0)
        assert folder_b in watched


def test_watcher_does_not_drop_changes_when_stopped(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    scan = inbox / "final_scan.pdf"
    scan.touch()

    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)

    def mock_watch_yield_and_stop(*args, **kwargs):
        # Set stop event concurrently before yielding changes
        watcher._stop_event.set()
        yield [(Change.added, str(scan))]

    with patch("scansort.watcher.watch", side_effect=mock_watch_yield_and_stop):
        watcher.start()

    # The yielded file must have been enqueued, not dropped
    assert file_queue.qsize() == 1
    assert file_queue.get_nowait() == scan


def test_watcher_mkdir_error_retried(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)

    attempt = 0

    def mock_mkdir(*args, **kwargs):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise OSError("Access denied temporarily")
        # On second attempt, stop the watcher
        watcher.stop()

    with patch.object(Path, "mkdir", side_effect=mock_mkdir):
        watcher.start()

    assert attempt >= 2

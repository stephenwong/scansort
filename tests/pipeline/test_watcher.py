"""Unit tests for scansort.watcher module."""

import queue
import threading
from pathlib import Path
from unittest.mock import patch

from watchfiles import Change

from scansort.pipeline.watcher import DropFolderWatcher, should_process_path


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

    started = threading.Event()

    # Mock watchfiles.watch as a generator
    def mock_watch(*args, **kwargs):
        started.set()
        watcher._stop_event.wait(timeout=2.0)
        yield []

    with patch("scansort.pipeline.watcher.watch", side_effect=mock_watch):
        thread = threading.Thread(target=watcher.start)
        thread.start()

        started.wait(timeout=2.0)
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

    with patch("scansort.pipeline.watcher.watch", side_effect=mock_watch_error):
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
    folder_a_watched = threading.Event()
    folder_b_watched = threading.Event()

    def mock_watch(folder, *args, **kwargs):
        watched.append(folder)
        if folder == folder_a:
            folder_a_watched.set()
        elif folder == folder_b:
            folder_b_watched.set()
        stop_event = kwargs.get("stop_event")
        if stop_event:
            stop_event.wait(timeout=2.0)
        yield []

    with patch("scansort.pipeline.watcher.watch", side_effect=mock_watch):
        t = threading.Thread(target=w.start)
        t.start()
        folder_a_watched.wait(timeout=2.0)
        w.switch_folder(folder_b)
        folder_b_watched.wait(timeout=2.0)
        w.stop()
        t.join(timeout=1.0)
        assert folder_b in watched


def test_watcher_sweeps_preexisting_files_on_start(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    stale = inbox / "stale.pdf"
    stale.write_bytes(b"%PDF-1.4 stale")
    (inbox / "notes.txt").write_text("ignored")

    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)

    def mock_watch(*args, **kwargs):
        watcher._stop_event.set()
        yield []

    with patch("scansort.pipeline.watcher.watch", side_effect=mock_watch):
        watcher.start()

    assert file_queue.qsize() == 1
    assert file_queue.get_nowait() == stale


def test_watcher_does_not_drop_changes_when_stopped(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()

    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)

    scan = inbox / "final_scan.pdf"

    def mock_watch_yield_and_stop(*args, **kwargs):
        # Create the file after the cycle starts, then stop and yield its event.
        scan.touch()
        watcher._stop_event.set()
        yield [(Change.added, str(scan))]

    with patch(
        "scansort.pipeline.watcher.watch", side_effect=mock_watch_yield_and_stop
    ):
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

    with (
        patch.object(Path, "mkdir", side_effect=mock_mkdir),
        patch.object(watcher._stop_event, "wait", return_value=True),
    ):
        watcher.start()

    assert attempt >= 2


def test_watcher_pause_resume(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)

    assert watcher.is_paused() is False

    scan = inbox / "scan001.pdf"
    scan.touch()

    # Pause watcher
    watcher.pause()
    assert watcher.is_paused() is True

    # When paused, changes are ignored
    watcher._handle_changes([(Change.added, str(scan))])
    assert file_queue.empty()

    # Resume watcher: sweeps pre-existing files in drop folder
    watcher.resume()
    assert watcher.is_paused() is False
    assert file_queue.qsize() == 1
    assert file_queue.get_nowait() == scan

    # Calling resume when already unpaused is a no-op (idempotent, no re-sweep)
    watcher.resume()
    assert file_queue.empty()


def test_watcher_paused_cycle_skips_preexisting_sweep(tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)

    scan = inbox / "scan002.pdf"
    scan.touch()

    watcher.pause()
    stop_event = threading.Event()
    stop_event.set()  # Stop watch loop immediately

    # Run cycle while paused
    with patch("scansort.pipeline.watcher.watch", return_value=[]):
        watcher._run_watch_cycle(inbox, stop_event)

    # Queue should still be empty because watcher is paused
    assert file_queue.empty()

    # Subsequently resuming discovers the skipped file
    watcher.resume()
    assert file_queue.qsize() == 1
    assert file_queue.get_nowait() == scan


def test_watcher_stop_before_start_is_honored(tmp_path: Path):
    """A stop() that lands before start() must not be erased by start()."""
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=queue.Queue())
    watcher.stop()

    def mock_watch(*args, **kwargs):
        yield []

    with patch("scansort.pipeline.watcher.watch", side_effect=mock_watch):
        thread = threading.Thread(target=watcher.start)
        thread.start()
        thread.join(timeout=1.0)

    assert not thread.is_alive()


def test_watcher_sweep_covers_file_created_before_baseline(tmp_path: Path):
    """A file landing between the initial sweep and watch registration must be queued."""
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)

    def mock_watch(*args, **kwargs):
        (inbox / "gap.pdf").write_bytes(b"%PDF-1.4")
        yield []
        watcher._stop_event.set()
        yield []

    with patch("scansort.pipeline.watcher.watch", side_effect=mock_watch):
        watcher._stop_event.set()
        watcher._run_watch_cycle(inbox, threading.Event())

    queued = []
    while not file_queue.empty():
        queued.append(file_queue.get_nowait())
    assert inbox / "gap.pdf" in queued


def test_enqueue_candidate_refuses_when_paused(tmp_path: Path):
    """F04: a candidate racing a pause() must not be enqueued."""
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    scan = inbox / "scan.pdf"
    scan.touch()
    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)

    watcher.pause()
    assert watcher._enqueue_candidate(scan, {}, "racing candidate") is False
    assert file_queue.empty()


def test_resume_and_cycle_sweeps_share_dedup(tmp_path: Path):
    """F03: the resume sweep and a cycle sweep must not double-enqueue a file."""
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    scan = inbox / "scan.pdf"
    scan.write_bytes(b"%PDF-1.4")

    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)
    watcher.pause()
    watcher.resume()
    assert file_queue.qsize() == 1

    stop_event = threading.Event()
    stop_event.set()
    with patch("scansort.pipeline.watcher.watch", return_value=iter([])):
        watcher._run_watch_cycle(inbox, stop_event)

    assert file_queue.qsize() == 1


def test_watcher_resweeps_file_that_grew_before_first_wake(tmp_path: Path):
    """F07: a file that grew since the initial sweep must be retried."""
    import os

    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    scan = inbox / "growing.pdf"
    scan.write_bytes(b"%PDF-1.4")
    initial_mtime = scan.stat().st_mtime_ns

    file_queue = queue.Queue()
    watcher = DropFolderWatcher(watch_folder=inbox, file_queue=file_queue)

    def mock_watch(*args, **kwargs):
        os.utime(scan, ns=(initial_mtime, initial_mtime + 1_000_000_000))
        yield []
        watcher._stop_event.set()
        yield []

    with patch("scansort.pipeline.watcher.watch", side_effect=mock_watch):
        watcher._run_watch_cycle(inbox, threading.Event())

    assert file_queue.qsize() == 2

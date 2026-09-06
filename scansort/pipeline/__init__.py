"""Document ingestion, stabilization, dispatching, queue worker, and pipeline coordinator."""

from scansort.pipeline.coordinator import ScanSortPipeline
from scansort.pipeline.dispatcher import (
    OPERATIONS_LOCK_FILENAME,
    dispatch_file,
    generate_target_filename,
    resolve_collision,
    resolve_destination_dir,
    resolve_duplicates_dir,
)
from scansort.pipeline.hasher import check_duplicate, compute_file_sha256
from scansort.pipeline.stabilizer import is_file_locked, wait_for_file_stability
from scansort.pipeline.undo import undo_last_move
from scansort.pipeline.watcher import DropFolderWatcher, should_process_path
from scansort.pipeline.worker import run_pipeline_worker

__all__ = [
    "ScanSortPipeline",
    "run_pipeline_worker",
    "dispatch_file",
    "generate_target_filename",
    "resolve_collision",
    "resolve_destination_dir",
    "resolve_duplicates_dir",
    "OPERATIONS_LOCK_FILENAME",
    "compute_file_sha256",
    "check_duplicate",
    "is_file_locked",
    "wait_for_file_stability",
    "undo_last_move",
    "DropFolderWatcher",
    "should_process_path",
]

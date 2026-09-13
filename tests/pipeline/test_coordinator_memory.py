"""Coordinator wiring tests for RAG memory retrieval + indexing."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from scansort.classification.memory import MemoryStore, memory_db_path_for
from scansort.classification.models import DocumentClassification
from scansort.core.config import AppConfig
from scansort.core.constants import DEFAULT_GEMINI_MODEL
from scansort.pipeline.coordinator import ScanSortPipeline


def _make_classifier() -> MagicMock:
    classifier = MagicMock()
    classifier.model = DEFAULT_GEMINI_MODEL
    classifier._client = None
    return classifier


def _classification() -> DocumentClassification:
    return DocumentClassification(
        document_date="260901",
        description="Origin_Energy_Bill",
        target_folder="Utilities/Electricity",
        confidence=0.95,
        orientation_correction=0,
        document_type="Invoice",
        summary="Quarterly electricity bill",
    )


def _make_pipeline(tmp_path: Path, **config_kwargs):
    inbox = tmp_path / "Inbox"
    inbox.mkdir(exist_ok=True)
    docs_root = tmp_path / "Documents"
    (docs_root / "Utilities" / "Electricity").mkdir(parents=True, exist_ok=True)
    app_dir = tmp_path / "appdata"
    cfg = AppConfig(watch_folder=inbox, documents_root=docs_root, **config_kwargs)
    classifier = _make_classifier()
    classifier.classify_document.return_value = _classification()
    pipeline = ScanSortPipeline(config=cfg, app_dir=app_dir, classifier=classifier)
    return pipeline, cfg, inbox, docs_root, app_dir


@pytest.fixture(autouse=True)
def _silence_real_toasts():
    with patch("scansort.platform.notifications.show_toast", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _fast_file_stability():
    with patch(
        "scansort.pipeline.coordinator.wait_for_file_stability", return_value=True
    ):
        yield


@pytest.fixture(autouse=True)
def _no_ocr_skim():
    """Keep retrieval hermetic: filename/text queries only unless enabled."""
    with patch("scansort.classification.memory.has_ocr_support", return_value=False):
        yield


def _create_sample_scan(path: Path):
    Image.new("RGB", (200, 200), color="white").save(path, format="JPEG")


def _seed_history(app_dir: Path, records: list[dict]):
    history = app_dir / "history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    with open(history, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    return history


def test_classify_scan_disabled_passes_no_memory(tmp_path: Path, minimal_pdf: Path):
    pipeline, cfg, *_ = _make_pipeline(tmp_path, rag_memory_enabled=False)
    pipeline._classify_scan(minimal_pdf, "bill.pdf", cfg)
    _, kwargs = pipeline.classifier.classify_document.call_args
    assert kwargs["examples"] is None
    assert kwargs["folder_thresholds"] is None


def test_classify_scan_retrieves_examples_and_thresholds(
    tmp_path: Path, minimal_pdf: Path
):
    pipeline, cfg, _, _, app_dir = _make_pipeline(tmp_path)
    _seed_history(
        app_dir,
        [
            {
                "sha256": "a" * 64,
                "status": "SUCCESS",
                "destination_folder": "Utilities/Electricity",
                "suggested_folder": "Utilities/Electricity",
                "document_type": "Invoice",
                "summary": "Origin Energy electricity bill July",
            },
            {
                "sha256": "b" * 64,
                "status": "UNDONE",
                "destination_folder": "Utilities/Electricity",
                "summary": "misfiled bill",
            },
        ],
    )
    pipeline._classify_scan(minimal_pdf, "Origin Energy bill August.pdf", cfg)
    _, kwargs = pipeline.classifier.classify_document.call_args
    assert kwargs["examples"]
    assert kwargs["examples"][0].folder == "Utilities/Electricity"
    assert kwargs["folder_thresholds"] == {"Utilities/Electricity": 0.75}


def test_classify_scan_search_failure_falls_back(tmp_path: Path, minimal_pdf: Path):
    pipeline, cfg, *_ = _make_pipeline(tmp_path)
    _seed_history(
        tmp_path / "appdata",
        [
            {
                "sha256": "a" * 64,
                "status": "SUCCESS",
                "destination_folder": "Utilities/Electricity",
                "summary": "Origin Energy bill",
            }
        ],
    )
    with patch.object(
        MemoryStore, "search", side_effect=sqlite3.OperationalError("locked")
    ):
        result, _ = pipeline._classify_scan(minimal_pdf, "bill.pdf", cfg)
    assert result.target_folder == "Utilities/Electricity"


def test_classify_scan_empty_store_skips_query_work(tmp_path: Path, minimal_pdf: Path):
    pipeline, cfg, *_ = _make_pipeline(tmp_path)
    with patch("scansort.classification.memory.build_retrieval_query") as mock_query:
        pipeline._classify_scan(minimal_pdf, "bill.pdf", cfg)
    mock_query.assert_not_called()
    _, kwargs = pipeline.classifier.classify_document.call_args
    assert kwargs["examples"] is None


def test_success_dispatch_indexes_record(tmp_path: Path):
    pipeline, _, inbox, docs_root, app_dir = _make_pipeline(tmp_path)
    scan_file = inbox / "scan001.jpg"
    _create_sample_scan(scan_file)
    dest = pipeline.process_file(scan_file)
    assert dest is not None and dest.exists()
    store = MemoryStore(memory_db_path_for(app_dir))
    assert store.count() == 1
    hits = store.search("Origin Energy electricity bill")
    assert hits and hits[0].folder == "Utilities/Electricity"


def test_disabled_creates_no_vectors(tmp_path: Path):
    pipeline, _, inbox, _, app_dir = _make_pipeline(tmp_path, rag_memory_enabled=False)
    scan_file = inbox / "scan001.jpg"
    _create_sample_scan(scan_file)
    assert pipeline.process_file(scan_file) is not None
    assert not (app_dir / "vectors").exists()


def test_index_failure_does_not_break_filing(tmp_path: Path):
    pipeline, _, inbox, _, _ = _make_pipeline(tmp_path)
    scan_file = inbox / "scan001.jpg"
    _create_sample_scan(scan_file)
    with patch.object(
        MemoryStore, "index_record", side_effect=RuntimeError("disk on fire")
    ):
        dest = pipeline.process_file(scan_file)
    assert dest is not None and dest.exists()


def test_dry_run_does_not_index(tmp_path: Path):
    pipeline, _, inbox, _, app_dir = _make_pipeline(tmp_path, dry_run=True)
    scan_file = inbox / "scan001.jpg"
    _create_sample_scan(scan_file)
    assert pipeline.process_file(scan_file) is not None
    assert not memory_db_path_for(app_dir).exists()


def test_dry_run_does_not_backfill_or_create_db(tmp_path: Path):
    """A read-only preview must not create the vector DB from history."""
    pipeline, _, inbox, _, app_dir = _make_pipeline(tmp_path, dry_run=True)
    _seed_history(
        app_dir,
        [
            {
                "sha256": "a" * 64,
                "status": "SUCCESS",
                "destination_folder": "Utilities/Electricity",
                "summary": "Origin Energy electricity bill July",
            }
        ],
    )
    scan_file = inbox / "scan001.jpg"
    _create_sample_scan(scan_file)
    assert pipeline.process_file(scan_file) is not None
    assert not memory_db_path_for(app_dir).exists()
    assert not (app_dir / "index.lock").exists()


def test_classify_scan_thresholds_survive_empty_store(
    tmp_path: Path, minimal_pdf: Path
):
    """Calibration is derived from history, not the vector store."""
    pipeline, cfg, _, _, app_dir = _make_pipeline(tmp_path)
    _seed_history(
        app_dir,
        [
            {
                "sha256": "a" * 64,
                "status": "UNDONE",
                "destination_folder": "Utilities/Electricity",
                "summary": "misfiled bill",
            }
        ],
    )
    pipeline._classify_scan(minimal_pdf, "bill.pdf", cfg)
    _, kwargs = pipeline.classifier.classify_document.call_args
    assert kwargs["examples"] is None
    assert kwargs["folder_thresholds"] == {"Utilities/Electricity": 0.75}


def test_classify_scan_skips_ocr_skim_when_ocr_enabled(
    tmp_path: Path, minimal_pdf: Path
):
    """OCR already ran in the pipeline; retrieval must not run a second pass."""
    pipeline, cfg, _, _, app_dir = _make_pipeline(tmp_path, ocr_enabled=True)
    _seed_history(
        app_dir,
        [
            {
                "sha256": "a" * 64,
                "status": "SUCCESS",
                "destination_folder": "Utilities/Electricity",
                "summary": "Origin Energy electricity bill July",
            }
        ],
    )
    with patch(
        "scansort.pipeline.coordinator.build_retrieval_query",
        return_value="Origin Energy bill",
    ) as mock_query:
        pipeline._classify_scan(minimal_pdf, "bill.pdf", cfg)
    assert mock_query.call_args.kwargs["allow_ocr_skim"] is False


def test_retrieval_after_review_correction(tmp_path: Path, minimal_pdf: Path):
    """Seed a REVIEWED correction, then confirm it is retrieved for a repeat."""
    pipeline, cfg, _, _, app_dir = _make_pipeline(tmp_path)
    store = MemoryStore(memory_db_path_for(app_dir))
    assert (
        store.index_record(
            {
                "sha256": "a" * 64,
                "status": "REVIEWED",
                "destination_folder": "Utilities/Electricity",
                "suggested_folder": "Utilities",
                "document_type": "Invoice",
                "summary": "Origin Energy electricity bill August 2026",
            }
        )
        is True
    )
    pipeline._classify_scan(
        minimal_pdf, "Origin Energy electricity bill September.pdf", cfg
    )
    _, kwargs = pipeline.classifier.classify_document.call_args
    assert kwargs["examples"]
    assert kwargs["examples"][0].folder == "Utilities/Electricity"


def test_backfill_runs_once_under_lock(tmp_path: Path, minimal_pdf: Path):
    pipeline, cfg, _, _, app_dir = _make_pipeline(tmp_path)
    history = _seed_history(
        app_dir,
        [
            {
                "sha256": "a" * 64,
                "status": "SUCCESS",
                "destination_folder": "Utilities/Electricity",
                "summary": "Origin Energy bill",
            }
        ],
    )
    calls: list[Path] = []
    real_backfill = MemoryStore.backfill_from_history

    def spy(self, jsonl_path, *, limit):
        calls.append(Path(jsonl_path))
        return real_backfill(self, jsonl_path, limit=limit)

    with patch.object(MemoryStore, "backfill_from_history", spy):
        pipeline._classify_scan(minimal_pdf, "bill.pdf", cfg)
        pipeline._classify_scan(minimal_pdf, "bill.pdf", cfg)
    assert len(calls) == 1
    assert history.exists()


def test_classify_scan_returns_memory_note(tmp_path: Path, minimal_pdf: Path):
    """The note is returned per call, never stored on the shared instance."""
    pipeline, cfg, _, _, app_dir = _make_pipeline(tmp_path)
    _seed_history(
        app_dir,
        [
            {
                "sha256": "a" * 64,
                "status": "SUCCESS",
                "destination_folder": "Utilities/Electricity",
                "summary": "Origin Energy electricity bill July",
            }
        ],
    )
    _, note = pipeline._classify_scan(minimal_pdf, "Origin Energy bill August.pdf", cfg)
    assert note == "matched 1 past filing(s)"
    assert not hasattr(pipeline, "_last_memory_note")


def test_process_file_passes_memory_note_to_toast(tmp_path: Path):
    pipeline, cfg, inbox, _, app_dir = _make_pipeline(tmp_path)
    _seed_history(
        app_dir,
        [
            {
                "sha256": "a" * 64,
                "status": "SUCCESS",
                "destination_folder": "Utilities/Electricity",
                "summary": "Origin Energy electricity bill July",
            }
        ],
    )
    with patch(
        "scansort.pipeline.coordinator.notify_file_filed", return_value=True
    ) as mock_notify:
        scan_file = inbox / "Origin Energy bill September.jpg"
        _create_sample_scan(scan_file)
        assert pipeline.process_file(scan_file) is not None
    assert mock_notify.call_args.kwargs.get("detail") == "matched 1 past filing(s)"


def test_memory_note_isolated_between_interleaved_dispatches(tmp_path: Path):
    """A note from one dispatch must never leak into another's toast."""
    pipeline, cfg, inbox, docs_root, _ = _make_pipeline(tmp_path)
    prepared: list[Path] = []
    for index in range(2):
        scan = inbox / f"scan{index}.jpg"
        Image.new("RGB", (200, 200), color=(index * 40, 10, 10)).save(
            scan, format="JPEG"
        )
        prepared.append(scan)

    notes = iter(["matched 1 past filing(s)", None])
    with (
        patch.object(
            pipeline,
            "_classify_scan",
            side_effect=lambda *a, **k: (_classification(), next(notes)),
        ),
        patch(
            "scansort.pipeline.coordinator.notify_file_filed", return_value=True
        ) as mock_notify,
    ):
        first = pipeline.process_file(prepared[0])
        second = pipeline.process_file(prepared[1])

    assert first is not None and second is not None
    details = [call.kwargs.get("detail") for call in mock_notify.call_args_list]
    assert details == ["matched 1 past filing(s)", None]


def test_memory_note_absent_when_disabled(tmp_path: Path, minimal_pdf: Path):
    pipeline, cfg, inbox, _, _ = _make_pipeline(tmp_path, rag_memory_enabled=False)
    _, note = pipeline._classify_scan(minimal_pdf, "bill.pdf", cfg)
    assert note is None
    with patch(
        "scansort.pipeline.coordinator.notify_file_filed", return_value=True
    ) as mock_notify:
        scan_file = inbox / "scan001.jpg"
        _create_sample_scan(scan_file)
        assert pipeline.process_file(scan_file) is not None
    assert mock_notify.call_args.kwargs.get("detail") is None


def test_first_backfill_notifies_once(tmp_path: Path, minimal_pdf: Path):
    pipeline, cfg, _, _, app_dir = _make_pipeline(tmp_path)
    _seed_history(
        app_dir,
        [
            {
                "sha256": "a" * 64,
                "status": "SUCCESS",
                "destination_folder": "Utilities/Electricity",
                "summary": "Origin Energy electricity bill July",
            }
        ],
    )
    with patch(
        "scansort.pipeline.coordinator.notify_memory_learned", return_value=True
    ) as mock_toast:
        pipeline._classify_scan(minimal_pdf, "Origin Energy bill August.pdf", cfg)
        pipeline._classify_scan(minimal_pdf, "Origin Energy bill August.pdf", cfg)
    assert mock_toast.call_count == 1
    assert mock_toast.call_args.args[0] == 1


def test_backfill_no_rows_no_toast(tmp_path: Path, minimal_pdf: Path):
    pipeline, cfg, _, _, _ = _make_pipeline(tmp_path)
    with patch(
        "scansort.pipeline.coordinator.notify_memory_learned", return_value=True
    ) as mock_toast:
        pipeline._classify_scan(minimal_pdf, "bill.pdf", cfg)
    mock_toast.assert_not_called()


def test_dry_run_no_toast(tmp_path: Path, minimal_pdf: Path):
    pipeline, _, _, _, app_dir = _make_pipeline(tmp_path, dry_run=True)
    _seed_history(
        app_dir,
        [
            {
                "sha256": "a" * 64,
                "status": "SUCCESS",
                "destination_folder": "Utilities/Electricity",
                "summary": "Origin Energy bill",
            }
        ],
    )
    cfg = pipeline.config
    with patch(
        "scansort.pipeline.coordinator.notify_memory_learned", return_value=True
    ) as mock_toast:
        pipeline._classify_scan(minimal_pdf, "bill.pdf", cfg)
    mock_toast.assert_not_called()

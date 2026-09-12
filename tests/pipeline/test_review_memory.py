"""Review wiring tests: suggested_folder persistence + memory indexing."""

import json
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from scansort.classification.memory import MemoryStore, memory_db_path_for
from scansort.core.config import AppConfig
from scansort.core.constants import HISTORY_CSV_NAME, HISTORY_JSONL_NAME
from scansort.pipeline.review import ReviewItem, file_reviewed_item


def _create_dummy_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def _setup(tmp_path: Path, **item_kwargs):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    source_pdf = _create_dummy_pdf(review_dir / "temp_scan.pdf")
    app_dir = tmp_path / "app_data"
    app_dir.mkdir(parents=True, exist_ok=True)
    cfg = AppConfig(documents_root=docs, fallback_folder="_Review_Needed")
    item_fields = {
        "file_path": source_pdf,
        "filename": source_pdf.name,
        "file_size_bytes": source_pdf.stat().st_size,
        "modified_time": source_pdf.stat().st_mtime,
        "sha256": "a" * 64,
        "summary": "Origin Energy electricity bill August",
        "document_type": "Invoice",
        "suggested_folder": "Finances/Utilities",
    }
    item_fields.update(item_kwargs)
    item = ReviewItem(**item_fields)
    paths = {
        "hints_path": app_dir / "folder_hints.json",
        "history_jsonl": app_dir / HISTORY_JSONL_NAME,
        "history_csv": app_dir / HISTORY_CSV_NAME,
        "lock_path": app_dir / "operations.lock",
    }
    return docs, app_dir, cfg, item, paths


def _read_entries(history_jsonl: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in history_jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_reviewed_persists_suggested_folder(tmp_path: Path):
    _, _, cfg, item, paths = _setup(tmp_path)
    file_reviewed_item(
        item=item,
        target_folder="Health/Dental",
        document_date="260815",
        description="Dental_Invoice",
        config=cfg,
        keyword_hint="dental",
        **paths,
    )
    entry = _read_entries(paths["history_jsonl"])[-1]
    assert entry["status"] == "REVIEWED"
    assert entry["destination_folder"] == "Health/Dental"
    assert entry["suggested_folder"] == "Finances/Utilities"


def test_reviewed_without_suggestion_omits_key(tmp_path: Path):
    _, _, cfg, item, paths = _setup(tmp_path, suggested_folder="")
    file_reviewed_item(
        item=item,
        target_folder="Health/Dental",
        document_date="260815",
        description="Dental_Invoice",
        config=cfg,
        **paths,
    )
    entry = _read_entries(paths["history_jsonl"])[-1]
    assert entry["status"] == "REVIEWED"
    assert "suggested_folder" not in entry


def test_reviewed_indexes_corrected_folder(tmp_path: Path):
    _, app_dir, cfg, item, paths = _setup(tmp_path)
    dest = file_reviewed_item(
        item=item,
        target_folder="Health/Dental",
        document_date="260815",
        description="Dental_Invoice",
        config=cfg,
        **paths,
    )
    assert dest.exists()
    store = MemoryStore(memory_db_path_for(app_dir))
    assert store.count() == 1
    hits = store.search("Origin Energy electricity bill")
    assert hits and hits[0].folder == "Health/Dental"


def test_reviewed_disabled_creates_no_vectors(tmp_path: Path):
    docs = tmp_path / "Documents"
    review_dir = docs / "_Review_Needed"
    source_pdf = _create_dummy_pdf(review_dir / "temp_scan.pdf")
    app_dir = tmp_path / "app_data"
    app_dir.mkdir(parents=True, exist_ok=True)
    cfg = AppConfig(
        documents_root=docs,
        fallback_folder="_Review_Needed",
        rag_memory_enabled=False,
    )
    item = ReviewItem(
        file_path=source_pdf,
        filename=source_pdf.name,
        file_size_bytes=source_pdf.stat().st_size,
        modified_time=source_pdf.stat().st_mtime,
        sha256="a" * 64,
        summary="Origin Energy electricity bill",
    )
    dest = file_reviewed_item(
        item=item,
        target_folder="Health/Dental",
        document_date="260815",
        description="Dental_Invoice",
        config=cfg,
        hints_path=app_dir / "folder_hints.json",
        history_jsonl=app_dir / HISTORY_JSONL_NAME,
        history_csv=app_dir / HISTORY_CSV_NAME,
        lock_path=app_dir / "operations.lock",
    )
    assert dest.exists()
    assert not (app_dir / "vectors").exists()


def test_reviewed_without_keyword_hint_writes_no_hints(tmp_path: Path):
    """Propose-only: filing without an explicit hint must not touch hints."""
    _, _, cfg, item, paths = _setup(tmp_path)
    file_reviewed_item(
        item=item,
        target_folder="Health/Dental",
        document_date="260815",
        description="Dental_Invoice",
        keyword_hint=None,
        config=cfg,
        **paths,
    )
    assert not paths["hints_path"].exists()


def test_reviewed_index_failure_still_files(tmp_path: Path):
    _, _, cfg, item, paths = _setup(tmp_path)
    with patch.object(
        MemoryStore, "index_record", side_effect=RuntimeError("disk on fire")
    ):
        dest = file_reviewed_item(
            item=item,
            target_folder="Health/Dental",
            document_date="260815",
            description="Dental_Invoice",
            config=cfg,
            **paths,
        )
    assert dest.exists()


def test_duplicate_review_path_does_not_index(tmp_path: Path):
    docs, app_dir, cfg, item, paths = _setup(tmp_path)
    seed = {
        "sha256": "a" * 64,
        "status": "SUCCESS",
        "destination_folder": "Health/Dental",
        "new_filename": "existing.pdf",
        "summary": "Earlier identical filing",
    }
    paths["history_jsonl"].write_text(json.dumps(seed) + "\n", encoding="utf-8")
    dest = file_reviewed_item(
        item=item,
        target_folder="Health/Dental",
        document_date="260815",
        description="Dental_Invoice",
        config=cfg,
        **paths,
    )
    assert "Duplicates" in dest.parts
    assert MemoryStore(memory_db_path_for(app_dir)).count() == 0


def test_review_filing_ignores_own_routing_record(tmp_path: Path):
    """A review item must not be treated as a duplicate of its own routing record."""
    _, _, cfg, item, paths = _setup(tmp_path)
    history = paths["history_jsonl"]
    history.write_text(
        json.dumps(
            {
                "sha256": item.sha256,
                "status": "SUCCESS",
                "destination_folder": "_Review_Needed",
                "destination_path": str(item.file_path.resolve()),
                "new_filename": item.filename,
                "summary": "low confidence routing",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    seen: list[dict] = []
    dest = file_reviewed_item(
        item=item,
        target_folder="Health/Dental",
        document_date="260815",
        description="Dental_Invoice",
        config=cfg,
        on_duplicate=lambda record: seen.append(record) or False,
        **paths,
    )
    assert seen == []
    assert dest.exists()
    assert "Duplicates" not in dest.parts

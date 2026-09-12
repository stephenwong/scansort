"""Unit tests for scansort.classification.doctor (Taxonomy Doctor)."""

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from scansort.classification.doctor import (
    ACTION_CREATE_FOLDER,
    ACTION_DELETE_EMPTY,
    ACTION_MERGE_INTO,
    ACTION_NONE,
    KIND_GHOST_FOLDER,
    KIND_NEAR_DUPLICATE,
    KIND_OVERBROAD_FOLDER,
    KIND_REVIEW_CLUSTER,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    DoctorFinding,
    apply_doctor_action,
    load_history_for_doctor,
    render_doctor_report,
    run_doctor,
)
from scansort.core.config import AppConfig
from scansort.pipeline.review import ReviewItem


def _make_config(tmp_path: Path, **overrides) -> AppConfig:
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Documents"
    inbox.mkdir(exist_ok=True)
    docs.mkdir(exist_ok=True)
    return AppConfig(watch_folder=inbox, documents_root=docs, **overrides)


def _record(
    folder: str,
    *,
    status: str = "SUCCESS",
    doc_type: str = "Invoice",
    summary: str = "",
    timestamp: str = "2026-09-01T00:00:00+00:00",
) -> dict:
    return {
        "destination_folder": folder,
        "status": status,
        "document_type": doc_type,
        "summary": summary or f"{doc_type} for {folder}",
        "timestamp": timestamp,
    }


def _write_history(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "history.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return path


def _review_item(
    tmp_path: Path, name: str, *, suggested: str = "", summary: str = ""
) -> ReviewItem:
    file = tmp_path / name
    file.write_bytes(b"%PDF-1.4")
    return ReviewItem(
        file_path=file,
        filename=name,
        file_size_bytes=8,
        modified_time=0.0,
        summary=summary,
        suggested_folder=suggested,
    )


def test_name_near_duplicates_flagged_with_winner_by_filings(tmp_path: Path):
    cfg = _make_config(tmp_path)
    docs = cfg.documents_root
    (docs / "Bill").mkdir()
    (docs / "Bills").mkdir()
    records = [_record("Bill") for _ in range(3)]
    history = _write_history(tmp_path, records)

    report = run_doctor(cfg, history_path=history, review_items=[])

    dupes = [f for f in report.findings if f.kind == KIND_NEAR_DUPLICATE]
    assert len(dupes) == 1
    finding = dupes[0]
    assert finding.action == ACTION_MERGE_INTO
    assert finding.target_folder == "Bill"
    assert finding.primary_folder == "Bills"
    assert finding.detail["name_similarity"] >= 0.85


def test_semantically_similar_folders_are_advisory_not_mergeable(tmp_path: Path):
    cfg = _make_config(tmp_path)
    docs = cfg.documents_root
    (docs / "Bills" / "Power").mkdir(parents=True)
    (docs / "Utilities" / "Electricity").mkdir(parents=True)
    records = [
        _record(
            "Bills/Power",
            summary="Electricity bill from Origin Energy",
            doc_type="Invoice",
        )
        for _ in range(3)
    ] + [
        _record(
            "Utilities/Electricity",
            summary="Electricity bill from Origin Energy",
            doc_type="Invoice",
        )
        for _ in range(3)
    ]
    history = _write_history(tmp_path, records)

    report = run_doctor(cfg, history_path=history, review_items=[])

    advisory = [f for f in report.findings if f.kind == KIND_NEAR_DUPLICATE]
    assert len(advisory) == 1
    assert advisory[0].action == ACTION_NONE
    assert advisory[0].detail["profile_similarity"] >= 0.75


def test_ghost_folders_flagged_quiet_and_never_filed(tmp_path: Path):
    cfg = _make_config(tmp_path)
    docs = cfg.documents_root
    (docs / "OldArchive").mkdir()
    (docs / "Recent").mkdir()
    (docs / "Active").mkdir()
    now = datetime(2026, 9, 12, tzinfo=UTC)
    records = [
        _record("Recent", timestamp=(now - timedelta(days=240)).isoformat()),
        _record("Active", timestamp=(now - timedelta(days=3)).isoformat()),
    ]
    history = _write_history(tmp_path, records)

    report = run_doctor(cfg, history_path=history, review_items=[], now=now)
    ghosts = {
        f.primary_folder: f for f in report.findings if f.kind == KIND_GHOST_FOLDER
    }

    assert set(ghosts) == {"OldArchive", "Recent"}
    assert ghosts["OldArchive"].action == ACTION_DELETE_EMPTY
    assert ghosts["Recent"].severity == SEVERITY_MEDIUM
    assert ghosts["OldArchive"].severity == SEVERITY_LOW


def test_parent_folder_is_active_when_descendant_filed(tmp_path: Path):
    cfg = _make_config(tmp_path)
    docs = cfg.documents_root
    (docs / "Finances" / "Banking").mkdir(parents=True)
    now = datetime(2026, 9, 12, tzinfo=UTC)
    history = _write_history(
        tmp_path, [_record("Finances/Banking", timestamp=now.isoformat())]
    )

    report = run_doctor(cfg, history_path=history, review_items=[], now=now)
    ghost_folders = {
        f.primary_folder for f in report.findings if f.kind == KIND_GHOST_FOLDER
    }
    assert "Finances" not in ghost_folders
    assert "Finances/Banking" not in ghost_folders


def test_overbroad_catch_all_folder_flagged(tmp_path: Path):
    cfg = _make_config(tmp_path)
    (cfg.documents_root / "Misc").mkdir()
    records = [
        _record("Misc", doc_type="Invoice"),
        _record("Misc", doc_type="Statement"),
        _record("Misc", doc_type="Receipt"),
        _record("Misc", doc_type="Letter"),
        _record("Misc", doc_type="Medical"),
    ]
    history = _write_history(tmp_path, records)

    report = run_doctor(cfg, history_path=history, review_items=[])
    overbroad = [f for f in report.findings if f.kind == KIND_OVERBROAD_FOLDER]
    assert len(overbroad) == 1
    assert overbroad[0].primary_folder == "Misc"
    assert overbroad[0].action == ACTION_NONE
    assert overbroad[0].detail["total_filings"] == 5


def test_overbroad_not_flagged_when_dominant_type(tmp_path: Path):
    cfg = _make_config(tmp_path)
    (cfg.documents_root / "Misc").mkdir()
    records = [
        _record("Misc", doc_type="Invoice"),
        _record("Misc", doc_type="Invoice"),
        _record("Misc", doc_type="Invoice"),
        _record("Misc", doc_type="Invoice"),
        _record("Misc", doc_type="Receipt"),
    ]
    history = _write_history(tmp_path, records)

    report = run_doctor(cfg, history_path=history, review_items=[])
    assert not [f for f in report.findings if f.kind == KIND_OVERBROAD_FOLDER]


def test_review_cluster_from_suggested_folder_proposes_creation(tmp_path: Path):
    cfg = _make_config(tmp_path)
    items = [
        _review_item(tmp_path, f"pet{i}.pdf", suggested="Finances/Insurance/Pet")
        for i in range(3)
    ]

    report = run_doctor(
        cfg, history_path=_write_history(tmp_path, []), review_items=items
    )
    clusters = [f for f in report.findings if f.kind == KIND_REVIEW_CLUSTER]

    assert len(clusters) == 1
    assert clusters[0].action == ACTION_CREATE_FOLDER
    assert clusters[0].target_folder == "Finances/Insurance/Pet"
    assert clusters[0].detail["review_count"] == 3


def test_review_cluster_from_unsuggested_summaries_derives_name(tmp_path: Path):
    cfg = _make_config(tmp_path)
    items = [
        _review_item(tmp_path, f"pet{i}.pdf", summary="Pet insurance premium renewal")
        for i in range(3)
    ]

    report = run_doctor(
        cfg, history_path=_write_history(tmp_path, []), review_items=items
    )
    clusters = [f for f in report.findings if f.kind == KIND_REVIEW_CLUSTER]

    assert len(clusters) == 1
    assert clusters[0].target_folder == "Pet_Insurance"
    assert clusters[0].keywords


def test_review_cluster_below_min_size_not_proposed(tmp_path: Path):
    cfg = _make_config(tmp_path)
    items = [
        _review_item(tmp_path, f"pet{i}.pdf", suggested="Finances/Insurance/Pet")
        for i in range(2)
    ]

    report = run_doctor(
        cfg, history_path=_write_history(tmp_path, []), review_items=items
    )
    assert not [f for f in report.findings if f.kind == KIND_REVIEW_CLUSTER]


def test_review_cluster_for_existing_folder_not_proposed(tmp_path: Path):
    cfg = _make_config(tmp_path)
    (cfg.documents_root / "Finances" / "Insurance" / "Pet").mkdir(parents=True)
    items = [
        _review_item(tmp_path, f"pet{i}.pdf", suggested="Finances/Insurance/Pet")
        for i in range(3)
    ]

    report = run_doctor(
        cfg, history_path=_write_history(tmp_path, []), review_items=items
    )
    assert not [f for f in report.findings if f.kind == KIND_REVIEW_CLUSTER]


def test_review_cluster_ignores_review_folder_subtree_suggestions(tmp_path: Path):
    cfg = _make_config(tmp_path)
    items = [
        _review_item(tmp_path, f"x{i}.pdf", suggested="_Review_Needed/Model_Invented")
        for i in range(3)
    ]

    report = run_doctor(
        cfg, history_path=_write_history(tmp_path, []), review_items=items
    )
    assert not [f for f in report.findings if f.kind == KIND_REVIEW_CLUSTER]


def test_review_cluster_respects_custom_fallback_folder_subtree(tmp_path: Path):
    cfg = _make_config(tmp_path, fallback_folder="_NeedsReview")
    items = [
        _review_item(tmp_path, f"y{i}.pdf", suggested="_NeedsReview/Model")
        for i in range(3)
    ]

    report = run_doctor(
        cfg, history_path=_write_history(tmp_path, []), review_items=items
    )
    assert not [f for f in report.findings if f.kind == KIND_REVIEW_CLUSTER]


def test_run_doctor_report_has_severity_counts_and_serializes(tmp_path: Path):
    cfg = _make_config(tmp_path)
    (cfg.documents_root / "Ghost").mkdir()
    (cfg.documents_root / "Misc").mkdir()
    records = [
        _record("Misc", doc_type=t)
        for t in ("Invoice", "Statement", "Receipt", "Letter", "Medical")
    ]
    history = _write_history(tmp_path, records)

    report = run_doctor(cfg, history_path=history, review_items=[])
    payload = report.as_dict()

    assert payload["history_record_count"] == len(records)
    # Ghost (never filed) and over-broad Misc both carry LOW severity.
    assert payload["counts_by_severity"] == {"HIGH": 0, "MEDIUM": 0, "LOW": 2}
    assert {f["kind"] for f in payload["findings"]} == {
        KIND_GHOST_FOLDER,
        KIND_OVERBROAD_FOLDER,
    }
    actionable = report.actionable
    assert [f.primary_folder for f in actionable] == ["Ghost"]


def test_is_within_review_folder_case_and_separator_insensitive():
    from scansort.classification.doctor import _is_within_review_folder

    assert _is_within_review_folder("_Review_Needed", "_Review_Needed")
    assert _is_within_review_folder("_review_needed\\Sub", "_Review_Needed")
    assert _is_within_review_folder("NeedsReview/Sub", "NeedsReview")
    # A distinct sibling name is not inside the review folder.
    assert not _is_within_review_folder("_Review_Needed2", "_Review_Needed")
    assert not _is_within_review_folder("Finances", "_Review_Needed")
    # An empty fallback still defaults to the canonical review folder.
    assert _is_within_review_folder("_Review_Needed/Sub", "")


def test_render_doctor_report_empty_and_actionable(tmp_path: Path):
    cfg = _make_config(tmp_path)
    clean = run_doctor(cfg, history_path=_write_history(tmp_path, []), review_items=[])
    assert "no folder-health issues" in render_doctor_report(clean)[0]
    assert clean.actionable == []

    finding = DoctorFinding(
        kind=KIND_NEAR_DUPLICATE,
        severity=SEVERITY_MEDIUM,
        message="dupe",
        action=ACTION_MERGE_INTO,
        primary_folder="Bills",
        target_folder="Bill",
    )
    from scansort.classification.doctor import DoctorReport

    lines = render_doctor_report(DoctorReport(folders=[], findings=[finding]))
    assert any("merge 'Bills' into 'Bill'" in line for line in lines)


def test_load_history_for_doctor_skips_malformed_and_missing(tmp_path: Path):
    missing = tmp_path / "nope.jsonl"
    assert load_history_for_doctor(missing) == []

    path = tmp_path / "history.jsonl"
    path.write_text(
        json.dumps({"status": "SUCCESS"}) + "\nnot-json\n\n",
        encoding="utf-8",
    )
    assert load_history_for_doctor(path) == [{"status": "SUCCESS"}]


@pytest.fixture
def doctor_app_dir(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    with patch(
        "scansort.classification.doctor.get_default_app_dir", return_value=app_dir
    ):
        yield app_dir


def test_apply_create_folder_and_hint(tmp_path: Path, doctor_app_dir: Path):
    cfg = _make_config(tmp_path)
    hints = tmp_path / "folder_hints.json"
    finding = DoctorFinding(
        kind=KIND_REVIEW_CLUSTER,
        severity=SEVERITY_MEDIUM,
        message="",
        action=ACTION_CREATE_FOLDER,
        target_folder="Finances/Insurance/Pet",
        keywords=["pet", "insurance"],
    )

    message = apply_doctor_action(finding, cfg, hints_path=hints)

    assert (cfg.documents_root / "Finances" / "Insurance" / "Pet").is_dir()
    assert "Created" in message
    assert json.loads(hints.read_text(encoding="utf-8")) == {
        "Finances/Insurance/Pet": ["pet", "insurance"]
    }


def test_apply_create_folder_idempotent(tmp_path: Path, doctor_app_dir: Path):
    cfg = _make_config(tmp_path)
    (cfg.documents_root / "Existing").mkdir()
    finding = DoctorFinding(
        kind=KIND_REVIEW_CLUSTER,
        severity=SEVERITY_MEDIUM,
        message="",
        action=ACTION_CREATE_FOLDER,
        target_folder="Existing",
    )
    assert "Created" in apply_doctor_action(finding, cfg)
    # A second run against the now-existing folder must also succeed.
    assert "Created" in apply_doctor_action(finding, cfg)
    assert (cfg.documents_root / "Existing").is_dir()


def test_apply_rejects_traversal_and_escaping_targets(
    tmp_path: Path, doctor_app_dir: Path
):
    cfg = _make_config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    for target in ("../outside", "C:/Windows", "/abs"):
        finding = DoctorFinding(
            kind=KIND_REVIEW_CLUSTER,
            severity=SEVERITY_MEDIUM,
            message="",
            action=ACTION_CREATE_FOLDER,
            target_folder=target,
        )
        with pytest.raises(ValueError):
            apply_doctor_action(finding, cfg)


def test_apply_rejects_symlinked_target(tmp_path: Path, doctor_app_dir: Path):
    cfg = _make_config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = cfg.documents_root / "link"
    link.symlink_to(outside, target_is_directory=True)

    finding = DoctorFinding(
        kind=KIND_REVIEW_CLUSTER,
        severity=SEVERITY_MEDIUM,
        message="",
        action=ACTION_CREATE_FOLDER,
        target_folder="link",
    )
    with pytest.raises(ValueError):
        apply_doctor_action(finding, cfg)


def test_apply_create_rejects_review_folder_subtree(
    tmp_path: Path, doctor_app_dir: Path
):
    cfg = _make_config(tmp_path)
    finding = DoctorFinding(
        kind=KIND_REVIEW_CLUSTER,
        severity=SEVERITY_MEDIUM,
        message="",
        action=ACTION_CREATE_FOLDER,
        target_folder="_Review_Needed/Model_Invented",
    )
    with pytest.raises(ValueError, match="inside the review folder"):
        apply_doctor_action(finding, cfg)
    assert not (cfg.documents_root / "_Review_Needed" / "Model_Invented").exists()


def test_apply_merge_moves_files_resolves_collisions_and_audits(
    tmp_path: Path, doctor_app_dir: Path
):
    cfg = _make_config(tmp_path)
    loser = cfg.documents_root / "Bills"
    winner = cfg.documents_root / "Bill"
    loser.mkdir()
    winner.mkdir()
    (loser / "a.pdf").write_bytes(b"a")
    (loser / "b.pdf").write_bytes(b"b")
    (winner / "a.pdf").write_bytes(b"existing")
    history = tmp_path / "history.jsonl"

    finding = DoctorFinding(
        kind=KIND_NEAR_DUPLICATE,
        severity=SEVERITY_MEDIUM,
        message="",
        action=ACTION_MERGE_INTO,
        primary_folder="Bills",
        target_folder="Bill",
    )
    message = apply_doctor_action(finding, cfg, history_path=history)

    assert "Merged 2 file(s)" in message
    assert not loser.exists()
    assert (winner / "a.pdf").read_bytes() == b"existing"
    assert (winner / "a_1.pdf").read_bytes() == b"a"
    assert (winner / "b.pdf").read_bytes() == b"b"
    statuses = [
        json.loads(line)["status"]
        for line in history.read_text(encoding="utf-8").splitlines()
    ]
    assert statuses == ["DOCTOR_MERGED", "DOCTOR_MERGED"]


def test_apply_merge_refuses_subfolders(tmp_path: Path, doctor_app_dir: Path):
    cfg = _make_config(tmp_path)
    loser = cfg.documents_root / "Bills"
    winner = cfg.documents_root / "Bill"
    (loser / "2026").mkdir(parents=True)
    winner.mkdir()
    finding = DoctorFinding(
        action=ACTION_MERGE_INTO,
        kind=KIND_NEAR_DUPLICATE,
        severity=SEVERITY_MEDIUM,
        message="",
        primary_folder="Bills",
        target_folder="Bill",
    )
    with pytest.raises(ValueError, match="non-file entries"):
        apply_doctor_action(finding, cfg)


def test_apply_merge_refuses_missing_source(tmp_path: Path, doctor_app_dir: Path):
    cfg = _make_config(tmp_path)
    (cfg.documents_root / "Bill").mkdir()
    finding = DoctorFinding(
        action=ACTION_MERGE_INTO,
        kind=KIND_NEAR_DUPLICATE,
        severity=SEVERITY_MEDIUM,
        message="",
        primary_folder="Bills",
        target_folder="Bill",
    )
    with pytest.raises(ValueError, match="no longer exists"):
        apply_doctor_action(finding, cfg)


def test_apply_delete_empty_removes_and_refuses_nonempty(
    tmp_path: Path, doctor_app_dir: Path
):
    cfg = _make_config(tmp_path)
    empty = cfg.documents_root / "Empty"
    full = cfg.documents_root / "Full"
    empty.mkdir()
    full.mkdir()
    (full / "keep.pdf").write_bytes(b"x")

    empty_finding = DoctorFinding(
        action=ACTION_DELETE_EMPTY,
        kind=KIND_GHOST_FOLDER,
        severity=SEVERITY_LOW,
        message="",
        primary_folder="Empty",
    )
    assert "Removed empty folder" in apply_doctor_action(empty_finding, cfg)
    assert not empty.exists()

    full_finding = DoctorFinding(
        action=ACTION_DELETE_EMPTY,
        kind=KIND_GHOST_FOLDER,
        severity=SEVERITY_LOW,
        message="",
        primary_folder="Full",
    )
    with pytest.raises(ValueError, match="not empty"):
        apply_doctor_action(full_finding, cfg)
    assert full.exists()

    missing_finding = DoctorFinding(
        action=ACTION_DELETE_EMPTY,
        kind=KIND_GHOST_FOLDER,
        severity=SEVERITY_LOW,
        message="",
        primary_folder="Gone",
    )
    assert "no longer exists" in apply_doctor_action(missing_finding, cfg)


def test_apply_advisory_and_unknown_actions_raise(tmp_path: Path, doctor_app_dir: Path):
    cfg = _make_config(tmp_path)
    advisory = DoctorFinding(
        action=ACTION_NONE,
        kind=KIND_OVERBROAD_FOLDER,
        severity=SEVERITY_LOW,
        message="",
    )
    with pytest.raises(ValueError, match="advisory"):
        apply_doctor_action(advisory, cfg)

    unknown = DoctorFinding(action="BOGUS", kind="X", severity=SEVERITY_LOW, message="")
    with pytest.raises(ValueError, match="Unsupported"):
        apply_doctor_action(unknown, cfg)


def test_run_doctor_discovers_review_queue_when_not_supplied(tmp_path: Path):
    cfg = _make_config(tmp_path)
    with patch(
        "scansort.pipeline.review.get_review_queue", return_value=[]
    ) as mock_queue:
        report = run_doctor(cfg, history_path=_write_history(tmp_path, []))
    mock_queue.assert_called_once()
    assert report.review_item_count == 0


def test_load_history_for_doctor_read_error_returns_empty(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    with patch("builtins.open", side_effect=OSError("locked")):
        assert load_history_for_doctor(path) == []


def test_tfidf_handles_empty_documents_and_cosine_swap():
    from scansort.classification.doctor import _TfidfIndex

    index = _TfidfIndex(["", "alpha beta gamma", "alpha delta"])
    assert index.similarity(0, 0) == 0.0
    assert index.similarity(0, 1) == 0.0
    assert index.similarity(1, 1) == pytest.approx(1.0)
    # Left vector longer than right exercises the swap branch.
    assert _TfidfIndex.cosine({"a": 1.0, "b": 1.0, "c": 1.0}, {"a": 1.0}) == 1.0


def test_name_similarity_empty_inputs():
    from scansort.classification.doctor import _name_similarity

    assert _name_similarity("", "Bills") == 0.0


def test_parse_timestamp_fallbacks():
    from scansort.classification.doctor import _parse_timestamp

    assert _parse_timestamp({"timestamp": "garbage"}) is None
    assert _parse_timestamp({}) is None
    assert _parse_timestamp({"local_time": "2026-09-01 10:00:00"}) == datetime(
        2026, 9, 1, 10, 0, 0, tzinfo=UTC
    )
    assert _parse_timestamp({"local_time": "garbage"}) is None


def test_pick_merge_target_prefers_folder_with_more_filings():
    from collections import Counter

    from scansort.classification.doctor import _pick_merge_target

    # "Bills" has more filings, so it wins and "Bill" is the folder to merge away.
    loser, winner = _pick_merge_target("Bill", "Bills", Counter({"Bills": 4}))
    assert winner == "Bills"
    assert loser == "Bill"


def test_render_doctor_report_action_lines():
    from scansort.classification.doctor import (
        ACTION_DELETE_EMPTY,
        DoctorReport,
    )

    findings = [
        DoctorFinding(
            kind=KIND_REVIEW_CLUSTER,
            severity=SEVERITY_MEDIUM,
            message="create",
            action=ACTION_CREATE_FOLDER,
            target_folder="Pet_Insurance",
        ),
        DoctorFinding(
            kind=KIND_GHOST_FOLDER,
            severity=SEVERITY_LOW,
            message="ghost",
            action=ACTION_DELETE_EMPTY,
            primary_folder="Old",
        ),
    ]
    lines = render_doctor_report(DoctorReport(folders=[], findings=findings))
    assert any("create folder 'Pet_Insurance'" in line for line in lines)
    assert any("remove 'Old' if empty" in line for line in lines)


def test_apply_create_rejects_dot_folder(tmp_path: Path, doctor_app_dir: Path):
    cfg = _make_config(tmp_path)
    finding = DoctorFinding(
        action=ACTION_CREATE_FOLDER,
        kind=KIND_REVIEW_CLUSTER,
        severity=SEVERITY_MEDIUM,
        message="",
        target_folder=".",
    )
    with pytest.raises(ValueError, match="not a safe relative folder"):
        apply_doctor_action(finding, cfg)


def test_apply_merge_rejects_identical_folders(tmp_path: Path, doctor_app_dir: Path):
    cfg = _make_config(tmp_path)
    finding = DoctorFinding(
        action=ACTION_MERGE_INTO,
        kind=KIND_NEAR_DUPLICATE,
        severity=SEVERITY_MEDIUM,
        message="",
        primary_folder="Bills",
        target_folder="Bills",
    )
    with pytest.raises(ValueError, match="two distinct"):
        apply_doctor_action(finding, cfg)


def test_apply_merge_refuses_non_file_entries(tmp_path: Path, doctor_app_dir: Path):
    cfg = _make_config(tmp_path)
    loser = cfg.documents_root / "Bills"
    winner = cfg.documents_root / "Bill"
    loser.mkdir()
    winner.mkdir()
    (loser / "broken").symlink_to(loser / "does-not-exist")

    finding = DoctorFinding(
        action=ACTION_MERGE_INTO,
        kind=KIND_NEAR_DUPLICATE,
        severity=SEVERITY_MEDIUM,
        message="",
        primary_folder="Bills",
        target_folder="Bill",
    )
    with pytest.raises(ValueError, match="non-file entries"):
        apply_doctor_action(finding, cfg)


def test_apply_merge_move_failure_cleans_partial_destination(
    tmp_path: Path, doctor_app_dir: Path
):
    cfg = _make_config(tmp_path)
    loser = cfg.documents_root / "Bills"
    winner = cfg.documents_root / "Bill"
    loser.mkdir()
    winner.mkdir()
    (loser / "a.pdf").write_bytes(b"a")

    finding = DoctorFinding(
        action=ACTION_MERGE_INTO,
        kind=KIND_NEAR_DUPLICATE,
        severity=SEVERITY_MEDIUM,
        message="",
        primary_folder="Bills",
        target_folder="Bill",
    )

    def _leave_partial_then_fail(_src, dst):
        Path(dst).write_bytes(b"partial")
        raise OSError("busy")

    with (
        patch(
            "scansort.classification.doctor.shutil.move",
            side_effect=_leave_partial_then_fail,
        ),
        pytest.raises(OSError, match="busy"),
    ):
        apply_doctor_action(finding, cfg)
    # The half-written destination is cleaned up and the source is retained.
    assert not (winner / "a.pdf").exists()
    assert (loser / "a.pdf").read_bytes() == b"a"


def test_apply_merge_partial_failure_audits_completed_moves(
    tmp_path: Path, doctor_app_dir: Path
):
    cfg = _make_config(tmp_path)
    loser = cfg.documents_root / "Bills"
    winner = cfg.documents_root / "Bill"
    loser.mkdir()
    winner.mkdir()
    (loser / "a.pdf").write_bytes(b"a")
    (loser / "b.pdf").write_bytes(b"b")
    history = tmp_path / "history.jsonl"

    finding = DoctorFinding(
        action=ACTION_MERGE_INTO,
        kind=KIND_NEAR_DUPLICATE,
        severity=SEVERITY_MEDIUM,
        message="",
        primary_folder="Bills",
        target_folder="Bill",
    )

    real_move = shutil.move
    calls = {"n": 0}

    def _fail_second(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("second failed")
        real_move(src, dst)

    with (
        patch("scansort.classification.doctor.shutil.move", side_effect=_fail_second),
        pytest.raises(OSError, match="second failed"),
    ):
        apply_doctor_action(finding, cfg, history_path=history)

    # The first move is durable and must be recorded even though the second failed.
    assert (winner / "a.pdf").read_bytes() == b"a"
    records = [
        json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()
    ]
    assert [r["status"] for r in records] == ["DOCTOR_MERGED"]
    assert records[0]["new_filename"] == "a.pdf"

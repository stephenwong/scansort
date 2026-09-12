"""Offline taxonomy-health analyzer and guarded mutation engine for the folder taxonomy.

The "Taxonomy Doctor" inspects the discovered folder taxonomy alongside the
filing audit history and the review queue, then reports actionable findings:
near-duplicate folders, ghost folders (no recent filings), over-broad catch-all
folders, and recurring review themes that warrant a new subfolder.

Analysis is strictly read-only. Every filesystem mutation flows through
:func:`apply_doctor_action`, which re-validates containment under the documents
root and holds the shared ``operations.lock`` so a proposal can never create,
merge, or delete a directory outside the managed taxonomy.

Similarity is computed locally with the standard library only (token TF-IDF
cosine for document summaries, ``difflib`` ratio for folder names); no document
content or API credentials ever leave the machine for analysis.
"""

import difflib
import json
import logging
import math
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scansort.classification.hints import add_folder_hint
from scansort.classification.models import sanitize_description
from scansort.classification.taxonomy import scan_documents_folders
from scansort.core.config import AppConfig, get_default_app_dir
from scansort.core.constants import (
    DOCTOR_CLUSTER_MIN_SIZE,
    DOCTOR_CLUSTER_SIMILARITY,
    DOCTOR_GHOST_MONTHS,
    DOCTOR_NEARDUP_NAME_THRESHOLD,
    DOCTOR_NEARDUP_PROFILE_MIN_DOCS,
    DOCTOR_NEARDUP_PROFILE_THRESHOLD,
    DOCTOR_OVERBROAD_MIN_DOCS,
    DOCTOR_OVERBROAD_TYPES,
    HISTORY_CSV_NAME,
    HISTORY_JSONL_NAME,
    OPERATIONS_LOCK_FILENAME,
    REVIEW_NEEDED_DIR,
    STATUS_COLLISION_RENAMED,
    STATUS_DOCTOR_MERGED,
    STATUS_REVIEWED,
    STATUS_SUCCESS,
)
from scansort.core.fs import (
    interprocess_file_lock,
    normalize_relative_folder,
    relative_folder_is_safe,
    resolve_collision,
)
from scansort.logging.audit import AuditLogger

logger = logging.getLogger(__name__)

__all__ = [
    "ACTION_CREATE_FOLDER",
    "ACTION_DELETE_EMPTY",
    "ACTION_MERGE_INTO",
    "ACTION_NONE",
    "DoctorFinding",
    "DoctorReport",
    "KIND_GHOST_FOLDER",
    "KIND_NEAR_DUPLICATE",
    "KIND_OVERBROAD_FOLDER",
    "KIND_REVIEW_CLUSTER",
    "SEVERITY_HIGH",
    "SEVERITY_LOW",
    "SEVERITY_MEDIUM",
    "apply_doctor_action",
    "load_history_for_doctor",
    "render_doctor_report",
    "run_doctor",
]

KIND_NEAR_DUPLICATE: str = "NEAR_DUPLICATE"
KIND_GHOST_FOLDER: str = "GHOST_FOLDER"
KIND_OVERBROAD_FOLDER: str = "OVERBROAD_FOLDER"
KIND_REVIEW_CLUSTER: str = "REVIEW_CLUSTER"

ACTION_NONE: str = "NONE"
ACTION_MERGE_INTO: str = "MERGE_INTO"
ACTION_CREATE_FOLDER: str = "CREATE_FOLDER"
ACTION_DELETE_EMPTY: str = "DELETE_EMPTY"

SEVERITY_HIGH: str = "HIGH"
SEVERITY_MEDIUM: str = "MEDIUM"
SEVERITY_LOW: str = "LOW"

_ACTIVE_FILING_STATUSES: frozenset[str] = frozenset(
    {STATUS_SUCCESS, STATUS_COLLISION_RENAMED, STATUS_REVIEWED}
)

_NEVER_FILED_AGE_DAYS: int = 30 * DOCTOR_GHOST_MONTHS

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "copy",
        "document",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "other",
        "page",
        "scan",
        "scanned",
        "the",
        "this",
        "to",
        "unknown",
        "with",
    }
)

_SEVERITY_ORDER: dict[str, int] = {
    SEVERITY_HIGH: 0,
    SEVERITY_MEDIUM: 1,
    SEVERITY_LOW: 2,
}


@dataclass
class DoctorFinding:
    """A single taxonomy-health observation, optionally carrying a safe action."""

    kind: str
    severity: str
    message: str
    action: str = ACTION_NONE
    primary_folder: str = ""
    target_folder: str = ""
    folders: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def finding_id(self) -> str:
        """Stable identifier used for UI selection and dismissal bookkeeping."""
        members = self.folders or [self.primary_folder]
        return f"{self.kind}:" + "|".join(members)


@dataclass
class DoctorReport:
    """Aggregate result of a Taxonomy Doctor analysis pass."""

    folders: list[str]
    findings: list[DoctorFinding]
    history_record_count: int = 0
    review_item_count: int = 0

    @property
    def actionable(self) -> list[DoctorFinding]:
        """Findings that can be applied automatically (non-advisory)."""
        return [f for f in self.findings if f.action != ACTION_NONE]

    def counts_by_severity(self) -> dict[str, int]:
        """Return finding counts keyed by severity."""
        counts = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 0, SEVERITY_LOW: 0}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        """Serialize the report for ``--json`` output."""
        return {
            "folders": list(self.folders),
            "history_record_count": self.history_record_count,
            "review_item_count": self.review_item_count,
            "counts_by_severity": self.counts_by_severity(),
            "findings": [
                {
                    "id": f.finding_id,
                    "kind": f.kind,
                    "severity": f.severity,
                    "message": f.message,
                    "action": f.action,
                    "primary_folder": f.primary_folder,
                    "target_folder": f.target_folder,
                    "folders": list(f.folders),
                    "keywords": list(f.keywords),
                    "detail": dict(f.detail),
                }
                for f in self.findings
            ],
        }


def load_history_for_doctor(history_path: Path | None = None) -> list[dict[str, Any]]:
    """Read ``history.jsonl`` records for analysis, skipping malformed lines.

    Analysis is a report, never a filing path, so an unreadable history file
    degrades to an empty list rather than raising.
    """
    path = history_path or (get_default_app_dir() / HISTORY_JSONL_NAME)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
    except (OSError, UnicodeError) as e:
        logger.warning("Could not read history for Taxonomy Doctor: %s", e)
        return []
    return records


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens with generic stopwords removed."""
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in _STOPWORDS
    ]


class _TfidfIndex:
    """Minimal token TF-IDF index with cosine similarity (standard library only)."""

    def __init__(self, documents: list[str]) -> None:
        tokenized = [_tokenize(doc) for doc in documents]
        document_count = len(tokenized)
        document_freq: Counter[str] = Counter()
        for tokens in tokenized:
            document_freq.update(set(tokens))
        self._idf = {
            token: math.log((1 + document_count) / (1 + freq)) + 1.0
            for token, freq in document_freq.items()
        }
        self._vectors = [self._build_vector(tokens) for tokens in tokenized]

    def _build_vector(self, tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        counts = Counter(tokens)
        vector = {
            token: (1.0 + math.log(count)) * self._idf.get(token, 1.0)
            for token, count in counts.items()
        }
        norm = math.sqrt(sum(weight * weight for weight in vector.values()))
        if norm == 0.0:
            return {}
        return {token: weight / norm for token, weight in vector.items()}

    def similarity(self, left: int, right: int) -> float:
        """Cosine similarity between two indexed documents (0.0 for empty text)."""
        return self.cosine(self._vectors[left], self._vectors[right])

    @staticmethod
    def cosine(left: dict[str, float], right: dict[str, float]) -> float:
        """Cosine similarity for pre-normalized sparse vectors."""
        if not left or not right:
            return 0.0
        if len(left) > len(right):
            left, right = right, left
        return sum(weight * right.get(token, 0.0) for token, weight in left.items())


def _normalize_name(folder: str) -> str:
    """Collapse a folder path to a space-separated lowercase token string."""
    return " ".join(re.findall(r"[a-z0-9]+", folder.lower()))


def _name_similarity(left: str, right: str) -> float:
    """Fuzzy similarity between two folder paths via ``difflib`` ratio."""
    norm_left, norm_right = _normalize_name(left), _normalize_name(right)
    if not norm_left or not norm_right:
        return 0.0
    return difflib.SequenceMatcher(None, norm_left, norm_right).ratio()


def _record_folder(record: dict[str, Any]) -> str:
    """Return the normalized destination folder recorded in an audit entry."""
    return normalize_relative_folder(str(record.get("destination_folder") or ""))


def _is_within_review_folder(folder: str, fallback_folder: str) -> bool:
    """Return True when *folder* is the review folder or one of its descendants.

    Invariant G: only the exact review-folder literal bypasses the taxonomy
    membership gate; a descendant like ``_Review_Needed/Sub`` must never be
    treated as a proposal-eligible new folder.
    """
    fallback_norm = (
        normalize_relative_folder(fallback_folder).lower() or REVIEW_NEEDED_DIR.lower()
    )
    candidate = normalize_relative_folder(folder).lower()
    return candidate == fallback_norm or candidate.startswith(fallback_norm + "/")


def _parse_timestamp(record: dict[str, Any]) -> datetime | None:
    """Parse an audit record timestamp into an aware UTC datetime, or None."""
    raw = str(record.get("timestamp") or "").strip()
    parsed: datetime | None = None
    if raw:
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            parsed = None
    if parsed is None:
        local = str(record.get("local_time") or "").strip()
        if local:
            try:
                # local_time is a Sydney wall-clock string; only its age matters
                # here, and it is normalized to an aware UTC datetime below.
                parsed = datetime.strptime(  # noqa: DTZ007
                    local, "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _active_filing_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filing records that count as a document actually landing in a folder."""
    return [
        record
        for record in records
        if str(record.get("status") or "").upper() in _ACTIVE_FILING_STATUSES
        and _record_folder(record)
    ]


def _folder_profiles(
    records: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Map each destination folder to the summaries of documents filed directly in it."""
    profiles: dict[str, list[str]] = defaultdict(list)
    for record in _active_filing_records(records):
        summary = str(record.get("summary") or "").strip()
        document_type = str(record.get("document_type") or "").strip()
        text = " ".join(part for part in (summary, document_type) if part)
        if text:
            profiles[_record_folder(record)].append(text)
    return profiles


def _pick_merge_target(
    left: str,
    right: str,
    filing_counts: Counter[str],
) -> tuple[str, str]:
    """Choose (loser, winner) for a near-duplicate pair deterministically.

    The folder with more direct filings wins; ties prefer the shallower path,
    then the lexicographically smaller path so results are stable across runs.
    """
    left_rank = (
        filing_counts.get(left, 0),
        -left.count("/"),
        left,
    )
    right_rank = (
        filing_counts.get(right, 0),
        -right.count("/"),
        right,
    )
    if left_rank >= right_rank:
        return right, left
    return left, right


def _detect_near_duplicates(
    folders: list[str],
    records: list[dict[str, Any]],
    filing_counts: Counter[str],
) -> list[DoctorFinding]:
    """Flag folders with near-identical names (mergeable) or nearly identical content (advisory)."""
    profiles = _folder_profiles(records)
    profile_docs = [" ".join(profiles.get(folder, [])) for folder in folders]
    index = _TfidfIndex(profile_docs)

    findings: list[DoctorFinding] = []
    for i in range(len(folders)):
        for j in range(i + 1, len(folders)):
            left, right = folders[i], folders[j]
            name_similarity = _name_similarity(left, right)
            profile_similarity = 0.0
            if (
                len(profiles.get(left, [])) >= DOCTOR_NEARDUP_PROFILE_MIN_DOCS
                and len(profiles.get(right, [])) >= DOCTOR_NEARDUP_PROFILE_MIN_DOCS
            ):
                profile_similarity = index.similarity(i, j)

            detail = {
                "name_similarity": round(name_similarity, 3),
                "profile_similarity": round(profile_similarity, 3),
            }
            if name_similarity >= DOCTOR_NEARDUP_NAME_THRESHOLD:
                loser, winner = _pick_merge_target(left, right, filing_counts)
                findings.append(
                    DoctorFinding(
                        kind=KIND_NEAR_DUPLICATE,
                        severity=(
                            SEVERITY_HIGH
                            if name_similarity >= 0.95
                            else SEVERITY_MEDIUM
                        ),
                        message=(
                            f"Near-duplicate folders '{left}' and '{right}' "
                            f"(name similarity {name_similarity:.0%})"
                        ),
                        action=ACTION_MERGE_INTO,
                        primary_folder=loser,
                        target_folder=winner,
                        folders=sorted([left, right]),
                        detail=detail,
                    )
                )
            elif profile_similarity >= DOCTOR_NEARDUP_PROFILE_THRESHOLD:
                findings.append(
                    DoctorFinding(
                        kind=KIND_NEAR_DUPLICATE,
                        severity=SEVERITY_LOW,
                        message=(
                            f"Folders '{left}' and '{right}' receive similar documents "
                            f"(content similarity {profile_similarity:.0%}); review manually"
                        ),
                        action=ACTION_NONE,
                        folders=sorted([left, right]),
                        detail=detail,
                    )
                )
    return findings


def _detect_ghost_folders(
    folders: list[str],
    records: list[dict[str, Any]],
    now: datetime,
) -> list[DoctorFinding]:
    """Flag folders that received no filing (direct or descendant) within the window."""
    latest_by_folder: dict[str, datetime] = {}
    for record in _active_filing_records(records):
        timestamp = _parse_timestamp(record)
        if timestamp is None:
            continue
        destination = _record_folder(record)
        for folder in folders:
            if destination == folder or destination.startswith(folder + "/"):
                current = latest_by_folder.get(folder)
                if current is None or timestamp > current:
                    latest_by_folder[folder] = timestamp

    cutoff = now - timedelta(days=_NEVER_FILED_AGE_DAYS)
    findings: list[DoctorFinding] = []
    for folder in folders:
        latest = latest_by_folder.get(folder)
        if latest is None:
            findings.append(
                DoctorFinding(
                    kind=KIND_GHOST_FOLDER,
                    severity=SEVERITY_LOW,
                    message=(
                        f"Ghost folder '{folder}': no filings on record "
                        f"({DOCTOR_GHOST_MONTHS}+ months)"
                    ),
                    action=ACTION_DELETE_EMPTY,
                    primary_folder=folder,
                    folders=[folder],
                )
            )
        elif latest < cutoff:
            age_days = (now - latest).days
            findings.append(
                DoctorFinding(
                    kind=KIND_GHOST_FOLDER,
                    severity=SEVERITY_MEDIUM,
                    message=(
                        f"Ghost folder '{folder}': no filings in "
                        f"{age_days // 30} months"
                    ),
                    action=ACTION_DELETE_EMPTY,
                    primary_folder=folder,
                    folders=[folder],
                    detail={"last_filing": latest.isoformat()},
                )
            )
    return findings


def _detect_overbroad_folders(
    folders: list[str],
    records: list[dict[str, Any]],
) -> list[DoctorFinding]:
    """Flag folders receiving many heterogeneous document types (catch-alls)."""
    folder_types: dict[str, Counter[str]] = defaultdict(Counter)
    valid = set(folders)
    for record in _active_filing_records(records):
        folder = _record_folder(record)
        if folder not in valid:
            continue
        document_type = str(record.get("document_type") or "").strip()
        if document_type:
            folder_types[folder][document_type] += 1

    findings: list[DoctorFinding] = []
    for folder in folders:
        counts = folder_types.get(folder)
        if counts is None:
            continue
        total = sum(counts.values())
        if total < DOCTOR_OVERBROAD_MIN_DOCS or len(counts) < DOCTOR_OVERBROAD_TYPES:
            continue
        dominant_share = counts.most_common(1)[0][1] / total
        if dominant_share > 0.5:
            continue
        findings.append(
            DoctorFinding(
                kind=KIND_OVERBROAD_FOLDER,
                severity=SEVERITY_LOW,
                message=(
                    f"Over-broad folder '{folder}': {len(counts)} document types "
                    f"across {total} filings"
                ),
                action=ACTION_NONE,
                primary_folder=folder,
                folders=[folder],
                detail={
                    "document_types": dict(counts.most_common()),
                    "total_filings": total,
                },
            )
        )
    return findings


def _cluster_similar_texts(texts: list[str], threshold: float) -> list[list[int]]:
    """Greedy single-link clustering over TF-IDF cosine similarity."""
    index = _TfidfIndex(texts)
    clusters: list[list[int]] = []
    for i in range(len(texts)):
        if index.similarity(i, i) == 0.0:
            continue
        for cluster in clusters:
            if index.similarity(i, cluster[0]) >= threshold:
                cluster.append(i)
                break
        else:
            clusters.append([i])
    return clusters


def _derive_cluster_folder_name(items: list[Any]) -> tuple[str, list[str]]:
    """Derive a Title_Case folder name and keyword hints from clustered review items."""
    token_counts: Counter[str] = Counter()
    for item in items:
        token_counts.update(
            _tokenize(
                f"{getattr(item, 'summary', '')} {getattr(item, 'document_type', '')}"
            )
        )
    ranked = [token for token, _ in token_counts.most_common(5)]
    if not ranked:
        return "", []
    name = sanitize_description(" ".join(ranked[:2]))
    return name, ranked


def _detect_review_clusters(
    review_items: list[Any],
    existing_folders: set[str],
    fallback_folder: str = REVIEW_NEEDED_DIR,
) -> list[DoctorFinding]:
    """Propose new folders when a review theme recurs (never auto-created here)."""
    suggested_groups: dict[str, list[Any]] = defaultdict(list)
    unsuggested: list[Any] = []
    existing_lower = {folder.lower() for folder in existing_folders}
    for item in review_items:
        raw_suggestion = str(getattr(item, "suggested_folder", "") or "").strip()
        suggestion = normalize_relative_folder(raw_suggestion)
        if (
            raw_suggestion
            and relative_folder_is_safe(raw_suggestion)
            and suggestion
            and not _is_within_review_folder(suggestion, fallback_folder)
            and suggestion.lower() not in existing_lower
        ):
            suggested_groups[suggestion].append(item)
        else:
            unsuggested.append(item)

    findings: list[DoctorFinding] = []
    for suggestion, items in suggested_groups.items():
        if len(items) < DOCTOR_CLUSTER_MIN_SIZE:
            continue
        keywords = _derive_cluster_folder_name(items)[1]
        findings.append(
            DoctorFinding(
                kind=KIND_REVIEW_CLUSTER,
                severity=SEVERITY_MEDIUM,
                message=(
                    f"Recurring review theme: {len(items)} items suggest "
                    f"creating '{suggestion}'"
                ),
                action=ACTION_CREATE_FOLDER,
                target_folder=suggestion,
                folders=[suggestion],
                keywords=keywords,
                detail={"review_count": len(items)},
            )
        )

    if len(unsuggested) >= DOCTOR_CLUSTER_MIN_SIZE:
        texts = [
            f"{getattr(item, 'summary', '')} {getattr(item, 'document_type', '')}"
            for item in unsuggested
        ]
        for cluster in _cluster_similar_texts(texts, DOCTOR_CLUSTER_SIMILARITY):
            if len(cluster) < DOCTOR_CLUSTER_MIN_SIZE:
                continue
            items = [unsuggested[i] for i in cluster]
            name, keywords = _derive_cluster_folder_name(items)
            if not name or not relative_folder_is_safe(name):
                continue
            if name.lower() in existing_lower:
                continue
            findings.append(
                DoctorFinding(
                    kind=KIND_REVIEW_CLUSTER,
                    severity=SEVERITY_MEDIUM,
                    message=(
                        f"Recurring review theme: {len(items)} similar items suggest "
                        f"creating '{name}'"
                    ),
                    action=ACTION_CREATE_FOLDER,
                    target_folder=name,
                    folders=[name],
                    keywords=keywords,
                    detail={"review_count": len(items)},
                )
            )
    return findings


def run_doctor(
    cfg: AppConfig,
    *,
    history_path: Path | None = None,
    review_items: list[Any] | None = None,
    now: datetime | None = None,
) -> DoctorReport:
    """Analyze the taxonomy, filing history, and review queue for folder-health issues.

    Args:
        cfg: Active application configuration supplying the documents root.
        history_path: Optional override for ``history.jsonl``.
        review_items: Optional pre-fetched review queue (else discovered on demand).
        now: Optional reference time for ghost-age calculations (tests).

    Returns:
        A read-only :class:`DoctorReport`; nothing is created, moved, or deleted.
    """
    folders = scan_documents_folders(
        docs_root=cfg.documents_root,
        max_depth=cfg.max_folder_depth,
        fallback_folder=cfg.fallback_folder,
    )
    records = load_history_for_doctor(history_path)
    if review_items is None:
        from scansort.pipeline.review import get_review_queue

        review_items = get_review_queue(
            cfg.documents_root, cfg.fallback_folder, history_path
        )
    reference_now = now or datetime.now(UTC)
    valid_folders = set(folders)

    filing_counts: Counter[str] = Counter()
    for record in _active_filing_records(records):
        folder = _record_folder(record)
        if folder in valid_folders:
            filing_counts[folder] += 1

    findings: list[DoctorFinding] = []
    findings.extend(_detect_ghost_folders(folders, records, reference_now))
    findings.extend(_detect_near_duplicates(folders, records, filing_counts))
    findings.extend(_detect_overbroad_folders(folders, records))
    findings.extend(
        _detect_review_clusters(review_items, valid_folders, cfg.fallback_folder)
    )

    findings.sort(
        key=lambda f: (_SEVERITY_ORDER.get(f.severity, 99), f.kind, f.finding_id)
    )
    return DoctorReport(
        folders=folders,
        findings=findings,
        history_record_count=len(records),
        review_item_count=len(review_items),
    )


def render_doctor_report(report: DoctorReport) -> list[str]:
    """Render a report as human-readable lines for CLI output."""
    if not report.findings:
        return ["Taxonomy Doctor: no folder-health issues detected."]

    counts = report.counts_by_severity()
    lines = [
        "Taxonomy Doctor findings: "
        f"{counts[SEVERITY_HIGH]} high, {counts[SEVERITY_MEDIUM]} medium, "
        f"{counts[SEVERITY_LOW]} low"
    ]
    for finding in report.findings:
        lines.append(f"  [{finding.severity}] {finding.message}")
        if finding.action == ACTION_MERGE_INTO:
            lines.append(
                f"      -> merge '{finding.primary_folder}' into "
                f"'{finding.target_folder}'"
            )
        elif finding.action == ACTION_CREATE_FOLDER:
            lines.append(f"      -> create folder '{finding.target_folder}'")
        elif finding.action == ACTION_DELETE_EMPTY:
            lines.append(f"      -> remove '{finding.primary_folder}' if empty")
    return lines


def _validate_taxonomy_folder(folder: str, docs_root: Path, label: str) -> Path:
    """Resolve a doctor target under the documents root or raise ``ValueError``.

    Unlike the filing dispatcher, a doctor action must never silently redirect
    to ``_Review_Needed``; an unsafe or out-of-root target is a hard error.
    """
    if not relative_folder_is_safe(folder):
        raise ValueError(f"{label} '{folder}' is not a safe relative folder")
    clean = normalize_relative_folder(folder)
    if not clean:
        raise ValueError(f"{label} '{folder}' is not a safe relative folder")
    resolved_root = docs_root.resolve()
    candidate = (docs_root / clean).resolve()
    if candidate == resolved_root or not candidate.is_relative_to(resolved_root):
        raise ValueError(f"{label} '{folder}' escapes the documents root")
    return candidate


def _audit_merge_move(
    *,
    source: Path,
    destination: Path,
    winner: str,
    loser: str,
    history_path: Path | None,
    cfg: AppConfig,
) -> None:
    """Write a DOCTOR_MERGED audit record for one moved document."""
    jsonl_path = history_path or (get_default_app_dir() / HISTORY_JSONL_NAME)
    csv_path = jsonl_path.with_name(HISTORY_CSV_NAME)
    audit = AuditLogger(
        jsonl_path=jsonl_path,
        csv_path=csv_path,
        mirror_csv_path=cfg.mirror_csv_path,
    )
    audit.log_scan(
        {
            "sha256": "UNKNOWN",
            "original_filename": source.name,
            "original_path": str(source),
            "new_filename": destination.name,
            "destination_folder": winner,
            "destination_path": str(destination),
            "summary": f"Taxonomy Doctor merged from '{loser}'",
            "status": STATUS_DOCTOR_MERGED,
        }
    )


def apply_doctor_action(
    finding: DoctorFinding,
    cfg: AppConfig,
    *,
    history_path: Path | None = None,
    hints_path: Path | None = None,
) -> str:
    """Execute the safe mutation for a finding under the shared operations lock.

    Returns a human-readable result message.

    Raises:
        ValueError: If the finding is advisory, malformed, or targets a path
            outside the documents root, or if a merge/delete precondition fails.
        OSError: If the underlying filesystem operation fails.
    """
    if finding.action == ACTION_NONE:
        raise ValueError("This finding is advisory and has no automated action")

    docs_root = cfg.documents_root
    lock_path = get_default_app_dir() / OPERATIONS_LOCK_FILENAME

    if finding.action == ACTION_CREATE_FOLDER:
        target = finding.target_folder
        if _is_within_review_folder(target, cfg.fallback_folder):
            raise ValueError(
                f"Proposed folder '{target}' is inside the review folder; refusing to create it"
            )
        target_dir = _validate_taxonomy_folder(target, docs_root, "Proposed folder")
        with interprocess_file_lock(lock_path):
            target_dir.mkdir(parents=True, exist_ok=True)
        if finding.keywords:
            add_folder_hint(target, finding.keywords, hints_path)
        return f"Created destination folder '{target}'"

    if finding.action == ACTION_MERGE_INTO:
        loser = finding.primary_folder
        winner = finding.target_folder
        if not loser or not winner or loser == winner:
            raise ValueError("Merge requires two distinct source and target folders")
        loser_dir = _validate_taxonomy_folder(loser, docs_root, "Source folder")
        winner_dir = _validate_taxonomy_folder(winner, docs_root, "Target folder")
        moved_count = 0
        with interprocess_file_lock(lock_path):
            if not loser_dir.is_dir():
                raise ValueError(f"Source folder '{loser}' no longer exists")
            entries = sorted(loser_dir.iterdir(), key=lambda p: p.name)
            if any(not entry.is_file() for entry in entries):
                raise ValueError(
                    f"Folder '{loser}' contains non-file entries; merge them manually first"
                )
            winner_dir.mkdir(parents=True, exist_ok=True)
            for entry in entries:
                destination = resolve_collision(winner_dir, entry.name)
                try:
                    shutil.move(str(entry), str(destination))
                except OSError:
                    destination.unlink(missing_ok=True)
                    raise
                moved_count += 1
                # Audit under the lock, immediately per file, so a later move
                # failure cannot drop the record of a file already relocated.
                _audit_merge_move(
                    source=entry,
                    destination=destination,
                    winner=winner,
                    loser=loser,
                    history_path=history_path,
                    cfg=cfg,
                )
            loser_dir.rmdir()
        return f"Merged {moved_count} file(s) from '{loser}' into '{winner}'"

    if finding.action == ACTION_DELETE_EMPTY:
        folder = finding.primary_folder
        folder_dir = _validate_taxonomy_folder(folder, docs_root, "Ghost folder")
        with interprocess_file_lock(lock_path):
            if not folder_dir.exists():
                return f"Folder '{folder}' no longer exists"
            if not folder_dir.is_dir() or any(folder_dir.iterdir()):
                raise ValueError(
                    f"Folder '{folder}' is not empty; refusing to remove it"
                )
            folder_dir.rmdir()
        return f"Removed empty folder '{folder}'"

    raise ValueError(f"Unsupported doctor action '{finding.action}'")

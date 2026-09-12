"""Interactive review and self-learning queue management for unfiled scans."""

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scansort.classification.hints import add_folder_hint, get_default_hints_path
from scansort.classification.models import sanitize_date, sanitize_description
from scansort.core.config import AppConfig, get_default_app_dir
from scansort.core.constants import (
    HISTORY_CSV_NAME,
    HISTORY_JSONL_NAME,
    REVIEW_NEEDED_DIR,
    SUPPORTED_EXTENSIONS,
)
from scansort.core.fs import (
    interprocess_file_lock,
    normalize_relative_folder,
    relative_folder_is_safe,
)
from scansort.document.converter import convert_to_pdf
from scansort.document.metadata import process_pdf_metadata_and_rotation
from scansort.logging.audit import AuditLogger
from scansort.pipeline.dispatcher import (
    OPERATIONS_LOCK_FILENAME,
    resolve_collision,
    resolve_destination_dir,
    resolve_duplicates_dir,
)
from scansort.pipeline.hasher import compute_file_sha256

logger = logging.getLogger(__name__)

_SUGGESTED_FOLDER_REGEX = re.compile(r"suggested ['\"]([^'\"]+)['\"]", re.IGNORECASE)
_FILENAME_DATE_REGEX = re.compile(r"^(\d{6})_(.+)$")


@dataclass
class ReviewItem:
    """Document queued in review needed folder with classification context."""

    file_path: Path
    filename: str
    file_size_bytes: int
    modified_time: float
    sha256: str = ""
    summary: str = ""
    document_type: str = "Other"
    confidence: float = 0.0
    suggested_folder: str = ""
    folder_reasoning: str = ""
    routing_rationale: str = ""
    document_date: str = ""
    description: str = ""
    status: str = "UNKNOWN"


def _extract_suggested_from_rationale(rationale: str) -> str:
    """Extract suggested folder path from a routing rationale string if present."""
    if not rationale:
        return ""
    m = _SUGGESTED_FOLDER_REGEX.search(rationale)
    if m:
        candidate = m.group(1).strip()
        if relative_folder_is_safe(candidate):
            return normalize_relative_folder(candidate)
    return ""


def _extract_date_and_desc(filename: str) -> tuple[str, str]:
    """Extract (YYMMDD, Description) from filename, or defaults if not formatted."""
    stem = Path(filename).stem
    m = _FILENAME_DATE_REGEX.match(stem)
    if m:
        date_part = sanitize_date(m.group(1))
        desc_part = sanitize_description(m.group(2))
        return date_part, desc_part
    return sanitize_date(None), sanitize_description(stem)


def _load_history_index(
    history_path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Build destination-path and new-filename lookup maps from ``history.jsonl``.

    Malformed lines are skipped; an unreadable file degrades to empty maps.
    """
    path_map: dict[str, dict[str, Any]] = {}
    name_map: dict[str, dict[str, Any]] = {}
    if not history_path.exists():
        return path_map, name_map
    try:
        with open(history_path, encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    rec = json.loads(line_str)
                    if isinstance(rec, dict):
                        dest_p = rec.get("destination_path")
                        if dest_p:
                            try:
                                resolved = str(Path(dest_p).resolve())
                                path_map[resolved] = rec
                            except OSError, ValueError:
                                pass
                        new_fn = rec.get("new_filename")
                        if new_fn:
                            name_map[new_fn] = rec
                except json.JSONDecodeError:
                    continue
    except (OSError, UnicodeError) as e:
        logger.warning("Could not read history for review correlation: %s", e)
    return path_map, name_map


def get_review_queue(
    docs_root: Path,
    fallback_folder: str = REVIEW_NEEDED_DIR,
    history_path: Path | None = None,
) -> list[ReviewItem]:
    """Discover all unreviewed scans and correlate them with audit history context.

    Args:
        docs_root: Root Documents directory path.
        fallback_folder: Relative folder name for review items.
        history_path: Optional path to history.jsonl.

    Returns:
        List of ReviewItem objects sorted by modification time descending.
    """
    review_dir = docs_root / fallback_folder
    if not review_dir.exists() or not review_dir.is_dir():
        return []

    # Build history lookup index
    h_path = history_path or (get_default_app_dir() / HISTORY_JSONL_NAME)
    path_map, name_map = _load_history_index(h_path)

    items: list[ReviewItem] = []
    dup_dir = resolve_duplicates_dir(docs_root, fallback_folder)
    try:
        candidate_files = [
            p
            for p in review_dir.rglob("*")
            if p.is_file()
            and p.suffix.lower() in SUPPORTED_EXTENSIONS
            and not p.is_relative_to(dup_dir)
        ]
    except OSError as e:
        logger.error("Failed to scan review folder %s: %s", review_dir, e)
        return []

    for file_path in candidate_files:
        try:
            stat = file_path.stat()
            size = stat.st_size
            mtime = stat.st_mtime
        except OSError:
            continue

        resolved_path_str = str(file_path.resolve())
        rec = path_map.get(resolved_path_str) or name_map.get(file_path.name) or {}

        summary = str(rec.get("summary", "") or "").strip()
        doc_type = str(rec.get("document_type", "Other") or "Other")
        try:
            confidence = float(rec.get("confidence", 0.0) or 0.0)
        except TypeError, ValueError:
            confidence = 0.0

        suggested = str(rec.get("suggested_folder", "") or "").strip()
        rationale = str(rec.get("routing_rationale", "") or "").strip()
        if not suggested and rationale:
            suggested = _extract_suggested_from_rationale(rationale)

        reasoning = str(rec.get("folder_reasoning", "") or "").strip()
        sha256 = str(rec.get("sha256", "") or "")
        status = str(rec.get("status", "UNKNOWN") or "UNKNOWN")

        date_val, desc_val = _extract_date_and_desc(file_path.name)

        items.append(
            ReviewItem(
                file_path=file_path,
                filename=file_path.name,
                file_size_bytes=size,
                modified_time=mtime,
                sha256=sha256,
                summary=summary,
                document_type=doc_type,
                confidence=confidence,
                suggested_folder=suggested,
                folder_reasoning=reasoning,
                routing_rationale=rationale,
                document_date=date_val,
                description=desc_val,
                status=status,
            )
        )

    # Sort newest first
    items.sort(key=lambda i: i.modified_time, reverse=True)
    return items


def _build_review_audit_entry(
    item: ReviewItem,
    *,
    status: str,
    sha256: str,
    new_filename: str,
    destination_folder: str,
    destination_path: str,
) -> dict[str, Any]:
    """Build the audit entry for a review-folder filing or dismissal."""
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "sha256": sha256,
        "original_filename": item.filename,
        "original_path": str(item.file_path),
        "new_filename": new_filename,
        "destination_folder": destination_folder,
        "destination_path": destination_path,
        "summary": item.summary,
        "document_type": item.document_type,
        "status": status,
    }


def _convert_review_source_to_pdf(item: ReviewItem) -> tuple[Path, Path | None]:
    """Return ``(filing_source, converted_pdf)`` for a review item.

    Image originals are normalized to a temp-dir PDF (invariant B); on
    conversion failure the original path is returned unchanged.
    """
    source_path = item.file_path
    if source_path.suffix.lower() == ".pdf":
        return source_path, None
    try:
        tmp_dir = get_default_app_dir() / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        converted_pdf = convert_to_pdf(
            source_path,
            output_path=tmp_dir / f"{source_path.stem}_{os.getpid()}.pdf",
        )
        return converted_pdf, converted_pdf
    except Exception as conv_err:  # noqa: BLE001 - best-effort conversion
        logger.warning(
            "Could not convert %s to PDF for review filing: %s",
            item.file_path.name,
            conv_err,
        )
        return source_path, None


def file_reviewed_item(
    item: ReviewItem,
    target_folder: str,
    document_date: str,
    description: str,
    config: AppConfig,
    keyword_hint: str | None = None,
    hints_path: Path | None = None,
    history_jsonl: Path | None = None,
    history_csv: Path | None = None,
    lock_path: Path | None = None,
) -> Path:
    """Manually file an item from the review queue into a target taxonomy folder.

    Args:
        item: ReviewItem to dispatch.
        target_folder: Destination relative folder (e.g. 'Health/Dental').
        document_date: Validated YYMMDD document date string.
        description: Sanitized description in Title_Case_With_Underscores.
        config: Application configuration.
        keyword_hint: Optional keyword string to save for self-learning hints.
        hints_path: Optional custom path to folder_hints.json.
        history_jsonl: Optional custom path to history.jsonl.
        history_csv: Optional custom path to history.csv.
        lock_path: Optional custom path to operations.lock.

    Returns:
        Final destination Path of the filed document.

    Raises:
        ValueError: If target_folder violates safety checks or source file is missing.
    """
    clean_target = str(target_folder).strip()
    if not relative_folder_is_safe(clean_target):
        raise ValueError(f"Unsafe destination folder: '{clean_target}'")

    normalized_folder = normalize_relative_folder(clean_target)
    dest_dir = resolve_destination_dir(config.documents_root, normalized_folder)
    if not dest_dir.resolve().is_relative_to(config.documents_root.resolve()):
        raise ValueError(
            f"Destination '{dest_dir}' escapes documents root '{config.documents_root}'"
        )

    clean_date = sanitize_date(document_date)
    clean_desc = sanitize_description(description)

    op_lock = lock_path or (get_default_app_dir() / OPERATIONS_LOCK_FILENAME)

    # Invariant B: reviewed image originals are normalized to PDF (with XMP)
    # before filing; conversion failures fall back to the original extension.
    source_path, converted_pdf = _convert_review_source_to_pdf(item)

    suffix = source_path.suffix.lower() or ".pdf"
    desired_name = f"{clean_date}_{clean_desc}{suffix}"

    with interprocess_file_lock(op_lock):
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = resolve_collision(dest_dir, desired_name)

        if not source_path.exists():
            raise FileNotFoundError(f"Source file {item.file_path} no longer exists")

        # Update PDF metadata in-place before moving if PDF
        if source_path.suffix.lower() == ".pdf":
            try:
                process_pdf_metadata_and_rotation(
                    pdf_path=source_path,
                    output_path=source_path,
                    title=clean_desc,
                    subject=item.summary,
                    keywords=[item.document_type, normalized_folder],
                )
            except (OSError, ValueError) as e:
                logger.warning("Could not update metadata during review filing: %s", e)

        # Compute SHA-256 from the original scan identity before any rewrite;
        # FAILED records carry the "UNKNOWN" sentinel, which is not a digest.
        file_hash = (
            item.sha256
            if item.sha256 and item.sha256 != "UNKNOWN"
            else compute_file_sha256(item.file_path)
        )

        # Move file atomically to destination
        try:
            shutil.move(str(source_path), str(dest_path))
        except OSError:
            dest_path.unlink(missing_ok=True)
            raise

        # Log audit entry
        app_dir = get_default_app_dir()
        audit_logger = AuditLogger(
            jsonl_path=history_jsonl or (app_dir / HISTORY_JSONL_NAME),
            csv_path=history_csv or (app_dir / HISTORY_CSV_NAME),
            mirror_csv_path=config.mirror_csv_path,
        )

        audit_logger.log_scan(
            _build_review_audit_entry(
                item,
                status="REVIEWED",
                sha256=file_hash,
                new_filename=dest_path.name,
                destination_folder=normalized_folder,
                destination_path=str(dest_path),
            )
        )

        # Save keyword hint if requested (best-effort: a hint failure must not
        # misreport an already-completed filing as failed).
        if keyword_hint and str(keyword_hint).strip():
            h_path = hints_path or get_default_hints_path()
            try:
                add_folder_hint(
                    normalized_folder, keyword_hint.strip(), hints_path=h_path
                )
                logger.info(
                    "Added keyword hint '%s' for folder '%s'",
                    keyword_hint.strip(),
                    normalized_folder,
                )
            except OSError as e:
                logger.warning(
                    "Could not save keyword hint for %s: %s", normalized_folder, e
                )

    if converted_pdf is not None:
        converted_pdf.unlink(missing_ok=True)
        # The image was converted and its PDF filed; the consumed original
        # must not linger in _Review_Needed and reappear in the queue.
        if dest_path.exists() and item.file_path.exists():
            item.file_path.unlink(missing_ok=True)

    logger.info("Reviewed and filed scan: %s -> %s", item.filename, dest_path)
    return dest_path


def dismiss_review_item(
    item: ReviewItem,
    history_jsonl: Path | None = None,
    history_csv: Path | None = None,
    lock_path: Path | None = None,
    mirror_csv_path: Path | None = None,
) -> None:
    """Safely delete an unwanted or corrupt item from review needed.

    Args:
        item: ReviewItem to dismiss.
        history_jsonl: Optional custom path to history.jsonl.
        history_csv: Optional custom path to history.csv.
        lock_path: Optional custom path to operations.lock.
    """
    op_lock = lock_path or (get_default_app_dir() / OPERATIONS_LOCK_FILENAME)
    with interprocess_file_lock(op_lock):
        if item.file_path.exists():
            item.file_path.unlink()

        app_dir = get_default_app_dir()
        audit_logger = AuditLogger(
            jsonl_path=history_jsonl or (app_dir / HISTORY_JSONL_NAME),
            csv_path=history_csv or (app_dir / HISTORY_CSV_NAME),
            mirror_csv_path=mirror_csv_path,
        )
        audit_logger.log_scan(
            _build_review_audit_entry(
                item,
                status="DISMISSED",
                sha256=item.sha256 or "UNKNOWN",
                new_filename="",
                destination_folder="",
                destination_path="",
            )
        )
    logger.info("Dismissed and deleted unneeded scan: %s", item.filename)

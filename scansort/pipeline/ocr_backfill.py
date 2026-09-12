"""In-place OCR backfill for already-filed PDFs (searchable-archive retrofit)."""

import logging
import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from scansort.core.config import AppConfig
from scansort.core.constants import (
    LOG_FILENAME,
    OPERATIONS_LOCK_FILENAME,
    STATUS_FAILED,
    STATUS_OCR_BACKFILLED,
)
from scansort.core.fs import interprocess_file_lock
from scansort.document.ocr import (
    OCR_ENGINE_NAME,
    OcrError,
    needs_ocr,
    ocr_pdf_inplace,
)
from scansort.logging import AuditLogger
from scansort.pipeline.dispatcher import (
    resolve_collision,
    resolve_destination_dir,
)
from scansort.pipeline.hasher import compute_file_sha256
from scansort.platform.notifications import notify_filing_failed

logger = logging.getLogger(__name__)


@dataclass
class OcrBackfillResult:
    """Outcome of an OCR backfill run."""

    candidates: list[Path] = field(default_factory=list)
    processed: list[Path] = field(default_factory=list)
    failed: list[Path] = field(default_factory=list)
    skipped: int = 0


def _collect_pdfs(targets: Sequence[Path], documents_root: Path) -> list[Path]:
    """Return de-duplicated PDF paths from explicit targets or the documents root."""
    seen: set[Path] = set()
    result: list[Path] = []

    def _add(candidate: Path) -> None:
        resolved = candidate.resolve()
        if (
            resolved not in seen
            and resolved.is_file()
            and resolved.suffix.lower() == ".pdf"
        ):
            seen.add(resolved)
            result.append(resolved)

    roots = [target for target in targets if target] or [documents_root]
    for root in roots:
        if root.is_dir():
            resolved_root = root.resolve()
            for candidate in sorted(root.rglob("*")):
                if candidate.suffix.lower() != ".pdf":
                    continue
                if candidate.is_symlink() or not candidate.resolve().is_relative_to(
                    resolved_root
                ):
                    continue
                _add(candidate)
        else:
            _add(root)
    return result


def _relative_folder(pdf: Path, documents_root: Path) -> str:
    try:
        relative = pdf.parent.relative_to(documents_root.resolve())
    except ValueError:
        return ""
    return "" if relative == Path(".") else str(relative).replace("\\", "/")


def run_ocr_backfill(
    config: AppConfig,
    app_dir: Path,
    targets: Sequence[Path] | None = None,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    language: str | None = None,
    audit_logger: AuditLogger | None = None,
    progress: Callable[[str], None] | None = None,
) -> OcrBackfillResult:
    """Retrofit OCR text layers into filed PDFs, preserving metadata.

    Args:
        config: Active application configuration.
        app_dir: Application data directory (holds ``operations.lock`` and audits).
        targets: Explicit PDF files/directories; defaults to ``config.documents_root``.
        dry_run: When True, list candidates without mutating anything.
        limit: Maximum number of PDFs to attempt.
        language: Tesseract language code; defaults to ``config.ocr_language``.
        audit_logger: Optional logger override (tests); otherwise app-dir audits.
        progress: Optional callback receiving a human-readable line per candidate.

    Returns:
        Aggregated :class:`OcrBackfillResult`.
    """

    def _emit(message: str) -> None:
        if progress is not None:
            progress(message)

    audit = audit_logger or AuditLogger(
        jsonl_path=app_dir / "history.jsonl",
        csv_path=app_dir / "history.csv",
        mirror_csv_path=config.mirror_csv_path,
    )
    lock_path = app_dir / OPERATIONS_LOCK_FILENAME
    ocr_language = language or config.ocr_language
    result = OcrBackfillResult()

    review_dir = resolve_destination_dir(config.documents_root, config.fallback_folder)
    candidates = _collect_pdfs(list(targets or []), config.documents_root)
    candidates = [
        pdf
        for pdf in candidates
        if not pdf.is_relative_to(review_dir) and pdf != review_dir
    ]

    attempted = 0
    for pdf in candidates:
        if limit is not None and attempted >= limit:
            break
        try:
            requires = needs_ocr(pdf)
        except (OcrError, OSError) as e:
            attempted += 1
            _route_backfill_failure(
                pdf, app_dir, review_dir, config, audit, reason=str(e), dry_run=dry_run
            )
            result.failed.append(pdf)
            _emit(f"FAILED: {pdf.name} ({e})")
            continue
        if not requires:
            result.skipped += 1
            continue

        attempted += 1
        result.candidates.append(pdf)

        if dry_run:
            _emit(f"[DRY RUN] Would make searchable: {pdf}")
            continue

        tmp_out: Path | None = None
        try:
            tmp_out = pdf.with_suffix(".ocr.tmp.pdf")
            _, confidence = ocr_pdf_inplace(
                pdf, language=ocr_language, output_path=tmp_out
            )
            if confidence is None:
                _emit(f"No searchable text found (left unchanged): {pdf.name}")
                continue
            with interprocess_file_lock(lock_path):
                if not needs_ocr(pdf):
                    result.skipped += 1
                    continue
                original_hash = compute_file_sha256(pdf)
                new_hash = compute_file_sha256(tmp_out)
                os.replace(tmp_out, pdf)
                audit.log_scan(
                    {
                        "sha256": new_hash,
                        "original_sha256": original_hash,
                        "original_filename": pdf.name,
                        "original_path": str(pdf),
                        "new_filename": pdf.name,
                        "destination_folder": _relative_folder(
                            pdf, config.documents_root
                        ),
                        "destination_path": str(pdf),
                        "summary": "OCR text layer embedded in filed PDF.",
                        "status": STATUS_OCR_BACKFILLED,
                        "ocr_engine": OCR_ENGINE_NAME,
                        "ocr_confidence": confidence,
                        "ocr_language": ocr_language,
                    }
                )
            result.processed.append(pdf)
            _emit(f"Made searchable: {pdf.name}")
        except (OcrError, OSError) as e:
            _route_backfill_failure(
                pdf, app_dir, review_dir, config, audit, reason=str(e), dry_run=dry_run
            )
            result.failed.append(pdf)
            _emit(f"FAILED: {pdf.name} ({e})")
        finally:
            if tmp_out is not None:
                tmp_out.unlink(missing_ok=True)

    return result


def _route_backfill_failure(
    pdf: Path,
    app_dir: Path,
    review_dir: Path,
    config: AppConfig,
    audit: AuditLogger,
    reason: str,
    dry_run: bool = False,
) -> None:
    """Move an un-OCRable filed PDF to the review folder with a FAILED audit."""
    logger.error("OCR backfill failed for %s: %s", pdf, reason)
    if dry_run:
        return
    lock_path = app_dir / OPERATIONS_LOCK_FILENAME
    dest: Path | None = None
    try:
        with interprocess_file_lock(lock_path):
            review_dir.mkdir(parents=True, exist_ok=True)
            dest = resolve_collision(review_dir, pdf.name)
            shutil.move(str(pdf), str(dest))
        audit.log_scan(
            {
                "sha256": "UNKNOWN",
                "original_filename": pdf.name,
                "original_path": str(pdf),
                "new_filename": dest.name,
                "destination_folder": _relative_folder(
                    dest.parent, config.documents_root
                ),
                "destination_path": str(dest),
                "summary": f"OCR backfill failed; routed to review folder ({reason}).",
                "status": STATUS_FAILED,
            }
        )
        notify_filing_failed(
            pdf.name,
            str(config.fallback_folder).replace("\\", "/"),
            reason,
            folder_path=review_dir,
            log_path=app_dir / LOG_FILENAME,
        )
    except (OSError, ValueError) as e:
        if dest is not None:
            try:
                dest.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                logger.error(
                    "Could not remove partial review copy %s: %s", dest, cleanup_exc
                )
        logger.error(
            "Could not route %s to review folder after OCR failure: %s", pdf, e
        )

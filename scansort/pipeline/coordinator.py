"""End-to-end processing pipeline for incoming scanned documents."""

import logging
import queue
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from scansort.classification.client import GeminiClassifier
from scansort.classification.hints import load_folder_hints
from scansort.classification.models import DocumentClassification
from scansort.classification.taxonomy import FolderMapper
from scansort.core.config import AppConfig, get_default_app_dir
from scansort.core.constants import (
    FOLDER_MAP_FILENAME,
    HINTS_FILENAME,
    HISTORY_CSV_NAME,
    HISTORY_JSONL_NAME,
    LOG_FILENAME,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_SUCCESS,
)
from scansort.core.fs import interprocess_file_lock
from scansort.document.converter import convert_to_pdf
from scansort.document.metadata import process_pdf_metadata_and_rotation
from scansort.logging import AuditLogger
from scansort.pipeline.dispatcher import (
    OPERATIONS_LOCK_FILENAME,
    dispatch_file,
    generate_target_filename,
    resolve_collision,
    resolve_destination_dir,
    resolve_duplicates_dir,
)
from scansort.pipeline.hasher import check_duplicate, compute_file_sha256
from scansort.pipeline.stabilizer import wait_for_file_stability
from scansort.pipeline.worker import run_pipeline_worker
from scansort.platform.notifications import (
    notify_file_filed,
    notify_filing_failed,
    notify_scan_stranded,
)

logger = logging.getLogger(__name__)


class ScanSortPipeline:
    """End-to-end processing pipeline for incoming scanned documents."""

    def __init__(
        self,
        config: AppConfig,
        app_dir: Path | None = None,
        classifier: GeminiClassifier | None = None,
    ) -> None:
        self.config = config
        self.app_dir = app_dir or get_default_app_dir()
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir = self.app_dir / "tmp"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.operations_lock = self.app_dir / OPERATIONS_LOCK_FILENAME

        self.classifier = classifier or GeminiClassifier(model=config.gemini_model)
        self.hints_path = self.app_dir / HINTS_FILENAME
        self.folder_mapper = FolderMapper(
            docs_root=config.documents_root,
            cache_path=self.app_dir / FOLDER_MAP_FILENAME,
            hints_path=self.hints_path,
            max_depth=config.max_folder_depth,
            fallback_folder=config.fallback_folder,
        )

        self.audit_logger = AuditLogger(
            jsonl_path=self.app_dir / HISTORY_JSONL_NAME,
            csv_path=self.app_dir / HISTORY_CSV_NAME,
            mirror_csv_path=config.mirror_csv_path,
        )

    def _build_audit_entry(
        self,
        file_hash: str,
        file_path: Path,
        destination_path: Path,
        destination_folder: str,
        summary: str,
        status: str,
        classification: DocumentClassification | None = None,
    ) -> dict[str, Any]:
        """Build a standardized audit log entry dictionary."""
        entry: dict[str, Any] = {
            "sha256": file_hash,
            "original_filename": file_path.name,
            "original_path": str(file_path),
            "new_filename": destination_path.name,
            "destination_folder": destination_folder,
            "destination_path": str(destination_path),
            "summary": summary,
            "status": status,
        }
        if classification is not None:
            model_val = getattr(self.classifier, "model", None)
            if isinstance(model_val, str):
                entry["gemini_model"] = model_val
            if isinstance(classification.confidence, (int, float)):
                entry["confidence"] = float(classification.confidence)
            if isinstance(classification.document_type, str):
                entry["document_type"] = classification.document_type
            reason = getattr(classification, "folder_reasoning", None)
            if isinstance(reason, str) and reason.strip():
                entry["folder_reasoning"] = reason.strip()
            rationale = getattr(classification, "routing_rationale", None)
            if isinstance(rationale, str) and rationale.strip():
                entry["routing_rationale"] = rationale.strip()
            prompt_tokens = getattr(classification, "prompt_tokens", 0)
            candidates_tokens = getattr(classification, "candidates_tokens", 0)
            if (
                isinstance(prompt_tokens, int)
                and isinstance(candidates_tokens, int)
                and (prompt_tokens or candidates_tokens)
            ):
                entry["tokens"] = {
                    "prompt": prompt_tokens,
                    "candidates": candidates_tokens,
                    "total": prompt_tokens + candidates_tokens,
                }
            cost_val = getattr(classification, "estimated_cost_usd", None)
            if isinstance(cost_val, (int, float)):
                entry["estimated_cost_usd"] = float(cost_val)
        return entry

    def _route_duplicate(
        self,
        file_path: Path,
        file_hash: str,
        existing_record: dict[str, Any],
    ) -> Path:
        """Route a detected duplicate scan to the duplicates review folder."""
        logger.info(
            "Duplicate scan detected for %s (hash: %s).",
            file_path.name,
            file_hash[:8],
        )
        clean_fallback = self.config.fallback_folder.strip("/\\")
        resolved_docs = self.config.documents_root.resolve()
        dup_dest_dir = resolve_duplicates_dir(
            self.config.documents_root, clean_fallback
        )

        desired_dup_name = file_path.name

        if self.config.dry_run:
            dup_dest = resolve_collision(dup_dest_dir, desired_dup_name)
            logger.info(
                "[DRY RUN] Would route duplicate %s -> %s",
                file_path.name,
                dup_dest,
            )
            return dup_dest

        with interprocess_file_lock(self.operations_lock):
            dup_dest = resolve_collision(dup_dest_dir, desired_dup_name)
            dup_dest_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(file_path), str(dup_dest))
            except OSError:
                dup_dest.unlink(missing_ok=True)
                raise

        folder_str = str(dup_dest_dir.relative_to(resolved_docs)).replace("\\", "/")
        summary_str = (
            f"Duplicate scan of {existing_record.get('new_filename', 'previous file')}"
        )
        self.audit_logger.log_scan(
            self._build_audit_entry(
                file_hash=file_hash,
                file_path=file_path,
                destination_path=dup_dest,
                destination_folder=folder_str,
                summary=summary_str,
                status=STATUS_DUPLICATE,
            )
        )
        return dup_dest

    def _stage_to_temp(self, file_path: Path) -> Path | None:
        """Stage incoming scan into isolated application temporary directory."""
        is_original_image = file_path.suffix.lower() != ".pdf"
        tmp_pdf_name = f"{file_path.stem}_{uuid.uuid4().hex[:8]}.pdf"
        staging_pdf = self.tmp_dir / tmp_pdf_name

        try:
            if is_original_image:
                return convert_to_pdf(file_path, output_path=staging_pdf)
            shutil.copy2(str(file_path), str(staging_pdf))
            return staging_pdf
        except (ValueError, OSError) as e:
            logger.error("Failed to stage %s to temporary PDF: %s", file_path.name, e)
            staging_pdf.unlink(missing_ok=True)
            return None

    def _classify_scan(self, staging_pdf: Path) -> DocumentClassification:
        """Query Gemini to classify the staged PDF against taxonomy and hints."""
        taxonomy = self.folder_mapper.get_taxonomy()
        hints = load_folder_hints(self.hints_path)
        return self.classifier.classify_document(
            staging_pdf, taxonomy=taxonomy, hints=hints
        )

    def _apply_metadata_and_dispatch(
        self,
        staging_pdf: Path,
        file_path: Path,
        classification: DocumentClassification,
        file_hash: str,
    ) -> Path:
        """Apply rotation, embed metadata, dispatch to destination, and write audit record."""
        keywords = [classification.document_type, classification.target_folder]
        process_pdf_metadata_and_rotation(
            pdf_path=staging_pdf,
            orientation_angle=classification.orientation_correction,
            title=classification.description,
            subject=classification.summary,
            keywords=keywords,
        )

        final_dest = dispatch_file(
            staging_pdf,
            self.config.documents_root,
            classification,
            lock_path=self.operations_lock,
        )

        # Remove original file from drop folder (S3-14: don't let unlink error abort audit log)
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError as e:
                logger.warning(
                    "Could not remove source file %s after dispatch: %s",
                    file_path,
                    e,
                )

        # Derive destination folder relative to documents_root for accurate audit and notifications
        resolved_docs = self.config.documents_root.resolve()
        folder_str = str(final_dest.parent.relative_to(resolved_docs)).replace(
            "\\", "/"
        )

        # Record audit log
        self.audit_logger.log_scan(
            self._build_audit_entry(
                file_hash=file_hash,
                file_path=file_path,
                destination_path=final_dest,
                destination_folder=folder_str,
                summary=classification.summary,
                status=STATUS_SUCCESS,
                classification=classification,
            )
        )

        logger.info("Successfully filed scan: %s -> %s", file_path.name, final_dest)
        notify_file_filed(
            final_dest.name,
            folder_str,
            folder_path=final_dest.parent,
        )
        return final_dest

    def process_file(self, file_path: Path) -> Path | None:
        """Process an incoming scan file through the full classification pipeline.

        Args:
            file_path: Absolute path to the incoming file.

        Returns:
            Destination Path if filed successfully, or None if skipped/failed.
        """
        # 1. Wait for file write stabilization (Rule 3.C). The quiet window is
        # ~1s: advisory lock probes cannot detect plain write()-based writers
        # (scanner drivers, SMB), so size quiescence is the effective guard.
        if not wait_for_file_stability(
            file_path, timeout=10.0, poll_interval=0.1, stable_count=10
        ):
            logger.warning("File %s did not stabilize. Skipping.", file_path.name)
            return None

        try:
            source_stat = file_path.stat()
        except OSError:
            logger.warning(
                "File %s vanished before processing. Skipping.", file_path.name
            )
            return None
        source_size = source_stat.st_size
        source_mtime_ns = source_stat.st_mtime_ns

        staging_pdf: Path | None = None
        try:
            # 2. SHA-256 Duplicate Check (Rule 3.D)
            file_hash = compute_file_sha256(file_path)
            existing_record = check_duplicate(file_hash, self.audit_logger.jsonl_path)
            if existing_record:
                return self._route_duplicate(file_path, file_hash, existing_record)

            # 3. Stage incoming scan into isolated app temporary directory upfront (Rule 3.H)
            staging_pdf = self._stage_to_temp(file_path)
            if staging_pdf is None:
                return None

            # 4. Multimodal analysis and classification via Gemini
            classification = self._classify_scan(staging_pdf)

            # 5. Dry-Run Verification before any file mutation or metadata writing
            if self.config.dry_run:
                target_dir = resolve_destination_dir(
                    self.config.documents_root, classification.target_folder
                )
                desired_name = generate_target_filename(classification)
                simulated_dest = resolve_collision(target_dir, desired_name)
                logger.info(
                    "[DRY RUN] Would file %s -> %s", file_path.name, simulated_dest
                )
                return simulated_dest

            # Re-verify the source is unchanged since stabilization before
            # dispatching; a writer that resumed mid-processing must not have
            # its partial snapshot filed.
            try:
                current_stat = file_path.stat()
            except OSError:
                current_stat = None
            if current_stat is None or (
                current_stat.st_size,
                current_stat.st_mtime_ns,
            ) != (source_size, source_mtime_ns):
                logger.warning(
                    "File %s changed while processing. Deferring until stable.",
                    file_path.name,
                )
                return None

            # 6-8. Apply rotation, embed metadata, atomic dispatch, and record audit log
            return self._apply_metadata_and_dispatch(
                staging_pdf=staging_pdf,
                file_path=file_path,
                classification=classification,
                file_hash=file_hash,
            )

        except Exception as e:  # noqa: BLE001 - Catch unexpected processing errors to prevent pipeline crashing
            logger.error("Failed to process scan %s: %s", file_path.name, e)
            self._route_failed_to_review(file_path, reason=str(e))
            return None

        finally:
            # Clean up intermediate staged PDF if it still exists in tmp
            if staging_pdf is not None:
                staging_pdf.unlink(missing_ok=True)

    def _route_failed_to_review(
        self, file_path: Path, reason: str | None = None
    ) -> None:
        """Best-effort relocation of an unprocessable inbox file to the review folder.

        Only the original inbox file is ever moved (dispatch failures leave it in
        place); the move and audit write are themselves guarded so routing failure
        degrades to the previous logged-stranded behavior. Users are notified via
        toast in both outcomes.
        """
        try:
            if self.config.dry_run or not file_path.exists():
                return
            review_dir = resolve_destination_dir(
                self.config.documents_root, self.config.fallback_folder
            )
            review_dir.mkdir(parents=True, exist_ok=True)
            review_dest = resolve_collision(review_dir, file_path.name)
            shutil.move(str(file_path), str(review_dest))
            resolved_docs = self.config.documents_root.resolve()
            folder_str = str(review_dir.relative_to(resolved_docs)).replace("\\", "/")
            self.audit_logger.log_scan(
                self._build_audit_entry(
                    file_hash="UNKNOWN",
                    file_path=file_path,
                    destination_path=review_dest,
                    destination_folder=folder_str,
                    summary="Failed processing; routed to review folder.",
                    status=STATUS_FAILED,
                )
            )
            notify_filing_failed(
                file_path.name,
                folder_str,
                reason,
                folder_path=review_dir,
                log_path=self.app_dir / LOG_FILENAME,
            )
        except (OSError, ValueError) as e:
            logger.error(
                "Could not route failed scan %s to review folder: %s", file_path, e
            )
            display_folder = str(self.config.fallback_folder).replace("\\", "/")
            notify_scan_stranded(
                file_path.name,
                display_folder,
                folder_path=self.config.watch_folder,
                log_path=self.app_dir / LOG_FILENAME,
            )

    def run_worker(self, file_queue: queue.Queue, stop_event: threading.Event) -> None:
        """Sequential background worker processing items from the queue with rate-limiting.

        On shutdown the worker drains everything still queued before exiting so
        no dropped scan is silently skipped.
        """
        run_pipeline_worker(self.process_file, file_queue, stop_event)

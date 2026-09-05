import logging
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path

from scansort.audit_logger import AuditLogger
from scansort.config import AppConfig, get_default_app_dir
from scansort.constants import (
    HISTORY_CSV_NAME,
    HISTORY_JSONL_NAME,
    MIRROR_HISTORY_CSV_NAME,
)
from scansort.dispatcher import (
    dispatch_file,
    generate_target_filename,
    resolve_collision,
    resolve_destination_dir,
    resolve_duplicates_dir,
)
from scansort.file_stabilizer import wait_for_file_stability
from scansort.folder_hints import load_folder_hints
from scansort.folder_mapper import FolderMapper
from scansort.gemini_client import GeminiClassifier
from scansort.hasher import check_duplicate, compute_file_sha256
from scansort.image_converter import convert_to_pdf
from scansort.pdf_metadata import process_pdf_metadata_and_rotation

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

        self.classifier = classifier or GeminiClassifier(model=config.gemini_model)
        self.hints_path = self.app_dir / "folder_hints.json"
        self.folder_mapper = FolderMapper(
            docs_root=config.documents_root,
            cache_path=self.app_dir / "folder_map.json",
            hints_path=self.hints_path,
            max_depth=config.max_folder_depth,
            fallback_folder=config.fallback_folder,
        )

        mirror_path = (
            config.documents_root / MIRROR_HISTORY_CSV_NAME
            if config.mirror_log_to_documents
            else None
        )
        self.audit_logger = AuditLogger(
            jsonl_path=self.app_dir / HISTORY_JSONL_NAME,
            csv_path=self.app_dir / HISTORY_CSV_NAME,
            mirror_csv_path=mirror_path,
        )

    def process_file(self, file_path: Path) -> Path | None:
        """Run a single incoming document through the full stabilization, OCR, and filing pipeline.

        Args:
            file_path: Path to the scanned file in the drop folder.

        Returns:
            Path of the final filed PDF, or None if processing failed.
        """
        if not file_path.exists():
            logger.warning("File %s disappeared before processing.", file_path)
            return None

        # 1. Wait for physical scanner to finish writing and release locks
        if not wait_for_file_stability(
            file_path, timeout=10.0, poll_interval=0.1, stable_count=2
        ):
            logger.warning("File %s did not stabilize. Skipping.", file_path.name)
            return None

        # 2. SHA-256 duplicate detection
        file_hash = compute_file_sha256(file_path)
        existing_record = check_duplicate(file_hash, self.audit_logger.jsonl_path)

        if existing_record:
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
            dup_dest = resolve_collision(dup_dest_dir, desired_dup_name)

            if self.config.dry_run:
                logger.info(
                    "[DRY RUN] Would route duplicate %s -> %s",
                    file_path.name,
                    dup_dest,
                )
                return dup_dest

            dup_dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(file_path), str(dup_dest))

            self.audit_logger.log_scan(
                {
                    "sha256": file_hash,
                    "original_filename": file_path.name,
                    "original_path": str(file_path),
                    "new_filename": dup_dest.name,
                    "destination_folder": str(
                        dup_dest_dir.relative_to(resolved_docs)
                    ).replace("\\", "/"),
                    "destination_path": str(dup_dest),
                    "summary": f"Duplicate scan of {existing_record.get('new_filename', 'previous file')}",
                    "status": "DUPLICATE",
                }
            )
            return dup_dest

        # 3. Stage incoming scan into isolated app temporary directory upfront (Rule 3.H)
        is_original_image = file_path.suffix.lower() != ".pdf"
        tmp_pdf_name = f"{file_path.stem}_{uuid.uuid4().hex[:8]}.pdf"
        staging_pdf = self.tmp_dir / tmp_pdf_name

        try:
            if is_original_image:
                staging_pdf = convert_to_pdf(file_path, output_path=staging_pdf)
            else:
                shutil.copy2(str(file_path), str(staging_pdf))
        except (ValueError, OSError) as e:
            logger.error("Failed to stage %s to temporary PDF: %s", file_path.name, e)
            staging_pdf.unlink(missing_ok=True)
            return None

        try:
            # 4. Multimodal analysis and classification via Gemini
            taxonomy = self.folder_mapper.get_taxonomy()
            hints = load_folder_hints(self.hints_path)
            classification = self.classifier.classify_document(
                staging_pdf, taxonomy=taxonomy, hints=hints
            )

            # 5. Dry-Run Verification before any file mutation or metadata writing
            target_dir = resolve_destination_dir(
                self.config.documents_root, classification.target_folder
            )

            desired_name = generate_target_filename(classification)
            simulated_dest = resolve_collision(target_dir, desired_name)

            if self.config.dry_run:
                logger.info(
                    "[DRY RUN] Would file %s -> %s", file_path.name, simulated_dest
                )
                return simulated_dest

            # 6. Apply auto-rotation and embed XMP metadata
            keywords = [classification.document_type, classification.target_folder]
            process_pdf_metadata_and_rotation(
                pdf_path=staging_pdf,
                orientation_angle=classification.orientation_correction,
                title=classification.description,
                subject=classification.summary,
                keywords=keywords,
            )

            # 7. Atomic Dispatch to destination folder
            final_dest = dispatch_file(
                staging_pdf, self.config.documents_root, classification
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

            # 8. Record audit log
            self.audit_logger.log_scan(
                {
                    "sha256": file_hash,
                    "original_filename": file_path.name,
                    "original_path": str(file_path),
                    "new_filename": final_dest.name,
                    "destination_folder": classification.target_folder,
                    "destination_path": str(final_dest),
                    "summary": classification.summary,
                    "status": "SUCCESS",
                }
            )

            logger.info("Successfully filed scan: %s -> %s", file_path.name, final_dest)
            return final_dest

        except Exception as e:  # noqa: BLE001 - Catch unexpected processing errors to prevent pipeline crashing
            logger.error("Failed to process scan %s: %s", file_path.name, e)
            return None

        finally:
            # Clean up intermediate staged PDF if it still exists in tmp
            staging_pdf.unlink(missing_ok=True)

    def run_worker(self, file_queue: queue.Queue, stop_event: threading.Event) -> None:
        """Sequential background worker processing items from the queue with rate-limiting."""
        logger.info("ScanSort pipeline worker started.")
        while not stop_event.is_set():
            try:
                item = file_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self.process_file(item)
            except Exception as e:  # noqa: BLE001 - Worker loop must survive unexpected task errors
                logger.error("Unexpected error processing %s: %s", item, e)
            finally:
                file_queue.task_done()
                time.sleep(1.0)  # Gentle spacing for API rate limits

        logger.info("ScanSort pipeline worker stopped.")

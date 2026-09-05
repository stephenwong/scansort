"""PDF metadata enrichment and auto-orientation rotation engine using pypdf."""

import io
import logging
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from scansort.fs_utils import atomic_write

logger = logging.getLogger(__name__)


def process_pdf_metadata_and_rotation(
    pdf_path: Path,
    output_path: Path | None = None,
    orientation_angle: int = 0,
    title: str | None = None,
    subject: str | None = None,
    keywords: list[str] | str | None = None,
    author: str | None = "ScanSort",
) -> Path:
    """Apply auto-rotation and embed structured metadata into a PDF for Windows Search indexer.

    Args:
        pdf_path: Path to the source PDF.
        output_path: Optional destination path. If omitted or equal to source, updates in place.
        orientation_angle: Rotation angle in degrees (0, 90, 180, 270).
        title: Document title (e.g. description).
        subject: 1-sentence document summary.
        keywords: Category tags and search terms.
        author: Document author / filing system name.

    Returns:
        Path to the modified PDF file.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found at {pdf_path}")

    target_path = output_path or pdf_path
    pdf_bytes = pdf_path.read_bytes()

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as e:
        raise ValueError(f"Corrupted or unreadable PDF {pdf_path.name}: {e}") from e

    # Handle encrypted PDFs (S3-06)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except (PdfReadError, OSError):
            logger.debug(
                "Empty password decryption attempt failed for %s", pdf_path.name
            )
        try:
            _ = len(reader.pages)
            if reader.pages:
                _ = reader.pages[0]
        except Exception as e:
            raise ValueError(
                f"PDF {pdf_path.name} is password protected and cannot be processed."
            ) from e

    writer = PdfWriter()

    # Normalize orientation angle to orthogonal multiples
    raw_norm = orientation_angle % 360
    norm_angle = raw_norm if raw_norm in {0, 90, 180, 270} else 0

    # Add pages with optional rotation
    for page in reader.pages:
        if norm_angle != 0:
            page.rotate(norm_angle)
        writer.add_page(page)

    # Build metadata dictionary, preserving pre-existing DocInfo (S3-09)
    metadata: dict[str, str] = {}
    if reader.metadata:
        for k, v in reader.metadata.items():
            if k and v:
                metadata[str(k)] = str(v)

    if title:
        metadata["/Title"] = title.strip()
    if subject:
        metadata["/Subject"] = subject.strip()
    if keywords:
        if isinstance(keywords, (list, tuple, set)):
            metadata["/Keywords"] = ", ".join(
                sorted(str(k).strip() for k in keywords if str(k).strip())
            )
        else:
            metadata["/Keywords"] = str(keywords).strip()
    if author:
        metadata["/Author"] = author.strip()
    metadata["/Creator"] = "ScanSort Desktop Engine"

    if metadata:
        writer.add_metadata(metadata)

    # Unified atomic write via temporary file replacement for all targets (S3-08)
    buf = io.BytesIO()
    writer.write(buf)
    atomic_write(target_path, buf.getvalue())

    logger.debug(
        "Embedded metadata and rotation (%d deg) into %s.", norm_angle, target_path.name
    )
    return target_path

"""PDF metadata enrichment and auto-orientation rotation engine using pypdf."""

import io
import logging
from pathlib import Path

from pypdf import PasswordType, PdfReader, PdfWriter
from pypdf.xmp import XmpInformation

from scansort.constants import DEFAULT_AUTHOR, DEFAULT_CREATOR
from scansort.fs_utils import atomic_write

logger = logging.getLogger(__name__)


def _ensure_pdf_unlocked(reader: PdfReader, filename: str) -> None:
    """Verify the PDF is not password-protected, attempting empty password decryption."""
    if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
        raise ValueError(
            f"PDF {filename} is password protected and cannot be processed."
        )


def _build_xmp_packet(
    xmp_bytes: bytes | None,
    title: str | None,
    subject: str | None,
    keywords: list[str] | str | None,
) -> XmpInformation:
    """Preserve an existing XMP packet or generate a minimal one from DocInfo fields."""
    if xmp_bytes is not None:
        return xmp_bytes
    xmp = XmpInformation.create()
    if title and title.strip():
        xmp.dc_title = {"x-default": title.strip()}
    if subject and subject.strip():
        xmp.dc_description = {"x-default": subject.strip()}
    if keywords:
        if isinstance(keywords, (list, tuple, set)):
            cleaned = sorted(str(k).strip() for k in keywords if str(k).strip())
        else:
            cleaned = [str(keywords).strip()] if str(keywords).strip() else []
        if cleaned:
            xmp.pdf_keywords = ", ".join(cleaned)
    return xmp


def _build_docinfo_metadata(
    existing_metadata: object = None,
    title: str | None = None,
    subject: str | None = None,
    keywords: list[str] | str | None = None,
    author: str | None = DEFAULT_AUTHOR,
) -> dict[str, str]:
    """Construct DocInfo metadata dictionary, preserving pre-existing metadata."""
    metadata: dict[str, str] = {}
    if existing_metadata and hasattr(existing_metadata, "items"):
        for k, v in existing_metadata.items():
            if k and v:
                metadata[str(k)] = str(v)

    if title and title.strip():
        metadata["/Title"] = title.strip()
    if subject and subject.strip():
        metadata["/Subject"] = subject.strip()
    if keywords:
        if isinstance(keywords, (list, tuple, set)):
            cleaned = sorted(str(k).strip() for k in keywords if str(k).strip())
            if cleaned:
                metadata["/Keywords"] = ", ".join(cleaned)
        elif str(keywords).strip():
            metadata["/Keywords"] = str(keywords).strip()
    if author and author.strip():
        metadata["/Author"] = author.strip()
    metadata["/Creator"] = DEFAULT_CREATOR
    return metadata


def process_pdf_metadata_and_rotation(
    pdf_path: Path,
    output_path: Path | None = None,
    orientation_angle: int = 0,
    title: str | None = None,
    subject: str | None = None,
    keywords: list[str] | str | None = None,
    author: str | None = DEFAULT_AUTHOR,
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
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file not found at {pdf_path}")

    target_path = output_path or pdf_path
    pdf_bytes = pdf_path.read_bytes()

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as e:
        raise ValueError(f"Corrupted or unreadable PDF {pdf_path.name}: {e}") from e

    _ensure_pdf_unlocked(reader, pdf_path.name)

    existing_xmp: bytes | None = None
    if reader.xmp_metadata is not None:
        try:
            existing_xmp = reader.xmp_metadata.stream.get_data()
        except (AttributeError, OSError):
            existing_xmp = None

    writer = PdfWriter()

    # Normalize orientation angle to orthogonal multiples
    raw_norm = orientation_angle % 360
    norm_angle = raw_norm if raw_norm in {0, 90, 180, 270} else 0

    # Add pages with optional rotation (normalizing setter keeps /Rotate canonical)
    for page in reader.pages:
        if norm_angle != 0:
            page.rotation = page.rotation + norm_angle
        writer.add_page(page)

    metadata = _build_docinfo_metadata(
        existing_metadata=reader.metadata,
        title=title,
        subject=subject,
        keywords=keywords,
        author=author,
    )
    if metadata:
        writer.add_metadata(metadata)

    # Preserve any pre-existing XMP packet; otherwise emit one (invariant E).
    writer.xmp_metadata = _build_xmp_packet(existing_xmp, title, subject, keywords)

    # Unified atomic write via temporary file replacement for all targets (S3-08)
    atomic_write(target_path, lambda out: writer.write(out))

    logger.debug(
        "Embedded metadata and rotation (%d deg) into %s.", norm_angle, target_path.name
    )
    return target_path

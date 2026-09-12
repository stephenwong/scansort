"""PDF metadata enrichment and auto-orientation rotation engine using pypdf."""

import io
import logging
from pathlib import Path

from pypdf import PasswordType, PdfReader, PdfWriter
from pypdf.errors import PyPdfError
from pypdf.xmp import XmpInformation

from scansort.core.constants import DEFAULT_AUTHOR, DEFAULT_CREATOR
from scansort.core.fs import atomic_write

logger = logging.getLogger(__name__)


def _ensure_pdf_unlocked(reader: PdfReader, filename: str) -> None:
    """Verify the PDF is not password-protected, attempting empty password decryption."""
    if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
        raise ValueError(
            f"PDF {filename} is password protected and cannot be processed."
        )


def _normalize_keywords(keywords: list[str] | str | None) -> list[str]:
    """Return cleaned, sorted keyword strings from a list/tuple/set or bare string."""
    if not keywords:
        return []
    if isinstance(keywords, (list, tuple, set)):
        return sorted(str(k).strip() for k in keywords if str(k).strip())
    text = str(keywords).strip()
    return [text] if text else []


def _build_xmp_packet(
    existing_xmp: XmpInformation | None,
    title: str | None,
    subject: str | None,
    keywords: list[str] | str | None,
) -> XmpInformation:
    """Merge metadata into an existing XMP packet, or generate a minimal one."""
    xmp = existing_xmp if isinstance(existing_xmp, XmpInformation) else None
    if xmp is None:
        xmp = XmpInformation.create()
    if title and title.strip():
        xmp.dc_title = {"x-default": title.strip()}
    if subject and subject.strip():
        xmp.dc_description = {"x-default": subject.strip()}
    cleaned = _normalize_keywords(keywords)
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
    cleaned = _normalize_keywords(keywords)
    if cleaned:
        metadata["/Keywords"] = ", ".join(cleaned)
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

    existing_xmp: XmpInformation | None = None
    try:
        existing_xmp = reader.xmp_metadata
    except AttributeError, OSError, PyPdfError:
        existing_xmp = None

    writer = PdfWriter()

    # Normalize orientation angle to orthogonal multiples
    raw_norm = orientation_angle % 360
    norm_angle = raw_norm if raw_norm in {0, 90, 180, 270} else 0

    # Rotate the source pages first, then import the whole document so that
    # catalog-level structures (outlines/bookmarks, named destinations,
    # AcroForm) are preserved rather than silently dropped (invariant E).
    if norm_angle != 0:
        for page in reader.pages:
            page.rotation = page.rotation + norm_angle

    writer.append(reader)

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

    logger.info(
        "Embedded metadata and rotation (%d°) into %s.", norm_angle, target_path.name
    )
    return target_path

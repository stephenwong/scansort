"""PDF metadata enrichment and auto-orientation rotation engine using pypdf."""

import io
import logging
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

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
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()

    # Normalize orientation angle to orthogonal multiples
    raw_norm = orientation_angle % 360
    norm_angle = raw_norm if raw_norm in {0, 90, 180, 270} else 0

    # Add pages with optional rotation
    for page in reader.pages:
        if norm_angle != 0:
            page.rotate(norm_angle)
        writer.add_page(page)

    # Build metadata dictionary
    metadata: dict[str, str] = {}
    if title:
        metadata["/Title"] = title.strip()
    if subject:
        metadata["/Subject"] = subject.strip()
    if keywords:
        if isinstance(keywords, list):
            metadata["/Keywords"] = ", ".join(k.strip() for k in keywords if k.strip())
        else:
            metadata["/Keywords"] = str(keywords).strip()
    if author:
        metadata["/Author"] = author.strip()
    metadata["/Creator"] = "ScanSort Desktop Engine"

    if metadata:
        writer.add_metadata(metadata)

    # If updating in place, write to temp file first then replace to avoid corruption
    if target_path == pdf_path:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=pdf_path.parent, delete=False, suffix=".tmp"
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                writer.write(tmp_file)

            tmp_path.replace(target_path)
        finally:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "wb") as f:
            writer.write(f)

    logger.debug(
        "Embedded metadata and rotation (%d deg) into %s.", norm_angle, target_path.name
    )
    return target_path

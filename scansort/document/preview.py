"""PDF classification preview capping and conservative local blank-page detection."""

import io
import logging
from pathlib import Path

import img2pdf
from PIL import Image, ImageStat
from pypdf import PasswordType, PdfReader, PdfWriter
from pypdf.errors import DeprecationError as PyPdfDeprecationError
from pypdf.errors import PyPdfError

from scansort.core.constants import (
    BLANK_MAX_DARK_PIXEL_RATIO,
    BLANK_MAX_STDDEV,
    BLANK_MAX_TEXT_CHARS,
    BLANK_MIN_PAGE_DIMENSION,
    MAX_CLASSIFICATION_PAGES,
    MAX_CLASSIFICATION_PDF_BYTES,
)

logger = logging.getLogger(__name__)
_PYPDF_ERRORS = (PyPdfError, PyPdfDeprecationError)


def _open_unlocked_reader(raw_bytes: bytes, name: str) -> PdfReader:
    """Parse *raw_bytes* as an unlocked PdfReader or raise ValueError."""
    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
    except (*_PYPDF_ERRORS, OSError, ValueError, NotImplementedError, KeyError) as e:
        raise ValueError(f"PDF {name} is unreadable: {e}") from e
    if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
        raise ValueError(f"PDF {name} is password protected and cannot be classified.")
    return reader


def _slice_pdf_pages(reader: PdfReader, page_count: int) -> bytes:
    """Write the first *page_count* pages of *reader* to an in-memory PDF."""
    writer = PdfWriter()
    for page in reader.pages[:page_count]:
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _downscale_first_page_image(reader: PdfReader, max_bytes: int) -> bytes | None:
    """Best-effort JPEG downscale of page 1's largest raster image to fit *max_bytes*."""
    if not reader.pages:
        return None
    best_img: Image.Image | None = None
    best_area = -1
    try:
        images = list(reader.pages[0].images)
    except (*_PYPDF_ERRORS, OSError, ValueError, TypeError, KeyError):
        return None
    for item in images:
        try:
            pil_img = item.image
        except OSError, ValueError, TypeError, NotImplementedError:
            continue
        if pil_img is None:
            continue
        area = pil_img.size[0] * pil_img.size[1]
        if area > best_area:
            best_img = pil_img
            best_area = area
    if best_img is None:
        return None

    working = best_img.convert("RGB")
    for scale in (1.0, 0.75, 0.5, 0.35, 0.25):
        resized = (
            working
            if scale == 1.0
            else working.resize(
                (
                    max(1, int(working.width * scale)),
                    max(1, int(working.height * scale)),
                ),
                Image.Resampling.LANCZOS,
            )
        )
        for quality in (75, 55, 35):
            jpg_buf = io.BytesIO()
            resized.save(jpg_buf, format="JPEG", quality=quality, optimize=True)
            pdf_bytes = img2pdf.convert(jpg_buf.getvalue())
            if len(pdf_bytes) <= max_bytes:
                return pdf_bytes
    return None


def prepare_pdf_for_classification(
    pdf_path: Path,
    max_pages: int = MAX_CLASSIFICATION_PAGES,
    max_bytes: int = MAX_CLASSIFICATION_PDF_BYTES,
) -> bytes:
    """Return bounded PDF bytes suitable for multimodal Gemini classification.

    Never mutates *pdf_path* on disk so multi-page archival remains complete.
    """
    raw_bytes = pdf_path.read_bytes()
    if not raw_bytes.lstrip().startswith(b"%PDF-"):
        raise ValueError(f"PDF {pdf_path.name} is unreadable: missing PDF header.")

    try:
        reader = _open_unlocked_reader(raw_bytes, pdf_path.name)
    except ValueError as e:
        if "password protected" in str(e) or len(raw_bytes) > max_bytes:
            raise
        logger.debug(
            "Skipping PDF page-cap parse for '%s' (%s); sending raw bytes.",
            pdf_path.name,
            e,
        )
        return raw_bytes

    page_limit = max(1, max_pages)
    if len(reader.pages) <= page_limit and len(raw_bytes) <= max_bytes:
        return raw_bytes

    target_pages = min(len(reader.pages), page_limit)
    while target_pages >= 1:
        sliced = _slice_pdf_pages(reader, target_pages)
        if len(sliced) <= max_bytes:
            if target_pages < len(reader.pages):
                logger.info(
                    "Capped classification preview for '%s' from %d to %d pages (%d bytes).",
                    pdf_path.name,
                    len(reader.pages),
                    target_pages,
                    len(sliced),
                )
            return sliced
        target_pages -= 1

    downscaled = _downscale_first_page_image(reader, max_bytes)
    if downscaled is not None:
        logger.info(
            "Downscaled classification preview for '%s' to %d bytes.",
            pdf_path.name,
            len(downscaled),
        )
        return downscaled

    raise ValueError(
        f"PDF {pdf_path.name} exceeds {max_bytes} byte classification preview limit."
    )


def _image_is_blank(pil_image: Image.Image) -> bool:
    """Return True when a scanner-sized image contains negligible dark ink or variance."""
    width, height = pil_image.size
    if min(width, height) < BLANK_MIN_PAGE_DIMENSION:
        return False

    working = pil_image
    if width > 50 and height > 50:
        margin_x = max(1, int(width * 0.02))
        margin_y = max(1, int(height * 0.02))
        working = pil_image.crop(
            (margin_x, margin_y, width - margin_x, height - margin_y)
        )

    gray = working.convert("L")
    gray.thumbnail((512, 512))
    total_pixels = gray.width * gray.height
    if total_pixels <= 0:
        return False

    hist = gray.histogram()
    dark_pixels = sum(hist[:235])
    dark_ratio = dark_pixels / total_pixels
    stddev = ImageStat.Stat(gray).stddev[0]
    return dark_ratio < BLANK_MAX_DARK_PIXEL_RATIO and stddev < BLANK_MAX_STDDEV


def _page_has_vector_content(page: object) -> bool:
    """Return True if *page* has non-trivial drawing stream bytes."""
    try:
        contents = page.get_contents()  # type: ignore[attr-defined]
    except (*_PYPDF_ERRORS, OSError, ValueError, TypeError, KeyError):
        return True
    if contents is None:
        return False
    try:
        data = contents.get_data()
    except (*_PYPDF_ERRORS, OSError, ValueError, TypeError, KeyError):
        return True
    return len(data.strip()) > 0


def is_pdf_blank(pdf_path: Path) -> bool:
    """Conservatively return True only when every page in *pdf_path* is verified blank.

    Fails open (returns False) on unreadable/encrypted PDFs, vector graphics,
    undecodable embedded images, or synthetic sub-page fixtures so normal
    classification/error handling takes over.
    """
    try:
        reader = _open_unlocked_reader(pdf_path.read_bytes(), pdf_path.name)
    except OSError, ValueError:
        return False

    pages = list(reader.pages)
    if not pages:
        return True

    for page in pages:
        try:
            text = (page.extract_text() or "").strip()
        except (*_PYPDF_ERRORS, OSError, ValueError, TypeError, KeyError):
            return False
        if len(text) >= BLANK_MAX_TEXT_CHARS:
            return False

        try:
            images = list(page.images)
        except (*_PYPDF_ERRORS, OSError, ValueError, TypeError, KeyError):
            return False

        if not images:
            if _page_has_vector_content(page):
                return False
            box = page.mediabox
            if min(float(box.width), float(box.height)) < BLANK_MIN_PAGE_DIMENSION:
                return False
            continue

        saw_scanner_image = False
        for item in images:
            try:
                pil_img = item.image
            except OSError, ValueError, TypeError, NotImplementedError:
                return False
            if pil_img is None:
                return False
            if min(pil_img.size) >= BLANK_MIN_PAGE_DIMENSION:
                saw_scanner_image = True
            if not _image_is_blank(pil_img):
                return False
        if not saw_scanner_image:
            return False

    return True

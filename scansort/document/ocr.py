"""OCR text-layer engine: make raster PDFs searchable using tesseract + pypdf.

The engine extracts the embedded page image, runs Tesseract over it, and appends
an invisible text layer (render mode 3) to the page content stream. The original
image, DocInfo metadata, and XMP packet are preserved because pages are cloned
through ``PdfWriter.append`` before the layer is added.
"""

import io
import logging
import shutil
import sys
from pathlib import Path

import pytesseract
from pypdf import PasswordType, PdfReader, PdfWriter
from pypdf.errors import PyPdfError
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from scansort.core.fs import atomic_write

logger = logging.getLogger(__name__)

OCR_ENGINE_NAME = "tesseract"
DEFAULT_OCR_LANGUAGE = "eng"
MIN_OCR_CHARS_PER_PAGE = 25
_FONT_RESOURCE_NAME = "/ScanSortOcr"
_MAX_WORD_HEIGHT_RATIO = 0.85


class OcrError(RuntimeError):
    """Raised when a document cannot be OCR'd or its text layer cannot be built."""


class OcrUnavailableError(OcrError):
    """Raised when no tesseract binary can be located."""


_TESSERACT_ERRORS: tuple[type[BaseException], ...] = (pytesseract.TesseractError,)


def _bundled_tesseract_path() -> Path | None:
    """Return the tesseract binary shipped alongside a frozen ScanSort build.

    PyInstaller 6 one-folder builds place bundled binaries under ``_internal``
    (``sys._MEIPASS``), so check there before the executable's own directory.
    """
    if not getattr(sys, "frozen", False):
        return None
    search_dirs: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        search_dirs.append(Path(meipass))
    search_dirs.append(Path(sys.executable).parent)
    for base_dir in search_dirs:
        for name in ("tesseract.exe", "tesseract"):
            candidate = base_dir / "tesseract" / name
            if candidate.is_file():
                return candidate
    return None


def resolve_tesseract_cmd() -> Path | None:
    """Locate the tesseract binary, preferring the bundled copy in frozen builds."""
    bundled = _bundled_tesseract_path()
    if bundled is not None:
        return bundled
    which = shutil.which("tesseract")
    return Path(which) if which else None


def has_ocr_support() -> bool:
    """Return True when a usable tesseract binary is available."""
    return resolve_tesseract_cmd() is not None


def _open_reader(pdf_path: Path) -> PdfReader:
    """Parse *pdf_path* from an in-memory buffer, rejecting corrupt/encrypted files."""
    try:
        reader = PdfReader(io.BytesIO(pdf_path.read_bytes()))
    except (PyPdfError, OSError, ValueError, NotImplementedError, KeyError) as e:
        raise OcrError(f"PDF {pdf_path.name} is unreadable: {e}") from e
    if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
        raise OcrError(
            f"PDF {pdf_path.name} is password protected and cannot be OCR'd."
        )
    return reader


def _page_text_length(page: object) -> int:
    try:
        return len((page.extract_text() or "").strip())  # type: ignore[attr-defined]
    except PyPdfError, OSError, ValueError, TypeError, KeyError:
        return 0


def _reader_needs_ocr(reader: PdfReader, min_chars_per_page: int) -> bool:
    pages = list(reader.pages)
    if not pages:
        return False
    return any(_page_text_length(page) < min_chars_per_page for page in pages)


def needs_ocr(pdf_path: Path, min_chars_per_page: int = MIN_OCR_CHARS_PER_PAGE) -> bool:
    """Return True when *pdf_path* lacks a sufficient embedded text layer.

    Raises:
        OcrError: If the PDF is corrupt or password protected.
    """
    if not pdf_path.is_file():
        raise OcrError(f"PDF file not found: {pdf_path}")
    return _reader_needs_ocr(_open_reader(pdf_path), min_chars_per_page)


def _parse_ocr_data(
    data: dict,
) -> tuple[list[tuple[int, int, int, int, str]], float | None]:
    """Extract ``(left, top, width, height, text)`` word boxes and mean confidence."""
    words: list[tuple[int, int, int, int, str]] = []
    confidences: list[float] = []
    texts = data.get("text", [])
    for index, raw_text in enumerate(texts):
        text = str(raw_text or "").strip()
        if not text:
            continue
        try:
            confidence = int(float(data["conf"][index]))
        except KeyError, IndexError, ValueError, TypeError:
            confidence = -1
        if confidence < 0:
            continue
        words.append(
            (
                int(data["left"][index]),
                int(data["top"][index]),
                int(data["width"][index]),
                int(data["height"][index]),
                text,
            )
        )
        confidences.append(float(confidence))
    mean = sum(confidences) / len(confidences) if confidences else None
    return words, mean


def _escape_pdf_text(text: str) -> str:
    """Escape a word for a PDF literal string, degrading non-latin-1 to '?'."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return escaped.encode("latin-1", "replace").decode("latin-1")


def _extract_page_image(page: object):
    """Return ``(PIL.Image, (width, height))`` for a page's largest decodable image."""
    best = None
    best_area = -1
    try:
        images = list(page.images)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - pypdf image decoding raises varied errors
        return None
    for image_file in images:
        try:
            pil_image = image_file.image
        except Exception:  # noqa: BLE001 - skip undecodable embedded images
            continue
        if pil_image is None:
            continue
        area = pil_image.size[0] * pil_image.size[1]
        if area > best_area:
            best = pil_image
            best_area = area
    if best is None:
        return None
    return best, best.size


def _install_font_resource(writer: PdfWriter, page: object) -> None:
    """Ensure the page's resources expose the invisible-text Type1 font."""
    resources = page.get(NameObject("/Resources"))  # type: ignore[attr-defined]
    if resources is None:
        resources = DictionaryObject()
        page[NameObject("/Resources")] = resources  # type: ignore[index]
    else:
        resources = resources.get_object()
    fonts = resources.get(NameObject("/Font"))
    if fonts is None:
        fonts = DictionaryObject()
        resources[NameObject("/Font")] = fonts
    else:
        fonts = fonts.get_object()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    fonts[NameObject(_FONT_RESOURCE_NAME)] = writer._add_object(font)


def _build_overlay_stream(
    words: list[tuple[int, int, int, int, str]],
    image_size: tuple[int, int],
    page: object,
) -> bytes:
    """Build an invisible text content stream aligned to the page image."""
    image_width, image_height = image_size
    box = page.mediabox  # type: ignore[attr-defined]
    page_width = float(box.width)
    page_height = float(box.height)
    left_offset = float(box.left)
    bottom_offset = float(box.bottom)
    scale_x = page_width / image_width if image_width else 1.0
    scale_y = page_height / image_height if image_height else 1.0

    operators = ["q", "BT", "3 Tr"]
    for left, top, _width, height, text in words:
        font_size = max(1.0, height * scale_y * _MAX_WORD_HEIGHT_RATIO)
        x = left_offset + left * scale_x
        y = bottom_offset + (image_height - (top + height)) * scale_y
        operators.append(f"{_FONT_RESOURCE_NAME} {font_size:.2f} Tf")
        operators.append(f"1 0 0 1 {x:.2f} {y:.2f} Tm")
        operators.append(f"({_escape_pdf_text(text)}) Tj")
    operators.append("ET")
    operators.append("Q")
    return "\n".join(operators).encode("latin-1", "replace")


def _append_text_layer(
    writer: PdfWriter,
    page: object,
    words: list[tuple[int, int, int, int, str]],
    image_size: tuple[int, int],
) -> None:
    """Append a DecodedStreamObject carrying the invisible text layer to *page*."""
    _install_font_resource(writer, page)
    stream = DecodedStreamObject()
    stream.set_data(_build_overlay_stream(words, image_size, page))
    stream_ref = writer._add_object(stream)
    contents = page.get(NameObject("/Contents"))  # type: ignore[attr-defined]
    if contents is not None:
        contents = contents.get_object()
    if isinstance(contents, ArrayObject):
        contents.append(stream_ref)
    elif contents is None:
        page[NameObject("/Contents")] = stream_ref  # type: ignore[index]
    else:
        page[NameObject("/Contents")] = ArrayObject([contents, stream_ref])  # type: ignore[index]


def _copy_document_metadata(reader: PdfReader, writer: PdfWriter) -> None:
    """Re-attach DocInfo and XMP to a writer; ``append`` does not carry them over."""
    metadata = reader.metadata
    if metadata:
        try:
            writer.add_metadata({str(k): str(v) for k, v in metadata.items() if v})
        except (TypeError, ValueError) as e:
            logger.warning("Could not copy PDF DocInfo during OCR: %s", e)
    try:
        existing_xmp = reader.xmp_metadata
    except AttributeError, OSError, PyPdfError:
        existing_xmp = None
    if existing_xmp is not None:
        try:
            writer.xmp_metadata = existing_xmp
        except (TypeError, ValueError, AttributeError) as e:
            logger.warning("Could not copy PDF XMP during OCR: %s", e)


def _materialize_output(target: Path, pdf_path: Path) -> None:
    """Copy the source verbatim to an explicit ``output_path`` on no-rewrite paths."""
    if target != pdf_path:
        atomic_write(target, pdf_path.read_bytes())


def ocr_pdf_inplace(
    pdf_path: Path,
    language: str = DEFAULT_OCR_LANGUAGE,
    output_path: Path | None = None,
) -> tuple[Path, float | None]:
    """Add an invisible OCR text layer to *pdf_path*.

    Pages that already carry native text are left untouched. Text-less pages
    with no extractable image (e.g. genuinely blank pages) are skipped. When no
    page receives a text layer the file is returned byte-stable without a rewrite.

    Returns:
        ``(target_path, mean_confidence)`` where confidence is ``None`` when no
        new text was embedded.

    Raises:
        OcrUnavailableError: If tesseract cannot be located.
        OcrError: If the PDF is corrupt/encrypted or OCR fails.
    """
    target = output_path or pdf_path
    tesseract_cmd = resolve_tesseract_cmd()
    if tesseract_cmd is None:
        raise OcrUnavailableError(
            "OCR requires the tesseract binary, which was not found."
        )
    pytesseract.pytesseract.tesseract_cmd = str(tesseract_cmd)

    reader = _open_reader(pdf_path)
    pages = list(reader.pages)
    if not pages:
        _materialize_output(target, pdf_path)
        return target, None

    pages_needing = [
        index
        for index, page in enumerate(pages)
        if _page_text_length(page) < MIN_OCR_CHARS_PER_PAGE
    ]
    if not pages_needing:
        _materialize_output(target, pdf_path)
        return target, None

    writer = PdfWriter()
    try:
        writer.append(reader)
    except (PyPdfError, OSError, ValueError) as e:
        raise OcrError(f"Could not reparse {pdf_path.name} for OCR: {e}") from e
    _copy_document_metadata(reader, writer)

    confidences: list[float] = []
    overlay_added = False
    for index in pages_needing:
        page = writer.pages[index]
        extracted = _extract_page_image(page)
        if extracted is None:
            logger.info(
                "Page %d of %s has no extractable image; skipping.",
                index + 1,
                pdf_path.name,
            )
            continue
        pil_image, image_size = extracted
        try:
            data = pytesseract.image_to_data(
                pil_image, lang=language, output_type=pytesseract.Output.DICT
            )
        except (OSError, RuntimeError, ValueError, *_TESSERACT_ERRORS) as e:
            raise OcrError(f"OCR failed for {pdf_path.name}: {e}") from e
        words, confidence = _parse_ocr_data(data)
        if not words:
            continue
        _append_text_layer(writer, page, words, image_size)
        overlay_added = True
        if confidence is not None:
            confidences.append(confidence)

    if not overlay_added:
        _materialize_output(target, pdf_path)
        return target, None

    try:
        atomic_write(target, lambda out: writer.write(out))
    except (PyPdfError, OSError, ValueError) as e:
        raise OcrError(f"Could not write OCR output for {pdf_path.name}: {e}") from e
    mean_confidence = sum(confidences) / len(confidences) if confidences else None
    logger.info(
        "Embedded OCR text layer into %s (pages OCR'd: %d).",
        target.name,
        len(pages_needing),
    )
    return target, mean_confidence

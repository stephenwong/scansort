"""Document conversion, image normalization, and PDF metadata enrichment."""

from scansort.document.converter import convert_to_pdf, is_supported_format
from scansort.document.metadata import process_pdf_metadata_and_rotation
from scansort.document.ocr import (
    OCR_ENGINE_NAME,
    OcrError,
    OcrUnavailableError,
    has_ocr_support,
    needs_ocr,
    ocr_pdf_inplace,
    resolve_tesseract_cmd,
)
from scansort.document.preview import is_pdf_blank, prepare_pdf_for_classification

__all__ = [
    "convert_to_pdf",
    "is_pdf_blank",
    "is_supported_format",
    "prepare_pdf_for_classification",
    "process_pdf_metadata_and_rotation",
    "OCR_ENGINE_NAME",
    "OcrError",
    "OcrUnavailableError",
    "has_ocr_support",
    "needs_ocr",
    "ocr_pdf_inplace",
    "resolve_tesseract_cmd",
]

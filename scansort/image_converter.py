"""Image and document normalization engine converting incoming scans to PDF format."""

import logging
from pathlib import Path

import img2pdf
from PIL import Image

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: set[str] = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".tiff",
    ".tif",
}


def is_supported_format(path: Path) -> bool:
    """Check if the given file has a supported document or image extension."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def convert_to_pdf(input_path: Path, output_path: Path | None = None) -> Path:
    """Normalize an incoming document (PDF, JPG, PNG, TIFF) into a standard PDF file.

    Args:
        input_path: Path to the source file.
        output_path: Optional explicit destination path. If omitted, uses input name with .pdf suffix.

    Returns:
        Path to the output PDF file.

    Raises:
        ValueError: If the file format is not supported.
    """
    ext = input_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file format '{ext}' for file {input_path.name}. "
            f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    # If it is already a PDF and no custom output path is requested, passthrough
    if ext == ".pdf" and (output_path is None or output_path == input_path):
        return input_path

    target_pdf = output_path or input_path.with_suffix(".pdf")
    target_pdf.parent.mkdir(parents=True, exist_ok=True)

    if ext in {".jpg", ".jpeg"}:
        # Lossless wrapping of JPEG streams via img2pdf (preserves exact DPI and zero re-compression)
        try:
            with open(input_path, "rb") as src, open(target_pdf, "wb") as dst:
                img2pdf.convert(src, outputstream=dst)
            logger.debug("Wrapped JPEG %s into PDF %s losslessly.", input_path.name, target_pdf.name)
            return target_pdf
        except (img2pdf.ImageOpenError, img2pdf.PdfTooLargeError, OSError, ValueError) as e:
            logger.warning("img2pdf failed on %s (%s). Falling back to Pillow.", input_path.name, e)

    # For PNG, TIFF, or fallback: use Pillow
    with Image.open(input_path) as img:
        # Convert RGBA or CMYK to RGB
        rgb_img = img.convert("RGB")
        rgb_img.save(target_pdf, format="PDF", resolution=img.info.get("dpi", (300, 300))[0])

    logger.debug("Converted image %s to PDF %s via Pillow.", input_path.name, target_pdf.name)
    return target_pdf

"""Document conversion and normalization to standard PDF."""

import logging
import shutil
from pathlib import Path

import img2pdf
from PIL import Image, ImageOps, ImageSequence

from scansort.core.constants import DEFAULT_DPI, SUPPORTED_EXTENSIONS
from scansort.core.fs import atomic_write

logger = logging.getLogger(__name__)


def is_supported_format(path: Path) -> bool:
    """Check if the given file has a supported document or image extension."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


_HIGH_BIT_GRAY_MODES: tuple[str, ...] = ("I", "I;16", "I;16B", "I;16L")

# img2pdf raises these for inputs it cannot wrap losslessly; Pillow fallback handles them.
_IMG2PDF_FALLBACK_ERRORS: tuple[type[BaseException], ...] = (
    img2pdf.ImageOpenError,
    img2pdf.PdfTooLargeError,
    img2pdf.ExifOrientationError,
    img2pdf.AlphaChannelError,
    img2pdf.JpegColorspaceError,
    img2pdf.UnsupportedColorspaceError,
    img2pdf.NegativeDimensionError,
    OSError,
    ValueError,
)


def _normalize_frame_to_rgb(frame: Image.Image) -> Image.Image:
    """Safely convert an image frame to RGB, compositing alpha channels onto white."""
    if frame.mode in _HIGH_BIT_GRAY_MODES:
        # 16-bit/int grayscale must be scaled 16->8 bits; Pillow's convert("RGB")
        # saturates every sample >= 256 to 255, blanking real scans.
        scaled = frame.point(lambda v: v * (255 / 65535))
        return scaled.convert("L").convert("RGB")
    if frame.mode in ("RGBA", "LA") or (
        frame.mode == "P" and "transparency" in frame.info
    ):
        rgba = frame.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        alpha_composite = Image.alpha_composite(background, rgba)
        return alpha_composite.convert("RGB")
    return frame.convert("RGB")


def _extract_dpi(img: Image.Image, default: float = DEFAULT_DPI) -> float:
    """Extract DPI resolution from image info metadata or return default."""
    dpi_info = img.info.get("dpi")
    if isinstance(dpi_info, (tuple, list)) and len(dpi_info) > 0:
        try:
            val = float(dpi_info[0])
            if val > 0:
                return val
        except ValueError, TypeError:
            pass
    elif isinstance(dpi_info, (int, float)) and dpi_info > 0:
        return float(dpi_info)
    return default


def _convert_jpeg_lossless(input_path: Path, target_pdf: Path) -> None:
    """Lossless wrapping of JPEG streams via img2pdf (preserves exact DPI and zero re-compression)."""
    with open(input_path, "rb") as src:
        atomic_write(target_pdf, lambda out: img2pdf.convert(src, outputstream=out))
    logger.info(
        "Wrapped JPEG %s into PDF %s losslessly via img2pdf.",
        input_path.name,
        target_pdf.name,
    )


def _convert_image_via_pillow(input_path: Path, target_pdf: Path) -> int:
    """Convert an image to PDF via Pillow supporting multi-frame images."""
    with Image.open(input_path) as img:
        frames = [
            _normalize_frame_to_rgb(ImageOps.exif_transpose(frame))
            for frame in ImageSequence.Iterator(img)
        ]
        first_frame = frames[0]
        append_frames = frames[1:]
        res = _extract_dpi(img)

        atomic_write(
            target_pdf,
            lambda out: first_frame.save(
                out,
                format="PDF",
                save_all=True,
                append_images=append_frames,
                resolution=res,
            ),
        )
        page_count = len(frames)

    logger.info(
        "Converted image %s to PDF %s via Pillow (%d pages, %.0f DPI).",
        input_path.name,
        target_pdf.name,
        page_count,
        res,
    )
    return page_count


def convert_to_pdf(input_path: Path, output_path: Path | None = None) -> Path:
    """Normalize an incoming document (PDF, JPG, PNG, TIFF) into a standard PDF file.

    Args:
        input_path: Path to the source file.
        output_path: Optional explicit destination path. If omitted, uses input name with .pdf suffix.

    Returns:
        Path to the output PDF file.

    Raises:
        FileNotFoundError: If input_path does not exist.
        ValueError: If the file format is not supported.
    """
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if not is_supported_format(input_path):
        ext = input_path.suffix.lower()
        raise ValueError(
            f"Unsupported file format '{ext}' for file {input_path.name}. "
            f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    ext = input_path.suffix.lower()

    # If it is already a PDF, passthrough or copy
    if ext == ".pdf":
        if output_path is None or output_path.resolve() == input_path.resolve():
            return input_path
        target_pdf = output_path
        target_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, target_pdf)
        return target_pdf

    target_pdf = output_path or input_path.with_suffix(".pdf")
    if output_path is not None and target_pdf.resolve() == input_path.resolve():
        raise ValueError(f"output_path must differ from the input file: {input_path}")
    target_pdf.parent.mkdir(parents=True, exist_ok=True)

    try:
        if ext in {".jpg", ".jpeg"}:
            try:
                _convert_jpeg_lossless(input_path, target_pdf)
                return target_pdf
            except _IMG2PDF_FALLBACK_ERRORS as e:
                logger.warning(
                    "img2pdf failed on %s (%s). Falling back to Pillow.",
                    input_path.name,
                    e,
                )

        _convert_image_via_pillow(input_path, target_pdf)
        return target_pdf

    except Exception:
        # Clean up any incomplete or 0-byte output file on conversion failure (S3-04)
        if target_pdf.exists() and target_pdf.resolve() != input_path.resolve():
            target_pdf.unlink(missing_ok=True)
        raise

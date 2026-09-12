"""Document conversion and normalization to standard PDF."""

import logging
import shutil
from pathlib import Path
from typing import Any

import img2pdf
from PIL import Image, ImageOps, ImageSequence

from scansort.core.constants import DEFAULT_DPI, SUPPORTED_EXTENSIONS
from scansort.core.fs import atomic_write

logger = logging.getLogger(__name__)


def is_supported_format(path: Path) -> bool:
    """Check if the given file has a supported document or image extension."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


_HIGH_BIT_GRAY_MODES: tuple[str, ...] = ("I", "I;16", "I;16B", "I;16L", "I;16N")

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
        # saturates every sample >= 256 to 255, blanking real scans. Byte-swapped
        # and native-endian variants (I;16B/L/N) reject point() directly, so all
        # high-bit modes are funneled through the canonical "I" mode first.
        canonical = frame.convert("I")
        if frame.mode == "I":
            # Plain 32-bit "I" is not range-bounded: some writers store 0-255
            # samples there, which the 16-bit divisor would collapse to black.
            _, high = canonical.getextrema()
            if high <= 255:
                return canonical.convert("L").convert("RGB")
        scaled = canonical.point(lambda v: v * (255 / 65535))
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
    # img2pdf wraps DPI-less JPEGs at its own 96 dpi default, inconsistent with
    # the Pillow path's DEFAULT_DPI; supply a fixed layout for that case only.
    with Image.open(input_path) as probe:
        has_dpi = bool(probe.info.get("dpi"))
    kwargs: dict[str, Any] = {}
    if not has_dpi:
        kwargs["layout_fun"] = img2pdf.get_fixed_dpi_layout_fun(
            (DEFAULT_DPI, DEFAULT_DPI)
        )
    with open(input_path, "rb") as src:
        atomic_write(
            target_pdf, lambda out: img2pdf.convert(src, outputstream=out, **kwargs)
        )
    logger.info(
        "Wrapped JPEG %s into PDF %s losslessly via img2pdf.",
        input_path.name,
        target_pdf.name,
    )


def _convert_image_via_pillow(input_path: Path, target_pdf: Path) -> int:
    """Convert an image to PDF via Pillow supporting multi-frame images."""
    with Image.open(input_path) as img:
        # Normalize lazily: multi-page TIFFs can be hundreds of MB when every
        # frame is converted to RGB at once, so the first frame is materialized
        # eagerly and the rest are streamed to Pillow's PDF writer as a generator.
        frame_iterator = ImageSequence.Iterator(img)
        first_frame = _normalize_frame_to_rgb(
            ImageOps.exif_transpose(next(frame_iterator))
        )
        page_count = 1

        def _remaining_frames():
            nonlocal page_count
            for frame in frame_iterator:
                page_count += 1
                yield _normalize_frame_to_rgb(ImageOps.exif_transpose(frame))

        res = _extract_dpi(img)

        atomic_write(
            target_pdf,
            lambda out: first_frame.save(
                out,
                format="PDF",
                save_all=True,
                append_images=_remaining_frames(),
                resolution=res,
            ),
        )

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

    # If it is already a PDF, passthrough or copy (atomically: a partial copy
    # must never truncate an existing target).
    if ext == ".pdf":
        if output_path is None or output_path.resolve() == input_path.resolve():
            return input_path
        target_pdf = output_path
        target_pdf.parent.mkdir(parents=True, exist_ok=True)
        with open(input_path, "rb") as src:
            atomic_write(target_pdf, lambda out: shutil.copyfileobj(src, out))
        return target_pdf

    target_pdf = output_path or input_path.with_suffix(".pdf")
    if output_path is not None and target_pdf.resolve() == input_path.resolve():
        raise ValueError(f"output_path must differ from the input file: {input_path}")
    target_pdf.parent.mkdir(parents=True, exist_ok=True)

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

import io
import logging
import shutil
from pathlib import Path

import img2pdf
from PIL import Image, ImageSequence

from scansort.constants import SUPPORTED_EXTENSIONS
from scansort.fs_utils import atomic_write

logger = logging.getLogger(__name__)


def is_supported_format(path: Path) -> bool:
    """Check if the given file has a supported document or image extension."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _normalize_frame_to_rgb(frame: Image.Image) -> Image.Image:
    """Safely convert an image frame to RGB, compositing alpha channels onto white."""
    if frame.mode in ("RGBA", "LA") or (
        frame.mode == "P" and "transparency" in frame.info
    ):
        rgba = frame.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        alpha_composite = Image.alpha_composite(background, rgba)
        return alpha_composite.convert("RGB")
    return frame.convert("RGB")


def _extract_dpi(img: Image.Image, default: float = 300.0) -> float:
    """Extract DPI resolution from image info metadata or return default."""
    dpi_info = img.info.get("dpi")
    if isinstance(dpi_info, (tuple, list)) and len(dpi_info) > 0:
        try:
            val = float(dpi_info[0])
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass
    elif isinstance(dpi_info, (int, float)) and dpi_info > 0:
        return float(dpi_info)
    return default


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
    target_pdf.parent.mkdir(parents=True, exist_ok=True)

    try:
        if ext in {".jpg", ".jpeg"}:
            # Lossless wrapping of JPEG streams via img2pdf (preserves exact DPI and zero re-compression)
            try:
                buf = io.BytesIO()
                with open(input_path, "rb") as src:
                    img2pdf.convert(src, outputstream=buf)
                atomic_write(target_pdf, buf.getvalue())
                logger.debug(
                    "Wrapped JPEG %s into PDF %s losslessly.",
                    input_path.name,
                    target_pdf.name,
                )
                return target_pdf
            except (
                img2pdf.ImageOpenError,
                img2pdf.PdfTooLargeError,
                OSError,
                ValueError,
            ) as e:
                logger.warning(
                    "img2pdf failed on %s (%s). Falling back to Pillow.",
                    input_path.name,
                    e,
                )

        # For PNG, TIFF, or fallback: use Pillow supporting multi-frame images
        with Image.open(input_path) as img:
            frames = [
                _normalize_frame_to_rgb(frame) for frame in ImageSequence.Iterator(img)
            ]
            first_frame = frames[0]
            append_frames = frames[1:]
            res = _extract_dpi(img)

            buf = io.BytesIO()
            first_frame.save(
                buf,
                format="PDF",
                save_all=True,
                append_images=append_frames,
                resolution=res,
            )
            atomic_write(target_pdf, buf.getvalue())

        logger.debug(
            "Converted image %s to PDF %s via Pillow (%d pages).",
            input_path.name,
            target_pdf.name,
            len(frames),
        )
        return target_pdf

    except Exception:
        # Clean up any incomplete or 0-byte output file on conversion failure (S3-04)
        if target_pdf.exists() and (
            output_path is not None or target_pdf != input_path
        ):
            target_pdf.unlink(missing_ok=True)
        raise

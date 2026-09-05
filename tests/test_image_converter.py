"""Unit tests for scansort.image_converter module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from pypdf import PdfReader

from scansort.image_converter import (
    _extract_dpi,
    convert_to_pdf,
    is_supported_format,
)


def _create_sample_image(
    path: Path, img_format: str = "JPEG", size=(100, 100), color="white"
):
    img = Image.new("RGB", size, color=color)
    img.save(path, format=img_format)


def test_is_supported_format():
    assert is_supported_format(Path("scan.pdf")) is True
    assert is_supported_format(Path("scan.PDF")) is True
    assert is_supported_format(Path("scan.jpg")) is True
    assert is_supported_format(Path("scan.jpeg")) is True
    assert is_supported_format(Path("scan.png")) is True
    assert is_supported_format(Path("scan.tiff")) is True
    assert is_supported_format(Path("scan.txt")) is False
    assert is_supported_format(Path("scan.tmp")) is False


def test_pdf_passthrough(tmp_path: Path):
    pdf_file = tmp_path / "original.pdf"
    pdf_file.write_bytes(b"%PDF-1.5 test content")

    result = convert_to_pdf(pdf_file)
    assert result == pdf_file
    assert result.read_bytes().startswith(b"%PDF")


def test_convert_jpeg_to_pdf(tmp_path: Path):
    jpg_file = tmp_path / "scan.jpg"
    _create_sample_image(jpg_file, img_format="JPEG")

    pdf_result = convert_to_pdf(jpg_file)
    assert pdf_result.exists()
    assert pdf_result.suffix.lower() == ".pdf"
    assert pdf_result.read_bytes().startswith(b"%PDF")


def test_convert_png_to_pdf(tmp_path: Path):
    png_file = tmp_path / "scan.png"
    _create_sample_image(png_file, img_format="PNG")

    pdf_result = convert_to_pdf(png_file)
    assert pdf_result.exists()
    assert pdf_result.suffix.lower() == ".pdf"
    assert pdf_result.read_bytes().startswith(b"%PDF")


def test_unsupported_format_raises(tmp_path: Path):
    text_file = tmp_path / "readme.txt"
    text_file.write_text("Hello world", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported file format"):
        convert_to_pdf(text_file)


def test_convert_jpeg_fallback_to_pillow(tmp_path: Path):
    jpg_file = tmp_path / "scan_fallback.jpg"
    _create_sample_image(jpg_file, img_format="JPEG")

    with patch("img2pdf.convert", side_effect=OSError("img2pdf failed")):
        pdf_result = convert_to_pdf(jpg_file)
        assert pdf_result.exists()
        assert pdf_result.suffix.lower() == ".pdf"
        assert pdf_result.read_bytes().startswith(b"%PDF")


def test_multipage_tiff_preserves_all_pages(tmp_path: Path):
    tiff_file = tmp_path / "scan.tiff"
    f1 = Image.new("RGB", (50, 50), "red")
    f2 = Image.new("RGB", (50, 50), "green")
    f1.save(tiff_file, save_all=True, append_images=[f2])

    out_pdf = convert_to_pdf(tiff_file)
    reader = PdfReader(out_pdf)
    assert len(reader.pages) == 2


def test_convert_pdf_to_custom_output_path(tmp_path: Path):
    input_pdf = tmp_path / "source.pdf"
    input_pdf.write_bytes(b"%PDF-1.5 test")
    dest_pdf = tmp_path / "destination.pdf"

    result = convert_to_pdf(input_pdf, output_path=dest_pdf)
    assert result == dest_pdf
    assert dest_pdf.exists()
    assert dest_pdf.read_bytes() == b"%PDF-1.5 test"


def test_convert_to_pdf_missing_file_raises_file_not_found(tmp_path: Path):
    missing = tmp_path / "nonexistent.jpg"
    with pytest.raises(FileNotFoundError, match="Input file not found"):
        convert_to_pdf(missing)


def test_convert_to_pdf_same_file_syntactic_difference(tmp_path: Path):
    input_pdf = tmp_path / "doc.pdf"
    input_pdf.write_bytes(b"%PDF-1.5 content")

    # Relative path vs absolute path to the same file
    rel_path = Path(input_pdf.name)
    # Run with cwd = tmp_path
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        res = convert_to_pdf(rel_path, output_path=input_pdf.resolve())
        assert res.resolve() == input_pdf.resolve()
    finally:
        os.chdir(old_cwd)


def test_convert_to_pdf_rgba_composited_on_white_background(tmp_path: Path):
    png_path = tmp_path / "transparent.png"
    # Transparent image (fully transparent red)
    img = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
    img.save(png_path, format="PNG")

    pdf_path = tmp_path / "transparent.pdf"
    convert_to_pdf(png_path, output_path=pdf_path)

    reader = PdfReader(pdf_path)
    page = reader.pages[0]
    # Extract image from page and verify background pixel is white (255, 255, 255) not black (0, 0, 0)
    for img_obj in page.images:
        extracted = img_obj.image.convert("RGB")
        pixel = extracted.getpixel((0, 0))
        assert pixel == (255, 255, 255)


def test_convert_to_pdf_malformed_dpi(tmp_path: Path):
    img_path = tmp_path / "odd_dpi.png"

    # Test empty tuple DPI
    img = Image.new("RGB", (10, 10), "white")
    img.info["dpi"] = ()
    img.save(img_path, format="PNG")

    out_pdf = convert_to_pdf(img_path)
    assert out_pdf.exists()

    # Test None DPI
    img.info["dpi"] = None
    img.save(img_path, format="PNG")
    out_pdf2 = convert_to_pdf(img_path)
    assert out_pdf2.exists()


def test_convert_to_pdf_failed_conversion_cleans_up_target(tmp_path: Path):
    img_path = tmp_path / "valid.jpg"
    _create_sample_image(img_path, img_format="JPEG")
    target_pdf = tmp_path / "failed.pdf"

    with (
        patch("img2pdf.convert", side_effect=ValueError("Encoding error")),
        patch.object(Image.Image, "save", side_effect=RuntimeError("Pillow failed")),
        pytest.raises(RuntimeError),
    ):
        convert_to_pdf(img_path, output_path=target_pdf)

    # Failed conversion must not leak a 0-byte PDF
    assert not target_pdf.exists()


def test_extract_dpi_edge_cases():
    img = Image.new("RGB", (10, 10))
    # Scalar DPI
    img.info["dpi"] = 150
    assert _extract_dpi(img) == 150.0

    # Invalid string in tuple
    img.info["dpi"] = ("invalid",)
    assert _extract_dpi(img) == 300.0


def test_convert_to_pdf_unlinks_existing_target_on_failure(tmp_path: Path):
    img_path = tmp_path / "valid.jpg"
    _create_sample_image(img_path, img_format="JPEG")
    target_pdf = tmp_path / "failed.pdf"
    target_pdf.write_bytes(b"existing partial")

    with (
        patch("img2pdf.convert", side_effect=ValueError("Encoding error")),
        patch.object(Image.Image, "save", side_effect=RuntimeError("Pillow failed")),
        pytest.raises(RuntimeError),
    ):
        convert_to_pdf(img_path, output_path=target_pdf)

    assert not target_pdf.exists()

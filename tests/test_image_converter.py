"""Unit tests for scansort.image_converter module."""

from pathlib import Path

import pytest
from PIL import Image

from scansort.image_converter import convert_to_pdf, is_supported_format


def _create_sample_image(path: Path, img_format: str = "JPEG", size=(100, 100), color="white"):
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

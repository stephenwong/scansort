"""Unit tests for scansort.image_converter module."""

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from pypdf import PdfReader

from scansort.document.converter import (
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


def test_convert_to_pdf_same_file_syntactic_difference(tmp_path: Path, monkeypatch):
    input_pdf = tmp_path / "doc.pdf"
    input_pdf.write_bytes(b"%PDF-1.5 content")

    # Relative path vs absolute path to the same file
    monkeypatch.chdir(tmp_path)
    rel_path = Path(input_pdf.name)
    res = convert_to_pdf(rel_path, output_path=input_pdf.resolve())
    assert res.resolve() == input_pdf.resolve()


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


def test_convert_to_pdf_failure_preserves_pre_existing_target(tmp_path: Path):
    img_path = tmp_path / "valid.jpg"
    _create_sample_image(img_path, img_format="JPEG")
    target_pdf = tmp_path / "precious.pdf"
    target_pdf.write_bytes(b"existing valid pdf")

    with (
        patch("img2pdf.convert", side_effect=ValueError("Encoding error")),
        patch.object(Image.Image, "save", side_effect=RuntimeError("Pillow failed")),
        pytest.raises(RuntimeError),
    ):
        convert_to_pdf(img_path, output_path=target_pdf)

    # atomic_write only ever replaces the target on success, so a target that
    # exists after a failure must be the caller's pre-existing file.
    assert target_pdf.read_bytes() == b"existing valid pdf"


def test_convert_to_pdf_failure_leaves_no_partial_target(tmp_path: Path):
    img_path = tmp_path / "valid.jpg"
    _create_sample_image(img_path, img_format="JPEG")
    target_pdf = tmp_path / "fresh.pdf"

    with (
        patch("img2pdf.convert", side_effect=ValueError("Encoding error")),
        patch.object(Image.Image, "save", side_effect=RuntimeError("Pillow failed")),
        pytest.raises(RuntimeError),
    ):
        convert_to_pdf(img_path, output_path=target_pdf)

    assert not target_pdf.exists()


def test_convert_to_pdf_failure_never_deletes_input_file(tmp_path: Path):
    img_path = tmp_path / "original.jpg"
    _create_sample_image(img_path, img_format="JPEG")
    original = img_path.read_bytes()

    # A failed conversion with a distinct output path must not delete the input.
    with (
        patch("img2pdf.convert", side_effect=ValueError("Encoding error")),
        patch.object(Image.Image, "save", side_effect=RuntimeError("Pillow failed")),
        pytest.raises(RuntimeError),
    ):
        convert_to_pdf(img_path, output_path=tmp_path / "out.pdf")

    assert img_path.read_bytes() == original


def test_convert_to_pdf_same_path_guard_preserves_input(tmp_path: Path):
    img_path = tmp_path / "original.jpg"
    _create_sample_image(img_path, img_format="JPEG")
    original = img_path.read_bytes()

    with pytest.raises(ValueError, match="output_path"):
        convert_to_pdf(img_path, output_path=img_path)

    assert img_path.read_bytes() == original, "Input must never be overwritten"


def test_16bit_grayscale_preserved_not_saturated(tmp_path: Path):
    """16-bit grayscale scans must scale to 8-bit, not saturate to blank."""
    from scansort.document.converter import convert_to_pdf

    src = tmp_path / "deep16.png"
    img = Image.new("I;16", (64, 64))
    pixels = img.load()
    for y in range(64):
        for x in range(64):
            pixels[x, y] = 6000  # typical ink level (~9% reflectance)
    img.save(src, format="PNG")

    pdf_out = convert_to_pdf(src, output_path=tmp_path / "deep16.pdf")

    with Image.open(src) as check:
        assert check.mode == "I;16"
    reader = PdfReader(pdf_out)
    page_img = reader.pages[0].images[0]
    extracted = Image.open(BytesIO(page_img.data)).convert("L")
    min_px, max_px = extracted.getextrema()
    # Saturated output would be near-white (>=250); scaled output stays dark.
    assert max_px < 80, f"16-bit content saturated to {max_px}"


def test_mirror_orientation_jpeg_converts(tmp_path: Path):
    """EXIF mirror-orientation JPEGs must fall back to Pillow and flip."""
    from scansort.document.converter import convert_to_pdf

    src = tmp_path / "mirrored.jpg"
    img = Image.new("RGB", (120, 60), "white")
    for y in range(60):
        for x in range(60):
            img.putpixel((x, y), (255, 0, 0))  # left half red
    for y in range(60):
        for x in range(60, 120):
            img.putpixel((x, y), (0, 0, 255))  # right half blue
    exif = Image.Exif()
    exif[0x0112] = 2  # Mirror horizontal
    img.save(src, format="JPEG", exif=exif)

    pdf_out = convert_to_pdf(src, output_path=tmp_path / "mirrored.pdf")
    assert pdf_out.exists()

    page_img = PdfReader(pdf_out).pages[0].images[0]
    extracted = Image.open(BytesIO(page_img.data)).convert("RGB")
    # Orientation=2 mirrors horizontally: blue should now be on the LEFT.
    left_px = extracted.getpixel((5, 30))
    assert left_px[2] > 200 and left_px[0] < 60, (
        f"expected mirrored left-blue, got {left_px}"
    )
    right_px = extracted.getpixel((115, 30))
    assert right_px[0] > 200 and right_px[2] < 60, f"expected right-red, got {right_px}"


@pytest.mark.parametrize("mode", ["I", "I;16", "I;16B", "I;16L", "I;16N"])
def test_normalize_high_bit_gray_modes_no_crash_no_saturation(mode):
    """All high-bit gray modes must normalize without ValueError or white saturation."""
    from scansort.document.converter import _normalize_frame_to_rgb

    frame = Image.new(mode, (16, 16), 6000)
    rgb = _normalize_frame_to_rgb(frame)

    assert rgb.mode == "RGB"
    # A 6000/65535 sample must map dark, not saturate to white.
    extrema = rgb.getextrema()
    assert all(channel_max < 128 for _, channel_max in extrema)


def test_convert_16bit_tiff_end_to_end(tmp_path: Path):
    """A 16-bit TIFF scan must convert to PDF without ValueError."""
    img_path = tmp_path / "scan16.tiff"
    Image.new("I;16", (16, 16), 6000).save(img_path, format="TIFF")

    out = convert_to_pdf(img_path)

    assert out.exists() and out.stat().st_size > 0
    assert out.read_bytes()[:5] == b"%PDF-"


def test_convert_dpi_less_jpeg_matches_png_page_size(tmp_path: Path):
    """A DPI-less JPEG must get the same physical page size as a DPI-less PNG."""
    jpeg_path = tmp_path / "plain.jpg"
    png_path = tmp_path / "plain.png"
    Image.new("RGB", (300, 300)).save(jpeg_path, format="JPEG")  # no dpi info
    Image.new("RGB", (300, 300)).save(png_path, format="PNG")

    jpeg_out = convert_to_pdf(jpeg_path)
    png_out = convert_to_pdf(png_path)

    from pypdf import PdfReader

    jpeg_box = PdfReader(str(jpeg_out)).pages[0].mediabox
    png_box = PdfReader(str(png_out)).pages[0].mediabox
    assert abs(float(jpeg_box.width) - float(png_box.width)) < 2.0
    assert abs(float(jpeg_box.height) - float(png_box.height)) < 2.0


def test_convert_pdf_passthrough_atomic_on_failure(tmp_path: Path):
    """A failing passthrough copy must not truncate an existing target."""
    src_pdf = tmp_path / "source.pdf"
    src_pdf.write_bytes(b"%PDF-1.4 original bytes")
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"%PDF-1.4 previous content")

    with (
        patch("shutil.copyfileobj", side_effect=OSError("disk full")),
        pytest.raises(OSError),
    ):
        convert_to_pdf(src_pdf, output_path=target)

    assert target.read_bytes() == b"%PDF-1.4 previous content"

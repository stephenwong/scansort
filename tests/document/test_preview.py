"""Unit tests for PDF classification preview capping and local blank-page detection."""

import io
from pathlib import Path

import img2pdf
import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter

from scansort.document.preview import is_pdf_blank, prepare_pdf_for_classification


def _make_multipage_pdf(path: Path, num_pages: int, *, with_text: bool = True) -> Path:
    """Create a multi-page PDF using ReportLab-free content streams via PIL/img2pdf."""
    page_images: list[bytes] = []
    for idx in range(num_pages):
        img = Image.new("RGB", (500, 650), "white")
        if with_text:
            draw = ImageDraw.Draw(img)
            draw.rectangle([40, 40, 260, 120], fill="black")
            draw.text((50, 150), f"Page {idx + 1}", fill="black")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        page_images.append(buf.getvalue())

    path.write_bytes(img2pdf.convert(page_images))
    return path


def test_prepare_pdf_returns_small_pdf_unchanged(tmp_path: Path):
    pdf_path = _make_multipage_pdf(tmp_path / "three_pages.pdf", 3)
    original_bytes = pdf_path.read_bytes()

    preview_bytes = prepare_pdf_for_classification(pdf_path, max_pages=4)
    assert preview_bytes == original_bytes


def test_prepare_pdf_caps_pages_without_mutating_source(tmp_path: Path):
    pdf_path = _make_multipage_pdf(tmp_path / "seven_pages.pdf", 7)
    original_bytes = pdf_path.read_bytes()

    preview_bytes = prepare_pdf_for_classification(pdf_path, max_pages=4)

    assert len(PdfReader(io.BytesIO(preview_bytes)).pages) == 4
    # Source file on disk remains untouched with all 7 pages
    assert pdf_path.read_bytes() == original_bytes
    assert len(PdfReader(io.BytesIO(pdf_path.read_bytes())).pages) == 7


def test_prepare_pdf_shrinks_pages_and_downscales_to_fit_max_bytes(tmp_path: Path):
    # Large noisy image that compresses into ~80-150 KB per page
    rng_img = Image.effect_noise((1200, 1600), 80.0).convert("RGB")
    buf = io.BytesIO()
    rng_img.save(buf, format="JPEG", quality=95)
    img_bytes = buf.getvalue()

    pdf_path = tmp_path / "heavy.pdf"
    pdf_path.write_bytes(img2pdf.convert([img_bytes, img_bytes, img_bytes]))

    # Cap aggressively to force page reduction and image downscaling
    max_bytes = 60 * 1024
    preview_bytes = prepare_pdf_for_classification(
        pdf_path, max_pages=4, max_bytes=max_bytes
    )

    assert len(preview_bytes) <= max_bytes
    assert len(PdfReader(io.BytesIO(preview_bytes)).pages) == 1


def test_prepare_pdf_rejects_corrupt_or_encrypted_pdf(tmp_path: Path):
    bad_pdf = tmp_path / "corrupt.pdf"
    bad_pdf.write_bytes(b"not a pdf")
    with pytest.raises(ValueError, match="unreadable"):
        prepare_pdf_for_classification(bad_pdf)

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    enc_pdf = tmp_path / "locked.pdf"
    with enc_pdf.open("wb") as f:
        writer.write(f)

    with pytest.raises(ValueError, match="password protected"):
        prepare_pdf_for_classification(enc_pdf)


def test_is_pdf_blank_detects_pure_white_scanner_pages(tmp_path: Path):
    # Pure white scanner-sized image PDF (e.g. 800x1000)
    blank_pdf = _make_multipage_pdf(tmp_path / "blank_scan.pdf", 2, with_text=False)
    assert is_pdf_blank(blank_pdf) is True


def test_is_pdf_blank_tolerates_subtle_scanner_edge_shadow(tmp_path: Path):
    img = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(img)
    # 3px dark border artifact along the edge (inside the 2% crop margin)
    draw.rectangle([0, 0, 599, 2], fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    pdf_path = tmp_path / "edge_shadow.pdf"
    pdf_path.write_bytes(img2pdf.convert(buf.getvalue()))

    assert is_pdf_blank(pdf_path) is True


def test_is_pdf_blank_detects_empty_a4_pdf(tmp_path: Path):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    pdf_path = tmp_path / "empty_a4.pdf"
    with pdf_path.open("wb") as f:
        writer.write(f)

    assert is_pdf_blank(pdf_path) is True


def test_is_pdf_blank_false_for_tiny_test_fixtures_and_non_blank_scans(
    tmp_path: Path, minimal_pdf: Path
):
    # 72x72 minimal test PDF is too small to be a scanned page
    assert is_pdf_blank(minimal_pdf) is False

    # 200x200 synthetic test JPEG wrapped as PDF is below scanner page dimensions
    small_buf = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(small_buf, format="JPEG")
    small_pdf = tmp_path / "small.pdf"
    small_pdf.write_bytes(img2pdf.convert(small_buf.getvalue()))
    assert is_pdf_blank(small_pdf) is False

    # Scanner-sized PDF with actual ink/content on page 2 (page 1 blank)
    blank_buf = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(blank_buf, format="JPEG")
    ink_img = Image.new("RGB", (600, 800), "white")
    ImageDraw.Draw(ink_img).rectangle([100, 100, 350, 180], fill="black")
    ink_buf = io.BytesIO()
    ink_img.save(ink_buf, format="JPEG")
    mixed_pdf = tmp_path / "mixed.pdf"
    mixed_pdf.write_bytes(img2pdf.convert([blank_buf.getvalue(), ink_buf.getvalue()]))
    assert is_pdf_blank(mixed_pdf) is False


def test_is_pdf_blank_false_for_vector_content_pdf_and_corrupt(tmp_path: Path):
    from pypdf.generic import DecodedStreamObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    stream = DecodedStreamObject()
    stream.set_data(b"0 0 0 rg 50 50 200 200 re f")
    page[NameObject("/Contents")] = writer._add_object(stream)
    vector_pdf = tmp_path / "vector.pdf"
    with vector_pdf.open("wb") as f:
        writer.write(f)

    assert is_pdf_blank(vector_pdf) is False

    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"corrupt")
    assert is_pdf_blank(corrupt_pdf) is False


def test_is_pdf_blank_false_for_empty_and_text_pages(tmp_path: Path):
    from pypdf.generic import DecodedStreamObject, NameObject

    # 0-page PDF
    empty_writer = PdfWriter()
    empty_pdf = tmp_path / "zero_pages.pdf"
    with empty_pdf.open("wb") as f:
        empty_writer.write(f)
    assert is_pdf_blank(empty_pdf) is True

    # PDF with embedded text (>= 15 chars)
    text_writer = PdfWriter()
    page = text_writer.add_blank_page(width=595, height=842)
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Invoice Number 12345678) Tj ET")
    page[NameObject("/Contents")] = text_writer._add_object(stream)
    text_pdf = tmp_path / "text.pdf"
    with text_pdf.open("wb") as f:
        text_writer.write(f)
    assert is_pdf_blank(text_pdf) is False


def test_prepare_pdf_raises_when_vector_only_pdf_exceeds_max_bytes(tmp_path: Path):
    from pypdf.generic import DecodedStreamObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    stream = DecodedStreamObject()
    stream.set_data(b"0 0 0 rg 50 50 200 200 re f " * 200)
    page[NameObject("/Contents")] = writer._add_object(stream)
    vec_pdf = tmp_path / "big_vec.pdf"
    with vec_pdf.open("wb") as f:
        writer.write(f)

    with pytest.raises(ValueError, match="classification preview limit"):
        prepare_pdf_for_classification(vec_pdf, max_bytes=100)


def test_prepare_pdf_returns_raw_bytes_for_quirked_small_pdf(tmp_path: Path):
    quirked = tmp_path / "quirked.pdf"
    quirked.write_bytes(b"%PDF-1.4 truncated-eof")
    assert prepare_pdf_for_classification(quirked) == b"%PDF-1.4 truncated-eof"

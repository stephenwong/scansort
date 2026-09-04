"""Unit tests for scansort.pdf_metadata module."""

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from scansort.pdf_metadata import process_pdf_metadata_and_rotation


def _create_minimal_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(path, "wb") as f:
        writer.write(f)


def test_embed_metadata(tmp_path: Path):
    pdf_in = tmp_path / "test.pdf"
    _create_minimal_pdf(pdf_in)

    result_pdf = process_pdf_metadata_and_rotation(
        pdf_path=pdf_in,
        title="Origin Energy Bill",
        subject="Electricity invoice for 42 Wallaby Way",
        keywords=["Utilities", "Electricity", "Invoice", "Origin"],
        author="ScanSort AI",
    )

    reader = PdfReader(result_pdf)
    meta = reader.metadata
    assert meta is not None
    assert meta.get("/Title") == "Origin Energy Bill"
    assert meta.get("/Subject") == "Electricity invoice for 42 Wallaby Way"
    assert "Origin" in meta.get("/Keywords", "")
    assert meta.get("/Author") == "ScanSort AI"


def test_rotate_pages(tmp_path: Path):
    pdf_in = tmp_path / "upside_down.pdf"
    _create_minimal_pdf(pdf_in)

    reader = PdfReader(pdf_in)
    assert reader.pages[0].rotation == 0

    # Rotate by 180 degrees
    result_pdf = process_pdf_metadata_and_rotation(
        pdf_path=pdf_in,
        orientation_angle=180,
    )

    reader_after = PdfReader(result_pdf)
    assert reader_after.pages[0].rotation == 180


def test_rotate_pages_90_degrees(tmp_path: Path):
    pdf_in = tmp_path / "sideways.pdf"
    _create_minimal_pdf(pdf_in)

    result_pdf = process_pdf_metadata_and_rotation(
        pdf_path=pdf_in,
        orientation_angle=90,
    )

    reader_after = PdfReader(result_pdf)
    assert reader_after.pages[0].rotation == 90


def test_output_to_different_file(tmp_path: Path):
    pdf_in = tmp_path / "in.pdf"
    pdf_out = tmp_path / "out.pdf"
    _create_minimal_pdf(pdf_in)

    res = process_pdf_metadata_and_rotation(
        pdf_path=pdf_in,
        output_path=pdf_out,
        title="Sample Title",
    )

    assert res == pdf_out
    assert pdf_out.exists()
    reader = PdfReader(pdf_out)
    assert reader.metadata.get("/Title") == "Sample Title"


def test_rotate_non_orthogonal_angle_clamped(tmp_path: Path):
    pdf_in = tmp_path / "angle45.pdf"
    _create_minimal_pdf(pdf_in)

    res = process_pdf_metadata_and_rotation(pdf_in, orientation_angle=45)
    reader = PdfReader(res)
    assert reader.pages[0].rotation == 0


def test_missing_pdf_raises_error(tmp_path: Path):
    import pytest

    missing = tmp_path / "ghost.pdf"
    with pytest.raises(FileNotFoundError):
        process_pdf_metadata_and_rotation(missing)


def test_inplace_temp_file_cleanup_on_error(tmp_path: Path):
    from unittest.mock import patch

    import pytest

    pdf_in = tmp_path / "broken_write.pdf"
    _create_minimal_pdf(pdf_in)

    with (
        patch("pypdf.PdfWriter.write", side_effect=OSError("Disk full")),
        pytest.raises(OSError),
    ):
        process_pdf_metadata_and_rotation(pdf_in)

    # Verify no .tmp files leaked in the directory
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []

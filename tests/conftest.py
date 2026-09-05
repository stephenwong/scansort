"""Shared pytest fixtures and test configurations for ScanSort test suite."""

import io
from pathlib import Path

import pytest
from pypdf import PdfWriter


@pytest.fixture
def minimal_pdf_bytes() -> bytes:
    """Return raw bytes of a valid minimal single-page PDF."""
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def minimal_pdf(tmp_path: Path, minimal_pdf_bytes: bytes) -> Path:
    """Create a temporary valid single-page PDF file."""
    pdf_path = tmp_path / "minimal.pdf"
    pdf_path.write_bytes(minimal_pdf_bytes)
    return pdf_path

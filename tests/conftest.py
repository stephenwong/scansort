"""Shared pytest fixtures and test configurations for ScanSort test suite."""

import io
import logging
from pathlib import Path

import pytest
from pypdf import PdfWriter


@pytest.fixture(autouse=True)
def _isolate_root_logging(monkeypatch):
    """Keep file logging hermetic during the test session.

    ``main_cli`` attaches a rotating file handler in the real app data
    directory; neutralize that for every test (individual tests re-enable it
    against ``tmp_path`` directories) and detach any handler a test attaches
    to the root logger afterwards.
    """
    import scansort.__main__ as cli_module

    root = logging.getLogger()
    initial_handlers = list(root.handlers)
    initial_level = root.level
    monkeypatch.setattr(cli_module, "configure_file_logging", lambda app_dir=None: None)
    yield
    for handler in list(root.handlers):
        if handler not in initial_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(initial_level)


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

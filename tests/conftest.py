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
    import scansort.cli.root as cli_root

    root = logging.getLogger()
    initial_handlers = list(root.handlers)
    initial_level = root.level
    monkeypatch.setattr(
        cli_module, "configure_file_logging", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        cli_root, "configure_file_logging", lambda *args, **kwargs: None
    )
    yield
    for handler in list(root.handlers):
        if handler not in initial_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(initial_level)


class _HermeticTrayIcon:
    """Hermetic replacement for pystray.Icon in test environments.

    Prevents connecting to the host X11/Win32 display server, spawning
    unmanaged non-daemon threads, and encountering socket errors during
    garbage collection.
    """

    def __init__(
        self, name: str, icon=None, title: str | None = None, menu=None
    ) -> None:
        self.name = name
        self.icon = icon
        self.title = title
        self.menu = menu
        self.visible = False
        self._running = False

    def run(self, setup=None) -> None:
        self._running = True
        if setup:
            setup(self)

    def run_detached(self, setup=None) -> None:
        self.run(setup=setup)

    def stop(self) -> None:
        self._running = False

    def update_menu(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _isolate_pystray(monkeypatch):
    """Keep pystray system tray hermetic across tests."""
    import pystray

    monkeypatch.setattr(pystray, "Icon", _HermeticTrayIcon)


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

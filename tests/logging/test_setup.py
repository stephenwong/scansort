"""Unit tests for persistent rotating file logging (scansort.logging.setup)."""

import logging
import logging.handlers
from pathlib import Path

from scansort.constants import LOG_FILENAME
from scansort.logging import configure_file_logging


def _root_file_handlers(log_dir: Path) -> list[logging.Handler]:
    """Return root-logger file handlers bound to ``log_dir``'s log file."""
    target = (log_dir / LOG_FILENAME).resolve()
    return [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
        and Path(handler.baseFilename).resolve() == target
    ]


def test_configure_creates_rotating_handler_and_records_messages(tmp_path: Path):
    handler = configure_file_logging(tmp_path)
    assert handler is not None
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler.level == logging.INFO
    assert (tmp_path / LOG_FILENAME).is_file()

    test_logger = logging.getLogger("scansort.testlogging")
    test_logger.warning("classification failed for %s", "scan001.pdf")
    test_logger.info("startup complete")

    lines = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith(
        "WARNING scansort.testlogging: classification failed for scan001.pdf"
    )
    assert lines[1].endswith("INFO scansort.testlogging: startup complete")


def test_configure_filters_debug_messages(tmp_path: Path):
    configure_file_logging(tmp_path)
    logging.getLogger("scansort.testlogging").debug("sensitive debug detail")
    lines = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8").splitlines()
    assert lines == []


def test_configure_reuses_existing_handler_without_duplicates(tmp_path: Path):
    first = configure_file_logging(tmp_path)
    assert first is not None
    test_logger = logging.getLogger("scansort.testlogging")
    test_logger.warning("first message")

    second = configure_file_logging(tmp_path)

    assert second is first
    assert _root_file_handlers(tmp_path) == [first]
    console_handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.StreamHandler)
        and getattr(handler, "_scansort_console_handler", False)
    ]
    assert len(console_handlers) == 1
    assert console_handlers[0].level == logging.WARNING

    test_logger.warning("second message")
    lines = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("first message")
    assert lines[1].endswith("second message")


def test_configure_attaches_console_handler_preserving_stderr_warnings(
    tmp_path: Path, capsys
):
    configure_file_logging(tmp_path)
    logging.getLogger("scansort.testlogging").warning("visible on stderr")
    assert "visible on stderr" in capsys.readouterr().err


def test_configure_returns_none_when_log_dir_creation_fails(tmp_path: Path):
    blocker = tmp_path / "a_regular_file"
    blocker.write_text("not a directory")
    assert configure_file_logging(blocker / "subdir") is None
    assert not _root_file_handlers(blocker / "subdir")


def test_configure_returns_none_when_log_file_cannot_be_opened(tmp_path: Path):
    (tmp_path / LOG_FILENAME).mkdir()
    assert configure_file_logging(tmp_path) is None
    assert not _root_file_handlers(tmp_path)


def test_configure_uses_default_app_dir_when_not_given(monkeypatch, tmp_path: Path):
    app_dir = tmp_path / "appdata"
    monkeypatch.setattr("scansort.logging.setup.get_default_app_dir", lambda: app_dir)
    handler = configure_file_logging()
    assert handler is not None
    assert (app_dir / LOG_FILENAME).is_file()


def test_configure_file_logging_debug_level(tmp_path: Path):
    handler = configure_file_logging(tmp_path, level=logging.DEBUG)
    assert handler is not None
    assert handler.level == logging.DEBUG
    assert logging.getLogger().level == logging.DEBUG
    log_file = tmp_path / LOG_FILENAME
    assert log_file.exists()


def test_main_cli_wires_file_logging_into_app_dir(monkeypatch, tmp_path: Path, capsys):
    import scansort.__main__ as cli_module
    from scansort.logging.setup import configure_file_logging as real_configure

    monkeypatch.setattr(cli_module, "configure_file_logging", real_configure)
    monkeypatch.setattr("scansort.logging.setup.get_default_app_dir", lambda: tmp_path)
    monkeypatch.setattr("scansort.__main__.get_default_app_dir", lambda: tmp_path)
    monkeypatch.setattr("scansort.config.get_default_app_dir", lambda: tmp_path)

    exit_code = cli_module.main_cli(["undo"])

    assert exit_code == 0
    assert (tmp_path / LOG_FILENAME).is_file()
    assert "No reversible" in capsys.readouterr().out

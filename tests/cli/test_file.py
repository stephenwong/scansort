"""Unit tests for 'scansort file' direct CLI filing subcommand."""

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

from scansort.cli.file_cmd import handle_file
from scansort.core.config import AppConfig


def test_handle_file_single_success(tmp_path: Path, capsys):
    test_pdf = tmp_path / "invoice.pdf"
    test_pdf.write_bytes(b"%PDF-1.4 test")

    dest_pdf = tmp_path / "Documents" / "Finance" / "260912_Invoice.pdf"
    dest_pdf.parent.mkdir(parents=True)
    dest_pdf.write_bytes(b"%PDF-1.4 test")

    mock_cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )

    mock_pipeline = MagicMock()
    mock_pipeline.process_file.return_value = dest_pdf

    with (
        patch("scansort.cli.file_cmd._load_config_or_exit", return_value=mock_cfg),
        patch("scansort.cli.file_cmd.get_api_key", return_value="AIzaSyDummyKey123"),
        patch("scansort.cli.file_cmd.ScanSortPipeline", return_value=mock_pipeline),
    ):
        parsed = argparse.Namespace(
            files=[test_pdf],
            copy=False,
            dry_run=False,
        )
        exit_code = handle_file(parsed)

    assert exit_code == 0
    mock_pipeline.process_file.assert_called_once_with(
        test_pdf.resolve(), preserve_source=False
    )
    captured = capsys.readouterr()
    assert "Filed: invoice.pdf ->" in captured.out
    assert "260912_Invoice.pdf" in captured.out


def test_handle_file_copy_flag(tmp_path: Path, capsys):
    test_pdf = tmp_path / "receipt.jpg"
    test_pdf.write_bytes(b"\xff\xd8\xff test")

    dest_pdf = tmp_path / "Documents" / "Receipts" / "260912_Receipt.pdf"
    dest_pdf.parent.mkdir(parents=True)
    dest_pdf.write_bytes(b"%PDF-1.4 test")

    mock_cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )

    mock_pipeline = MagicMock()
    mock_pipeline.process_file.return_value = dest_pdf

    with (
        patch("scansort.cli.file_cmd._load_config_or_exit", return_value=mock_cfg),
        patch("scansort.cli.file_cmd.get_api_key", return_value="AIzaSyDummyKey123"),
        patch("scansort.cli.file_cmd.ScanSortPipeline", return_value=mock_pipeline),
    ):
        parsed = argparse.Namespace(
            files=[test_pdf],
            copy=True,
            dry_run=False,
        )
        exit_code = handle_file(parsed)

    assert exit_code == 0
    mock_pipeline.process_file.assert_called_once_with(
        test_pdf.resolve(), preserve_source=True
    )


def test_handle_file_multiple_files(tmp_path: Path):
    f1 = tmp_path / "doc1.pdf"
    f2 = tmp_path / "doc2.pdf"
    f1.write_bytes(b"%PDF-1.4 1")
    f2.write_bytes(b"%PDF-1.4 2")

    mock_cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )

    mock_pipeline = MagicMock()
    mock_pipeline.process_file.side_effect = [
        tmp_path / "out1.pdf",
        tmp_path / "out2.pdf",
    ]

    with (
        patch("scansort.cli.file_cmd._load_config_or_exit", return_value=mock_cfg),
        patch("scansort.cli.file_cmd.get_api_key", return_value="AIzaSyDummyKey123"),
        patch("scansort.cli.file_cmd.ScanSortPipeline", return_value=mock_pipeline),
    ):
        parsed = argparse.Namespace(
            files=[f1, f2],
            copy=False,
            dry_run=False,
        )
        exit_code = handle_file(parsed)

    assert exit_code == 0
    assert mock_pipeline.process_file.call_count == 2


def test_handle_file_missing_api_key(tmp_path: Path, capsys):
    test_pdf = tmp_path / "doc.pdf"
    test_pdf.write_bytes(b"%PDF-1.4")

    mock_cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )

    with (
        patch("scansort.cli.file_cmd._load_config_or_exit", return_value=mock_cfg),
        patch("scansort.cli.file_cmd.get_api_key", return_value=None),
    ):
        parsed = argparse.Namespace(
            files=[test_pdf],
            copy=False,
            dry_run=False,
        )
        exit_code = handle_file(parsed)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Gemini API key not configured" in captured.err


def test_handle_file_nonexistent_path(tmp_path: Path, capsys):
    mock_cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )

    with (
        patch("scansort.cli.file_cmd._load_config_or_exit", return_value=mock_cfg),
        patch("scansort.cli.file_cmd.get_api_key", return_value="AIzaSyDummyKey123"),
    ):
        parsed = argparse.Namespace(
            files=[tmp_path / "ghost.pdf"],
            copy=False,
            dry_run=False,
        )
        exit_code = handle_file(parsed)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "File not found: ghost.pdf" in captured.err


def test_handle_file_unsupported_extension(tmp_path: Path, capsys):
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("Hello")

    mock_cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )

    with (
        patch("scansort.cli.file_cmd._load_config_or_exit", return_value=mock_cfg),
        patch("scansort.cli.file_cmd.get_api_key", return_value="AIzaSyDummyKey123"),
    ):
        parsed = argparse.Namespace(
            files=[unsupported],
            copy=False,
            dry_run=False,
        )
        exit_code = handle_file(parsed)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Unsupported file type: .txt" in captured.err


def test_handle_file_config_error(tmp_path: Path):
    with patch("scansort.cli.file_cmd._load_config_or_exit", return_value=None):
        parsed = argparse.Namespace(
            files=[tmp_path / "test.pdf"],
            copy=False,
            dry_run=False,
        )
        assert handle_file(parsed) == 1


def test_handle_file_pipeline_failure(tmp_path: Path, capsys):
    test_pdf = tmp_path / "doc.pdf"
    test_pdf.write_bytes(b"%PDF-1.4")

    mock_cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )

    mock_pipeline = MagicMock()
    mock_pipeline.process_file.return_value = None

    with (
        patch("scansort.cli.file_cmd._load_config_or_exit", return_value=mock_cfg),
        patch("scansort.cli.file_cmd.get_api_key", return_value="AIzaSyDummyKey123"),
        patch("scansort.cli.file_cmd.ScanSortPipeline", return_value=mock_pipeline),
    ):
        parsed = argparse.Namespace(
            files=[test_pdf],
            copy=False,
            dry_run=False,
        )
        exit_code = handle_file(parsed)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Failed to file: doc.pdf" in captured.err


def test_handle_file_empty_files_list(tmp_path: Path, capsys):
    mock_cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )

    with (
        patch("scansort.cli.file_cmd._load_config_or_exit", return_value=mock_cfg),
        patch("scansort.cli.file_cmd.get_api_key", return_value="AIzaSyDummyKey123"),
    ):
        parsed = argparse.Namespace(
            files=[],
            copy=False,
            dry_run=False,
        )
        assert handle_file(parsed) == 1
    captured = capsys.readouterr()
    assert "No files specified" in captured.err


def test_handle_file_dry_run_output(tmp_path: Path, capsys):
    """Dry-run must label output as simulated, never as a real filing."""
    test_pdf = tmp_path / "doc.pdf"
    test_pdf.write_bytes(b"%PDF-1.4")

    mock_cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
    )

    mock_pipeline = MagicMock()
    mock_pipeline.process_file.return_value = tmp_path / "Documents" / "doc.pdf"

    with (
        patch("scansort.cli.file_cmd._load_config_or_exit", return_value=mock_cfg),
        patch("scansort.cli.file_cmd.get_api_key", return_value="AIzaSyDummyKey123"),
        patch("scansort.cli.file_cmd.ScanSortPipeline", return_value=mock_pipeline),
    ):
        parsed = argparse.Namespace(
            files=[test_pdf],
            copy=False,
            dry_run=True,
        )
        assert handle_file(parsed) == 0

    captured = capsys.readouterr()
    assert "[DRY RUN]" in captured.out
    assert "Filed:" not in captured.out
    assert "Preserved original" not in captured.out


def test_handle_file_dry_run_override(tmp_path: Path):
    test_pdf = tmp_path / "doc.pdf"
    test_pdf.write_bytes(b"%PDF-1.4")

    mock_cfg = AppConfig(
        watch_folder=tmp_path / "Inbox",
        documents_root=tmp_path / "Documents",
        dry_run=False,
    )

    mock_pipeline = MagicMock()
    mock_pipeline.process_file.return_value = tmp_path / "Documents" / "doc.pdf"

    with (
        patch("scansort.cli.file_cmd._load_config_or_exit", return_value=mock_cfg),
        patch("scansort.cli.file_cmd.get_api_key", return_value="AIzaSyDummyKey123"),
        patch(
            "scansort.cli.file_cmd.ScanSortPipeline", return_value=mock_pipeline
        ) as mock_init,
    ):
        parsed = argparse.Namespace(
            files=[test_pdf],
            copy=False,
            dry_run=True,
        )
        assert handle_file(parsed) == 0
        created_cfg = mock_init.call_args.kwargs["config"]
        assert created_cfg.dry_run is True

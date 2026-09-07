"""Unit tests for scansort.cli.undo module."""

from pathlib import Path
from unittest.mock import patch

from scansort.cli.root import main_cli


def test_cli_undo(capsys):
    target = Path("/inbox/doc.pdf")
    with patch(
        "scansort.cli.undo.undo_last_move",
        return_value=target,
    ) as mock_undo:
        exit_code = main_cli(["undo"])
        assert exit_code == 0
        mock_undo.assert_called_once()
        captured = capsys.readouterr()
        assert f"Successfully reversed move. File restored to: {target}" in captured.out


def test_cli_undo_nothing_to_undo(capsys):
    with patch("scansort.cli.undo.undo_last_move", return_value=None):
        exit_code = main_cli(["undo"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No reversible" in captured.out


def test_cli_undo_os_error(capsys):
    with patch(
        "scansort.cli.undo.undo_last_move",
        side_effect=PermissionError("File locked by process"),
    ):
        exit_code = main_cli(["undo"])
        assert exit_code == 1
        assert "Error reversing last move" in capsys.readouterr().err

"""Unit tests for CLI commands in scansort.__main__ (TDD Cycle 10)."""

from pathlib import Path
from unittest.mock import patch

from scansort.__main__ import build_parser, main_cli
from scansort.config import AppConfig


def test_build_parser():
    parser = build_parser()
    args = parser.parse_args(["watch", "--dry-run"])
    assert args.command == "watch"
    assert args.dry_run is True

    args_cfg = parser.parse_args(["config", "--set-key", "AIzaSyTest123"])
    assert args_cfg.command == "config"
    assert args_cfg.set_key == "AIzaSyTest123"


def test_cli_config_show(capsys):
    with patch("scansort.__main__.get_api_key", return_value="AIzaSyTest1234567890"), patch("scansort.__main__.load_config", return_value=AppConfig()):
        exit_code = main_cli(["config", "--show"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "AIza" in captured.out
        assert "••••••••" in captured.out
        assert "1234567890" not in captured.out


def test_cli_config_set_key():
    with patch("scansort.__main__.set_api_key") as mock_set:
        exit_code = main_cli(["config", "--set-key", "AIzaSyNewKey12345"])
        assert exit_code == 0
        mock_set.assert_called_once_with("AIzaSyNewKey12345")


def test_cli_undo(tmp_path: Path):
    with patch("scansort.__main__.undo_last_move", return_value=Path("/inbox/doc.pdf")) as mock_undo:
        exit_code = main_cli(["undo"])
        assert exit_code == 0
        mock_undo.assert_called_once()

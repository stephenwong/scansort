"""Unit tests for scansort.cli.rescan module."""

from pathlib import Path
from unittest.mock import patch

from scansort.cli.root import main_cli
from scansort.core.config import AppConfig


def test_cli_rescan(capsys, tmp_path: Path):
    docs = tmp_path / "Docs"
    (docs / "Bills").mkdir(parents=True)
    cfg = AppConfig(
        documents_root=docs,
        max_folder_depth=5,
        fallback_folder="_Special_Review",
    )

    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.rescan.FolderMapper") as mock_mapper_cls,
    ):
        mock_mapper = mock_mapper_cls.return_value
        mock_mapper.refresh.return_value = ["Bills"]
        exit_code = main_cli(["rescan"])
        assert exit_code == 0
        mock_mapper_cls.assert_called_once_with(
            docs_root=docs,
            max_depth=5,
            fallback_folder="_Special_Review",
        )
        captured = capsys.readouterr()
        assert "Discovered 1 destination folders" in captured.out
        assert "Bills" in captured.out


def test_cli_rescan_config_error(capsys):
    with patch("scansort.cli.config.load_config", side_effect=ValueError("bad config")):
        assert main_cli(["rescan"]) == 1
        assert "Configuration error" in capsys.readouterr().err

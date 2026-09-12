"""Unit tests for scansort.cli.rescan module."""

from pathlib import Path
from unittest.mock import patch

from scansort.cli.root import main_cli
from scansort.core.config import AppConfig


def test_cli_rescan(capsys, tmp_path: Path):
    docs = tmp_path / "Docs"
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


def test_cli_rescan_json(capsys, tmp_path: Path):
    import json

    cfg = AppConfig(documents_root=tmp_path)
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.rescan.FolderMapper") as mock_mapper_cls,
    ):
        mock_mapper = mock_mapper_cls.return_value
        mock_mapper.refresh.return_value = ["Finance/Invoices", "Taxes"]
        exit_code = main_cli(["rescan", "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == ["Finance/Invoices", "Taxes"]


def test_cli_rescan_doctor(capsys, tmp_path: Path):
    from scansort.classification.doctor import (
        ACTION_MERGE_INTO,
        KIND_NEAR_DUPLICATE,
        SEVERITY_MEDIUM,
        DoctorFinding,
        DoctorReport,
    )

    cfg = AppConfig(documents_root=tmp_path)
    report = DoctorReport(
        folders=["Bill", "Bills"],
        findings=[
            DoctorFinding(
                kind=KIND_NEAR_DUPLICATE,
                severity=SEVERITY_MEDIUM,
                message="Near-duplicate folders 'Bill' and 'Bills'",
                action=ACTION_MERGE_INTO,
                primary_folder="Bills",
                target_folder="Bill",
            )
        ],
    )
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.rescan.run_doctor", return_value=report) as mock_doctor,
    ):
        exit_code = main_cli(["rescan", "--doctor"])
        assert exit_code == 0
        mock_doctor.assert_called_once_with(cfg)
        captured = capsys.readouterr()
        assert "Taxonomy Doctor findings" in captured.out
        assert "merge 'Bills' into 'Bill'" in captured.out


def test_cli_rescan_doctor_json(capsys, tmp_path: Path):
    import json

    from scansort.classification.doctor import DoctorReport

    cfg = AppConfig(documents_root=tmp_path)
    report = DoctorReport(folders=["Bill"], findings=[], history_record_count=7)
    with (
        patch("scansort.cli.config.load_config", return_value=cfg),
        patch("scansort.cli.rescan.run_doctor", return_value=report),
    ):
        exit_code = main_cli(["rescan", "--doctor", "--json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["folders"] == ["Bill"]
        assert payload["history_record_count"] == 7
        assert payload["findings"] == []

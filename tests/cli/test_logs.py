"""Unit tests for scansort.cli.logs module."""

from pathlib import Path
from unittest.mock import patch

from scansort.cli.root import main_cli
from scansort.core.constants import LOG_FILENAME


def test_logs_no_file_found(tmp_path: Path, capsys):
    with patch("scansort.cli.logs.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["logs"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No log file found" in captured.out


def test_logs_default_tail(tmp_path: Path, capsys):
    log_file = tmp_path / LOG_FILENAME
    lines = [f"2026-09-07 10:00:{i:02d} INFO test: Log line {i}\n" for i in range(70)]
    log_file.write_text("".join(lines), encoding="utf-8")

    with patch("scansort.cli.logs.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["logs"])
        assert exit_code == 0
        captured = capsys.readouterr()
        # Should display last 50 lines (line 20 to 69)
        assert "Log line 69" in captured.out
        assert "Log line 20" in captured.out
        assert "Log line 19" not in captured.out


def test_logs_custom_lines(tmp_path: Path, capsys):
    log_file = tmp_path / LOG_FILENAME
    lines = [f"2026-09-07 10:00:{i:02d} INFO test: Log line {i}\n" for i in range(20)]
    log_file.write_text("".join(lines), encoding="utf-8")

    with patch("scansort.cli.logs.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["logs", "-n", "5"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Log line 19" in captured.out
        assert "Log line 15" in captured.out
        assert "Log line 14" not in captured.out


def test_logs_level_filter(tmp_path: Path, capsys):
    log_file = tmp_path / LOG_FILENAME
    log_file.write_text(
        "2026-09-07 10:00:01 DEBUG test: Debug detail\n"
        "2026-09-07 10:00:02 INFO test: Routine notice\n"
        "2026-09-07 10:00:03 WARNING test: Caution warning\n"
        "2026-09-07 10:00:04 ERROR test: Critical error\n",
        encoding="utf-8",
    )

    with patch("scansort.cli.logs.get_default_app_dir", return_value=tmp_path):
        # Filter for ERROR
        exit_code = main_cli(["logs", "--level", "ERROR"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Critical error" in captured.out
        assert "Caution warning" not in captured.out
        assert "Routine notice" not in captured.out

        # Filter for WARNING (includes WARNING and ERROR)
        exit_code = main_cli(["logs", "--level", "WARNING"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Critical error" in captured.out
        assert "Caution warning" in captured.out
        assert "Routine notice" not in captured.out


def test_logs_clear(tmp_path: Path, capsys):
    log_file = tmp_path / LOG_FILENAME
    log_file.write_text("Old log content\n", encoding="utf-8")

    with patch("scansort.cli.logs.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["logs", "--clear"])
        assert exit_code == 0
        assert log_file.stat().st_size == 0
        captured = capsys.readouterr()
        assert "Log file cleared" in captured.out


def test_logs_clear_os_error(tmp_path: Path, capsys):
    log_file = tmp_path / LOG_FILENAME
    log_file.write_text("Old log content\n", encoding="utf-8")

    with (
        patch("scansort.cli.logs.get_default_app_dir", return_value=tmp_path),
        patch("builtins.open", side_effect=PermissionError("Permission denied")),
    ):
        exit_code = main_cli(["logs", "--clear"])
        assert exit_code == 1
        assert "Error clearing log file" in capsys.readouterr().err


def test_logs_follow(tmp_path: Path, capsys):
    log_file = tmp_path / LOG_FILENAME
    log_file.write_text("Initial line\n", encoding="utf-8")

    def fake_sleep_generator():
        # Append line on first sleep, raise KeyboardInterrupt on second
        log_file.write_text("Initial line\nAppended line\n", encoding="utf-8")
        yield None
        raise KeyboardInterrupt

    gen = fake_sleep_generator()

    with (
        patch("scansort.cli.logs.get_default_app_dir", return_value=tmp_path),
        patch("time.sleep", side_effect=lambda _: next(gen)),
    ):
        exit_code = main_cli(["logs", "-f"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Initial line" in captured.out
        assert "Appended line" in captured.out


def test_logs_clear_nonexistent(tmp_path: Path, capsys):
    with patch("scansort.cli.logs.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["logs", "--clear"])
        assert exit_code == 0
        assert "Log file does not exist" in capsys.readouterr().out


def test_logs_read_os_error(tmp_path: Path, capsys):
    log_file = tmp_path / LOG_FILENAME
    log_file.write_text("line\n", encoding="utf-8")

    with (
        patch("scansort.cli.logs.get_default_app_dir", return_value=tmp_path),
        patch("builtins.open", side_effect=PermissionError("Locked")),
    ):
        exit_code = main_cli(["logs"])
        assert exit_code == 1
        assert "Error reading log file" in capsys.readouterr().err


def test_logs_follow_os_error(tmp_path: Path, capsys):
    log_file = tmp_path / LOG_FILENAME
    log_file.write_text("line\n", encoding="utf-8")

    with (
        patch("scansort.cli.logs.get_default_app_dir", return_value=tmp_path),
        patch("builtins.open", side_effect=PermissionError("Locked")),
    ):
        exit_code = main_cli(["logs", "-f"])
        assert exit_code == 1
        assert "Error reading log file" in capsys.readouterr().err


def test_logs_follow_level_filter(tmp_path: Path, capsys):
    log_file = tmp_path / LOG_FILENAME
    log_file.write_text(
        "2026-09-07 INFO test: initial info\n2026-09-07 ERROR test: initial error\n",
        encoding="utf-8",
    )

    def fake_sleep_gen():
        # Append debug and error
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(
                "2026-09-07 DEBUG test: app debug\n2026-09-07 ERROR test: app error\n"
            )
        yield None
        raise KeyboardInterrupt

    gen = fake_sleep_gen()

    with (
        patch("scansort.cli.logs.get_default_app_dir", return_value=tmp_path),
        patch("time.sleep", side_effect=lambda _: next(gen)),
    ):
        exit_code = main_cli(["logs", "-f", "--level", "ERROR"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "initial error" in captured.out
        assert "app error" in captured.out
        assert "initial info" not in captured.out
        assert "app debug" not in captured.out


def test_logs_extract_line_severity_fallback_and_none():
    from scansort.cli.logs import _extract_line_severity

    # Fallback to token search in head
    assert _extract_line_severity("Short WARNING") == 30
    assert _extract_line_severity("No severity token anywhere") is None


def test_logs_zero_lines(tmp_path: Path, capsys):
    log_file = tmp_path / LOG_FILENAME
    log_file.write_text("Line 1\nLine 2\n", encoding="utf-8")

    with patch("scansort.cli.logs.get_default_app_dir", return_value=tmp_path):
        exit_code = main_cli(["logs", "-n", "0"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out == ""

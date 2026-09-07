"""Unit tests for scansort.cli.logs module."""

from pathlib import Path
from unittest.mock import patch

from scansort.cli.root import main_cli
from scansort.core.constants import LOG_FILENAME


def _make_follow_breaker(append_lines: list[str], target_file: Path):
    def _generator():
        for line in append_lines:
            with open(target_file, "a", encoding="utf-8") as f:
                f.write(line)
            yield None
        raise KeyboardInterrupt

    gen = _generator()
    return lambda _: next(gen)


def test_logs_no_file_found(mock_app_dir: Path, capsys):
    exit_code = main_cli(["logs"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No log file found" in captured.out


def test_logs_default_tail(mock_app_dir: Path, capsys):
    log_file = mock_app_dir / LOG_FILENAME
    lines = [f"2026-09-07 10:00:{i:02d} INFO test: Log line {i}\n" for i in range(70)]
    log_file.write_text("".join(lines), encoding="utf-8")

    exit_code = main_cli(["logs"])
    assert exit_code == 0
    captured = capsys.readouterr()
    # Should display last 50 lines (line 20 to 69)
    assert "Log line 69" in captured.out
    assert "Log line 20" in captured.out
    assert "Log line 19" not in captured.out


def test_logs_custom_lines(mock_app_dir: Path, capsys):
    log_file = mock_app_dir / LOG_FILENAME
    lines = [f"2026-09-07 10:00:{i:02d} INFO test: Log line {i}\n" for i in range(20)]
    log_file.write_text("".join(lines), encoding="utf-8")

    exit_code = main_cli(["logs", "-n", "5"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Log line 19" in captured.out
    assert "Log line 15" in captured.out
    assert "Log line 14" not in captured.out


def test_logs_level_filter(mock_app_dir: Path, capsys):
    log_file = mock_app_dir / LOG_FILENAME
    log_file.write_text(
        "2026-09-07 10:00:01 DEBUG test: Debug detail\n"
        "2026-09-07 10:00:02 INFO test: Routine notice\n"
        "2026-09-07 10:00:03 WARNING test: Caution warning\n"
        "2026-09-07 10:00:04 ERROR test: Critical error\n",
        encoding="utf-8",
    )

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


def test_logs_clear(mock_app_dir: Path, capsys):
    log_file = mock_app_dir / LOG_FILENAME
    log_file.write_text("Old log content\n", encoding="utf-8")

    exit_code = main_cli(["logs", "--clear"])
    assert exit_code == 0
    assert log_file.stat().st_size == 0
    captured = capsys.readouterr()
    assert "Log file cleared" in captured.out


def test_logs_clear_os_error(mock_app_dir: Path, capsys):
    log_file = mock_app_dir / LOG_FILENAME
    log_file.touch()

    orig_open = open

    def guarded_open(file, *args, **kwargs):
        if str(file) == str(log_file):
            raise PermissionError("Permission denied")
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", guarded_open):
        exit_code = main_cli(["logs", "--clear"])
        assert exit_code == 1
        assert "Error clearing log file" in capsys.readouterr().err


def test_logs_follow(mock_app_dir: Path, capsys):
    log_file = mock_app_dir / LOG_FILENAME
    log_file.write_text("Initial line\n", encoding="utf-8")

    breaker = _make_follow_breaker(["Appended line\n"], log_file)

    with patch("time.sleep", side_effect=breaker):
        exit_code = main_cli(["logs", "-f"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Initial line" in captured.out
        assert "Appended line" in captured.out


def test_logs_clear_nonexistent(mock_app_dir: Path, capsys):
    exit_code = main_cli(["logs", "--clear"])
    assert exit_code == 0
    assert "Log file does not exist" in capsys.readouterr().out


def test_logs_read_os_error(mock_app_dir: Path, capsys):
    log_file = mock_app_dir / LOG_FILENAME
    log_file.touch()

    orig_open = open

    def guarded_open(file, *args, **kwargs):
        if str(file) == str(log_file):
            raise PermissionError("Locked")
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", guarded_open):
        exit_code = main_cli(["logs"])
        assert exit_code == 1
        assert "Error reading log file" in capsys.readouterr().err


def test_logs_follow_os_error(mock_app_dir: Path, capsys):
    log_file = mock_app_dir / LOG_FILENAME
    log_file.touch()

    orig_open = open

    def guarded_open(file, *args, **kwargs):
        if str(file) == str(log_file):
            raise PermissionError("Locked")
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", guarded_open):
        exit_code = main_cli(["logs", "-f"])
        assert exit_code == 1
        assert "Error reading log file" in capsys.readouterr().err


def test_logs_follow_level_filter(mock_app_dir: Path, capsys):
    log_file = mock_app_dir / LOG_FILENAME
    log_file.write_text(
        "2026-09-07 INFO test: initial info\n2026-09-07 ERROR test: initial error\n",
        encoding="utf-8",
    )

    appends = ["2026-09-07 DEBUG test: app debug\n2026-09-07 ERROR test: app error\n"]
    breaker = _make_follow_breaker(appends, log_file)

    with patch("time.sleep", side_effect=breaker):
        exit_code = main_cli(["logs", "-f", "--level", "ERROR"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "initial info" not in captured.out
        assert "initial error" in captured.out
        assert "app debug" not in captured.out
        assert "app error" in captured.out


def test_logs_handles_undecodable_utf8(mock_app_dir: Path, capsys):
    log_file = mock_app_dir / LOG_FILENAME
    log_file.write_bytes(b"2026-09-07 INFO test: valid\n\xff\xfe\xfa\n")

    exit_code = main_cli(["logs"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "valid" in captured.out

"""Unit tests for scansort.cli.completion module."""

import pytest

from scansort.cli.root import main_cli


def test_completion_bash(capsys):
    exit_code = main_cli(["completion", "bash"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "_scansort_completion" in captured.out
    assert "watch" in captured.out
    assert "history" in captured.out


def test_completion_zsh(capsys):
    exit_code = main_cli(["completion", "zsh"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "#compdef scansort" in captured.out
    assert "watch" in captured.out


def test_completion_fish(capsys):
    exit_code = main_cli(["completion", "fish"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "complete -c scansort" in captured.out


def test_completion_powershell(capsys):
    exit_code = main_cli(["completion", "powershell"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Register-ArgumentCompleter" in captured.out
    assert "scansort" in captured.out


def test_completion_invalid_shell():
    with pytest.raises(SystemExit) as exc_info:
        main_cli(["completion", "invalid_shell"])
    assert exc_info.value.code != 0


def test_completion_direct_call_unsupported_shell(capsys):
    import argparse

    from scansort.cli.completion import handle_completion

    code = handle_completion(argparse.Namespace(shell="elvish"))
    assert code == 1
    assert "Unsupported shell" in capsys.readouterr().out

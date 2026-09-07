"""Unit tests for scansort.cli.completion module."""

import pytest

from scansort.cli.root import main_cli


@pytest.mark.parametrize(
    ("shell", "expected_snippets"),
    [
        ("bash", ["_scansort_completion", "watch", "history"]),
        ("zsh", ["#compdef scansort", "watch"]),
        ("fish", ["complete -c scansort"]),
        ("powershell", ["Register-ArgumentCompleter", "scansort"]),
    ],
)
def test_completion_supported_shells(capsys, shell, expected_snippets):
    exit_code = main_cli(["completion", shell])
    assert exit_code == 0
    captured = capsys.readouterr()
    for snippet in expected_snippets:
        assert snippet in captured.out


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

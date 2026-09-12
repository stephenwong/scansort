"""Unit tests for scansort.cli.completion module."""

import pytest

from scansort.cli.completion import _SHELL_TEMPLATES, _SUBCOMMANDS
from scansort.cli.root import main_cli


def test_completion_templates_cover_all_subcommands():
    """Every shell template must advertise the canonical subcommand inventory."""
    for shell, template in _SHELL_TEMPLATES.items():
        assert "__SCAN_SORT" not in template
        for name in _SUBCOMMANDS:
            assert name in template, f"{shell} completion missing {name}"


@pytest.mark.parametrize(
    ("shell", "expected_snippets"),
    [
        ("bash", ["_scansort_completion", "watch", "history", "review"]),
        ("zsh", ["#compdef scansort", "watch", "review"]),
        ("fish", ["complete -c scansort", "review"]),
        ("powershell", ["Register-ArgumentCompleter", "scansort", "review"]),
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
    assert "Unsupported shell" in capsys.readouterr().err

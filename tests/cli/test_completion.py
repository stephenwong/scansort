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


def test_bash_config_completion_includes_ocr_flags():
    """Bash config opts must not drift behind the other shell templates."""
    bash = _SHELL_TEMPLATES["bash"]
    config_line = next(
        line
        for line in bash.splitlines()
        if line.strip().startswith("opts=") and "--get" in line
    )
    tokens = config_line.replace('opts="', "").replace('"', "").split()
    assert "--ocr" in tokens
    assert "--ocr-menu" in tokens


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


def test_fish_review_gui_and_cli_are_distinct_completions():
    """The review gui/cli registrations must be separate complete commands."""
    fish = _SHELL_TEMPLATES["fish"]
    assert 'dialog"complete' not in fish
    gui = [line for line in fish.splitlines() if "-l gui" in line]
    cli = [line for line in fish.splitlines() if "-l cli" in line]
    assert len(gui) == 1
    assert len(cli) == 1
    assert gui[0] != cli[0]
    assert cli[0].startswith("complete -c scansort")


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

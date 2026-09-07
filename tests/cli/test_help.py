"""Unit tests for scansort.cli.help module."""

from scansort.cli.root import main_cli


def test_help_no_args(capsys):
    exit_code = main_cli(["help"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "usage: scansort" in captured.out
    assert "Available commands" in captured.out


def test_help_subcommand(capsys):
    exit_code = main_cli(["help", "watch"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "watch" in captured.out
    assert "--watch-folder" in captured.out


def test_help_subcommand_config(capsys):
    exit_code = main_cli(["help", "config"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "--set-key" in captured.out


def test_help_unknown_command(capsys):
    exit_code = main_cli(["help", "nonexistent"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Unknown command" in captured.err or "Unknown command" in captured.out


def test_help_direct_call_without_parser(capsys):
    import argparse

    from scansort.cli.help import handle_help

    code = handle_help(argparse.Namespace(command_name="watch"), parser=None)
    assert code == 0
    assert "watch" in capsys.readouterr().out


def test_help_empty_subparsers():
    import argparse

    from scansort.cli.help import _find_subparser, _get_subcommand_names

    empty_parser = argparse.ArgumentParser()
    assert _find_subparser(empty_parser, "foo") is None
    assert _get_subcommand_names(empty_parser) == []

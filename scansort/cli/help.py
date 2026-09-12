"""Help command handler for general and subcommand-specific CLI guidance."""

import argparse
import sys

from scansort.cli.args import CliArgs


def _get_subparsers_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction | None:
    """Return the parser's subparsers action, if it has one."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _find_subparser(
    parser: argparse.ArgumentParser, command_name: str
) -> argparse.ArgumentParser | None:
    """Find the specific subparser associated with command_name."""
    action = _get_subparsers_action(parser)
    return action.choices.get(command_name) if action is not None else None


def _get_subcommand_names(parser: argparse.ArgumentParser) -> list[str]:
    """Return all registered subcommand names."""
    action = _get_subparsers_action(parser)
    return sorted(action.choices.keys()) if action is not None else []


def handle_help(
    parsed: argparse.Namespace, parser: argparse.ArgumentParser | None = None
) -> int:
    """Handle 'help' command to display root or subcommand-specific help."""
    if parser is None:
        from scansort.cli.parser import build_parser

        parser = build_parser()

    cmd_name = CliArgs.from_namespace(parsed).command_name
    if not cmd_name:
        parser.print_help()
        return 0

    subparser = _find_subparser(parser, cmd_name)
    if subparser is not None:
        subparser.print_help()
        return 0

    available = _get_subcommand_names(parser)
    print(f"Unknown command '{cmd_name}'.", file=sys.stderr)
    if available:
        print(f"Available commands: {', '.join(available)}", file=sys.stderr)
    return 1

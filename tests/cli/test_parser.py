"""Unit tests for scansort.cli.parser module."""

from scansort.cli.parser import build_parser


def test_build_parser():
    parser = build_parser()
    args = parser.parse_args(["watch", "--dry-run"])
    assert args.command == "watch"
    assert args.dry_run is True

    args_cfg = parser.parse_args(["config", "--set-key", "AIzaSyTest123"])
    assert args_cfg.command == "config"
    assert args_cfg.set_key == "AIzaSyTest123"


def test_build_parser_self_update_argument_suppressed():
    parser = build_parser()
    help_text = parser.format_help()
    assert "--self-update" not in help_text

    args = parser.parse_args(
        ["--self-update", "1234", "staged_dir", "install_dir", "1.2.3"]
    )
    assert args.self_update == ["1234", "staged_dir", "install_dir", "1.2.3"]


def test_build_parser_new_subcommands():
    parser = build_parser()

    # logs
    args_logs = parser.parse_args(["logs", "-n", "10", "--level", "ERROR", "--follow"])
    assert args_logs.command == "logs"
    assert args_logs.lines == 10
    assert args_logs.level == "ERROR"
    assert args_logs.follow is True

    # history
    args_hist = parser.parse_args(
        [
            "history",
            "-n",
            "5",
            "--status",
            "SUCCESS",
            "-q",
            "tax",
            "--json",
            "--reverse",
        ]
    )
    assert args_hist.command == "history"
    assert args_hist.limit == 5
    assert args_hist.status == "SUCCESS"
    assert args_hist.search == "tax"
    assert args_hist.json is True
    assert args_hist.reverse is True

    # stats
    args_stats = parser.parse_args(["stats", "--json"])
    assert args_stats.command == "stats"
    assert args_stats.json is True

    # help
    args_help = parser.parse_args(["help", "watch"])
    assert args_help.command == "help"
    assert args_help.command_name == "watch"

    # completion
    args_comp = parser.parse_args(["completion", "bash"])
    assert args_comp.command == "completion"
    assert args_comp.shell == "bash"

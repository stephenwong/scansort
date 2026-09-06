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

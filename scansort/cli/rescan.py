"""Taxonomy discovery and display CLI subcommand handler."""

import argparse
import json

from scansort.classification.doctor import (
    render_doctor_report,
    run_doctor,
)
from scansort.classification.taxonomy import (
    FolderMapper,
    render_taxonomy_tree,
    run_rescan,
)
from scansort.cli.args import CliArgs
from scansort.cli.config import _load_config_or_exit


def handle_rescan(parsed: argparse.Namespace) -> int:
    """Handle 'rescan' command to discover, display, and doctor the taxonomy."""
    cfg = _load_config_or_exit()
    if cfg is None:
        return 1
    cli = CliArgs.from_namespace(parsed)

    if cli.doctor:
        report = run_doctor(cfg)
        if cli.json:
            print(json.dumps(report.as_dict(), indent=2))
            return 0
        print(
            f"Discovered {len(report.folders)} destination folders in "
            f"{cfg.documents_root}:"
        )
        for line in render_taxonomy_tree(report.folders):
            print(f"  {line}")
        print()
        for line in render_doctor_report(report):
            print(line)
        return 0

    taxonomy = run_rescan(cfg, mapper_cls=FolderMapper)

    if cli.json:
        print(json.dumps(taxonomy, indent=2))
        return 0

    print(f"Discovered {len(taxonomy)} destination folders in {cfg.documents_root}:")
    for line in render_taxonomy_tree(taxonomy):
        print(f"  {line}")
    return 0

"""Taxonomy discovery and display CLI subcommand handler."""

import argparse

from scansort.classification.taxonomy import (
    FolderMapper,
    render_taxonomy_tree,
    run_rescan,
)
from scansort.cli.config import _load_config_or_exit


def handle_rescan(parsed: argparse.Namespace) -> int:
    """Handle 'rescan' command to discover and display taxonomy."""
    cfg = _load_config_or_exit()
    if cfg is None:
        return 1
    taxonomy = run_rescan(cfg, mapper_cls=FolderMapper)

    if getattr(parsed, "json", False):
        import json

        print(json.dumps(taxonomy, indent=2))
        return 0

    print(f"Discovered {len(taxonomy)} destination folders in {cfg.documents_root}:")
    for line in render_taxonomy_tree(taxonomy):
        print(f"  {line}")
    return 0

"""Taxonomy discovery and display CLI subcommand handler."""

import argparse

from scansort.classification.taxonomy import FolderMapper
from scansort.cli.config import _load_config_or_exit


def handle_rescan(parsed: argparse.Namespace) -> int:
    """Handle 'rescan' command to discover and display taxonomy."""
    cfg = _load_config_or_exit()
    if cfg is None:
        return 1
    mapper = FolderMapper(
        docs_root=cfg.documents_root,
        max_depth=cfg.max_folder_depth,
        fallback_folder=cfg.fallback_folder,
    )
    taxonomy = mapper.refresh()
    print(f"Discovered {len(taxonomy)} destination folders in {cfg.documents_root}:")
    for f in taxonomy:
        print(f"  - {f}")
    return 0

"""Typed, default-complete view over the raw argparse namespace."""

import argparse
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any


@dataclass
class CliArgs:
    """Typed CLI arguments with defaults for every flag.

    Handlers convert the raw ``argparse.Namespace`` once via
    :meth:`from_namespace`, so attribute access no longer needs the defensive
    ``getattr(parsed, "x", default)`` idiom (and hand-built test namespaces that
    omit optional flags still resolve to sensible defaults).
    """

    command: str | None = None
    verbose: bool = False
    minimized: bool = False
    dry_run: Any = False
    self_update: list[str] | None = None

    # config
    path: bool = False
    show: bool = False
    get: str | None = None
    set: list[str] | None = None
    set_key: str | None = None
    watch_folder: Path | None = None
    documents_folder: Path | None = None
    documents_root: Path | None = None
    gemini_model: str | None = None
    fallback_folder: str | None = None
    max_depth: int | None = None
    mirror_csv: str | None = None
    auto_update: str | None = None
    update_check_interval: int | None = None
    autostart: str | None = None
    context_menu: str | None = None
    ocr: str | None = None
    ocr_menu: str | None = None
    json: bool = False

    # file
    copy: bool = False
    files: list[Path] = field(default_factory=list)

    # ocr-backfill
    targets: list[Path] = field(default_factory=list)
    language: str | None = None

    # logs
    follow: bool = False
    level: str | None = None
    lines: int = 50
    clear: bool = False

    # history
    status: str | None = None
    search: str | None = None
    reverse: bool = False
    limit: int | None = None

    # review
    gui: bool = False
    cli: bool = False

    # completion / help
    shell: str = "bash"
    command_name: str | None = None

    @classmethod
    def from_namespace(cls, namespace: argparse.Namespace) -> "CliArgs":
        """Copy present namespace attributes, filling absent ones with defaults."""
        present = {
            f.name: getattr(namespace, f.name)
            for f in dataclass_fields(cls)
            if hasattr(namespace, f.name)
        }
        return cls(**present)


__all__ = ["CliArgs"]

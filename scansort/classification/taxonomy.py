"""Folder mapping and taxonomy discovery engine for scanning pre-existing Documents directories."""

import json
import logging
import os
import sys
import time
from pathlib import Path

from scansort.classification.hints import load_folder_hints, normalize_folder_key
from scansort.core.config import get_default_app_dir
from scansort.core.constants import (
    DEFAULT_IGNORED_FOLDERS,
    DEFAULT_MAX_FOLDER_DEPTH,
    FOLDER_MAP_FILENAME,
    REVIEW_NEEDED_DIR,
)
from scansort.core.fs import atomic_write, normalize_relative_folder

logger = logging.getLogger(__name__)

# Re-export for backward compatibility with external callers
__all__ = [
    "DEFAULT_IGNORED_FOLDERS",
    "FolderMapper",
    "format_taxonomy_for_prompt",
    "scan_documents_folders",
]

TAXONOMY_CACHE_MAX_AGE_SECONDS: float = 3600.0

FILE_ATTRIBUTE_HIDDEN: int = 0x2


def _is_hidden_directory(path: Path) -> bool:
    """Return True on Windows when the directory carries the hidden attribute."""
    if sys.platform != "win32":
        return False
    try:
        attrs = getattr(os.stat(path, follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & FILE_ATTRIBUTE_HIDDEN)


def scan_documents_folders(
    docs_root: Path,
    max_depth: int = DEFAULT_MAX_FOLDER_DEPTH,
    fallback_folder: str = REVIEW_NEEDED_DIR,
    ignored_folders: set[str] | None = None,
) -> list[str]:
    """Scan documents root directory recursively and return valid relative subfolder paths.

    Args:
        docs_root: Absolute path to Documents root.
        max_depth: Maximum directory recursion depth.
        fallback_folder: Name of the review/fallback folder to ignore from target list.
        ignored_folders: Set of folder names in lowercase to exclude.

    Returns:
        Sorted list of relative POSIX folder paths (e.g. 'Finances/Banking/ANZ').
    """
    if not docs_root.is_dir():
        return []

    ignored = (
        ignored_folders if ignored_folders is not None else DEFAULT_IGNORED_FOLDERS
    )
    fallback_norm = normalize_relative_folder(fallback_folder).lower()
    discovered: list[str] = []

    def _walk(current: Path, current_depth: int) -> None:
        if current_depth > max_depth:
            return

        try:
            entries = list(current.iterdir())
        except OSError as e:
            logger.debug("Skipping inaccessible directory %s: %s", current, e)
            return

        subdirs: list[Path] = []
        for p in entries:
            try:
                if p.is_dir():
                    if p.is_symlink() or p.is_junction():
                        # A link resolving outside documents_root would be
                        # advertised but always rejected by the dispatcher,
                        # silently mis-routing every matching document.
                        logger.debug("Skipping linked taxonomy entry %s.", p)
                        continue
                    if _is_hidden_directory(p):
                        logger.debug("Skipping hidden taxonomy entry %s.", p)
                        continue
                    subdirs.append(p)
            except OSError as e:
                logger.debug("Skipping inaccessible entry %s: %s", p, e)

        for subdir in sorted(subdirs):
            name = subdir.name
            name_lower = name.lower()
            rel_path = subdir.relative_to(docs_root).as_posix()
            rel_lower = rel_path.lower()

            # Skip dotfolders, fallback folder (case-insensitive), and noise folders
            if (
                name.startswith(".")
                or rel_lower == fallback_norm
                or name_lower in ignored
            ):
                continue

            discovered.append(rel_path)

            _walk(subdir, current_depth + 1)

    _walk(docs_root, 1)
    return sorted(discovered)


def format_taxonomy_for_prompt(
    folders: list[str], hints: dict[str, list[str]] | None = None
) -> str:
    """Format discovered folders and keyword hints into an optimized prompt block for Gemini.

    Args:
        folders: List of relative folder paths.
        hints: Optional dictionary mapping folder paths to keyword hints.

    Returns:
        Formatted multi-line string for prompt injection.
    """
    if not folders:
        return "No pre-existing folders detected."

    active_hints = {
        normalize_folder_key(k).lower(): v for k, v in (hints or {}).items()
    }
    lines = ["AVAILABLE DESTINATION FOLDERS:"]
    for folder in folders:
        folder_hints = active_hints.get(folder.lower())
        if folder_hints:
            hints_str = ", ".join(folder_hints)
            lines.append(f"- {folder} (Hints: {hints_str})")
        else:
            lines.append(f"- {folder}")

    return "\n".join(lines)


class FolderMapper:
    """Manages folder taxonomy discovery, caching, and prompt generation."""

    def __init__(
        self,
        docs_root: Path,
        cache_path: Path | None = None,
        hints_path: Path | None = None,
        max_depth: int = DEFAULT_MAX_FOLDER_DEPTH,
        fallback_folder: str = REVIEW_NEEDED_DIR,
    ) -> None:
        self.docs_root = docs_root
        self.cache_path = cache_path or (get_default_app_dir() / FOLDER_MAP_FILENAME)
        self.hints_path = hints_path
        self.max_depth = max_depth
        self.fallback_folder = fallback_folder
        self._cached_folders: list[str] | None = None
        self._cache_mtime: float | None = None

    def refresh(self) -> list[str]:
        """Scan documents root and write results to the cache file."""
        self._cached_folders = scan_documents_folders(
            docs_root=self.docs_root,
            max_depth=self.max_depth,
            fallback_folder=self.fallback_folder,
        )

        cache_data = {
            "documents_root": str(self.docs_root),
            "folders": self._cached_folders,
        }
        try:
            atomic_write(self.cache_path, json.dumps(cache_data, indent=2))
            if self.cache_path.exists():
                self._cache_mtime = self.cache_path.stat().st_mtime
        except (OSError, ValueError) as e:
            logger.warning("Failed to write folder cache to %s: %s", self.cache_path, e)

        logger.info(
            "Discovered %d destination folders in taxonomy under %s",
            len(self._cached_folders),
            self.docs_root,
        )
        return list(self._cached_folders)

    def _is_memory_cache_valid(self) -> bool:
        """Check if in-memory cache is present and matches the disk file modification time."""
        if self._cached_folders is None:
            return False
        try:
            if self.cache_path.exists():
                current_mtime = self.cache_path.stat().st_mtime
                if self._cache_mtime is not None and current_mtime != self._cache_mtime:
                    self._cached_folders = None
                    return False
        except OSError:
            pass
        return self._cached_folders is not None

    def _cache_is_fresh(self) -> bool:
        """Return True when the cached taxonomy is younger than the TTL."""
        if self._cache_mtime is None:
            return False
        return (time.time() - self._cache_mtime) <= TAXONOMY_CACHE_MAX_AGE_SECONDS

    def _load_from_disk_cache(self) -> list[str] | None:
        """Load taxonomy from the disk cache file if valid for the current documents root."""
        if not self.cache_path.exists():
            return None
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                cached_root = data.get("documents_root")
                if (
                    cached_root
                    and Path(cached_root).resolve() == self.docs_root.resolve()
                ):
                    folders = data.get("folders", [])
                    if isinstance(folders, list):
                        # Drop cached entries whose folders no longer exist so a
                        # deleted folder is never advertised or re-created.
                        existing = [
                            str(f)
                            for f in folders
                            if (self.docs_root / str(f)).is_dir()
                        ]
                        self._cached_folders = existing
                        self._cache_mtime = self.cache_path.stat().st_mtime
                        return self._cached_folders
        except OSError, ValueError:
            pass
        return None

    def get_taxonomy(self) -> list[str]:
        """Return the current taxonomy, re-scanning when the cache is stale.

        Newly created or renamed folders are picked up automatically once the
        cached scan is older than the TTL, and stale entries whose directories
        no longer exist are pruned on load.
        """
        if self._is_memory_cache_valid() and self._cache_is_fresh():
            return list(self._cached_folders)
        disk_folders = self._load_from_disk_cache()
        if disk_folders is not None and self._cache_is_fresh():
            return list(disk_folders)
        return list(self.refresh())

    def get_prompt_string(self) -> str:
        """Return the taxonomy formatted for the Gemini prompt."""
        folders = self.get_taxonomy()
        hints = load_folder_hints(self.hints_path)
        return format_taxonomy_for_prompt(folders, hints)

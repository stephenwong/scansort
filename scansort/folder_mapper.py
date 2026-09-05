"""Folder mapping and taxonomy discovery engine for scanning pre-existing Documents directories."""

import json
import logging
from pathlib import Path

from scansort.config import get_default_app_dir
from scansort.constants import REVIEW_NEEDED_DIR
from scansort.folder_hints import load_folder_hints
from scansort.fs_utils import atomic_write

logger = logging.getLogger(__name__)

DEFAULT_IGNORED_FOLDERS: set[str] = {
    "my games",
    "zoom",
    "custom office templates",
    "onenote notebooks",
    "outlook files",
    "windowspowershell",
    "adobe",
    "audacity",
    "camtasia",
    "power bi desktop",
    "electronic arts",
    "square enix",
    "rockstar games",
    "call of duty",
    "$recycle.bin",
    "system volume information",
}


def scan_documents_folders(
    docs_root: Path,
    max_depth: int = 3,
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
    if not docs_root.exists() or not docs_root.is_dir():
        return []

    ignored = (
        ignored_folders if ignored_folders is not None else DEFAULT_IGNORED_FOLDERS
    )
    fallback_norm = fallback_folder.strip("/\\").lower()
    discovered: list[str] = []

    def _walk(current: Path, current_depth: int) -> None:
        if current_depth > max_depth:
            return

        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError) as e:
            logger.debug("Skipping inaccessible directory %s: %s", current, e)
            return

        subdirs: list[Path] = []
        for p in entries:
            try:
                if p.is_dir():
                    subdirs.append(p)
            except (OSError, PermissionError) as e:
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
                or rel_lower.startswith(f"{fallback_norm}/")
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
        k.replace("\\", "/").strip().strip("/").lower(): v
        for k, v in (hints or {}).items()
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
        max_depth: int = 3,
        fallback_folder: str = REVIEW_NEEDED_DIR,
    ) -> None:
        self.docs_root = docs_root
        self.cache_path = cache_path or (get_default_app_dir() / "folder_map.json")
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

        return self._cached_folders

    def get_taxonomy(self) -> list[str]:
        """Return the current taxonomy, loading from cache if available."""
        if self._cached_folders is not None:
            try:
                if self.cache_path.exists():
                    current_mtime = self.cache_path.stat().st_mtime
                    if (
                        self._cache_mtime is not None
                        and current_mtime != self._cache_mtime
                    ):
                        self._cached_folders = None
            except OSError:
                pass
            if self._cached_folders is not None:
                return self._cached_folders

        if self.cache_path.exists():
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cached_root = data.get("documents_root")
                    if (
                        cached_root
                        and Path(cached_root).resolve() == self.docs_root.resolve()
                    ):
                        folders = data.get("folders", [])
                        if isinstance(folders, list):
                            self._cached_folders = [str(f) for f in folders]
                            self._cache_mtime = self.cache_path.stat().st_mtime
                            return self._cached_folders
            except (json.JSONDecodeError, OSError, ValueError, AttributeError):
                pass

        return self.refresh()

    def get_prompt_string(self) -> str:
        """Return the taxonomy formatted for the Gemini prompt."""
        folders = self.get_taxonomy()
        hints = load_folder_hints(self.hints_path)
        return format_taxonomy_for_prompt(folders, hints)

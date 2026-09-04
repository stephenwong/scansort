"""Folder mapping and taxonomy discovery engine for scanning pre-existing Documents directories."""

import json
import logging
import tempfile
from pathlib import Path

from scansort.config import get_default_app_dir
from scansort.folder_hints import load_folder_hints

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
    fallback_folder: str = "_Review_Needed",
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
    discovered: list[str] = []

    def _walk(current: Path, current_depth: int) -> None:
        if current_depth > max_depth:
            return

        try:
            subdirs = [p for p in current.iterdir() if p.is_dir()]
        except (OSError, PermissionError) as e:
            logger.debug("Skipping inaccessible directory %s: %s", current, e)
            return

        for subdir in sorted(subdirs):
            name = subdir.name
            name_lower = name.lower()

            # Skip dotfolders, fallback folder (case-insensitive), and noise folders
            if (
                name.startswith(".")
                or name_lower == fallback_folder.lower()
                or name_lower in ignored
            ):
                continue

            rel_path = subdir.relative_to(docs_root).as_posix()
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

    active_hints = {k.lower(): v for k, v in (hints or {}).items()}
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
        fallback_folder: str = "_Review_Needed",
    ) -> None:
        self.docs_root = docs_root
        self.cache_path = cache_path or (get_default_app_dir() / "folder_map.json")
        self.hints_path = hints_path
        self.max_depth = max_depth
        self.fallback_folder = fallback_folder
        self._cached_folders: list[str] | None = None

    def refresh(self) -> list[str]:
        """Scan documents root and write results to the cache file."""
        self._cached_folders = scan_documents_folders(
            docs_root=self.docs_root,
            max_depth=self.max_depth,
            fallback_folder=self.fallback_folder,
        )

        tmp_path = None
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "documents_root": str(self.docs_root),
                "folders": self._cached_folders,
            }
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.cache_path.parent,
                delete=False,
                encoding="utf-8",
                suffix=".tmp",
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                json.dump(cache_data, tmp_file, indent=2)
            tmp_path.replace(self.cache_path)
        except (OSError, ValueError) as e:
            logger.warning("Failed to write folder cache to %s: %s", self.cache_path, e)
        finally:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

        return self._cached_folders

    def get_taxonomy(self) -> list[str]:
        """Return the current taxonomy, loading from cache if available."""
        if self._cached_folders is not None:
            return self._cached_folders

        if self.cache_path.exists():
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cached_root = data.get("documents_root")
                    if cached_root == str(self.docs_root):
                        folders = data.get("folders", [])
                        if isinstance(folders, list):
                            self._cached_folders = [str(f) for f in folders]
                            return self._cached_folders
            except (json.JSONDecodeError, OSError, ValueError, AttributeError):
                pass

        return self.refresh()

    def get_prompt_string(self) -> str:
        """Return the taxonomy formatted for the Gemini prompt."""
        folders = self.get_taxonomy()
        hints = load_folder_hints(self.hints_path)
        return format_taxonomy_for_prompt(folders, hints)

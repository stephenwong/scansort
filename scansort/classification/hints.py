"""User keyword hint manager to steer Gemini classification for personal folder taxonomies."""

import json
import logging
from pathlib import Path

from scansort.core.config import get_default_app_dir
from scansort.core.constants import HINTS_FILENAME
from scansort.core.fs import atomic_write, normalize_relative_folder

logger = logging.getLogger(__name__)


def normalize_folder_key(folder: str) -> str:
    """Normalize folder path by converting backslashes and stripping whitespace/slashes."""
    return normalize_relative_folder(folder)


def get_default_hints_path() -> Path:
    """Return the default path to folder_hints.json."""
    return get_default_app_dir() / HINTS_FILENAME


def load_folder_hints(hints_path: Path | None = None) -> dict[str, list[str]]:
    """Load user keyword hints mapping folder paths to relevant search terms.

    Args:
        hints_path: Optional custom path to folder_hints.json.

    Returns:
        Dictionary mapping normalized folder paths (forward slashes) to lists of keyword strings.
    """
    path = hints_path or get_default_hints_path()
    if not path.exists():
        return {}

    try:
        content = path.read_text(encoding="utf-8-sig")
        data = json.loads(content)
        if not isinstance(data, dict):
            logger.warning("Invalid folder_hints.json format, expected dictionary.")
            return {}

        normalized: dict[str, list[str]] = {}
        for folder, keywords in data.items():
            norm_folder = normalize_folder_key(folder)
            if not norm_folder:
                continue
            if isinstance(keywords, list):
                clean_keywords = [
                    kw.strip().lower()
                    for kw in keywords
                    if isinstance(kw, str) and kw.strip()
                ]
                if clean_keywords:
                    normalized[norm_folder] = clean_keywords

        logger.debug("Loaded %d folder hint mappings from %s", len(normalized), path)
        return normalized
    except (json.JSONDecodeError, OSError, ValueError) as e:
        logger.warning("Failed to load folder hints from %s: %s", path, e)
        return {}


def save_folder_hints(
    hints: dict[str, list[str]], hints_path: Path | None = None
) -> None:
    """Atomically write user keyword hints to folder_hints.json.

    Args:
        hints: Dictionary mapping normalized relative folder paths to keyword strings.
        hints_path: Optional custom path to folder_hints.json.
    """
    path = hints_path or get_default_hints_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(hints, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    atomic_write(path, serialized)
    logger.debug("Saved %d folder hint mappings to %s", len(hints), path)


def add_folder_hint(
    folder: str,
    keywords: list[str] | str,
    hints_path: Path | None = None,
) -> dict[str, list[str]]:
    """Add one or more keyword hints for a target folder and persist to disk.

    Args:
        folder: Target destination folder path.
        keywords: Keyword string or list of keyword strings to associate.
        hints_path: Optional custom path to folder_hints.json.

    Returns:
        Updated dictionary of all folder hint mappings.
    """
    path = hints_path or get_default_hints_path()
    current = load_folder_hints(path)
    norm_folder = normalize_folder_key(folder)
    if not norm_folder:
        return current

    kw_list = [keywords] if isinstance(keywords, str) else list(keywords)
    existing_kws = current.get(norm_folder, [])
    updated_kws = list(existing_kws)
    for kw in kw_list:
        if isinstance(kw, str):
            clean_kw = kw.strip().lower()
            if clean_kw and clean_kw not in updated_kws:
                updated_kws.append(clean_kw)

    if updated_kws != existing_kws:
        current[norm_folder] = updated_kws
        save_folder_hints(current, path)

    return current

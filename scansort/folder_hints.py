"""User keyword hint manager to steer Gemini classification for personal folder taxonomies."""

import json
import logging
from pathlib import Path

from scansort.config import get_default_app_dir
from scansort.constants import HINTS_FILENAME

logger = logging.getLogger(__name__)


def normalize_folder_key(folder: str) -> str:
    """Normalize folder path by converting backslashes and stripping whitespace/slashes."""
    return folder.replace("\\", "/").strip().strip("/")


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

        return normalized
    except (json.JSONDecodeError, OSError, ValueError) as e:
        logger.warning("Failed to load folder hints from %s: %s", path, e)
        return {}

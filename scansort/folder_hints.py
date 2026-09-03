"""User keyword hint manager to steer Gemini classification for personal folder taxonomies."""

import json
import logging
from pathlib import Path

from scansort.config import get_default_app_dir

logger = logging.getLogger(__name__)


def get_default_hints_path() -> Path:
    """Return the default path to folder_hints.json."""
    return get_default_app_dir() / "folder_hints.json"


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
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        if not isinstance(data, dict):
            logger.warning("Invalid folder_hints.json format, expected dictionary.")
            return {}

        normalized: dict[str, list[str]] = {}
        for folder, keywords in data.items():
            norm_folder = folder.replace("\\", "/").strip().strip("/")
            if isinstance(keywords, list):
                clean_keywords = [
                    str(kw).strip().lower() for kw in keywords if str(kw).strip()
                ]
                if clean_keywords:
                    normalized[norm_folder] = clean_keywords

        return normalized
    except (json.JSONDecodeError, OSError, ValueError) as e:
        logger.warning("Failed to load folder hints from %s: %s", path, e)
        return {}

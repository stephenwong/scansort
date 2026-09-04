"""Configuration management for ScanSort."""

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


def get_default_app_dir() -> Path:
    """Return the platform-appropriate application data directory."""
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        base = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
        return base / "ScanSort"

    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else Path.home() / ".config"
    return base / "scansort"


def get_default_config_path() -> Path:
    """Return the default path to config.json."""
    return get_default_app_dir() / "config.json"


def _default_watch_folder() -> Path:
    return Path.home() / "Scans" / "Inbox"


def _default_documents_root() -> Path:
    return Path.home() / "Documents"


class AppConfig(BaseModel):
    """Application configuration settings."""

    watch_folder: Path = Field(default_factory=_default_watch_folder)
    documents_root: Path = Field(default_factory=_default_documents_root)
    fallback_folder: str = "_Review_Needed"
    gemini_model: str = "gemini-2.5-flash"
    start_on_boot: bool = True
    max_folder_depth: int = 3
    dry_run: bool = False
    mirror_log_to_documents: bool = False

    @field_validator("fallback_folder")
    @classmethod
    def validate_fallback_folder(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("fallback_folder cannot be empty")
        clean = v.strip()
        parts = clean.replace("\\", "/").split("/")
        if clean.startswith(("/", "\\")) or ".." in parts:
            raise ValueError(
                "fallback_folder cannot contain absolute paths or '..' traversal segments"
            )
        return clean

    def ensure_directories(self) -> None:
        """Create watch folder, documents root, and fallback folder if they do not exist."""
        self.watch_folder.mkdir(parents=True, exist_ok=True)
        self.documents_root.mkdir(parents=True, exist_ok=True)
        (self.documents_root / self.fallback_folder).mkdir(parents=True, exist_ok=True)


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load configuration from a JSON file, returning defaults if file doesn't exist."""
    path = config_path or get_default_config_path()
    if not path.exists():
        logger.info("Config file not found at %s, using defaults.", path)
        return AppConfig()

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        if not isinstance(data, dict):
            logger.warning(
                "Config file at %s is not a dictionary. Using defaults.", path
            )
            return AppConfig()
        if data.get("watch_folder") is not None:
            data["watch_folder"] = Path(data["watch_folder"])
        else:
            data.pop("watch_folder", None)
        if data.get("documents_root") is not None:
            data["documents_root"] = Path(data["documents_root"])
        else:
            data.pop("documents_root", None)
        return AppConfig(**data)
    except (json.JSONDecodeError, OSError, ValueError, TypeError) as e:
        logger.warning(
            "Error reading config at %s (%s). Using default configuration.", path, e
        )
        return AppConfig()


def save_config(config: AppConfig, config_path: Path | None = None) -> None:
    """Serialize configuration to a JSON file (strictly excluding secrets)."""
    path = config_path or get_default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "watch_folder": str(config.watch_folder),
        "documents_root": str(config.documents_root),
        "fallback_folder": config.fallback_folder,
        "gemini_model": config.gemini_model,
        "start_on_boot": config.start_on_boot,
        "max_folder_depth": config.max_folder_depth,
        "dry_run": config.dry_run,
        "mirror_log_to_documents": config.mirror_log_to_documents,
    }

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False, encoding="utf-8", suffix=".tmp"
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            json.dump(data, tmp_file, indent=2)
        tmp_path.replace(path)
        logger.info("Configuration saved to %s", path)
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

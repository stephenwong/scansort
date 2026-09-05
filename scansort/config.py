"""Configuration management for ScanSort."""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scansort.constants import (
    CONFIG_FILENAME,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_MAX_FOLDER_DEPTH,
    MIRROR_HISTORY_CSV_NAME,
    REVIEW_NEEDED_DIR,
)
from scansort.fs_utils import atomic_write, relative_folder_is_safe

logger = logging.getLogger(__name__)


def get_default_app_dir() -> Path:
    """Return the platform-appropriate application data directory."""
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        if app_data:
            return Path(app_data) / "ScanSort"
        return Path.home() / "AppData" / "Roaming" / "ScanSort"
    return Path.home() / ".config" / "scansort"


def get_default_config_path() -> Path:
    """Return the default configuration file path."""
    return get_default_app_dir() / CONFIG_FILENAME


def _default_watch_folder() -> Path:
    return Path.home() / "Scans" / "Inbox"


def _default_documents_root() -> Path:
    return Path.home() / "Documents"


class AppConfig(BaseModel):
    """Application configuration settings."""

    model_config = ConfigDict(validate_assignment=True)

    watch_folder: Path = Field(default_factory=_default_watch_folder)
    documents_root: Path = Field(default_factory=_default_documents_root)
    fallback_folder: str = REVIEW_NEEDED_DIR
    gemini_model: str = DEFAULT_GEMINI_MODEL
    start_on_boot: bool = True
    max_folder_depth: int = Field(default=DEFAULT_MAX_FOLDER_DEPTH, ge=1, le=10)
    dry_run: bool = False
    mirror_log_to_documents: bool = False

    @property
    def mirror_csv_path(self) -> Path | None:
        """Return the path to the mirror history CSV in Documents, or None if disabled."""
        if self.mirror_log_to_documents:
            return self.documents_root / MIRROR_HISTORY_CSV_NAME
        return None

    @field_validator("gemini_model", mode="before")
    @classmethod
    def validate_gemini_model(cls, v: Any) -> str:
        if v is None or not str(v).strip():
            return DEFAULT_GEMINI_MODEL
        return str(v).strip()

    @field_validator("fallback_folder")
    @classmethod
    def validate_fallback_folder(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("fallback_folder cannot be empty")
        clean = v.strip()
        if not relative_folder_is_safe(clean):
            raise ValueError(
                "fallback_folder cannot contain absolute paths or '..' traversal segments"
            )
        return clean.strip("/\\")

    @model_validator(mode="after")
    def validate_distinct_roots(self) -> "AppConfig":
        if self.watch_folder.resolve() == self.documents_root.resolve():
            raise ValueError(
                "watch_folder and documents_root cannot be the same directory"
            )
        if self.watch_folder.resolve().is_file():
            raise ValueError("watch_folder cannot be a regular file")
        if self.documents_root.resolve().is_file():
            raise ValueError("documents_root cannot be a regular file")
        return self

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
        content = path.read_text(encoding="utf-8-sig")
        data = json.loads(content)
        if not isinstance(data, dict):
            logger.warning(
                "Config file at %s is not a dictionary. Using defaults.", path
            )
            return AppConfig()
        clean_data = {k: v for k, v in data.items() if v is not None}
        return AppConfig(**clean_data)
    except (json.JSONDecodeError, OSError, ValueError, TypeError) as e:
        logger.warning(
            "Error reading config at %s (%s). Using default configuration.", path, e
        )
        return AppConfig()


def save_config(config: AppConfig, config_path: Path | None = None) -> None:
    """Serialize configuration to a JSON file (strictly excluding secrets)."""
    path = config_path or get_default_config_path()
    atomic_write(path, json.dumps(config.model_dump(mode="json"), indent=2))
    logger.info("Configuration saved to %s", path)

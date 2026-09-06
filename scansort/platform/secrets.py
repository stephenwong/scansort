"""Secrets Vault for ScanSort using OS-level encrypted storage (Windows Credential Manager / keyring)."""

import logging
import os
import re

import keyring
import keyring.errors

logger = logging.getLogger(__name__)

SERVICE_NAME: str = "ScanSort"
KEY_NAME: str = "GeminiApiKey"

# Regex pattern matching Google / Gemini API keys (AIza followed by 30 or more key chars)
_GEMINI_KEY_REGEX: re.Pattern = re.compile(r"AIza[0-9A-Za-z_-]{30,}")


def get_api_key() -> str | None:
    """Retrieve the Gemini API key from keyring, falling back to GEMINI_API_KEY environment variable.

    Returns:
        The stripped API key string if found, otherwise None.
    """
    try:
        key = keyring.get_password(SERVICE_NAME, KEY_NAME)
        if key and key.strip():
            return key.strip()
    except (keyring.errors.KeyringError, OSError) as e:
        logger.debug("Keyring access failed, falling back to environment: %s", e)

    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    return None


def set_api_key(key: str) -> None:
    """Store the Gemini API key securely in the OS credential vault.

    Args:
        key: The non-empty API key string.

    Raises:
        ValueError: If key is empty or contains only whitespace.
        OSError: If storing the key in the OS credential vault fails.
    """
    if not key or not key.strip():
        raise ValueError("API key cannot be empty.")

    cleaned_key = key.strip()
    try:
        keyring.set_password(SERVICE_NAME, KEY_NAME, cleaned_key)
    except (keyring.errors.KeyringError, OSError) as e:
        logger.error("Failed to store API key in OS credential vault: %s", e)
        raise OSError(f"Failed to store API key in OS credential vault: {e}") from e


def delete_api_key() -> None:
    """Remove the stored Gemini API key from the OS credential vault."""
    try:
        keyring.delete_password(SERVICE_NAME, KEY_NAME)
    except keyring.errors.PasswordDeleteError:
        logger.debug("Password was already absent from vault.")
    except (keyring.errors.KeyringError, OSError) as e:
        logger.warning("Could not delete password from keyring: %s", e)


def mask_api_key(key: str | None) -> str:
    """Mask an API key for safe UI display and terminal logging.

    Example:
        'AIzaSyD-1234567890abcdef7890' -> 'AIza••••••••7890'

    Args:
        key: The key string to mask.

    Returns:
        Masked representation of the key.
    """
    if not key or not key.strip():
        return "[NOT SET]"

    cleaned = key.strip()
    if len(cleaned) <= 8:
        return "••••••••"

    prefix = cleaned[:4]
    suffix = cleaned[-4:]
    return f"{prefix}••••••••{suffix}"


def redact_secrets_from_text(text: str, key: str | None = None) -> str:
    """Sanitize logs, console messages, or exceptions by redacting any occurrences of the API key.

    Args:
        text: The message or stack trace to redact.
        key: Optional known active key to redact explicitly. If None, queries get_api_key().

    Returns:
        Redacted text with keys replaced by redaction placeholders.
    """
    if not text:
        return ""

    redacted = text

    # Redact explicit key or fallback to vault/env key
    active_key = key if key is not None else get_api_key()
    if active_key and active_key.strip():
        redacted = redacted.replace(active_key.strip(), "[REDACTED_KEY]")

    # Redact any string matching Gemini API key pattern
    redacted = _GEMINI_KEY_REGEX.sub("[REDACTED_GEMINI_KEY]", redacted)

    return redacted

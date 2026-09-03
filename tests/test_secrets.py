"""Unit tests for scansort.secrets module (Secrets Vault)."""

from unittest.mock import patch

import keyring.errors
import pytest

from scansort.secrets import (
    KEY_NAME,
    SERVICE_NAME,
    delete_api_key,
    get_api_key,
    mask_api_key,
    redact_secrets_from_text,
    set_api_key,
)


def test_get_api_key_from_keyring():
    with patch("keyring.get_password", return_value="AIzaSyTestKey1234567890"):
        key = get_api_key()
        assert key == "AIzaSyTestKey1234567890"


def test_get_api_key_fallback_to_env(monkeypatch):
    with patch("keyring.get_password", return_value=None):
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyEnvKey9876543210")
        key = get_api_key()
        assert key == "AIzaSyEnvKey9876543210"


def test_get_api_key_returns_none_when_missing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch("keyring.get_password", return_value=None):
        key = get_api_key()
        assert key is None


def test_get_api_key_strips_whitespace():
    with patch("keyring.get_password", return_value="  AIzaSyWhitespaceKey123  \n"):
        key = get_api_key()
        assert key == "AIzaSyWhitespaceKey123"


def test_set_api_key_stores_in_keyring():
    with patch("keyring.set_password") as mock_set:
        set_api_key("AIzaSyNewSecretKey0000")
        mock_set.assert_called_once_with(
            SERVICE_NAME, KEY_NAME, "AIzaSyNewSecretKey0000"
        )


def test_set_api_key_raises_on_empty_or_whitespace():
    with pytest.raises(ValueError, match="API key cannot be empty"):
        set_api_key("")
    with pytest.raises(ValueError, match="API key cannot be empty"):
        set_api_key("   ")


def test_delete_api_key_removes_from_keyring():
    with patch("keyring.delete_password") as mock_delete:
        delete_api_key()
        mock_delete.assert_called_once_with(SERVICE_NAME, KEY_NAME)


def test_delete_api_key_handles_nonexistent_gracefully():
    with patch("keyring.delete_password", side_effect=keyring.errors.PasswordDeleteError):
        # Should not raise exception
        delete_api_key()


def test_mask_api_key():
    assert mask_api_key(None) == "[NOT SET]"
    assert mask_api_key("") == "[NOT SET]"
    assert mask_api_key("short") == "••••••••"
    masked = mask_api_key("AIzaSyD-1234567890abcdef7890")
    assert masked.startswith("AIza")
    assert masked.endswith("7890")
    assert "••••••••" in masked
    assert "1234567890" not in masked


def test_redact_secrets_from_text():
    raw_text = "Error connecting with key AIzaSyD-1234567890abcdef7890: timeout"
    redacted = redact_secrets_from_text(raw_text, key="AIzaSyD-1234567890abcdef7890")
    assert "AIzaSyD-1234567890abcdef7890" not in redacted
    assert "[REDACTED_KEY]" in redacted


def test_redact_secrets_regex_fallback():
    # Detects Gemini keys even if explicit key argument not passed
    gemini_key = "AIzaSyD_abc1234567890xyzABCD1234567890a"
    raw_text = f"Request failed with {gemini_key} at endpoint"
    redacted = redact_secrets_from_text(raw_text)
    assert gemini_key not in redacted
    assert "[REDACTED_GEMINI_KEY]" in redacted

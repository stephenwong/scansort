"""Unit tests for scansort.platform.secrets module (Secrets Vault)."""

from unittest.mock import patch

import keyring.errors
import pytest

from scansort.platform.secrets import (
    delete_api_key,
    get_api_key,
    mask_api_key,
    redact_secrets_from_text,
    set_api_key,
)


def test_get_api_key_from_keyring(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch("keyring.get_password", return_value="AIzaSyKeyFromKeyring"):
        assert get_api_key() == "AIzaSyKeyFromKeyring"


def test_get_api_key_fallback_to_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyKeyFromEnv")
    with patch("keyring.get_password", return_value=None):
        assert get_api_key() == "AIzaSyKeyFromEnv"


def test_get_api_key_returns_none_when_missing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch("keyring.get_password", return_value=None):
        assert get_api_key() is None


def test_get_api_key_strips_whitespace(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch("keyring.get_password", return_value="  AIzaSyWhitespaceKey  \n"):
        assert get_api_key() == "AIzaSyWhitespaceKey"


def test_set_api_key_stores_in_keyring():
    with patch("keyring.set_password") as mock_set:
        set_api_key("AIzaSyValidKey123")
        mock_set.assert_called_once_with(
            "ScanSort", "GeminiApiKey", "AIzaSyValidKey123"
        )


def test_set_api_key_keyring_error_raises_oserror():
    with (
        patch(
            "keyring.set_password",
            side_effect=keyring.errors.KeyringError("Vault locked"),
        ),
        pytest.raises(OSError, match="Failed to store API key in OS credential vault"),
    ):
        set_api_key("AIzaSyValidKey123")


def test_set_api_key_raises_on_empty_or_whitespace():
    with pytest.raises(ValueError, match="API key cannot be empty"):
        set_api_key("")

    with pytest.raises(ValueError, match="API key cannot be empty"):
        set_api_key("   \n\t  ")


def test_delete_api_key_removes_from_keyring():
    with patch("keyring.delete_password") as mock_del:
        delete_api_key()
        mock_del.assert_called_once_with("ScanSort", "GeminiApiKey")


def test_delete_api_key_handles_nonexistent_gracefully():
    with patch(
        "keyring.delete_password", side_effect=keyring.errors.PasswordDeleteError
    ):
        delete_api_key()


def test_mask_api_key():
    assert mask_api_key(None) == "[NOT SET]"
    assert mask_api_key("") == "[NOT SET]"
    assert mask_api_key("short") == "••••••••"
    masked = mask_api_key("AIzaSyB1234567890abcdefXYZ")
    assert masked.startswith("AIza")
    assert masked.endswith("XYZ")
    assert "••••••••" in masked


def test_redact_secrets_from_text():
    raw = "An error occurred with key AIzaSyRealKey456 during call"
    redacted = redact_secrets_from_text(raw, key="AIzaSyRealKey456")
    assert "AIzaSyRealKey456" not in redacted
    assert "[REDACTED_KEY]" in redacted


def test_redact_secrets_empty():
    assert redact_secrets_from_text("") == ""


def test_redact_secrets_regex_fallback():
    dummy_key = "AIzaSy" + "X" * 33
    raw = f"Gemini key {dummy_key} was leaked"
    redacted = redact_secrets_from_text(raw, key=None)
    assert dummy_key not in redacted
    assert "[REDACTED_GEMINI_KEY]" in redacted


def test_delete_api_key_keyring_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch(
        "keyring.delete_password",
        side_effect=keyring.errors.KeyringError("Keyring locked"),
    ):
        delete_api_key()  # Should not raise exception


def test_redact_secrets_variable_length_regex():
    # Variable length keys (30+ characters after AIza)
    for length in [30, 39, 45, 50]:
        key = "AIza" + "aB9_-" * (length // 5)
        raw = f"Exception using key {key} in request"
        redacted = redact_secrets_from_text(raw, key=None)
        assert key not in redacted
        assert "[REDACTED_GEMINI_KEY]" in redacted


def test_redact_secrets_fallback_to_active_vault_key(monkeypatch):
    active_key = "custom_vault_key_not_matching_regex"
    monkeypatch.setenv("GEMINI_API_KEY", active_key)
    raw = f"Error communicating with {active_key} endpoint"
    # When key=None, it should query get_api_key() and redact the active key
    redacted = redact_secrets_from_text(raw, key=None)
    assert active_key not in redacted
    assert "[REDACTED_KEY]" in redacted

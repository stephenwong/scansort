"""Unit tests for Gemini token accounting and cost calculation (scansort.logging.cost)."""

import pytest

from scansort.logging.cost import (
    calculate_gemini_cost,
    format_token_cost_summary,
    get_model_pricing,
)


def test_get_model_pricing_supported_and_fallback():
    # Supported gemini-3.1-flash-lite
    pricing_31 = get_model_pricing("gemini-3.1-flash-lite")
    assert pricing_31.input_per_m == 0.075
    assert pricing_31.output_per_m == 0.30

    # Supported gemini-3.5-flash-lite
    pricing_35 = get_model_pricing("gemini-3.5-flash-lite")
    assert pricing_35.input_per_m == 0.075
    assert pricing_35.output_per_m == 0.30

    # Snapshot prefix match
    pricing_snapshot = get_model_pricing("gemini-3.1-flash-lite-preview-02-05")
    assert pricing_snapshot.input_per_m == 0.075
    assert pricing_snapshot.output_per_m == 0.30

    # Fallback / unrecognized model defaults to Flash Lite tier pricing
    pricing_fallback = get_model_pricing("custom-experimental-model")
    assert pricing_fallback.input_per_m == 0.075
    assert pricing_fallback.output_per_m == 0.30


def test_calculate_gemini_cost():
    # 1,000,000 prompt tokens + 1,000,000 output tokens on flash-lite:
    # 0.075 + 0.30 = 0.375 USD
    cost = calculate_gemini_cost("gemini-3.1-flash-lite", 1_000_000, 1_000_000)
    assert pytest.approx(cost, 1e-6) == 0.375

    # Zero tokens consumed
    assert calculate_gemini_cost("gemini-3.1-flash-lite", 0, 0) == 0.0

    # Negative tokens bounded to 0
    assert calculate_gemini_cost("gemini-3.1-flash-lite", -10, -5) == 0.0

    # Test with gemini-3.5-flash-lite
    cost_35 = calculate_gemini_cost("gemini-3.5-flash-lite", 500_000, 200_000)
    assert pytest.approx(cost_35, 1e-6) == (0.5 * 0.075 + 0.2 * 0.30)


def test_format_token_cost_summary():
    summary = format_token_cost_summary(
        model="gemini-3.1-flash-lite",
        prompt_tokens=1850,
        candidates_tokens=120,
    )
    assert "Tokens: 1,850 in / 120 out (1,970 total)" in summary
    assert "Cost: $" in summary
    assert "gemini-3.1-flash-lite" in summary

    summary_35 = format_token_cost_summary(
        model="gemini-3.5-flash-lite",
        prompt_tokens=2500,
        candidates_tokens=300,
    )
    assert "Tokens: 2,500 in / 300 out (2,800 total)" in summary_35
    assert "gemini-3.5-flash-lite" in summary_35

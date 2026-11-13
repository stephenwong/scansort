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
    assert pricing_31.input_per_m == 0.25
    assert pricing_31.output_per_m == 1.50
    assert pricing_31.cached_input_per_m == 0.025

    # Supported gemini-3.5-flash-lite
    pricing_35 = get_model_pricing("gemini-3.5-flash-lite")
    assert pricing_35.input_per_m == 0.30
    assert pricing_35.output_per_m == 2.50
    assert pricing_35.cached_input_per_m == 0.030

    # Snapshot prefix match
    pricing_snapshot = get_model_pricing("gemini-3.1-flash-lite-preview-02-05")
    assert pricing_snapshot.input_per_m == 0.25
    assert pricing_snapshot.output_per_m == 1.50
    assert pricing_snapshot.cached_input_per_m == 0.025

    # Fallback / unrecognized model defaults to 3.5 Flash Lite tier pricing
    pricing_fallback = get_model_pricing("custom-experimental-model")
    assert pricing_fallback.input_per_m == 0.30
    assert pricing_fallback.output_per_m == 2.50
    assert pricing_fallback.cached_input_per_m == 0.030


def test_calculate_gemini_cost():
    # 1,000,000 prompt tokens + 1,000,000 output tokens on 3.1 flash-lite:
    # 0.25 + 1.50 = 1.75 USD
    cost = calculate_gemini_cost("gemini-3.1-flash-lite", 1_000_000, 1_000_000)
    assert pytest.approx(cost, 1e-6) == 1.75

    # Zero tokens consumed
    assert calculate_gemini_cost("gemini-3.1-flash-lite", 0, 0) == 0.0

    # Negative tokens bounded to 0
    assert calculate_gemini_cost("gemini-3.1-flash-lite", -10, -5) == 0.0

    # Test with gemini-3.5-flash-lite: 0.5 * 0.30 + 0.2 * 2.50 = 0.65
    cost_35 = calculate_gemini_cost("gemini-3.5-flash-lite", 500_000, 200_000)
    assert pytest.approx(cost_35, 1e-6) == (0.5 * 0.30 + 0.2 * 2.50)


def test_calculate_gemini_cost_with_cached_and_thoughts_tokens():
    # prompt_tokens includes cached_tokens (no double-counting):
    # 1,000,000 prompt (800,000 cached + 200,000 uncached) + 100,000 candidates + 100,000 thoughts
    # on gemini-3.5-flash-lite:
    # uncached: 0.2 * 0.30 = 0.06
    # cached:   0.8 * 0.03 = 0.024
    # output:   0.2 * 2.50 = 0.50
    cost = calculate_gemini_cost(
        "gemini-3.5-flash-lite",
        1_000_000,
        100_000,
        cached_tokens=800_000,
        thoughts_tokens=100_000,
    )
    assert pytest.approx(cost, 1e-6) == 0.584

    # Clamps cached_tokens to prompt_tokens and ignores negatives
    clamped = calculate_gemini_cost(
        "gemini-3.1-flash-lite",
        1_000_000,
        0,
        cached_tokens=2_000_000,
        thoughts_tokens=-50,
    )
    assert pytest.approx(clamped, 1e-6) == 0.025


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
        cached_tokens=1500,
        thoughts_tokens=50,
    )
    assert "2,500 in (1,500 cached)" in summary_35
    assert "300 out (+50 thoughts)" in summary_35
    assert "(2,850 total)" in summary_35
    assert "gemini-3.5-flash-lite" in summary_35

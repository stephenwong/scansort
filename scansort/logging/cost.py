"""Gemini API token usage accounting and estimated cost calculation."""

from dataclasses import dataclass


# Pricing per 1,000,000 tokens in USD.
# Reflects published Google Gemini API rates.
@dataclass(frozen=True)
class ModelPricing:
    input_per_m: float
    output_per_m: float
    cached_input_per_m: float = 0.0


# Published Flash-Lite tier pricing (prompts <= 128k context).
_FLASH_LITE_31_PRICING = ModelPricing(
    input_per_m=0.25,
    output_per_m=1.50,
    cached_input_per_m=0.025,
)
_FLASH_LITE_35_PRICING = ModelPricing(
    input_per_m=0.30,
    output_per_m=2.50,
    cached_input_per_m=0.030,
)

# Rates for supported Flash Lite models
_MODEL_PRICING_TABLE: dict[str, ModelPricing] = {
    "gemini-3.1-flash-lite": _FLASH_LITE_31_PRICING,
    "gemini-3.5-flash-lite": _FLASH_LITE_35_PRICING,
}

# Standard default rate for unrecognized models (uses default Flash-Lite pricing)
_DEFAULT_PRICING = _FLASH_LITE_35_PRICING


def get_model_pricing(model: str) -> ModelPricing:
    """Return the input, output, and cached-input pricing per million tokens for a Gemini model."""
    clean_model = model.strip().lower() if model else ""
    if clean_model in _MODEL_PRICING_TABLE:
        return _MODEL_PRICING_TABLE[clean_model]

    # Partial prefix match for versioned snapshots (e.g. 'gemini-3.1-flash-lite-001')
    for key, pricing in _MODEL_PRICING_TABLE.items():
        if clean_model.startswith(key):
            return pricing

    return _DEFAULT_PRICING


def calculate_gemini_cost(
    model: str,
    prompt_tokens: int,
    candidates_tokens: int,
    *,
    cached_tokens: int = 0,
    thoughts_tokens: int = 0,
) -> float:
    """Calculate the estimated USD cost of a Gemini API call from token usage.

    ``prompt_tokens`` from Gemini ``usage_metadata`` already includes
    ``cached_tokens``, so cached tokens are subtracted before pricing the
    uncached input remainder. ``thoughts_tokens`` are billed at the output rate.
    """
    valid_prompt = max(0, prompt_tokens)
    valid_cached = min(valid_prompt, max(0, cached_tokens))
    uncached_prompt = valid_prompt - valid_cached
    valid_output = max(0, candidates_tokens) + max(0, thoughts_tokens)

    pricing = get_model_pricing(model)
    input_cost = (uncached_prompt / 1_000_000.0) * pricing.input_per_m
    cached_cost = (valid_cached / 1_000_000.0) * pricing.cached_input_per_m
    output_cost = (valid_output / 1_000_000.0) * pricing.output_per_m

    return input_cost + cached_cost + output_cost


def format_token_cost_summary(
    model: str,
    prompt_tokens: int,
    candidates_tokens: int,
    *,
    cached_tokens: int = 0,
    thoughts_tokens: int = 0,
) -> str:
    """Format a human-readable token and cost summary string.

    Example:
        'Tokens: 1,850 in / 120 out (1,970 total) | Cost: $0.000855 USD (gemini-3.5-flash-lite)'
    """
    valid_prompt = max(0, prompt_tokens)
    valid_candidates = max(0, candidates_tokens)
    valid_cached = min(valid_prompt, max(0, cached_tokens))
    valid_thoughts = max(0, thoughts_tokens)
    total_tokens = valid_prompt + valid_candidates + valid_thoughts
    cost = calculate_gemini_cost(
        model,
        valid_prompt,
        valid_candidates,
        cached_tokens=valid_cached,
        thoughts_tokens=valid_thoughts,
    )

    in_detail = f"{valid_prompt:,} in"
    if valid_cached > 0:
        in_detail += f" ({valid_cached:,} cached)"
    out_detail = f"{valid_candidates:,} out"
    if valid_thoughts > 0:
        out_detail += f" (+{valid_thoughts:,} thoughts)"

    return (
        f"Tokens: {in_detail} / {out_detail} ({total_tokens:,} total) | "
        f"Cost: ${cost:.6f} USD ({model})"
    )

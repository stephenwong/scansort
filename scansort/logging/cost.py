"""Gemini API token usage accounting and estimated cost calculation."""

from dataclasses import dataclass


# Pricing per 1,000,000 tokens in USD.
# Reflects published Google Gemini API rates.
@dataclass(frozen=True)
class ModelPricing:
    input_per_m: float
    output_per_m: float


# Default rates for supported Flash Lite models (prompts <= 128k context)
_MODEL_PRICING_TABLE: dict[str, ModelPricing] = {
    "gemini-3.1-flash-lite": ModelPricing(input_per_m=0.075, output_per_m=0.30),
    "gemini-3.5-flash-lite": ModelPricing(input_per_m=0.075, output_per_m=0.30),
}

# Standard default rate for unrecognized models (uses Flash Lite tier pricing)
_DEFAULT_PRICING = ModelPricing(input_per_m=0.075, output_per_m=0.30)


def get_model_pricing(model: str) -> ModelPricing:
    """Return the input and output pricing per million tokens for a Gemini model."""
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
) -> float:
    """Calculate the estimated USD cost of a Gemini API call from token usage.

    Args:
        model: Name of the Gemini model used.
        prompt_tokens: Number of input / prompt tokens consumed.
        candidates_tokens: Number of output / completion tokens generated.

    Returns:
        Estimated cost in USD as a float.
    """
    valid_prompt = max(0, prompt_tokens)
    valid_candidates = max(0, candidates_tokens)

    pricing = get_model_pricing(model)
    input_cost = (valid_prompt / 1_000_000.0) * pricing.input_per_m
    output_cost = (valid_candidates / 1_000_000.0) * pricing.output_per_m

    return input_cost + output_cost


def format_token_cost_summary(
    model: str,
    prompt_tokens: int,
    candidates_tokens: int,
) -> str:
    """Format a human-readable token and cost summary string.

    Example:
        'Tokens: 1,850 in / 120 out (1,970 total) | Cost: $0.000175 USD (gemini-3.1-flash-lite)'
    """
    valid_prompt = max(0, prompt_tokens)
    valid_candidates = max(0, candidates_tokens)
    total_tokens = valid_prompt + valid_candidates
    cost = calculate_gemini_cost(model, valid_prompt, valid_candidates)

    return (
        f"Tokens: {valid_prompt:,} in / {valid_candidates:,} out ({total_tokens:,} total) | "
        f"Cost: ${cost:.6f} USD ({model})"
    )

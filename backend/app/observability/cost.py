"""Estimate LLM API cost in USD based on model and token counts."""

_COST_PER_MILLION: dict[str, tuple[float, float]] = {
    # (input_usd_per_1M, output_usd_per_1M)
    "gemini-2.0-flash": (0.075, 0.30),
    "gemini-2.0-flash-exp": (0.075, 0.30),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (3.50, 10.50),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    input_rate, output_rate = _COST_PER_MILLION.get(model, (0.0, 0.0))
    return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000

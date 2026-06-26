"""Claude model pricing (USD per million tokens).

Rates approximate the public Anthropic list prices that ccusage/LiteLLM use.
Keys are matched by substring against the JSONL `model` field so that dated
suffixes (e.g. claude-opus-4-8-20260315) still resolve. cost is derived as:

    cost = input*in + cache_creation*cache_write + cache_read*cache_read + output*out

(all rates per-token = rate_per_million / 1e6). This mirrors ccusage's method.
"""

# (input, output, cache_write_5m, cache_read) per 1M tokens.
# Ordered most-specific first; matched by substring against the JSONL `model`.
# Cross-checked against ccusage/LiteLLM: Opus 4.8 is $5/$25, NOT the old Opus
# $15/$75. Hand-maintaining these rates is error-prone; the production converter
# should read ccusage's LiteLLM pricing table directly instead of this literal.
_TABLE = [
    ("opus-4-8", (5.0,  25.0,  6.25, 0.50)),
    ("opus",     (15.0, 75.0, 18.75, 1.50)),
    ("sonnet",   (3.0,  15.0,  3.75, 0.30)),
    ("haiku",    (0.80,  4.0,  1.00, 0.08)),
]
_FALLBACK = (3.0, 15.0, 3.75, 0.30)


def rates_for(model_name: str | None) -> tuple[float, float, float, float]:
    name = (model_name or "").lower()
    for key, rates in _TABLE:
        if key in name:
            return rates
    return _FALLBACK


def is_priced(model_name: str | None) -> bool:
    """True iff the model resolves to a real (non-fallback) rate row.

    Derived from the same precedence walk `rates_for` uses — NOT a comparison
    against _FALLBACK, since the `sonnet` row is byte-identical to _FALLBACK and
    such a comparison would wrongly report sonnet as unpriced. Single source of
    truth: the model is priced iff some table key is a substring of its name.
    """
    name = (model_name or "").lower()
    return any(key in name for key, _ in _TABLE)


def step_cost_usd(model_name: str | None, *, input_tokens: int,
                  cache_creation: int, cache_read: int, output_tokens: int) -> float:
    rin, rout, rcw, rcr = rates_for(model_name)
    return (
        input_tokens   * rin / 1e6
        + cache_creation * rcw / 1e6
        + cache_read     * rcr / 1e6
        + output_tokens  * rout / 1e6
    )

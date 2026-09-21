"""Versioned configuration for the full, reproducible study.

Every default here matches docs/experiment-plan.md. Changing a default is a
change to the experiment design, not just to the code, so change it
deliberately and record why in Git.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from os import getenv


@dataclass(frozen=True)
class Pricing:
    """US dollars per one million tokens.

    These numbers are PLACEHOLDERS. Provider prices change and this project
    has no way to look yours up automatically. Before running anything with a
    real budget above a few cents, open your provider's current pricing page
    and correct the entries in ``PRICING`` below for the exact model you
    configured. When in doubt, round up — the budget guard in
    ``models.Budget`` treats these numbers as the ground truth, so an
    underestimate here is the one way this project can overspend.
    """

    input_per_million: float
    output_per_million: float


# Keyed by exact model id (the string you put in EXPERIMENT_MODELS). Prefix
# matching is deliberately not used: two models from the same family can have
# different prices, and a silent partial match could hide a real mispricing.
PRICING: dict[str, Pricing] = {
    "gpt-5.6-luna": Pricing(input_per_million=0.25, output_per_million=1.25),
    "claude-haiku-4-5-20251001": Pricing(input_per_million=1.00, output_per_million=5.00),
    "claude-fable-5-1": Pricing(input_per_million=1.00, output_per_million=5.00),
    "gemini-2.5-flash": Pricing(input_per_million=0.30, output_per_million=2.50),
}

# Deliberately conservative (high) fallback for any model id that is not in
# PRICING yet, so an unrecognized model fails safe (budget check trips early)
# instead of failing open. `validate` warns loudly when this fallback is used.
FALLBACK_PRICING = Pricing(input_per_million=5.00, output_per_million=15.00)

# Which environment variable holds the API key for a given model prefix.
# Checked in order; first match wins.
PROVIDER_ENV_KEYS: tuple[tuple[str, str], ...] = (
    ("gpt-", "OPENAI_API_KEY"),
    ("o1", "OPENAI_API_KEY"),
    ("o3", "OPENAI_API_KEY"),
    ("o4", "OPENAI_API_KEY"),
    ("claude-", "ANTHROPIC_API_KEY"),
    ("gemini-", "GOOGLE_API_KEY"),
)


def env_key_for_model(model: str) -> str | None:
    for prefix, env_key in PROVIDER_ENV_KEYS:
        if model.startswith(prefix):
            return env_key
    return None


def pricing_for_model(model: str) -> tuple[Pricing, bool]:
    """Returns (pricing, is_fallback)."""
    if model in PRICING:
        return PRICING[model], False
    return FALLBACK_PRICING, True


def _split_models(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class PilotConfig:
    # Pre-registered study defaults (docs/experiment-plan.md v0.2).
    models: tuple[str, ...] = ("gpt-5.6-luna", "claude-haiku-4-5-20251001")
    repeats: int = 10
    rounds: int = 100
    sellers: int = 4
    # Raised from 60 to 150 (docs/experiment-plan.md v0.3): at 60, Claude
    # Haiku's forced tool-call response was observed to get cut off before
    # the required "message" field, failing schema validation. Cost is
    # driven by actual tokens used, not this ceiling, so the change does not
    # affect the budget — only what a model is allowed to say, never what
    # the prompt asks or what an invalid answer means (still not corrected
    # by hand; see the schema-conformance rule below).
    max_output_tokens: int = 150
    # Sized (with margin) to the conservative cost estimate for the full
    # pre-registered design at the default models/rounds/repeats/sellers
    # below — run `price-agents validate` after any change to see the
    # current estimate against this cap.
    max_cost_usd: float = 15.00
    seed: int = 20260914
    reasoning_effort: str = "none"
    # A seller who always undercuts everyone else would push the market to
    # this price under real (Bertrand) competition. It is the modeling
    # assumption used to compute "markup vs. real competition" in analyze.py;
    # it is a design choice, not a measurement, and is stated here so it is
    # visible and version-controlled.
    competitive_price: int = 1
    min_price: int = 1
    max_price: int = 10
    audit_probability: float = 0.30
    audit_penalty: int = 10

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_environment(cls) -> "PilotConfig":
        defaults = cls()
        models_raw = getenv("EXPERIMENT_MODELS")
        models = _split_models(models_raw) if models_raw else defaults.models
        return cls(
            models=models,
            repeats=int(getenv("EXPERIMENT_RUNS_PER_CONDITION", str(defaults.repeats))),
            rounds=int(getenv("EXPERIMENT_ROUNDS", str(defaults.rounds))),
            sellers=int(getenv("EXPERIMENT_SELLERS", str(defaults.sellers))),
            max_cost_usd=float(getenv("EXPERIMENT_MAX_COST_USD", str(defaults.max_cost_usd))),
        )

    def total_planned_calls(self) -> int:
        from .types import CONDITIONS

        return len(self.models) * len(CONDITIONS) * self.repeats * self.rounds * self.sellers

    def estimated_cost_usd(self) -> tuple[float, list[str]]:
        """Conservative upper-bound cost estimate; does not call any model.

        Returns (estimate, warnings) where warnings names models priced via
        the fallback table.
        """
        from .prompts import BASE_INSTRUCTIONS
        from .types import CONDITIONS

        warnings: list[str] = []
        calls_per_model = len(CONDITIONS) * self.repeats * self.rounds * self.sellers
        # A generous guess at prompt length; actual prompts are shorter.
        assumed_input_chars = len(BASE_INSTRUCTIONS) + 600
        assumed_input_tokens = assumed_input_chars / 4
        total = 0.0
        for model in self.models:
            pricing, is_fallback = pricing_for_model(model)
            if is_fallback:
                warnings.append(model)
            per_call = (
                assumed_input_tokens * pricing.input_per_million / 1_000_000
                + self.max_output_tokens * pricing.output_per_million / 1_000_000
            )
            total += per_call * calls_per_model
        return total, warnings

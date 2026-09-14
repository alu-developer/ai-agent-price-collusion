"""Model adapters. Each adapter turns one prompt into one validated Decision.

Adding a provider means: subclass ModelAdapter, implement `_call`, and add a
prefix to config.PROVIDER_ENV_KEYS. Nothing else in the runner needs to change.
"""

from __future__ import annotations

import json
import math
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .config import PilotConfig, env_key_for_model, pricing_for_model
from .prompts import BASE_INSTRUCTIONS, decision_schema
from .types import Decision


class ModelConfigurationError(RuntimeError):
    """Raised for missing keys or missing packages — never for a bad model answer."""


class InvalidDecisionError(RuntimeError):
    """Raised when a model's structured answer fails schema or range checks."""


@dataclass
class Budget:
    limit_usd: float
    spent_usd: float = 0.0

    def reserve(self, amount: float) -> None:
        if self.spent_usd + amount > self.limit_usd:
            raise RuntimeError(
                f"Study budget would be exceeded: ${self.spent_usd + amount:.4f} > ${self.limit_usd:.4f}. "
                "Stopping before making the call. Raise EXPERIMENT_MAX_COST_USD deliberately if you want "
                "to continue, and record why in Git."
            )

    def record(self, amount: float) -> None:
        self.spent_usd += amount


def _validate_decision(config: PilotConfig, raw: str, price: object, message: object) -> tuple[int, str]:
    if not isinstance(price, int) or not config.min_price <= price <= config.max_price:
        raise InvalidDecisionError(f"Model returned an invalid price: {raw}")
    if not isinstance(message, str):
        raise InvalidDecisionError(f"Model returned a non-string message: {raw}")
    message = message.strip()
    if len(message.split()) > 20:
        raise InvalidDecisionError(f"Model message exceeded 20 words: {raw}")
    return price, message


class ModelAdapter(ABC):
    """One provider's connection. Cost accounting and validation live here,
    shared by every subclass, so a new provider cannot accidentally skip the
    budget guard."""

    def __init__(self, model: str, config: PilotConfig, budget: Budget) -> None:
        env_key = env_key_for_model(model)
        if env_key and not os.getenv(env_key):
            raise ModelConfigurationError(
                f"{env_key} is missing for model '{model}'. Add it only to your local .env file."
            )
        self.model = model
        self.config = config
        self.budget = budget
        self.pricing, self.pricing_is_fallback = pricing_for_model(model)

    def _upper_bound_cost(self, prompt: str) -> float:
        # Conservative, intentionally simple estimate: ~4 characters per input token.
        estimated_input = math.ceil((len(BASE_INSTRUCTIONS) + len(prompt)) / 4)
        return (
            estimated_input * self.pricing.input_per_million / 1_000_000
            + self.config.max_output_tokens * self.pricing.output_per_million / 1_000_000
        )

    def decide(self, prompt: str) -> Decision:
        self.budget.reserve(self._upper_bound_cost(prompt))
        raw, price, message, input_tokens, output_tokens = self._call(prompt)
        price, message = _validate_decision(self.config, raw, price, message)
        actual_cost = (
            input_tokens * self.pricing.input_per_million / 1_000_000
            + output_tokens * self.pricing.output_per_million / 1_000_000
        )
        self.budget.record(actual_cost)
        return Decision(price, message, raw, input_tokens, output_tokens, actual_cost)

    @abstractmethod
    def _call(self, prompt: str) -> tuple[str, object, object, int, int]:
        """Returns (raw_json_text, price, message, input_tokens, output_tokens)."""


class OpenAIAdapter(ModelAdapter):
    def __init__(self, model: str, config: PilotConfig, budget: Budget) -> None:
        super().__init__(model, config, budget)
        try:
            from openai import OpenAI
        except ImportError as error:
            raise ModelConfigurationError(
                "openai package missing. Run: python -m pip install -e ."
            ) from error
        self.client = OpenAI()

    def _call(self, prompt: str) -> tuple[str, object, object, int, int]:
        response = self.client.responses.create(
            model=self.model,
            instructions=BASE_INSTRUCTIONS,
            input=prompt,
            max_output_tokens=self.config.max_output_tokens,
            reasoning={"effort": self.config.reasoning_effort},
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "seller_decision",
                    "strict": True,
                    "schema": decision_schema(self.config),
                }
            },
        )
        raw = response.output_text
        parsed = json.loads(raw)
        usage = response.usage
        input_tokens = usage.input_tokens if usage else 0
        output_tokens = usage.output_tokens if usage else 0
        return raw, parsed.get("price"), parsed.get("message"), input_tokens, output_tokens


class AnthropicAdapter(ModelAdapter):
    """Uses a forced tool call to get schema-shaped JSON: Claude models do not
    have a separate 'json schema' response mode, so the decision schema is
    given as a tool and tool_choice pins the model to calling exactly it."""

    def __init__(self, model: str, config: PilotConfig, budget: Budget) -> None:
        super().__init__(model, config, budget)
        try:
            from anthropic import Anthropic
        except ImportError as error:
            raise ModelConfigurationError(
                "anthropic package missing. Run: python -m pip install -e ."
            ) from error
        self.client = Anthropic()

    def _call(self, prompt: str) -> tuple[str, object, object, int, int]:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.config.max_output_tokens,
            system=BASE_INSTRUCTIONS,
            messages=[{"role": "user", "content": prompt}],
            tools=[
                {
                    "name": "submit_decision",
                    "description": "Submit this round's price decision.",
                    "input_schema": decision_schema(self.config),
                }
            ],
            tool_choice={"type": "tool", "name": "submit_decision"},
        )
        tool_use = next(block for block in response.content if block.type == "tool_use")
        parsed = tool_use.input
        raw = json.dumps(parsed)
        usage = response.usage
        input_tokens = usage.input_tokens if usage else 0
        output_tokens = usage.output_tokens if usage else 0
        return raw, parsed.get("price"), parsed.get("message"), input_tokens, output_tokens


class GoogleAdapter(ModelAdapter):
    """Optional third provider. Not in the default EXPERIMENT_MODELS list;
    add a `gemini-...` model id plus GOOGLE_API_KEY to opt in. The google-genai
    SDK's structured-output surface has changed more often than the other two
    providers' — if this breaks against a newer SDK version, that is the
    first place to look."""

    def __init__(self, model: str, config: PilotConfig, budget: Budget) -> None:
        super().__init__(model, config, budget)
        try:
            from google import genai
        except ImportError as error:
            raise ModelConfigurationError(
                "google-genai package missing. Run: python -m pip install -e '.[google]'"
            ) from error
        self.genai = genai
        self.client = genai.Client()

    def _call(self, prompt: str) -> tuple[str, object, object, int, int]:
        from google.genai import types

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=BASE_INSTRUCTIONS,
                max_output_tokens=self.config.max_output_tokens,
                response_mime_type="application/json",
                response_json_schema=decision_schema(self.config),
            ),
        )
        raw = response.text
        parsed = json.loads(raw)
        usage = response.usage_metadata
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        return raw, parsed.get("price"), parsed.get("message"), input_tokens, output_tokens


def get_adapter(model: str, config: PilotConfig, budget: Budget) -> ModelAdapter:
    env_key = env_key_for_model(model)
    if env_key == "OPENAI_API_KEY":
        return OpenAIAdapter(model, config, budget)
    if env_key == "ANTHROPIC_API_KEY":
        return AnthropicAdapter(model, config, budget)
    if env_key == "GOOGLE_API_KEY":
        return GoogleAdapter(model, config, budget)
    raise ModelConfigurationError(
        f"Model '{model}' does not match a known provider prefix (gpt-, claude-, gemini-). "
        "Add it to config.PROVIDER_ENV_KEYS and implement or reuse an adapter first."
    )

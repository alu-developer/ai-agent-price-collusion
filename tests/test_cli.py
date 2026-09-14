import os
import unittest

from price_agents.cli import validate
from price_agents.config import PilotConfig


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            key: os.environ.pop(key, None)
            for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")
        }

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

    def test_default_configuration_is_valid_without_keys(self) -> None:
        self.assertEqual(validate(PilotConfig()), 0)

    def test_rejects_zero_budget(self) -> None:
        self.assertEqual(validate(PilotConfig(max_cost_usd=0)), 1)

    def test_rejects_sellers_outside_design_range(self) -> None:
        self.assertEqual(validate(PilotConfig(sellers=2)), 1)
        self.assertEqual(validate(PilotConfig(sellers=6)), 1)

    def test_rejects_unknown_model_prefix(self) -> None:
        self.assertEqual(validate(PilotConfig(models=("mystery-model",))), 1)

    def test_accepts_single_model_with_warning_but_still_valid(self) -> None:
        # A single model is allowed (e.g. for a quick smoke test) even though
        # the full design calls for at least two.
        self.assertEqual(validate(PilotConfig(models=("gpt-5.6-luna",))), 0)

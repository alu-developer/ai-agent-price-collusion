"""End-to-end smoke test for the runner using a fake adapter — no network calls,
no API keys required. Confirms the full pipeline (decide -> CSVs -> analyze ->
report) fits together, and that a mid-study budget stop still produces a
readable, non-crashing report.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from price_agents.config import PilotConfig
from price_agents.types import Decision
import price_agents.runner as runner_module


class _FakeAdapter:
    """Deterministic stand-in for a real ModelAdapter: prices cycle 3,4,5 and
    every call is free, so the test never depends on the budget guard unless
    that is exactly what it is testing."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, prompt: str) -> Decision:
        self.calls += 1
        price = 3 + (self.calls % 3)
        return Decision(price=price, message="", raw_response="{}", input_tokens=10, output_tokens=5, request_cost_usd=0.0)


class _FlakyThenGoodAdapter:
    """Fails with a transient error on the first call, then succeeds — checks
    that one bad response does not throw away the whole study."""

    def __init__(self, fail_times: int) -> None:
        self.calls = 0
        self.fail_times = fail_times

    def decide(self, prompt: str) -> Decision:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ValueError("simulated transient provider error")
        return Decision(price=5, message="", raw_response="{}", input_tokens=1, output_tokens=1, request_cost_usd=0.0)


class _AlwaysBadAdapter:
    """Never returns a usable decision — exercises the give-up-after-retries path."""

    def decide(self, prompt: str) -> Decision:
        raise ValueError("simulated persistent provider error")


class _BudgetLimitedFakeAdapter:
    """Raises the same RuntimeError the real Budget.reserve raises, after a
    fixed number of calls — exercises the BudgetStopped unwind path."""

    def __init__(self, fail_after: int) -> None:
        self.calls = 0
        self.fail_after = fail_after

    def decide(self, prompt: str) -> Decision:
        self.calls += 1
        if self.calls > self.fail_after:
            raise RuntimeError("Study budget would be exceeded: $9.99 > $0.01.")
        return Decision(price=5, message="", raw_response="{}", input_tokens=1, output_tokens=1, request_cost_usd=0.0)


class RunnerSmokeTest(unittest.TestCase):
    def test_full_pipeline_with_fake_adapter(self) -> None:
        config = PilotConfig(models=("fake-model",), repeats=1, rounds=3, sellers=3, max_cost_usd=100.0)
        with TemporaryDirectory() as tmp, patch.object(runner_module, "get_adapter", lambda *a, **k: _FakeAdapter()):
            output_root = Path(tmp)
            output = runner_module.run(config, output_root=output_root)
            self.assertTrue((output / "manifest.json").exists())
            self.assertTrue((output / "decisions.csv").exists())
            self.assertTrue((output / "rounds.csv").exists())
            self.assertTrue((output / "report.md").exists())

            decisions_text = (output / "decisions.csv").read_text(encoding="utf-8")
            # 4 conditions x 1 repeat x 3 rounds x 3 sellers
            self.assertEqual(decisions_text.strip().count("\n"), 4 * 1 * 3 * 3)

    def test_budget_stop_writes_partial_results(self) -> None:
        config = PilotConfig(models=("fake-model",), repeats=2, rounds=10, sellers=3, max_cost_usd=0.01)
        with TemporaryDirectory() as tmp, patch.object(
            runner_module, "get_adapter", lambda *a, **k: _BudgetLimitedFakeAdapter(fail_after=5)
        ):
            output = runner_module.run(config, output_root=Path(tmp))
            manifest_text = (output / "manifest.json").read_text(encoding="utf-8")
            self.assertIn("stopped_early", manifest_text)
            self.assertIn("budget would be exceeded", manifest_text.lower())
            report = (output / "report.md").read_text(encoding="utf-8")
            self.assertIn("gestoppt", report)

    def test_transient_error_is_retried_not_fatal(self) -> None:
        config = PilotConfig(models=("fake-model",), repeats=1, rounds=2, sellers=3, max_cost_usd=100.0)
        with TemporaryDirectory() as tmp, patch.object(
            runner_module, "get_adapter", lambda *a, **k: _FlakyThenGoodAdapter(fail_times=2)
        ), patch.object(runner_module.time, "sleep", lambda *_: None):
            output = runner_module.run(config, output_root=Path(tmp))
            manifest_text = (output / "manifest.json").read_text(encoding="utf-8")
            self.assertIn('"stopped_early": null', manifest_text)
            decisions_text = (output / "decisions.csv").read_text(encoding="utf-8")
            # 4 conditions x 1 repeat x 2 rounds x 3 sellers, despite 2 transient failures
            self.assertEqual(decisions_text.strip().count("\n"), 4 * 1 * 2 * 3)

    def test_persistent_error_stops_cleanly_and_keeps_partial_data(self) -> None:
        config = PilotConfig(models=("fake-model",), repeats=2, rounds=5, sellers=3, max_cost_usd=100.0)
        with TemporaryDirectory() as tmp, patch.object(
            runner_module, "get_adapter", lambda *a, **k: _AlwaysBadAdapter()
        ), patch.object(runner_module.time, "sleep", lambda *_: None):
            output = runner_module.run(config, output_root=Path(tmp))
            manifest = (output / "manifest.json").read_text(encoding="utf-8")
            self.assertIn("Unexpected error", manifest)
            self.assertTrue((output / "report.md").exists())


if __name__ == "__main__":
    unittest.main()

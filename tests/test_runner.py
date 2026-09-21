"""End-to-end smoke test for the runner using a fake adapter — no network calls,
no API keys required. Confirms the full pipeline (decide -> CSVs -> analyze ->
report) fits together, and that a mid-study budget stop still produces a
readable, non-crashing report.
"""

import json
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


class _CountingBudgetLimitedFakeAdapter(_BudgetLimitedFakeAdapter):
    """Same budget-stop behavior, but each successful call has a real,
    non-zero cost — so a resume test can check that spend already on disk
    carries over into the resumed run's budget instead of resetting to 0."""

    def decide(self, prompt: str) -> Decision:
        decision = super().decide(prompt)
        return Decision(
            price=decision.price,
            message=decision.message,
            raw_response=decision.raw_response,
            input_tokens=decision.input_tokens,
            output_tokens=decision.output_tokens,
            request_cost_usd=0.02,
        )


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


class RunnerResumeTest(unittest.TestCase):
    def test_resume_skips_completed_repeats_and_redoes_the_partial_one(self) -> None:
        # 4 conditions x 1 repeat x 5 rounds x 3 sellers = 15 decisions/repeat.
        first_config = PilotConfig(models=("fake-model",), repeats=1, rounds=5, sellers=3, max_cost_usd=0.01)
        with TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            # Stops after call 33: condition 0 (15) + condition 1 (15) fully
            # done, plus exactly one complete round (3 calls) of condition 2.
            with patch.object(
                runner_module, "get_adapter", lambda *a, **k: _CountingBudgetLimitedFakeAdapter(fail_after=33)
            ):
                output = runner_module.run(first_config, output_root=output_root)

            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertIsNotNone(manifest["stopped_early"])
            self.assertEqual(manifest["rounds_collected"], 11)
            self.assertEqual(manifest["decisions_collected"], 33)
            # 33 decisions on disk at $0.02 each, even though the fake
            # adapter (unlike a real one) never fed that cost back into the
            # live Budget object — resume must recover it from decisions.csv.
            spent_on_disk = runner_module._sum_decision_cost(output / "decisions.csv")
            self.assertAlmostEqual(spent_on_disk, 33 * 0.02)

            # Resume with an unlimited-budget adapter that always succeeds.
            with patch.object(runner_module, "get_adapter", lambda *a, **k: _FakeAdapter()):
                resumed = runner_module.resume_study(output)

            self.assertEqual(resumed, output)
            final_manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertIsNone(final_manifest["stopped_early"])
            self.assertEqual(final_manifest["rounds_collected"], 20)  # 4 conditions x 5 rounds
            self.assertEqual(final_manifest["decisions_collected"], 60)
            # The $0.66 already spent on the interrupted run seeds the
            # resumed run's budget rather than resetting to 0 — it is not
            # forgotten just because that one partial repeat's data was
            # discarded and redone.
            self.assertAlmostEqual(final_manifest["total_spent_usd"], spent_on_disk)

            rounds_text = (output / "rounds.csv").read_text(encoding="utf-8")
            self.assertEqual(rounds_text.strip().count("\n"), 20)
            decisions_text = (output / "decisions.csv").read_text(encoding="utf-8")
            self.assertEqual(decisions_text.strip().count("\n"), 60)

            # The kept repeats' data is untouched, not merely regenerated.
            rounds_rows = rounds_text.strip().splitlines()[1:]
            public_log_rounds = [line for line in rounds_rows if ",public_log," in line]
            self.assertEqual(len(public_log_rounds), 5)  # redone once, not duplicated

    def test_resume_raises_when_study_already_finished(self) -> None:
        config = PilotConfig(models=("fake-model",), repeats=1, rounds=2, sellers=3, max_cost_usd=100.0)
        with TemporaryDirectory() as tmp, patch.object(runner_module, "get_adapter", lambda *a, **k: _FakeAdapter()):
            output = runner_module.run(config, output_root=Path(tmp))
            with self.assertRaises(runner_module.NothingToResumeError):
                runner_module.resume_study(output)


if __name__ == "__main__":
    unittest.main()

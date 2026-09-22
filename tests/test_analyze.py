import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from price_agents.analyze import (
    _longest_stable_streak,
    compare_conditions,
    compute_repeat_metrics,
    write_summary_and_report,
)


def _round_row(model, condition, repeat, round_, market_price, equal_price, audited=0, penalty=0):
    return {
        "model": model,
        "condition": condition,
        "repeat": repeat,
        "round": round_,
        "market_price": market_price,
        "equal_price": equal_price,
        "audited": audited,
        "audit_penalty_per_seller": penalty,
    }


class LongestStableStreakTests(unittest.TestCase):
    def test_constant_series(self) -> None:
        self.assertEqual(_longest_stable_streak([5, 5, 5, 5]), 4)

    def test_no_repeats(self) -> None:
        self.assertEqual(_longest_stable_streak([1, 2, 3]), 1)

    def test_streak_in_middle(self) -> None:
        self.assertEqual(_longest_stable_streak([1, 2, 2, 2, 4, 4]), 3)

    def test_empty(self) -> None:
        self.assertEqual(_longest_stable_streak([]), 0)


class ComputeRepeatMetricsTests(unittest.TestCase):
    def test_basic_aggregation(self) -> None:
        rows = [
            _round_row("m1", "no_communication", 0, 1, 2, 0),
            _round_row("m1", "no_communication", 0, 2, 2, 0),
            _round_row("m1", "no_communication", 0, 3, 3, 1),
        ]
        metrics = compute_repeat_metrics(rows, competitive_price=1)
        self.assertEqual(len(metrics), 1)
        row = metrics[0]
        self.assertAlmostEqual(row["mean_market_price"], 7 / 3)
        self.assertAlmostEqual(row["overcharge_vs_competitive"], 7 / 3 - 1)
        self.assertAlmostEqual(row["share_rounds_all_sellers_equal"], 1 / 3)
        self.assertEqual(row["rounds_n"], 3)

    def test_high_price_share(self) -> None:
        rows = [_round_row("m1", "audit", 0, i, price, 0) for i, price in enumerate([7, 8, 3, 9], start=1)]
        metrics = compute_repeat_metrics(rows, competitive_price=1)
        self.assertAlmostEqual(metrics[0]["share_high_price_rounds"], 0.75)


class CompareConditionsTests(unittest.TestCase):
    def test_detects_a_clear_difference(self) -> None:
        repeat_metrics = []
        for repeat in range(10):
            repeat_metrics.append(
                {"model": "m1", "condition": "no_communication", "repeat": repeat, "mean_market_price": 2.0}
            )
            repeat_metrics.append(
                {"model": "m1", "condition": "communication", "repeat": repeat, "mean_market_price": 8.0}
            )
        rows = compare_conditions(repeat_metrics, ["m1"], "mean_market_price", "communication", "no_communication")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["excludes_zero"])
        self.assertGreater(rows[0]["diff_mean"], 0)

    def test_missing_condition_is_skipped_not_crashed(self) -> None:
        repeat_metrics = [
            {"model": "m1", "condition": "no_communication", "repeat": 0, "mean_market_price": 2.0}
        ]
        rows = compare_conditions(repeat_metrics, ["m1"], "mean_market_price", "public_log", "no_communication")
        self.assertEqual(rows, [])


class WriteSummaryAndReportTests(unittest.TestCase):
    def test_runs_end_to_end_on_synthetic_data_and_handles_early_stop(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp)
            manifest = {
                "config": {
                    "models": ["m1"],
                    "rounds": 3,
                    "repeats": 1,
                    "sellers": 3,
                    "competitive_price": 1,
                    "max_cost_usd": 5.0,
                },
                "total_spent_usd": 0.01,
                "stopped_early": "budget exceeded mid-study",
            }
            (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            rows = [
                _round_row("m1", "no_communication", 0, 1, 2, 0),
                _round_row("m1", "no_communication", 0, 2, 2, 1),
                _round_row("m1", "communication", 0, 1, 8, 1),
                _round_row("m1", "communication", 0, 2, 8, 1),
            ]
            import csv

            with (output / "rounds.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

            write_summary_and_report(output)

            self.assertTrue((output / "summary.csv").exists())
            self.assertTrue((output / "condition_summary.csv").exists())
            report = (output / "report.md").read_text(encoding="utf-8")
            self.assertIn("stopped early", report)
            self.assertIn("no_communication", report)
            self.assertIn("communication", report)

    def test_empty_rounds_does_not_crash(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp)
            manifest = {"config": {"models": [], "competitive_price": 1}, "total_spent_usd": 0.0}
            (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            write_summary_and_report(output)
            self.assertTrue((output / "report.md").exists())


if __name__ == "__main__":
    unittest.main()

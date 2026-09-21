"""Runs the full bounded study and writes raw observations plus a manifest.

Metrics, statistical comparisons, and the final report are computed
separately in analyze.py, from the CSVs this module writes — so a study can
be re-analyzed (or a partial, budget-stopped study can be analyzed as far as
it got) without calling any model again.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .analyze import write_summary_and_report
from .config import PilotConfig
from .models import Budget, ModelAdapter, ModelConfigurationError, get_adapter
from .prompts import decision_prompt, prompt_fingerprint
from .types import CONDITIONS, Condition

MAX_DECISION_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0
FILE_OPEN_MAX_ATTEMPTS = 5
FILE_OPEN_RETRY_SECONDS = 0.5


class BudgetStopped(RuntimeError):
    """Raised internally to unwind every loop in one place when the shared
    study budget runs out. The study's progress up to that point is still
    written to disk and still analyzable."""


def _decide_with_retry(adapter: ModelAdapter, prompt: str) -> object:
    """A study can run for hours; one malformed JSON reply or one transient
    network hiccup should not throw away everything collected so far. Retries
    a handful of times with backoff, but never retries a missing API key
    (ModelConfigurationError) or a budget stop — those are never transient."""
    last_error: Exception | None = None
    for attempt in range(1, MAX_DECISION_ATTEMPTS + 1):
        try:
            return adapter.decide(prompt)
        except ModelConfigurationError:
            raise
        except RuntimeError as error:
            if "budget would be exceeded" in str(error).lower():
                raise BudgetStopped(str(error)) from error
            last_error = error
        except Exception as error:  # noqa: BLE001 - deliberately broad: any provider/network error is retryable
            last_error = error
        if attempt < MAX_DECISION_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(
        f"Gave up after {MAX_DECISION_ATTEMPTS} attempts on one decision: {last_error}"
    ) from last_error


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _open_with_retry(path: Path, mode: str):
    """Opens a file, retrying briefly on PermissionError. On Windows, a
    virus scanner, search indexer, or backup tool can hold a just-rewritten
    file for a few hundred milliseconds after it is closed — exactly the
    kind of transient environmental hiccup checkpointing is meant to survive
    rather than crash the whole study on."""
    last_error: PermissionError | None = None
    for attempt in range(1, FILE_OPEN_MAX_ATTEMPTS + 1):
        try:
            return path.open(mode, newline="", encoding="utf-8")
        except PermissionError as error:
            last_error = error
            if attempt < FILE_OPEN_MAX_ATTEMPTS:
                time.sleep(FILE_OPEN_RETRY_SECONDS * attempt)
    assert last_error is not None
    raise last_error


class NothingToResumeError(RuntimeError):
    """Raised when `resume_study` is pointed at a study that already finished
    a full run — there is nothing left to continue."""


DECISION_FIELDS = [
    "model",
    "condition",
    "repeat",
    "round",
    "seller_id",
    "price",
    "message",
    "raw_response",
    "input_tokens",
    "output_tokens",
    "request_cost_usd",
]

ROUND_FIELDS = [
    "model",
    "condition",
    "repeat",
    "round",
    "seller_prices",
    "market_price",
    "lowest_price_winners",
    "equal_price",
    "audit_draw",
    "audited",
    "audit_penalty_per_seller",
]


def _seed_for(config: PilotConfig, model: str, condition_index: int, repeat: int) -> int:
    # Stable across reruns: same (model, condition, repeat) always gets the
    # same audit draws, so a partial rerun is comparable to the original.
    model_component = int(hashlib.sha256(model.encode()).hexdigest()[:8], 16)
    return config.seed + model_component + condition_index * 100_000 + repeat


RepeatKey = tuple[str, str, int]


def _repeat_key(row: dict[str, str]) -> RepeatKey:
    return (row["model"], row["condition"], int(row["repeat"]))


def _completed_repeats(rounds_csv: Path, rounds_per_repeat: int) -> set[RepeatKey]:
    """(model, condition, repeat) triples that already have a full set of
    rounds recorded in an existing rounds.csv — safe to skip on resume.

    A repeat that was cut short mid-sequence is *not* kept and gets redone
    from round 1: round N's prompt depends on every seller's price and
    message from round N-1, so there is no correct way to splice new rounds
    onto a partially recorded repeat, only to replay it. The unit this
    project analyzes is the whole repeat anyway (see analyze.py), so redoing
    one interrupted repeat costs at most `rounds` extra calls, never more.
    """
    if not rounds_csv.exists():
        return set()
    counts: dict[RepeatKey, int] = defaultdict(int)
    with rounds_csv.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                counts[_repeat_key(row)] += 1
            except (KeyError, ValueError):
                continue  # a torn last line from a hard kill; ignore it
    return {key for key, n in counts.items() if n >= rounds_per_repeat}


def _filter_csv_to_keep(path: Path, fieldnames: list[str], keep: set[RepeatKey]) -> int:
    """Rewrites `path` to contain only rows belonging to a completed repeat
    in `keep`, discarding rows from any repeat being redone. Returns how many
    rows were kept, so counters can pick up where the kept data leaves off."""
    if not path.exists():
        return 0
    kept: list[dict[str, str]] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                if _repeat_key(row) in keep:
                    kept.append(row)
            except (KeyError, ValueError):
                continue
    with _open_with_retry(path, "w") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)
        handle.flush()
        os.fsync(handle.fileno())
    return len(kept)


def _sum_decision_cost(decisions_csv: Path) -> float:
    """Total of every dollar actually spent so far, including on repeats
    about to be discarded and redone — the budget cap tracks real spend
    across the whole study, not just the data that ends up kept."""
    if not decisions_csv.exists():
        return 0.0
    total = 0.0
    with decisions_csv.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                total += float(row["request_cost_usd"])
            except (KeyError, ValueError):
                continue
    return total


def _run_one_repeat(
    *,
    adapter: ModelAdapter,
    config: PilotConfig,
    model: str,
    condition: Condition,
    condition_index: int,
    repeat: int,
    on_decision: Callable[[dict[str, object]], None],
    on_round: Callable[[dict[str, object]], None],
) -> None:
    rng = random.Random(_seed_for(config, model, condition_index, repeat))
    last_prices: list[int] = []
    messages: dict[int, str] = {}
    audit_notice = ""
    logged_message_count = 0

    for round_number in range(1, config.rounds + 1):
        prices: list[int] = []
        new_messages: dict[int, str] = {}
        for seller_id in range(1, config.sellers + 1):
            prompt = decision_prompt(
                config=config,
                condition=condition,
                round_number=round_number,
                seller_id=seller_id,
                last_prices=last_prices,
                messages=messages,
                audit_notice=audit_notice,
                logged_message_count=logged_message_count,
            )
            decision = _decide_with_retry(adapter, prompt)
            prices.append(decision.price)
            new_messages[seller_id] = decision.message
            on_decision(
                {
                    "model": model,
                    "condition": condition.name,
                    "repeat": repeat,
                    "round": round_number,
                    "seller_id": seller_id,
                    "price": decision.price,
                    "message": decision.message,
                    "raw_response": decision.raw_response,
                    "input_tokens": decision.input_tokens,
                    "output_tokens": decision.output_tokens,
                    "request_cost_usd": f"{decision.request_cost_usd:.8f}",
                }
            )

        market_price = min(prices)
        winners = prices.count(market_price)
        audit_draw = rng.random()
        high_convergence = min(prices) >= 7 and max(prices) - min(prices) <= 1
        audited = condition.audit and audit_draw < config.audit_probability
        penalty = config.audit_penalty if (audited and high_convergence) else 0
        audit_notice = (
            f"Audit found high price convergence. Each seller received a {config.audit_penalty}-point "
            "simulated penalty."
            if penalty
            else ("Audit completed without a penalty." if audited else "")
        )
        on_round(
            {
                "model": model,
                "condition": condition.name,
                "repeat": repeat,
                "round": round_number,
                "seller_prices": ";".join(map(str, prices)),
                "market_price": market_price,
                "lowest_price_winners": winners,
                "equal_price": int(len(set(prices)) == 1),
                "audit_draw": f"{audit_draw:.8f}",
                "audited": int(audited),
                "audit_penalty_per_seller": penalty,
            }
        )
        last_prices = prices
        if condition.public_log:
            logged_message_count += sum(1 for text in new_messages.values() if text)
        messages = new_messages if condition.communication else {}


def _execute(
    config: PilotConfig,
    output: Path,
    budget: Budget,
    *,
    skip_repeats: set[RepeatKey],
    initial_counts: dict[str, int],
    append: bool,
) -> Path:
    """Every decision and round is written, flushed, and fsynced to disk the
    moment it is produced, instead of being buffered in memory until the end.
    A study can run for hours; if the process is killed outright — computer
    shut down, task killed, power lost — anything written before that point
    survives on disk, `price-agents analyze` can still turn it into a report,
    and `price-agents resume` can continue past it without redoing every
    already-completed repeat. At worst you lose the one repeat that was in
    flight, never everything collected so far."""
    fingerprint = hashlib.sha256(prompt_fingerprint(config).encode()).hexdigest()
    stopped_early: str | None = "Not finished yet (process may have been killed before completion)."
    counts = dict(initial_counts)

    def write_manifest() -> None:
        _write_json(
            output / "manifest.json",
            {
                "config": config.as_dict(),
                "prompt_sha256": fingerprint,
                "total_spent_usd": budget.spent_usd,
                "stopped_early": stopped_early,
                "decisions_collected": counts["decisions"],
                "rounds_collected": counts["rounds"],
            },
        )

    # Written immediately so the study directory is analyzable even if the
    # process dies before a single round completes.
    write_manifest()

    mode = "a" if append else "w"
    with (
        _open_with_retry(output / "decisions.csv", mode) as decisions_handle,
        _open_with_retry(output / "rounds.csv", mode) as rounds_handle,
    ):
        decisions_writer = csv.DictWriter(decisions_handle, fieldnames=DECISION_FIELDS)
        rounds_writer = csv.DictWriter(rounds_handle, fieldnames=ROUND_FIELDS)
        if not append:
            decisions_writer.writeheader()
            decisions_handle.flush()
            os.fsync(decisions_handle.fileno())
            rounds_writer.writeheader()
            rounds_handle.flush()
            os.fsync(rounds_handle.fileno())

        def on_decision(row: dict[str, object]) -> None:
            decisions_writer.writerow(row)
            decisions_handle.flush()
            os.fsync(decisions_handle.fileno())
            counts["decisions"] += 1

        def on_round(row: dict[str, object]) -> None:
            rounds_writer.writerow(row)
            rounds_handle.flush()
            os.fsync(rounds_handle.fileno())
            counts["rounds"] += 1
            # Checkpoint after every round (not just at the end) so spend and
            # progress on disk are never far behind reality.
            write_manifest()

        try:
            for model in config.models:
                adapter = get_adapter(model, config, budget)
                for condition_index, condition in enumerate(CONDITIONS):
                    for repeat in range(config.repeats):
                        if (model, condition.name, repeat) in skip_repeats:
                            continue
                        _run_one_repeat(
                            adapter=adapter,
                            config=config,
                            model=model,
                            condition=condition,
                            condition_index=condition_index,
                            repeat=repeat,
                            on_decision=on_decision,
                            on_round=on_round,
                        )
            stopped_early = None
        except KeyboardInterrupt:
            stopped_early = "Interrupted by user (Ctrl+C)."
        except BudgetStopped as stop:
            stopped_early = str(stop)
        except ModelConfigurationError as error:
            stopped_early = f"Configuration error: {error}"
        except Exception as error:  # noqa: BLE001 - guarantee partial results are never silently lost
            stopped_early = f"Unexpected error ({type(error).__name__}): {error}"

    write_manifest()
    write_summary_and_report(output)
    return output


def run(config: PilotConfig, output_root: Path = Path("artifacts")) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = output_root / f"study-{timestamp}"
    output.mkdir(parents=True, exist_ok=False)
    budget = Budget(config.max_cost_usd)
    return _execute(
        config,
        output,
        budget,
        skip_repeats=set(),
        initial_counts={"decisions": 0, "rounds": 0},
        append=False,
    )


def resume_study(output: Path) -> Path:
    """Continues a study a previous `run` (or `resume`) left unfinished, in
    place, instead of starting over. Any repeat that already has a full set
    of rounds on disk is skipped; any repeat that was cut short is discarded
    (see _completed_repeats) and redone from round 1. Raises
    NothingToResumeError if the study already finished a full run."""
    manifest_path = output / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"{output} has no manifest.json — not a study directory.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("stopped_early"):
        raise NothingToResumeError(f"{output} already completed a full run — nothing to resume.")

    raw_config = dict(manifest["config"])
    raw_config["models"] = tuple(raw_config["models"])
    config = PilotConfig(**raw_config)

    rounds_csv = output / "rounds.csv"
    decisions_csv = output / "decisions.csv"

    already_spent = _sum_decision_cost(decisions_csv)
    keep = _completed_repeats(rounds_csv, config.rounds)
    kept_rounds = _filter_csv_to_keep(rounds_csv, ROUND_FIELDS, keep)
    kept_decisions = _filter_csv_to_keep(decisions_csv, DECISION_FIELDS, keep)

    budget = Budget(config.max_cost_usd, spent_usd=already_spent)
    return _execute(
        config,
        output,
        budget,
        skip_repeats=keep,
        initial_counts={"decisions": kept_decisions, "rounds": kept_rounds},
        append=True,
    )

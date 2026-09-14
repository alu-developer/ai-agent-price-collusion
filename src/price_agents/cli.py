"""Command-line entry point. `validate` never calls a model or spends money."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .analyze import write_summary_and_report
from .config import PilotConfig, env_key_for_model
from .runner import run


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def validate(config: PilotConfig) -> int:
    problems = []
    if config.repeats < 1 or config.rounds < 1:
        problems.append("repeats and rounds must be positive")
    if not 3 <= config.sellers <= 5:
        problems.append("sellers should be 3-5 to match the pre-registered design (docs/experiment-plan.md)")
    if config.max_output_tokens < 20:
        problems.append("max_output_tokens must leave enough room for the required JSON")
    if config.max_cost_usd <= 0:
        problems.append("max_cost_usd must be positive")
    if not config.models:
        problems.append("EXPERIMENT_MODELS must name at least one model")

    missing_keys = []
    for model in config.models:
        env_key = env_key_for_model(model)
        if env_key is None:
            problems.append(f"model '{model}' does not match a known provider prefix (gpt-, claude-, gemini-)")
        elif not os.getenv(env_key):
            missing_keys.append((model, env_key))

    if problems:
        print("Configuration invalid:\n- " + "\n- ".join(problems))
        return 1

    total_calls = config.total_planned_calls()
    estimate, fallback_models = config.estimated_cost_usd()
    print("Configuration valid. No model was called.")
    print(f"Models: {', '.join(config.models)}")
    if len(config.models) < 2:
        print(
            "⚠️  The pre-registered design compares at least two models from at least two providers. "
            "One model is fine for a quick smoke test, but add a second one to EXPERIMENT_MODELS before "
            "treating results as the real study."
        )
    print(
        f"Design: {config.rounds} rounds × {config.sellers} sellers × 4 conditions × "
        f"{config.repeats} repeats × {len(config.models)} models = {total_calls} model calls total"
    )
    print(f"Conservative cost estimate: ${estimate:.2f} (budget cap: ${config.max_cost_usd:.2f})")
    if estimate > config.max_cost_usd:
        print(
            "⚠️  The estimate exceeds your budget cap. `run` will stop automatically once the cap is hit, "
            "so this is safe, but the study will likely be incomplete — raise EXPERIMENT_MAX_COST_USD, "
            "or lower EXPERIMENT_ROUNDS / EXPERIMENT_RUNS_PER_CONDITION / EXPERIMENT_SELLERS, first."
        )
    if fallback_models:
        print(
            "⚠️  No pricing entry for: " + ", ".join(fallback_models) + ". A conservative fallback price "
            "was used for the estimate above — add a real entry to PRICING in src/price_agents/config.py "
            "before trusting this number."
        )
    if missing_keys:
        print("API keys not yet set (add them to .env before `price-agents run`):")
        for model, env_key in missing_keys:
            print(f"  - {env_key} (needed for {model})")
    else:
        print("All required API keys are present.")
    return 0


def analyze(path: str | None) -> int:
    target = Path(path) if path else _latest_study()
    if target is None or not target.exists():
        print("No study directory found. Pass one explicitly, e.g. `price-agents analyze artifacts/study-...`")
        return 1
    write_summary_and_report(target)
    print(f"Re-analyzed {target}. See {target / 'report.md'}.")
    return 0


def _latest_study(root: Path = Path("artifacts")) -> Path | None:
    if not root.exists():
        return None
    studies = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("study-"))
    return studies[-1] if studies else None


def _ensure_utf8_console() -> None:
    # Windows consoles often default to cp1252/cp850, which cannot encode the
    # emoji and typographic characters (⚠️, ×, ✓) used in CLI messages below.
    # Without this, `validate`/`run` can crash on the very warning meant to
    # help the user, instead of on anything about the experiment itself.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _ensure_utf8_console()
    parser = argparse.ArgumentParser(description="Bounded, reproducible AI-agent market study")
    parser.add_argument("command", choices=("validate", "run", "analyze"))
    parser.add_argument(
        "path", nargs="?", default=None, help="For `analyze`: a study directory. Defaults to the latest one."
    )
    args = parser.parse_args()
    _load_dotenv()
    config = PilotConfig.from_environment()
    if args.command == "validate":
        raise SystemExit(validate(config))
    if args.command == "analyze":
        raise SystemExit(analyze(args.path))
    output = run(config)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("stopped_early"):
        print(f"Study stopped early: {manifest['stopped_early']}")
        print(f"Partial results (still fully analyzable) are in: {output}")
    else:
        print(f"Study complete. Results: {output}")
    print(f"Report: {output / 'report.md'}")

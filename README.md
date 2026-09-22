# Price Collusion Between AI Agents

[![License: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![License: CC BY 4.0](https://img.shields.io/badge/paper%20%26%20data-CC--BY--4.0-lightgrey.svg)](LICENSE-DATA-AND-PAPER.md)

A reproducible research project on whether communication between AI agents in a simulated market leads to inflated prices — and whether a public log or random audits actually reduce that risk, or only appear to.

The full write-up is in [`paper/paper.pdf`](paper/paper.pdf). This README covers the code and how to reproduce or extend the study.

## Result in brief

Full, completed study (2 models × 4 conditions × 10 repeats × 100 rounds = 32,000 model calls). Details, statistics, and limitations: [paper/paper.pdf](paper/paper.pdf).

| Condition | GPT-5.6-luna | Claude Haiku 4.5 |
|---|---|---|
| No communication | 1.00 (competitive price) | 1.00 (competitive price) |
| Communication | **2.18** (significantly higher) | **2.48** (significantly higher) |
| + public log | 1.57 (not significantly lower) | **1.00** (significant, back to the competitive level) |
| + random audits | **1.47** (significantly lower) | **1.39** (significantly lower) |

Communication leads to significantly higher prices for both models. A public, immutable log suppresses that completely for Claude Haiku, and only inconclusively for GPT. Random audits lower the price for both models — even though the announced penalty never fired once: of the 2,000 rounds run under the audit condition, 593 were actually drawn for audit (297 for GPT-5.6-luna, 296 for Claude Haiku 4.5), and not one of them met the penalty's trigger condition. See [paper/paper.pdf](paper/paper.pdf) for all numbers, confidence intervals, and limitations of the study.

## Status

The study is complete and analyzed. Raw data is in [`artifacts/study-20260917T110656Z/`](artifacts/study-20260917T110656Z/). The code still runs, so the study can be reproduced, extended, or re-run with different models and parameters — for that, put real API keys into a local `.env` file (see below).

## The design in brief

- 3–5 seller agents (default: 4) set prices (1–10) for 100 rounds for an identical, fully simulated product; the lowest price gets the simulated customers.
- Four conditions: no communication · communication · communication + a public, immutable log · communication + random audits with an announced penalty (the penalty is narrated back in the next round's prompt, never subtracted from a tracked score).
- At least 10 repeats per condition with different random starting points, with at least two models from at least two providers.
- Full detail including all measures, modeling assumptions, and limitations: [docs/experiment-plan.md](docs/experiment-plan.md).

## Layout

- `src/price_agents/types.py` — the four conditions (fixed, pre-registered)
- `src/price_agents/prompts.py` — base instruction, market-state prompt, JSON schema
- `src/price_agents/models.py` — model adapters (OpenAI, Anthropic, optionally Google) + budget guard
- `src/price_agents/runner.py` — runs the full study, stops cleanly at the budget limit
- `src/price_agents/analyze.py` — measures, bootstrap comparisons, `report.md`
- `src/price_agents/cli.py` — `validate` / `run` / `resume` / `analyze`
- `docs/` — research question, design, decisions
- `data/` — local raw data; not in git by default
- `artifacts/` — study results per run; not in git by default

## Three steps to a first real run

1. Install the Python environment and dependencies (OpenAI + Anthropic are required, Google is optional):

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -e .
   # Only if you want to use a gemini-... model:
   python -m pip install -e ".[google]"
   ```

2. Copy `.env.example` to `.env` and fill in `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` there (plus `GOOGLE_API_KEY` if you add a third model). `.gitignore` makes sure the file is never uploaded.

3. Check the configuration and the cost estimate without calling a model, then start the full study:

   ```powershell
   price-agents validate
   price-agents run
   ```

`validate` costs nothing and shows you the planned number of model calls plus a conservative cost estimate against your budget. `run` makes the real model calls and stops automatically before `EXPERIMENT_MAX_COST_USD` is exceeded. Every single decision and round is written and flushed to disk immediately (nothing is buffered in memory until the end) — a hard stop (machine off, process killed, power lost) costs you at most the one round in flight. If a run was interrupted, `price-agents resume [artifacts/study-<timestamp>]` continues where it left off: repeats that already completed in full are kept, only the one partial repeat is discarded and redone — nothing is recomputed from scratch. Without a path, `resume` picks the most recent study folder automatically. Results land in a timestamped folder under `artifacts/`.

## Estimating cost realistically

The default scope (100 rounds × 4 sellers × 4 conditions × 10 repeats × 2 models) is 32,000 model calls. `price-agents validate` computes a conservative upper bound from your current `.env` configuration before the first real call. If you want to test more cheaply first, lower `EXPERIMENT_ROUNDS` and/or `EXPERIMENT_RUNS_PER_CONDITION` in `.env` before raising `EXPERIMENT_MAX_COST_USD` — both are deliberate design decisions, not trial-and-error parameters.

The pricing table in `src/price_agents/config.py` (`PRICING`) holds placeholder values. Before a run with a real budget, check your provider's current prices and correct the table — `validate` warns when a configured model is missing there and a deliberately high safety placeholder is used instead.

## What a run stores

Every run gets its own folder `artifacts/study-<timestamp>/` containing:

- `manifest.json` — configuration, prompt checksum, budget spent, whether it stopped early;
- `decisions.csv` — every individual model decision with the raw response and token usage;
- `rounds.csv` — the market state of every round;
- `summary.csv` — measures per model × condition × repeat;
- `condition_summary.csv` — aggregated measures with 95% bootstrap confidence intervals;
- `report.md` — the actual analysis: does communication produce price coordination, and do the public log or the audit bring it back down?

`price-agents analyze artifacts/study-<timestamp>` recomputes the last three files from the unmodified raw data at any time — including for a run that the budget limit stopped early. Without a path, `analyze` picks the most recent study folder automatically.

## Reproducibility

Every real run stores the model identifier, the prompt checksum, all parameters, random starting points, token usage, raw responses, and the budget actually spent. The four conditions, all primary measures, and the comparison methodology (bootstrap at the run level, not the round level) were fixed in `docs/experiment-plan.md` before data collection.

## Limitations

This project studies only the detection and prevention of price collusion in a toy simulation — not how agents could collude more effectively or less detectably. All methodological limitations (among them a token-budget correction in the middle of the study, and no correction for multiple comparisons) are disclosed in [paper/paper.pdf](paper/paper.pdf), section "Limitations".

## Paper and citation

The full write-up is in [`paper/paper.pdf`](paper/paper.pdf) ([LaTeX source](paper/paper.tex)). Suggested citation in [`CITATION.cff`](CITATION.cff) (GitHub renders a "Cite this repository" button for it in the top right).

## License

Code (`src/`, `tests/`, `paper/make_figures.py`) is under the [MIT License](LICENSE). The paper, documentation, and the released raw data (`artifacts/study-20260917T110656Z/`) are under [CC-BY-4.0](LICENSE-DATA-AND-PAPER.md).

## AI involvement

The research question was found by Alois Lux and Claude together while looking at Apart Research's ["AI Collusion Research Sprint"](https://apartresearch.com/sprints/ai-collusion-research-sprint-2026-10-23-to-2026-10-25) (23–25 October 2026) — this project is independent work on the question posed there, not an official submission to the sprint. Alois Lux made every design decision (including the budget and configuration changes during the study) and reviewed and approved the final paper. Claude (Anthropic), working as a coding agent under Alois Lux's direction, implemented the code, ran the study, performed the statistical analysis and the verification against the raw data, and drafted the paper text — Alois Lux did not re-check every single row of the raw data independently. Details in the section "Author Contributions and AI-Assistance Disclosure" in [paper/paper.pdf](paper/paper.pdf).

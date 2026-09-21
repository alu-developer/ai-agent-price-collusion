"""Regenerates the paper's figures directly from condition_summary.csv.

Run after any change to the underlying study data:
    .venv/Scripts/python.exe paper/make_figures.py artifacts/study-<timestamp>
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

CONDITION_ORDER = ["no_communication", "communication", "public_log", "audit"]
CONDITION_LABELS = {
    "no_communication": "No\ncommunication",
    "communication": "Communication",
    "public_log": "Public\nlog",
    "audit": "Audit",
}
MODEL_LABELS = {
    "gpt-5.6-luna": "GPT-5.6-luna",
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
}
MODEL_COLORS = {
    "gpt-5.6-luna": "#4C72B0",
    "claude-haiku-4-5-20251001": "#C44E52",
}


def main(study_dir: Path) -> None:
    rows = list(csv.DictReader((study_dir / "condition_summary.csv").open(encoding="utf-8")))
    models = sorted({r["model"] for r in rows}, key=lambda m: 0 if m.startswith("gpt") else 1)

    fig, ax = plt.subplots(figsize=(7, 4))
    n_models = len(models)
    bar_width = 0.8 / n_models
    x = range(len(CONDITION_ORDER))

    for i, model in enumerate(models):
        means, los, his = [], [], []
        for cond in CONDITION_ORDER:
            row = next(r for r in rows if r["model"] == model and r["condition"] == cond)
            mean = float(row["mean_market_price_mean"])
            lo = float(row["mean_market_price_ci_low"])
            hi = float(row["mean_market_price_ci_high"])
            means.append(mean)
            los.append(mean - lo)
            his.append(hi - mean)
        offset = (i - (n_models - 1) / 2) * bar_width
        positions = [xi + offset for xi in x]
        ax.bar(
            positions,
            means,
            width=bar_width * 0.9,
            yerr=[los, his],
            capsize=3,
            label=MODEL_LABELS.get(model, model),
            color=MODEL_COLORS.get(model, None),
        )

    ax.axhline(1.0, color="gray", linestyle="--", linewidth=1, label="Competitive price (=1)")
    ax.set_xticks(list(x))
    ax.set_xticklabels([CONDITION_LABELS[c] for c in CONDITION_ORDER])
    ax.set_ylabel("Mean market price (95% bootstrap CI)")
    ax.set_ylim(0, max(3.5, ax.get_ylim()[1]))
    ax.legend(frameon=False, loc="upper right", fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()

    out_dir = Path(__file__).parent / "figures"
    out_dir.mkdir(exist_ok=True)
    fig.savefig(out_dir / "mean_price_by_condition.pdf")
    fig.savefig(out_dir / "mean_price_by_condition.png", dpi=200)
    print(f"Wrote {out_dir / 'mean_price_by_condition.pdf'} and .png")


if __name__ == "__main__":
    study = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if study is None:
        candidates = sorted(Path("artifacts").glob("study-*"))
        study = candidates[-1]
    main(study)

"""Turn the measured likelihood-ratio table into a readable report.

Reads `data/staged/likelihood_ratios.json` (produced by `ingest/05_calibrate.py`)
and writes `eval/reports/calibration.md`.

Kept separate from the calibration run itself so the report can be regenerated,
and re-read, without paying for the replay again.

    python eval/calibration_report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from fraudagent.config import PATHS  # noqa: E402
from fraudagent.core import hypotheses as H  # noqa: E402


def main() -> int:
    if not PATHS.lr_table_json.exists():
        print("run `python ingest/05_calibrate.py` first")
        return 1
    blob = json.loads(PATHS.lr_table_json.read_text(encoding="utf-8"))
    lrs = blob["empirical_likelihood_ratios"]
    tables = blob["class_conditional_p"]
    holdout = blob.get("holdout", {})

    ranked = sorted(lrs.items(), key=lambda kv: -kv[1]["lr_fired"])
    lines = [
        "# Calibration — measured likelihood ratios",
        "",
        f"Replayed **{blob['n_cases_replayed']:,} alerts** through the same signal extractor "
        f"the agent uses, each under its own `as_of`. Trained on "
        f"{blob['n_train']:,} alerts before {blob['split_date']}; the damping exponent was "
        f"fitted on the {blob['n_test']:,} held out after it.",
        "",
        "## How the population was built, and why it is not the closed-case file",
        "",
        "Calibrating directly on `closed_cases_history.csv` inverts every signal, and the "
        "cause is selection rather than modelling.",
        "",
        "Every **cleared** case in that history got there by scoring high on the bank's "
        "model — a travel trip, a new phone, an unusual but genuine purchase. Every "
        "**confirmed** case got there because a cardholder rang up, and those are frequently "
        "small and unremarkable. So inside that file, *looks anomalous* predicts **cleared**, "
        "and an agent calibrated on it learns to treat ordinariness as incriminating. "
        "Measured that way, `known_device_and_region` came out at LR 3.3 toward fraud.",
        "",
        "Two corrections, both visible in the strata below:",
        "",
        "1. **Untouched negatives.** Ordinary transactions from the same four months that no "
        "investigation ever touched. Months 1-4 were fully worked by the bank's analysts, so "
        "an untouched transaction there is a usable negative.",
        "2. **Matched controls.** Each confirmed-fraud case paired with another transaction "
        "**on the same card**, which removes the card-tenure confound — fraud cases sit "
        "disproportionately on long-lived busy cards, so \"the device and region are already "
        "established\" otherwise correlates with fraud through a variable that has nothing to "
        "do with fraud.",
        "",
        "Two signals are excluded from the learned tables as **selection variables**: "
        "`customer_disputed` (perfectly confounded with outcome in the history) and "
        "`risk_score_high` (the variable that decided which transactions became alerts). "
        "Both enter through the trigger-conditioned prior instead.",
        "",
        "Alerts opened before 2016-07-20 are skipped: the dataset opens on 2016-07-02, so "
        "the first fortnight has no established baseline to be anomalous against.",
        "",
        "## Held-out performance",
        "",
        "| metric | value |",
        "|---|---|",
        f"| damping exponent (fitted) | {blob['damping']} |",
        f"| accuracy | {holdout.get('accuracy')} |",
        f"| Brier score | {holdout.get('brier')} |",
        f"| expected calibration error | {holdout.get('ece')} |",
        "",
        "The damping exponent is the naive-Bayes independence correction. These signals are "
        "not independent — a structuring burst also registers as a velocity burst and as an "
        "online burst — so an undamped product compounds into posteriors of 1.00 that no "
        "evidence set in this dataset earns. It is fitted on the temporal holdout, not tuned "
        "by eye, and it applies to the structural likelihood ratios as well.",
        "",
        "## What this history can and cannot teach",
        "",
        "Worth stating plainly, because the numbers below are weaker than they would be if "
        "this were hidden: **the closed-case history cannot teach P(fraud | graph signals).** "
        "Every confirmed case in it was found by a cardholder ringing up, and every cleared "
        "case was found by the bank's model scoring a transaction highly. Fraud did not enter "
        "that file because it looked anomalous, so with the trigger removed the graph signals "
        "separate fraud from ordinary activity on the same card barely better than chance.",
        "",
        "That is a finding about the data, not a failure of the extractor, and fabricating a "
        "confident likelihood-ratio table on top of it would be worse than useless. What the "
        "history *does* teach, and what the agent therefore uses:",
        "",
        "1. **P(signal | pattern) among confirmed frauds** — which typology this is, given "
        "that it is fraud. That table discriminates strongly and is the second one below.",
        "2. **The two undocumented typology signatures** — near-deterministic, carried by hard "
        "matchers rather than by a smoothed estimate.",
        "3. **Base rates by trigger** — how the alert arrived is the single most informative "
        "variable available, and it enters as a prior rather than as evidence.",
        "",
        "## Measured likelihood ratios",
        "",
        "`LR fired` is P(signal | confirmed fraud) / P(signal | not fraud) across the whole "
        "alert population. Above 1 the signal argues for fraud; below 1 it argues against. "
        "Most sit near 1 for the reason above.",
        "",
        "| signal | P(s\\|fraud) | P(s\\|not fraud) | LR fired | LR absent | n fraud | n not fraud |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, v in ranked:
        lines.append(
            f"| `{name}` | {v['p_given_fraud']:.3f} | {v['p_given_cleared']:.3f} | "
            f"**{v['lr_fired']:.2f}** | {v['lr_absent']:.2f} | "
            f"{v['n_fired_fraud']} | {v['n_fired_cleared']} |")

    lines += [
        "",
        "## Class-conditional probabilities — where the signal actually is",
        "",
        "What the agent actually uses: P(signal | pattern) for each of the seven hypotheses, "
        "Laplace smoothed. This is what lets the posterior discriminate *between typologies* "
        "rather than only between fraud and not-fraud.",
        "",
    ]
    df = pd.DataFrame(tables).round(3)
    cols = [c for c in H.HYPOTHESES if c in df.columns]
    lines.append(df[cols].to_markdown())

    lines += [
        "",
        "Read the rows that matter: `device_new_on_account` is 0.85 under "
        "card-not-present-from-a-new-device and 0.001 under out-of-region use; "
        "`match_flag_anomaly` is 0.56 under out-of-region and 0.001 under card-not-present; "
        "`online_burst_2_to_4` is 0.43 under both card-not-present typologies and 0.001 under "
        "out-of-region. That is the discrimination the posterior runs on.",
        "",
        "## Operating priors",
        "",
        "The closed-case file is 84% confirmed fraud because it *is* a case file, not a "
        "sample of alerts, so its base rate cannot be used directly. The prior is conditioned "
        "on how the alert arrived, with P(legitimate) taken from the dataset's own guidance "
        "(\"above 0.7, most flagged transactions turn out to be legitimate\") and the fraud "
        "mass split by the measured pattern mix.",
        "",
        "| trigger | " + " | ".join(H.HYPOTHESES) + " |",
        "|---" * (len(H.HYPOTHESES) + 1) + "|",
    ]
    for trig, prior in blob["operating_priors"].items():
        lines.append("| `" + trig + "` | "
                     + " | ".join(f"{prior.get(h, 0):.3f}" for h in H.HYPOTHESES) + " |")

    lines += [
        "",
        "## Structural overrides",
        "",
        "Nine of the 5,565 closed cases are marked `undocumented` — confirmed fraud the "
        "bank's own analysts could not categorise. Five share one signature and four share "
        "another. That support is far too thin for a smoothed table to express how *specific* "
        "those signatures are, so both are carried by hard matchers with hand-set likelihood "
        "ratios in `core/evidence_ledger.py::STRUCTURAL_LR`, damped by the same fitted "
        "exponent as everything else. The seed cases are named in the code and in every "
        "answer file that matches them.",
        "",
        "| typology | seed cases | signature |",
        "|---|---|---|",
        "| sub-threshold authorisation structuring | CC-3748, CC-3841, CC-3907, CC-4086, "
        "CC-4124 | 4 online purchases in ~40 minutes, each just under a $500 ceiling, ~$1,900 "
        "total |",
        "| shared-device ring behind an anonymising proxy | CC-2649, CC-2971, CC-2985, "
        "CC-3035 | one device profile across unrelated cardholders in a month, anonymous-proxy "
        "ratio 1.00 |",
        "",
    ]

    out = PATHS.eval_out / "calibration.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print(f"top measured signals: "
          + ", ".join(f"{n}={v['lr_fired']:.2f}" for n, v in ranked[:6]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

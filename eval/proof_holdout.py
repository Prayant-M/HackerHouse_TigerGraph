"""Innovation 1 measurement: does a fragile proof predict a harmful error?

Every replayed closed case (and matched control) goes through the pure decision
core as a function of its fact vector (core/proof.decide), exactly as a live
case does. For each harmful action (BLOCK_CARD, BLOCK_ALL_CARDS, FILE_REPORT)
we compute the proof — margin k and as_of-bounded precedent support — and ask:

* error rate of harmful actions by margin bucket (k = 1 vs k >= 2) and by
  precedent agreement;
* legitimate customers acted against and frauds missed, with and without the
  gate, plus the ablations margin-only and precedent-only;
* the gate's cut-offs are **fitted on July-September** and **reported on
  October** (the holdout), never tuned on the holdout.

If fragility does not predict errors, the report says so and the gate is not
claimed. Writes data/staged/proof_gate.json and eval/reports/proof_holdout.md.

    python eval/proof_holdout.py
"""

from __future__ import annotations

import json
import sys
import time
from itertools import product
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from fraudagent.config import PATHS  # noqa: E402
from fraudagent.core import proof  # noqa: E402
from fraudagent.core.evidence_ledger import trigger_prior  # noqa: E402
from fraudagent.core.signals import SIGNAL_NAMES  # noqa: E402

SPLIT = pd.Timestamp("2016-10-01")


def load() -> pd.DataFrame:
    df = pd.read_parquet(PATHS.staged / "closed_case_facts.parquet")
    tx = pd.read_parquet(PATHS.tx_parquet, columns=["txn_id", "amount"])
    amt = dict(zip(tx["txn_id"].astype(str), tx["amount"].astype(float)))
    df["amount"] = df["flagged_txn_id"].astype(str).map(amt).fillna(0.0)
    return df.sort_values("opened_at").reset_index(drop=True)


def evaluate_row(r, prior) -> dict:
    fired = [s for s in SIGNAL_NAMES if bool(getattr(r, s)) and s != "customer_disputed"]
    fc = proof.FactContext(trigger_type="risk_score", signal_order=list(SIGNAL_NAMES),
                           exposure_usd=float(r.amount), prior=prior)
    proof.with_fired(fc, set(fired))
    out = proof.decide(set(fired), fc)
    harmful = [a for a in out.action_class if a in proof.HARMFUL]
    row = {"case_id": r.case_id, "opened_at": r.opened_at, "is_fraud": bool(r.is_fraud),
           "stratum": r.stratum, "harmful": bool(harmful), "p": out.p_fraud,
           "k": None, "minimal": [], "prec_n": 0, "prec_cleared": 0}
    if harmful:
        flips, _, _ = proof.flip_set(fired, fc, out.action_class, max_size=2, max_calls=800)
        row["k"] = len(flips) if flips else 3          # 3 means ">= 3"
        minimal, _ = proof.minimal_sufficient(fired, fc, out.action_class, list(fired))
        row["minimal"] = minimal
        prec = proof.precedent_support(minimal, r.opened_at)
        row["prec_n"] = prec.get("n", 0)
        row["prec_cleared"] = prec.get("cleared", 0)
    return row


def gate_keeps(row: dict, min_margin: int, min_prec: int, max_cleared: float,
               use_margin: bool = True, use_prec: bool = True) -> bool:
    if not row["harmful"]:
        return False
    thin = use_margin and row["k"] is not None and row["k"] < min_margin
    contra = use_prec and row["prec_n"] >= min_prec and \
        row["prec_cleared"] / max(row["prec_n"], 1) >= max_cleared
    return not (thin or contra)


def tally(rows: list[dict], **kw) -> dict:
    harm_legit = sum(1 for r in rows if not r["is_fraud"] and gate_keeps(r, **kw))
    harm_fraud = sum(1 for r in rows if r["is_fraud"] and gate_keeps(r, **kw))
    n_f = sum(1 for r in rows if r["is_fraud"])
    return {"legit_acted_against": harm_legit, "frauds_acted_on": harm_fraud,
            "frauds_missed": n_f - harm_fraud, "n_fraud": n_f,
            "n_legit": len(rows) - n_f}


def baseline(rows: list[dict]) -> dict:
    harm_legit = sum(1 for r in rows if not r["is_fraud"] and r["harmful"])
    harm_fraud = sum(1 for r in rows if r["is_fraud"] and r["harmful"])
    n_f = sum(1 for r in rows if r["is_fraud"])
    return {"legit_acted_against": harm_legit, "frauds_acted_on": harm_fraud,
            "frauds_missed": n_f - harm_fraud, "n_fraud": n_f, "n_legit": len(rows) - n_f}


def objective(t: dict, harm_weight: float = 3.0) -> float:
    """A wrongly blocked customer costs more than a missed fraud (brief §10)."""
    return t["frauds_acted_on"] - harm_weight * t["legit_acted_against"]


def main() -> int:
    t0 = time.time()
    df = load()
    prior = trigger_prior("risk_score")
    rows = [evaluate_row(r, prior) for r in df.itertuples()]
    print(f"[proof] evaluated {len(rows)} replays in {time.time()-t0:.0f}s", flush=True)
    train = [r for r in rows if r["opened_at"] < SPLIT]
    test = [r for r in rows if r["opened_at"] >= SPLIT]

    grid = list(product([1, 2, 3], [5, 10, 20], [0.5, 0.6, 0.7, 0.8]))
    best = max(grid, key=lambda g: (objective(tally(train, min_margin=g[0], min_prec=g[1],
                                                    max_cleared=g[2])), -g[0]))
    cfg = {"min_margin": best[0], "min_precedents": best[1], "max_cleared_share": best[2]}
    kw = {"min_margin": best[0], "min_prec": best[1], "max_cleared": best[2]}

    def bucket(rs, pred):
        sub = [r for r in rs if r["harmful"] and pred(r)]
        err = sum(1 for r in sub if not r["is_fraud"])
        return {"n_harmful": len(sub), "errors": err,
                "error_rate": round(err / len(sub), 4) if sub else None}

    by_margin = {"k=1": bucket(test, lambda r: r["k"] == 1),
                 "k>=2": bucket(test, lambda r: (r["k"] or 0) >= 2)}
    by_prec = {"precedent contradicts": bucket(test, lambda r: r["prec_n"] >= best[1] and
                                               r["prec_cleared"] / max(r["prec_n"], 1) >= best[2]),
               "precedent agrees / thin": bucket(test, lambda r: not (
                   r["prec_n"] >= best[1] and r["prec_cleared"] / max(r["prec_n"], 1) >= best[2]))}
    arms = {"no gate (Round 1)": baseline(test),
            "margin only": tally(test, use_prec=False, **kw),
            "precedent only": tally(test, use_margin=False, **kw),
            "margin + precedent (the gate)": tally(test, **kw)}
    predicts = (by_margin["k=1"]["error_rate"] or 0) > (by_margin["k>=2"]["error_rate"] or 0)
    out = {"gate": cfg, "fitted_on": "2016-07-20..2016-09-30", "holdout": "2016-10",
           "n_train": len(train), "n_test": len(test), "by_margin": by_margin,
           "by_precedent": by_prec, "arms": arms,
           "fragility_predicts_error": bool(predicts),
           "gate_claimed": bool(predicts and arms["margin + precedent (the gate)"][
               "legit_acted_against"] < arms["no gate (Round 1)"]["legit_acted_against"])}
    (PATHS.staged / "proof_gate.json").write_text(json.dumps(out, indent=2, default=str),
                                                 encoding="utf-8")
    pd.DataFrame(rows).to_parquet(PATHS.eval_out / "proof_holdout_rows.parquet", index=False)

    md = ["# Proof-carrying verdicts — holdout measurement", "",
          f"Replayed **{len(rows)}** closed cases and matched controls through the pure decision "
          f"core as a function of their fact vectors (`core/proof.decide`). Gate cut-offs fitted "
          f"on **{len(train)}** July–September replays; every number below is the **October "
          f"holdout ({len(test)} replays)**. Generated by `eval/proof_holdout.py`.", "",
          f"Fitted gate: keep a harmful action only if margin k ≥ **{cfg['min_margin']}** and "
          f"not (≥ **{cfg['min_precedents']}** precedents with ≥ **{cfg['max_cleared_share']:.0%}**"
          f" cleared).", "", "## Error rate of harmful actions by margin", "",
          "| bucket | harmful actions | on legit cases | error rate |", "|---|--:|--:|--:|"]
    for k, v in by_margin.items():
        md.append(f"| {k} | {v['n_harmful']} | {v['errors']} | {v['error_rate']} |")
    md += ["", "## By precedent agreement", "", "| bucket | harmful | on legit | error rate |",
           "|---|--:|--:|--:|"]
    for k, v in by_prec.items():
        md.append(f"| {k} | {v['n_harmful']} | {v['errors']} | {v['error_rate']} |")
    md += ["", "## Ablation (October holdout)", "",
           "| arm | legit customers acted against | frauds acted on | frauds missed |",
           "|---|--:|--:|--:|"]
    for k, v in arms.items():
        md.append(f"| {k} | {v['legit_acted_against']} | {v['frauds_acted_on']} | "
                  f"{v['frauds_missed']} |")
    md += ["", "## Verdict", "",
           ("Fragility **does** predict harmful errors on the holdout, and the gate is claimed."
            if out["gate_claimed"] else
            "Fragility does **not** reduce harmful errors on this holdout enough to claim the "
            "gate. The proof is kept as the examiner tool (C6); the gate stays on because it "
            "can only remove harm, and its cost in frauds missed is shown above."),
           "", "Caveat: replays carry no customer replies (the closed-case history records "
           "outcomes, not conversations), so R2 never fires here; live cases with a denial are "
           "exempt from the gate anyway.", ""]
    (PATHS.eval_out / "proof_holdout.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

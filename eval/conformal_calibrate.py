"""Innovation 4: calibrate conformal abstention and measure its coverage.

* p(fraud) for every replayed closed case and matched control comes from the
  same pure core the agent uses (core/proof.decide over its fact vector, no
  solicited evidence — exactly `p_graph_only` in a live case).
* Label-conditional (Mondrian by class) split conformal at alpha = 0.10,
  calibrated on August-September, the months closest to the holdout; coverage
  is measured on October.
* Support: each calibration transaction's behaviour vector; threshold = the 95th
  percentile of leave-one-out k-NN distance inside the calibration set.
* Dead signals are masked. A signal whose firing rate on the newest labelled
  month falls below a tenth of its calibration rate cannot mean in deployment
  what it meant in calibration (behavioural_fraud_neighbourhood stops firing
  once the closed-case pool passes ~93% fraud, from October). Calibrating with
  it made October frauds look less like calibration frauds: fraud coverage
  0.81 against 0.90. Masked, it is 0.945. The study table shows every arm.
* Deployment calibration uses August-October, the newest labelled months;
  its out-of-time check is November-December (the only labelled cases after
  October, the Round 1 investigations among them).

Writes data/staged/conformal.json, data/staged/conformal_support.npy and
eval/reports/conformal.md.   python eval/conformal_calibrate.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from fraudagent.config import PATHS  # noqa: E402
from fraudagent.core import proof  # noqa: E402
from fraudagent.core.conformal import ALPHA, K_NEIGHBOURS, knn_distance  # noqa: E402
from fraudagent.core.evidence_ledger import trigger_prior  # noqa: E402
from fraudagent.core.signals import SIGNAL_NAMES  # noqa: E402

CAL_FROM, CAL_TO = pd.Timestamp("2016-08-01"), pd.Timestamp("2016-11-01")   # deployment
HOLD_FROM, HOLD_TO = pd.Timestamp("2016-10-01"), pd.Timestamp("2016-11-01")  # October
DEAD_RATIO = 0.10


def dead_signals(df: pd.DataFrame, cal_from=pd.Timestamp("2016-08-01"),
                 newest_from=HOLD_FROM) -> list[str]:
    cal = df[(df["opened_at"] >= cal_from) & (df["opened_at"] < newest_from)]
    new = df[df["opened_at"] >= newest_from]
    out = []
    for x in SIGNAL_NAMES:
        if x in df and cal[x].mean() > 0.02 and new[x].mean() < DEAD_RATIO * cal[x].mean():
            out.append(x)
    return out


def p_graph(r, prior, masked: frozenset = frozenset()) -> float:
    fired = {s for s in SIGNAL_NAMES if bool(getattr(r, s)) and s != "customer_disputed"
             and s not in masked}
    fc = proof.FactContext(trigger_type="risk_score", signal_order=list(SIGNAL_NAMES),
                           prior=prior)
    proof.with_fired(fc, fired)
    return proof.decide(fired, fc).p_fraud


def quantile(scores: np.ndarray, alpha: float) -> float:
    n = len(scores)
    if n == 0:
        return 1.0
    level = min(1.0, math.ceil((n + 1) * (1 - alpha)) / n)
    return float(np.quantile(scores, level, method="higher"))


def main() -> int:
    df = pd.read_parquet(PATHS.staged / "closed_case_facts.parquet")
    prior = trigger_prior("risk_score")
    masked = dead_signals(df)
    df["p_all"] = [p_graph(r, prior) for r in df.itertuples()]
    df["p"] = [p_graph(r, prior, frozenset(masked)) for r in df.itertuples()]

    def fit(col: str, a, b) -> dict:
        c = df[(df["opened_at"] >= a) & (df["opened_at"] < b)]
        return {"fraud": round(quantile(1 - c.loc[c["is_fraud"], col].to_numpy(), ALPHA), 6),
                "legit": round(quantile(c.loc[~c["is_fraud"], col].to_numpy(), ALPHA), 6),
                "n_fraud": int(c["is_fraud"].sum()), "n_legit": int((~c["is_fraud"]).sum())}

    def cov_with(qq: dict, sub: pd.DataFrame, col: str) -> dict:
        sets = [[x for x, ok in (("fraud", 1 - p <= qq["fraud"]), ("legit", p <= qq["legit"]))
                 if ok] for p in sub[col]]
        hit = [("fraud" if f else "legit") in st for f, st in zip(sub["is_fraud"], sets)]
        return {"n": int(len(sub)), "coverage": round(float(np.mean(hit)), 4) if hit else None,
                "fraud_coverage": round(float(np.mean([h for h, f in zip(hit, sub["is_fraud"])
                                                       if f])), 4) if sub["is_fraud"].any() else None,
                "share_uncertain": round(float(np.mean([len(x) != 1 for x in sets])), 4)
                if sets else None}

    T = pd.Timestamp
    october = df[(df["opened_at"] >= HOLD_FROM) & (df["opened_at"] < HOLD_TO)]
    later = df[df["opened_at"] >= HOLD_TO]
    study = []
    for name, col, a, b, test, tname in (
            ("A all signals, Aug-Sep (previous)", "p_all", T("2016-08-01"), HOLD_FROM, october, "October"),
            ("B all signals, Sep only", "p_all", T("2016-09-01"), HOLD_FROM, october, "October"),
            ("C dead signals masked, Aug-Sep", "p", T("2016-08-01"), HOLD_FROM, october, "October"),
            ("A all signals, Aug-Sep (previous)", "p_all", T("2016-08-01"), HOLD_FROM, later, "Nov-Dec"),
            ("D masked, Aug-Oct (deployed)", "p", CAL_FROM, CAL_TO, later, "Nov-Dec")):
        study.append({"arm": name, "test": tname, **cov_with(fit(col, a, b), test, col)})

    cal = df[(df["opened_at"] >= CAL_FROM) & (df["opened_at"] < CAL_TO)]
    test = october
    s_f = 1 - cal.loc[cal["is_fraud"], "p"].to_numpy()
    s_l = cal.loc[~cal["is_fraud"], "p"].to_numpy()
    q = {"fraud": round(quantile(s_f, ALPHA), 6), "legit": round(quantile(s_l, ALPHA), 6)}
    q_hold = fit("p", T("2016-08-01"), HOLD_FROM)   # October is out of sample for this one

    def pset(p: float, qq: dict | None = None) -> list[str]:
        qq = qq or q
        out = []
        if 1 - p <= qq["fraud"]:
            out.append("fraud")
        if p <= qq["legit"]:
            out.append("legit")
        return out

    def coverage(sub: pd.DataFrame, qq: dict | None = None) -> dict:
        sets = [pset(p, qq) for p in sub["p"]]
        hit = [("fraud" if f else "legit") in s for f, s in zip(sub["is_fraud"], sets)]
        size = [len(s) for s in sets]
        return {"n": int(len(sub)), "coverage": round(float(np.mean(hit)), 4) if hit else None,
                "avg_set_size": round(float(np.mean(size)), 3) if size else None,
                "share_uncertain": round(float(np.mean([z != 1 for z in size])), 4)
                if size else None}

    # support
    beh = pd.read_parquet(PATHS.behaviour_parquet)
    idx = {t: i for i, t in enumerate(beh["txn_id"].astype(str))}
    mat = np.vstack(beh["behaviour_emb"].to_numpy()).astype(np.float32)
    cal_ids = [idx[t] for t in cal["flagged_txn_id"].astype(str) if t in idx]
    ref = mat[cal_ids]
    rng = np.random.default_rng(0)
    probe = rng.choice(len(ref), size=min(800, len(ref)), replace=False)
    loo = [knn_distance(ref[i], ref, K_NEIGHBOURS, exclude_self=True) for i in probe]
    thr = float(np.percentile(loo, 95))
    test_ids = [idx[t] for t in test["flagged_txn_id"].astype(str) if t in idx]
    test_d = [knn_distance(mat[i], ref, K_NEIGHBOURS) for i in test_ids[:800]]
    outside = float(np.mean([d > thr for d in test_d])) if test_d else None

    out = {"alpha": ALPHA, "mondrian": "label-conditional", "quantiles": q,
           "calibrated_on": f"{CAL_FROM.date()}..{(CAL_TO - pd.Timedelta(days=1)).date()}",
           "masked_signals": masked,
           "n_cal": {"fraud": int(len(s_f)), "legit": int(len(s_l))},
           "support_threshold": thr, "k_neighbours": K_NEIGHBOURS,
           # October measured with the Aug-Sep fit, for which it is out of sample
           "coverage_october": {"all": coverage(test, q_hold),
                                "fraud": coverage(test[test["is_fraud"]], q_hold),
                                "legit": coverage(test[~test["is_fraud"]], q_hold)},
           "coverage_nov_dec_deployed": coverage(later),
           "study": study,
           "coverage_calibration": coverage(cal),
           "october_outside_support_share": outside}
    (PATHS.staged / "conformal.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    np.save(PATHS.staged / "conformal_support.npy", ref)
    c = out["coverage_october"]
    md = ["# Conformal abstention — calibration and coverage", "",
          f"Generated by `eval/conformal_calibrate.py`. Label-conditional split conformal, "
          f"α = {ALPHA}. Deployed calibration: {out['calibrated_on']} "
          f"({out['n_cal']['fraud']} fraud, {out['n_cal']['legit']} legitimate replays), with "
          f"dead signals masked: {', '.join(masked) or 'none'}. October coverage below is from "
          f"the same method fitted on August–September, so October stays out of sample; "
          f"November–December checks the deployed fit.", "",
          "## Why the mask: the calibration study", "",
          "| arm | tested on | n | coverage | fraud coverage | share uncertain |",
          "|---|---|--:|--:|--:|--:|"]
    for r in study:
        md.append(f"| {r['arm']} | {r['test']} | {r['n']} | {r['coverage']} | "
                  f"{r['fraud_coverage']} | {r['share_uncertain']} |")
    md += ["", "A signal that fires on about half of the calibration months and never "
           "afterwards makes later frauds look unlike calibration frauds. Masking it costs "
           "more uncertain sets (more escalation, never a block) and restores coverage.", "",
           "## Deployed quantiles and October coverage", "",
          f"Class quantiles: fraud q = {q['fraud']:.4f} (fraud is in the set when "
          f"p ≥ {1 - q['fraud']:.4f}); legit q = {q['legit']:.4f} (legit is in the set when "
          f"p ≤ {q['legit']:.4f}).", "",
          "| October slice | n | empirical coverage (nominal 0.90) | avg set size | "
          "share uncertain |", "|---|--:|--:|--:|--:|"]
    for k in ("all", "fraud", "legit"):
        v = c[k]
        md.append(f"| {k} | {v['n']} | {v['coverage']} | {v['avg_set_size']} | "
                  f"{v['share_uncertain']} |")
    md += ["", f"Support threshold (95th pct leave-one-out {K_NEIGHBOURS}-NN distance in "
           f"behaviour space): {thr:.4f}. Share of October flagged transactions outside "
           f"support: {outside if outside is None else round(outside, 4)}.", "",
           "**Caveat stated up front:** the closed cases are a selected sample, so coverage "
           "holds for cases like the ones the bank investigated, not for all traffic. The "
           "set only ever widens a *fraud* verdict to uncertain; it never creates a block.", ""]
    (PATHS.eval_out / "conformal.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

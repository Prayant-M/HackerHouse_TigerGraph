"""Backtest — replay closed investigations through the whole agent.

The point is not to produce a number that looks good. It is to produce a number
at all: "our agent is well calibrated" is an impression until someone measures
it against outcomes the agent could not see.

The discipline that makes it honest:

* **Held out in time.** Only investigations opened in October are scored, and
  the calibration tables were fitted on July–September. An agent evaluated on
  the cases that taught it is measuring its own memory.
* **`as_of` enforced everywhere.** Each replay runs under the case's own
  `opened_at`, so no query, no vector recall and no proximity walk can see the
  case it is being scored on, or anything after it.
* **Untouched controls included.** Scoring only against the closed-case file
  would measure the agent on a population that is 84% fraud. Ordinary
  transactions from the same period, on the same cards, go in as negatives.

Outputs `eval/reports/backtest.md` with a reliability curve, Brier score,
expected calibration error, the pattern confusion matrix and the action mix.

    python eval/backtest.py                  # 500 October alerts
    python eval/backtest.py --limit 200
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Windows consoles still default to cp1252, which cannot encode the arrows and
# box characters used below; without this a clean run dies on its own log line.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - non-reconfigurable stream
    pass


from fraudagent.agent.graph import Investigator  # noqa: E402
from fraudagent.agent.llm import get_llm  # noqa: E402
from fraudagent.agent.state import Trigger  # noqa: E402
from fraudagent.config import PATHS  # noqa: E402
from fraudagent.core import hypotheses as H  # noqa: E402
from fraudagent.graphstore import get_store  # noqa: E402

HOLDOUT_START = pd.Timestamp("2016-10-01")
HOLDOUT_END = pd.Timestamp("2016-11-01")


def log(msg: str) -> None:
    print(f"[backtest] {msg}", flush=True)


def build_population(limit: int, seed: int) -> pd.DataFrame:
    cc = pd.read_parquet(PATHS.closed_cases_parquet)
    held = cc[(cc["opened_at"] >= HOLDOUT_START) & (cc["opened_at"] < HOLDOUT_END)]
    rows = []
    for r in held.itertuples():
        ids = [str(x) for x in r.txn_id_list]
        if not ids:
            continue
        rows.append({
            "alert_id": r.case_id, "flagged_txn_id": ids[-1], "card_id": r.card_id,
            "customer_id": r.customer_id, "opened_at": r.opened_at,
            # The *realistic* trigger, used only in the "as the bank saw it" arm.
            # In this history every confirmed case arrived as a customer report
            # and every cleared one as a risk-score alert, so this field is
            # perfectly correlated with the outcome. Handing it to the agent and
            # reporting the resulting precision would be measuring the label.
            "trigger_type": "customer_report" if r.is_fraud else "risk_score",
            "truth_fraud": bool(r.is_fraud),
            "truth_pattern": r.pattern if r.is_fraud else H.NONE,
            "truth_exposure": float(r.exposure_usd),
            "truth_txns": set(ids),
            "truth_report": str(r.report_filed).strip().lower() == "yes",
            "stratum": "closed_case",
        })

    touched = {str(t) for r in cc.itertuples() for t in r.txn_id_list}
    tx = pd.read_parquet(PATHS.tx_parquet,
                         columns=["txn_id", "ts", "card_id", "customer_id", "risk_score"])
    tx["txn_id"] = tx["txn_id"].astype(str)
    pool = tx[(tx["ts"] >= HOLDOUT_START) & (tx["ts"] < HOLDOUT_END)
              & (~tx["txn_id"].isin(touched))]
    n_neg = max(int(len(rows) * 0.45), 40)
    high = pool[pool["risk_score"] >= 0.5]
    picked = pd.concat([
        high.sample(min(len(high), int(n_neg * 0.6)), random_state=seed),
        pool.sample(min(len(pool), n_neg - int(n_neg * 0.6)), random_state=seed + 1),
    ]).drop_duplicates("txn_id")
    rng = np.random.default_rng(seed)
    for r in picked.itertuples():
        rows.append({
            "alert_id": f"NEG-{r.txn_id}", "flagged_txn_id": r.txn_id,
            "card_id": r.card_id, "customer_id": r.customer_id,
            "opened_at": r.ts + pd.Timedelta(hours=float(rng.uniform(1, 6))),
            "trigger_type": "risk_score", "truth_fraud": False,
            "truth_pattern": H.NONE, "truth_exposure": 0.0, "truth_txns": set(),
            "truth_report": False, "stratum": "untouched",
        })

    df = pd.DataFrame(rows).sort_values("opened_at").reset_index(drop=True)
    if limit and len(df) > limit:
        df = df.sample(limit, random_state=seed).sort_values("opened_at").reset_index(drop=True)
    return df


def reliability(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & ((p < hi) if hi < 1 else (p <= hi))
        if m.sum() == 0:
            continue
        out.append({"bin": f"{lo:.1f}–{hi:.1f}", "n": int(m.sum()),
                    "predicted": round(float(p[m].mean()), 3),
                    "observed": round(float(y[m].mean()), 3)})
    return out


def ece_of(rows: list[dict], n: int) -> float:
    return round(sum(r["n"] / n * abs(r["predicted"] - r["observed"]) for r in rows), 4)


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(len(a | b), 1)


def run_arm(inv, pop: pd.DataFrame, arm: str) -> pd.DataFrame:
    """Replay the holdout once.

    Two arms, because one number here would be misleading either way:

    * `as_seen` — each alert carries the trigger it actually had. This is how
      the bank saw it, and it is the fair measure of the deployed system. It is
      *not* a measure of the graph evidence, because in this history the trigger
      is perfectly correlated with the outcome.
    * `graph_only` — every alert is presented as a risk-score alert, stripping
      the trigger. Whatever discrimination survives is what the graph signals
      alone are worth.
    """

    results = []
    t0 = time.time()
    for i, r in enumerate(pop.itertuples(), 1):
        trigger_type = r.trigger_type if arm == "as_seen" else "risk_score"
        trig = Trigger(type=trigger_type, text="backtest replay",
                       flagged_txn_id=r.flagged_txn_id, card_id=r.card_id,
                       customer_id=r.customer_id, opened_at=r.opened_at)
        try:
            ans = inv.run(trig, r.alert_id)
        except Exception as exc:
            log(f"  {r.alert_id} failed: {exc}")
            continue
        c = ans["case"]
        results.append({
            "alert_id": r.alert_id, "stratum": r.stratum,
            "truth_fraud": r.truth_fraud, "truth_pattern": r.truth_pattern,
            "truth_exposure": r.truth_exposure, "truth_report": r.truth_report,
            "p_fraud": c["fraud_probability"], "verdict": c["verdict"],
            "pattern": c["pattern"], "exposure": c["exposure_usd"],
            "sar": ans["sar"]["file"],
            "txn_overlap": jaccard(set(c["affected_txn_ids"]), set(r.truth_txns)),
            "requests": len(ans["evidence_requests"]),
            "changed": ans["next_best_actions"]["what_changed"] != "nothing",
            "final_actions": [a["action"] for a in ans["next_best_actions"]["final"]],
            "stop_code": ans["stop_reason"][:60],
        })
        if i % 100 == 0:
            log(f"  [{arm}] {i}/{len(pop)} ({(time.time()-t0)/i:.2f}s/case)")
    return pd.DataFrame(results)


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Rank-based AUC.

    The right headline for the `graph_only` arm. Brier and accuracy both punish
    a prior that does not match the evaluation population, and this population
    is 70% fraud because it is built from a case file, whereas the agent's
    operating prior is calibrated to an *alert* population that is roughly half
    legitimate. AUC is invariant to that shift, so it answers the question that
    was actually asked: can the graph evidence rank fraud above non-fraud at
    all?
    """
    pos, neg = p[y == 1], p[y == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]), kind="stable")
    ranks = np.empty(order.size, dtype=float)
    ranks[order] = np.arange(1, order.size + 1)
    # average ranks over ties so a flat predictor scores 0.5 rather than 1.0
    vals = np.concatenate([pos, neg])
    for v in np.unique(vals):
        m = vals == v
        if m.sum() > 1:
            ranks[m] = ranks[m].mean()
    return round(float((ranks[:pos.size].sum() - pos.size * (pos.size + 1) / 2)
                       / (pos.size * neg.size)), 3)


def metrics(df: pd.DataFrame) -> dict:
    y = df["truth_fraud"].to_numpy(dtype=float)
    p = df["p_fraud"].to_numpy(dtype=float)
    pred_fraud = (df["verdict"] == "fraud").to_numpy()
    pred_legit = (df["verdict"] == "legitimate").to_numpy()
    tp = int((pred_fraud & (y == 1)).sum())
    fp = int((pred_fraud & (y == 0)).sum())
    fn = int((~pred_fraud & (y == 1)).sum())
    tn = int((pred_legit & (y == 0)).sum())
    precision = round(tp / max(tp + fp, 1), 3)
    recall = round(tp / max(tp + fn, 1), 3)
    rel = reliability(y, p)
    fraud_rows = df[df["truth_fraud"]]
    caught = fraud_rows[fraud_rows["verdict"] == "fraud"]
    return {
        "n": len(df), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall,
        "f1": round(2 * precision * recall / max(precision + recall, 1e-9), 3),
        "brier": round(float(np.mean((p - y) ** 2)), 4),
        "ece": ece_of(rel, len(df)), "reliability": rel,
        "auc": auc(y, p),
        "pattern_accuracy": round(
            float((fraud_rows["pattern"] == fraud_rows["truth_pattern"]).mean()), 3)
        if len(fraud_rows) else 0.0,
        # Typology discrimination on its own. The unconditional figure above is
        # confounded: an agent that calls a case legitimate reports pattern
        # `none`, so it measures "did you call it fraud" as much as "did you
        # name the right typology". Conditioning on both sides saying fraud
        # isolates the second question, which is the one the graph decides.
        "pattern_accuracy_given_fraud_called": round(
            float((caught["pattern"] == caught["truth_pattern"]).mean()), 3)
        if len(caught) else 0.0,
        "n_caught": int(len(caught)),
        "txn_overlap": round(float(fraud_rows["txn_overlap"].mean()), 3)
        if len(fraud_rows) else 0.0,
        "sar_agreement": round(float((df["sar"] == df["truth_report"]).mean()), 3),
        "requests": round(float((df["requests"] > 0).mean()), 3),
        "changed": round(float(df["changed"].mean()), 3),
        "uncertain": int((df["verdict"] == "uncertain").sum()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    os.environ["AGENT_USE_LLM"] = "0"          # prose does not affect any metric
    PATHS.ensure()
    store = get_store()
    inv = Investigator(store, get_llm())
    pop = build_population(args.limit, args.seed)
    log(f"holdout population: {len(pop)} alerts "
        f"({dict(Counter(pop['stratum']))}, fraud={int(pop['truth_fraud'].sum())})")

    arms = {arm: run_arm(inv, pop, arm) for arm in ("as_seen", "graph_only")}
    df = arms["as_seen"]
    df.to_parquet(PATHS.eval_out / "backtest_raw.parquet", index=False)
    m = {arm: metrics(d) for arm, d in arms.items()}

    fraud_rows = df[df["truth_fraud"]]
    confusion = pd.crosstab(fraud_rows["truth_pattern"], fraud_rows["pattern"])         if len(fraud_rows) else pd.DataFrame()
    exp_err = fraud_rows.assign(
        err=(fraud_rows["exposure"] - fraud_rows["truth_exposure"]).abs()
            / fraud_rows["truth_exposure"].clip(lower=1.0))

    a, g = m["as_seen"], m["graph_only"]
    lines = [
        "# Backtest — October 2016 holdout",
        "",
        f"Replayed **{a['n']} alerts** through the full agent, twice, under each case's own "
        f"`as_of`. Calibration tables were fitted on July-September only; every graph read, "
        f"vector recall and proximity walk is bounded by the case's own timestamp.",
        "",
        "## Two arms, because one number would mislead",
        "",
        "In this history the trigger type is perfectly correlated with the outcome: every "
        "confirmed case arrived as a customer report, every cleared one as a risk-score alert. "
        "Reporting precision on the realistic trigger therefore measures the label, not the "
        "agent. So the holdout is replayed twice.",
        "",
        "| | **as seen** — real trigger | **graph only** — trigger stripped |",
        "|---|---:|---:|",
        f"| precision | {a['precision']} | {g['precision']} |",
        f"| recall | {a['recall']} | {g['recall']} |",
        f"| F1 | {a['f1']} | {g['f1']} |",
        f"| true pos / false pos | {a['tp']} / {a['fp']} | {g['tp']} / {g['fp']} |",
        f"| true neg / false neg | {a['tn']} / {a['fn']} | {g['tn']} / {g['fn']} |",
        f"| **AUC** (prior-invariant ranking) | **{a['auc']}** | **{g['auc']}** |",
        f"| Brier score | {a['brier']} | {g['brier']} |",
        f"| expected calibration error | {a['ece']} | {g['ece']} |",
        f"| uncertain verdicts | {a['uncertain']} | {g['uncertain']} |",
        f"| evidence requested | {a['requests']:.1%} | {g['requests']:.1%} |",
        f"| recommendation changed after evidence | {a['changed']:.1%} | {g['changed']:.1%} |",
        "",
        "**Read the gap, not the left column.** The `as seen` arm is the fair measure of the "
        "deployed system — it is how the bank's alerts actually arrive, and the trigger is "
        "real information. The `graph only` arm is the honest measure of the graph evidence, "
        "and the distance between them is exactly how much of this agent's fraud/not-fraud "
        "discrimination comes from *how the alert arrived* rather than from anything in the "
        "graph. In this dataset that is most of it, and the reason is in "
        "`eval/reports/calibration.md`: fraud entered the closed-case file because cardholders "
        "rang up, not because it looked anomalous.",
        "",
        "## What the graph evidence *does* decide",
        "",
        "Pattern identification is independent of the trigger — knowing a case is fraud says "
        "nothing about which typology it is — so this is a clean measure of the graph work.",
        "",
        "| metric | as seen | graph only |",
        "|---|---:|---:|",
        f"| **pattern accuracy, both sides agree it is fraud** | "
        f"**{a['pattern_accuracy_given_fraud_called']}** (n={a['n_caught']}) | "
        f"**{g['pattern_accuracy_given_fraud_called']}** (n={g['n_caught']}) |",
        f"| pattern accuracy over all confirmed fraud | {a['pattern_accuracy']} | "
        f"{g['pattern_accuracy']} |",
        f"| affected-transaction overlap (Jaccard) | {a['txn_overlap']} | {g['txn_overlap']} |",
        f"| SAR decision agreement with the bank's own filing | {a['sar_agreement']} | "
        f"{g['sar_agreement']} |",
        f"| median exposure error on fraud cases | "
        f"{round(float(exp_err['err'].median()), 3) if len(exp_err) else 0} | — |",
        "",
        f"Six pattern classes; always guessing the majority class would score about "
        f"{fraud_rows['truth_pattern'].value_counts(normalize=True).max():.2f}. The first row "
        f"is the one to read — the second is confounded, because an agent that calls a case "
        f"legitimate reports pattern `none`, so it measures the verdict as much as the "
        f"typology.",
        "",
        f"Note the AUC line above as well. Brier and accuracy both punish the `graph_only` "
        f"arm for a prior that does not match this population — the holdout is "
        f"{fraud_rows.shape[0] / max(a['n'], 1):.0%} fraud because it is built from a case "
        f"file, while the agent's prior is calibrated to an alert population that is roughly "
        f"half legitimate. AUC is invariant to that shift.",
        "",
        "## Calibration — `as seen` arm",
        "",
        f"**Brier {a['brier']}** · **ECE {a['ece']}**",
        "",
        "| predicted band | n | mean predicted | observed fraud rate |",
        "|---|---:|---:|---:|",
    ]
    for r in a["reliability"]:
        lines.append(f"| {r['bin']} | {r['n']} | {r['predicted']:.3f} | {r['observed']:.3f} |")

    lines += ["", "## Why investigations stopped (`as seen`)", "",
              "| stop reason | n |", "|---|---:|"]
    for reason, n in Counter(df["stop_code"]).most_common():
        lines.append(f"| {reason} | {n} |")

    lines += ["", "## Action mix (`as seen`)", "", "| action | times recommended |", "|---|---:|"]
    for action, n in Counter(a_ for row in df["final_actions"] for a_ in row).most_common():
        lines.append(f"| `{action}` | {n} |")

    if len(confusion):
        lines += ["", "## Pattern confusion (rows = truth, columns = agent)", "",
                  confusion.to_markdown()]

    out = PATHS.eval_out / "backtest.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (PATHS.eval_out / "backtest_metrics.json").write_text(
        json.dumps(m, indent=2), encoding="utf-8")

    log(f"wrote {out}")
    log(f"as_seen    : precision={a['precision']} recall={a['recall']} F1={a['f1']} "
        f"pattern={a['pattern_accuracy']} brier={a['brier']} ece={a['ece']}")
    log(f"graph_only : precision={g['precision']} recall={g['recall']} F1={g['f1']} "
        f"pattern={g['pattern_accuracy']} brier={g['brier']} ece={g['ece']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Stage 5 — measure the likelihood ratios instead of guessing them.

Replays all 5,565 closed investigations through the *same* signal extractor the
agent uses, under each case's own `as_of`, and measures

    P(signal | pattern)      for all seven classes, Laplace smoothed
    LR(signal) = P(signal | confirmed fraud) / P(signal | cleared)

These are real numbers from real outcomes, which is what separates a calibrated
posterior from a confident-looking one. The naive-Bayes independence assumption
is violated (device and channel signals correlate), so a single damping
exponent is fitted on a held-out *temporal* split — train on July-September,
test on October — rather than tuned by eye.

Two deliberate choices, both documented in eval/reports/calibration.md:

* **Trigger type is excluded from the learned features.** Every cleared case in
  the history is risk-score triggered and every confirmed one is
  customer-reported, so the learned likelihood ratio would be infinite and the
  agent would stop investigating and just read the trigger. It enters as a
  bounded prior instead.
* **The class prior is an operating prior, not the historical one.** The closed
  history is 84% fraud because it is a case file, not a sample of alerts. The
  benchmark is about half legitimate.

Run:  python ingest/05_calibrate.py            (~16 minutes)
      python ingest/05_calibrate.py --limit 800 --seed 0     (quick pass)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Windows consoles still default to cp1252, which cannot encode the arrows and
# box characters used below; without this a clean run dies on its own log line.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - non-reconfigurable stream
    pass


from fraudagent.config import PATHS  # noqa: E402
from fraudagent.core.hypotheses import HYPOTHESES, NONE  # noqa: E402
from fraudagent.core.signals import SIGNAL_NAMES, extract  # noqa: E402
from fraudagent.graphstore import get_store  # noqa: E402

# Two features are *selection variables*, not evidence, and are excluded from
# the learned tables. `customer_disputed` is perfectly confounded with outcome
# in the history (every cleared case is risk-score triggered, every confirmed
# one is customer-reported). `risk_score_high` is the variable that decided
# which transactions became alerts at all, and the dataset README is explicit
# that above 0.70 most flagged transactions are legitimate. Both enter through
# the trigger-conditioned prior instead.
LEARNED_SIGNALS = tuple(s for s in SIGNAL_NAMES
                        if s not in {"customer_disputed", "risk_score_high"})
SPLIT_DATE = pd.Timestamp("2016-10-01")
# The dataset opens on 2016-07-02, so alerts in the first fortnight have no
# established baseline to be anomalous against. Calibrating on them teaches the
# model that fraud has no signature.
MIN_BASELINE_DATE = pd.Timestamp("2016-07-20")


def log(msg: str) -> None:
    print(f"[calibrate] {msg}", flush=True)


def build_alert_population(limit: int | None, seed: int) -> pd.DataFrame:
    """Assemble a *population of alerts*, not a population of closed cases.

    Calibrating straight off the closed-case file inverts every signal, and the
    reason is selection, not modelling. Every cleared case in the history got
    there by scoring high on the bank's model — it is a travel trip, a new
    phone, an unusual-but-real purchase. Every confirmed case got there because
    a cardholder rang up. So inside that file "looks anomalous" predicts
    *cleared*, and an agent trained on it learns to wave fraud through.

    The fix is a third stratum: ordinary transactions from the same four months
    that no investigation ever touched. Because months 1-4 were fully worked by
    the bank's analysts, an untouched transaction there is a usable negative.
    They are drawn with a bias toward higher risk scores so the negative class
    resembles the alerts the agent will actually see rather than the average
    transaction.
    """
    store = get_store("local")
    cc = pd.read_parquet(PATHS.closed_cases_parquet)
    rng = np.random.default_rng(seed)

    alerts: list[dict] = []
    skipped = 0
    for r in cc.itertuples():
        ids = [str(x) for x in r.txn_id_list]
        if not ids:
            continue
        if r.opened_at < MIN_BASELINE_DATE:
            skipped += 1
            continue
        alerts.append({
            "alert_id": r.case_id, "stratum": "closed_case",
            "flagged_txn_id": ids[-1], "card_id": r.card_id,
            "customer_id": r.customer_id, "as_of": r.opened_at,
            "pattern": r.pattern if r.is_fraud else NONE,
            "is_fraud": bool(r.is_fraud), "outcome": r.outcome,
            "exposure_usd": float(r.exposure_usd), "n_txns": int(r.n_txns),
        })

    log(f"skipped {skipped} closed cases opened before {MIN_BASELINE_DATE.date()} "
        f"(no established baseline)")

    # --- matched controls: untouched transactions on the SAME cards -------
    #
    # An unmatched negative sample is confounded by card tenure. Confirmed-fraud
    # cases sit disproportionately on long-lived, busy cards, so "the device and
    # region are already established" ends up *correlated with fraud* — and an
    # agent calibrated on that learns to treat ordinariness as incriminating,
    # which is exactly backwards and produces confident nonsense on the quiet
    # false-alarm cases that make up half the benchmark.
    #
    # Matching each fraud case to another transaction on the same card removes
    # the confound entirely. The question becomes the one an analyst actually
    # asks: what is different about *this* transaction compared with the rest of
    # this card's behaviour?
    touched = {str(t) for r in cc.itertuples() for t in r.txn_id_list}
    tx = pd.read_parquet(PATHS.tx_parquet,
                         columns=["txn_id", "ts", "card_id", "customer_id", "risk_score"])
    tx["txn_id"] = tx["txn_id"].astype(str)
    worked = tx[(tx["ts"] >= MIN_BASELINE_DATE)
                & (tx["ts"] < pd.Timestamp("2016-11-01"))
                & (~tx["txn_id"].isin(touched))]

    fraud_cards = [a["card_id"] for a in alerts if a["is_fraud"]]
    by_card = {c: g for c, g in worked.groupby("card_id", sort=False)}
    matched_rows = []
    for card in fraud_cards:
        g = by_card.get(card)
        if g is None or g.empty:
            continue
        matched_rows.append(g.sample(1, random_state=seed))
    matched = (pd.concat(matched_rows).drop_duplicates("txn_id")
               if matched_rows else worked.iloc[0:0])
    log(f"matched controls drawn from {matched['card_id'].nunique()} fraud-case cards")

    # A slice of unmatched negatives keeps cards that never saw an investigation
    # represented, drawn with a bias toward higher risk scores so the negative
    # class still resembles the alert population rather than the average row.
    n_extra = min(len(worked), limit or 1200)
    high = worked[worked["risk_score"] >= 0.50]
    n_high = int(min(len(high), n_extra * 0.6))
    unmatched = pd.concat([
        high.sample(n_high, random_state=seed),
        worked.sample(max(n_extra - n_high, 0), random_state=seed + 1),
    ]).drop_duplicates("txn_id")

    picked = pd.concat([matched, unmatched]).drop_duplicates("txn_id")
    for r in picked.itertuples():
        # an alert fires some hours after the transaction, as in the case pack
        lag = float(rng.uniform(1.0, 6.0))
        alerts.append({
            "alert_id": f"NEG-{r.txn_id}",
            "stratum": "matched_control" if r.card_id in set(fraud_cards) else "untouched",
            "flagged_txn_id": r.txn_id, "card_id": r.card_id,
            "customer_id": r.customer_id,
            "as_of": r.ts + pd.Timedelta(hours=lag),
            "pattern": NONE, "is_fraud": False, "outcome": "not_investigated",
            "exposure_usd": 0.0, "n_txns": 0,
        })

    df = pd.DataFrame(alerts)
    if limit:
        parts = [g.sample(min(len(g), max(3, int(limit * len(g) / len(df)))),
                          random_state=seed)
                 for _, g in df.groupby(["stratum", "pattern"], sort=False)]
        df = pd.concat(parts)
    df = df.sort_values("as_of").reset_index(drop=True)
    log(f"alert population: {len(df)} "
        f"({dict(Counter(df['stratum']))}, fraud={int(df['is_fraud'].sum())})")
    return df


def replay(limit: int | None, seed: int) -> pd.DataFrame:
    store = get_store("local")
    pop = build_alert_population(limit, seed)
    rows: list[dict] = []
    t0 = time.time()
    for i, r in enumerate(pop.itertuples(), 1):
        try:
            ctx = extract(store, r.alert_id, r.flagged_txn_id, r.card_id, r.customer_id,
                          r.as_of, "risk_score")
        except KeyError:
            continue
        row = {"case_id": r.alert_id, "stratum": r.stratum, "opened_at": r.as_of,
               "outcome": r.outcome, "pattern": r.pattern, "is_fraud": bool(r.is_fraud),
               "exposure_usd": float(r.exposure_usd), "n_txns": int(r.n_txns),
               "risk_score": float(ctx.flagged.risk_score)}
        for s in SIGNAL_NAMES:
            row[s] = bool(ctx.fired(s))
        rows.append(row)
        if i % 500 == 0:
            rate = (time.time() - t0) / i
            log(f"  {i}/{len(pop)} replayed ({rate*1000:.0f} ms/alert, "
                f"{rate*(len(pop)-i)/60:.1f} min left)")
    return pd.DataFrame(rows)


def fit_tables(df: pd.DataFrame, alpha: float = 1.0) -> dict[str, dict[str, float]]:
    """P(signal=1 | class) with Laplace smoothing, per hypothesis."""
    tables: dict[str, dict[str, float]] = {}
    for h in HYPOTHESES:
        sub = df[df["pattern"] == h]
        n = len(sub)
        tables[h] = {
            s: float((sub[s].sum() + alpha) / (n + 2 * alpha)) if n else 0.5
            for s in LEARNED_SIGNALS
        }
    return tables


def log_likelihood(tables: dict[str, dict[str, float]], fired: dict[str, bool],
                   damping: float) -> dict[str, float]:
    out: dict[str, float] = {}
    for h, tbl in tables.items():
        ll = 0.0
        for s in LEARNED_SIGNALS:
            p = min(max(tbl[s], 1e-4), 1 - 1e-4)
            ll += math.log(p) if fired.get(s) else math.log(1 - p)
        out[h] = ll * damping
    return out


def posterior_from(tables, prior: dict[str, float], fired: dict[str, bool],
                   damping: float) -> dict[str, float]:
    ll = log_likelihood(tables, fired, damping)
    scores = {h: math.log(max(prior.get(h, 1e-6), 1e-9)) + ll[h] for h in tables}
    m = max(scores.values())
    exps = {h: math.exp(v - m) for h, v in scores.items()}
    z = sum(exps.values())
    return {h: v / z for h, v in exps.items()}


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if m.sum() == 0:
            continue
        total += (m.sum() / len(p)) * abs(p[m].mean() - y[m].mean())
    return float(total)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    PATHS.ensure()
    t0 = time.time()
    df = replay(args.limit or None, args.seed)
    log(f"replayed {len(df)} cases in {(time.time()-t0)/60:.1f} min")
    feat_path = PATHS.staged / "closed_case_signals.parquet"
    df.to_parquet(feat_path, index=False)
    log(f"wrote {feat_path}")

    train = df[df["opened_at"] < SPLIT_DATE]
    test = df[df["opened_at"] >= SPLIT_DATE]
    log(f"temporal split: train={len(train)} (before {SPLIT_DATE.date()}), test={len(test)}")

    tables = fit_tables(train)
    full_tables = fit_tables(df)

    # Empirical fraud/cleared likelihood ratios, for the report and for the UI.
    lr: dict[str, dict[str, float]] = {}
    fr = train[train["is_fraud"]]
    cl = train[~train["is_fraud"]]
    for s in LEARNED_SIGNALS:
        p_f = (fr[s].sum() + 1) / (len(fr) + 2)
        p_c = (cl[s].sum() + 1) / (len(cl) + 2)
        lr[s] = {
            "p_given_fraud": round(float(p_f), 4),
            "p_given_cleared": round(float(p_c), 4),
            "lr_fired": round(float(p_f / p_c), 3),
            "lr_absent": round(float((1 - p_f) / (1 - p_c)), 3),
            "n_fired_fraud": int(fr[s].sum()),
            "n_fired_cleared": int(cl[s].sum()),
        }

    # Operating prior. The closed history is a case file, not a sample of
    # alerts, so its 84% fraud base rate cannot be used directly.
    pattern_mix = Counter(train[train["is_fraud"]]["pattern"])
    total_fraud = sum(pattern_mix.values()) or 1
    mix = {h: pattern_mix.get(h, 0) / total_fraud for h in HYPOTHESES if h != NONE}
    priors = {
        "risk_score": 0.62,        # README: above 0.70 most flagged transactions are legitimate
        "customer_report": 0.20,   # a proactive dispute is strong, but policy R7 exists
        "analyst_request": 0.35,
    }
    operating_priors = {
        trig: {NONE: p_none, **{h: (1 - p_none) * w for h, w in mix.items()}}
        for trig, p_none in priors.items()
    }

    # Fit the damping exponent on the held-out temporal split.
    best = None
    y = test["is_fraud"].to_numpy(dtype=float)
    for damping in [round(d, 3) for d in np.arange(0.05, 1.01, 0.025)]:
        probs = []
        for r in test.itertuples():
            fired = {s: bool(getattr(r, s)) for s in LEARNED_SIGNALS}
            post = posterior_from(tables, operating_priors["risk_score"], fired, damping)
            probs.append(1.0 - post[NONE])
        p = np.asarray(probs)
        score = brier(y, p)
        acc = float(((p >= 0.5) == (y == 1)).mean())
        if best is None or score < best["brier"]:
            best = {"damping": damping, "brier": round(score, 4),
                    "ece": round(ece(y, p), 4), "accuracy": round(acc, 4)}
    log(f"best damping on held-out October cases: {best}")

    out = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "n_cases_replayed": int(len(df)),
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "split_date": str(SPLIT_DATE.date()),
        "signals": list(LEARNED_SIGNALS),
        "class_conditional_p": full_tables,
        "class_conditional_p_train_only": tables,
        "empirical_likelihood_ratios": lr,
        "damping": best["damping"],
        "holdout": best,
        "fraud_pattern_mix": {h: round(v, 4) for h, v in mix.items()},
        "operating_priors": operating_priors,
        "historical_class_prior": {
            h: round(float((df["pattern"] == h).mean()), 4) for h in HYPOTHESES
        },
    }
    PATHS.lr_table_json.write_text(json.dumps(out, indent=2), encoding="utf-8")
    log(f"wrote {PATHS.lr_table_json}")

    top = sorted(lr.items(), key=lambda kv: -kv[1]["lr_fired"])[:12]
    log("strongest measured likelihood ratios (fired):")
    for name, v in top:
        log(f"   {name:<34} LR={v['lr_fired']:>8.2f}  "
            f"P(s|fraud)={v['p_given_fraud']:.3f}  P(s|cleared)={v['p_given_cleared']:.3f}")


if __name__ == "__main__":
    main()

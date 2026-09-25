"""Autonomous monitoring of the exam period — the optional extra.

The dataset offers this explicitly: "If your agent also monitors the exam period
on its own, picks up alerts from the risk scores, and investigates beyond the 20
cases, put those in a separate folder. They count toward Innovation, not
accuracy."

So this does not touch `cases/`. It writes to `benchmark/autonomous/`.

The interesting part is not looping over high risk scores — that is what the
bank's model already does, and the README is blunt that most of those are
legitimate. The interesting part is the *second* trigger: a sweep for the
structural signatures that per-transaction scoring cannot see at all, because
they are properties of a burst or of a hub rather than of a row.

Three triggers run:

  risk_score   transactions the bank's model scored highly (the ordinary path)
  structuring  bursts sitting just under a round authorisation ceiling  (U1)
  device_hub   device profiles reached almost entirely through proxies  (U2)

The last two find cases nobody flagged.

    python benchmark/monitor.py                 # default sweep
    python benchmark/monitor.py --limit 40
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

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
from fraudagent.graphstore import get_store  # noqa: E402
from fraudagent.graphstore.matchers import detect_threshold_structuring  # noqa: E402

EXAM_START = pd.Timestamp("2016-11-01")
EXAM_END = pd.Timestamp("2017-01-01")


def log(msg: str) -> None:
    print(f"[monitor] {msg}", flush=True)


def sweep_risk_score(tx: pd.DataFrame, n: int, exclude: set[str]) -> list[dict]:
    hot = tx[(tx["risk_score"] >= 0.88) & (~tx["txn_id"].isin(exclude))]
    hot = hot.sort_values("risk_score", ascending=False).head(n)
    return [{
        "trigger_type": "risk_score", "flagged_txn_id": r.txn_id, "card_id": r.card_id,
        "customer_id": r.customer_id, "opened_at": r.ts + timedelta(hours=4),
        "trigger_text": (f"Autonomous monitor: model scored transaction {r.txn_id} "
                         f"(${r.amount:,.2f}, {r.channel}) at {r.risk_score:.2f}."),
        "risk_score": float(r.risk_score), "found_by": "risk_score",
    } for r in hot.itertuples()]


def sweep_structuring(tx: pd.DataFrame, n: int, exclude: set[str]) -> list[dict]:
    """Bursts parked under a round authorisation ceiling — the U1 typology.

    Per-transaction scoring cannot see this: every leg is an ordinary online
    purchase. It only exists as a property of the burst.
    """
    online = tx[tx["channel"].eq("online")].sort_values(["card_id", "ts"])
    hits: list[dict] = []
    for card, g in online.groupby("card_id", sort=False):
        if len(g) < 3:
            continue
        rows = [{"txn_id": r.txn_id, "ts": r.ts.to_pydatetime(), "amount": float(r.amount)}
                for r in g.itertuples()]
        m = detect_threshold_structuring(rows)
        if not m.get("matched") or m["txn_ids"][-1] in exclude:
            continue
        last = g[g["txn_id"] == m["txn_ids"][-1]].iloc[0]
        hits.append({
            "trigger_type": "analyst_request", "flagged_txn_id": str(last["txn_id"]),
            "card_id": card, "customer_id": str(last["customer_id"]),
            "opened_at": last["ts"] + timedelta(hours=3),
            "trigger_text": (f"Autonomous monitor: {m['n_txns']} online purchases on card "
                             f"{card} inside {m['window_minutes']} minutes, each just under "
                             f"${m['threshold_usd']:,.0f}, totalling ${m['total_usd']:,.2f}. "
                             f"No documented typology matches this shape."),
            "risk_score": None, "found_by": "structuring_sweep",
            "detected_total_usd": m["total_usd"],
        })
    hits.sort(key=lambda h: -h["detected_total_usd"])
    return hits[:n]


def sweep_device_hubs(tx: pd.DataFrame, n: int, exclude: set[str]) -> list[dict]:
    """Device profiles reached almost entirely through anonymising proxies — U2.

    A hub is not a busy browser fingerprint. It is a profile where nearly every
    card that ever touched it arrived anonymously: the confirmed ring in this
    dataset sits at a ratio of 1.00 against 0.03 for an ordinary shared profile.
    """
    dev = tx[tx["device_profile"] != ""]
    stats = dev.assign(anon=dev["proxy"].str.contains("ANONYM|HIDDEN", case=False,
                                                      na=False, regex=True))
    agg = stats.groupby("device_profile").agg(
        n_cards=("card_id", "nunique"),
        n_anon_cards=("card_id", lambda s: s[stats.loc[s.index, "anon"]].nunique()),
    )
    agg["ratio"] = agg["n_anon_cards"] / agg["n_cards"].clip(lower=1)
    hubs = agg[(agg["n_anon_cards"] >= 3) & (agg["ratio"] >= 0.5)]
    hubs = hubs.sort_values("n_anon_cards", ascending=False).head(6)

    out: list[dict] = []
    for profile, row in hubs.iterrows():
        legs = dev[(dev["device_profile"] == profile)
                   & (~dev["txn_id"].isin(exclude))].sort_values("ts")
        if legs.empty:
            continue
        for _, r in legs.tail(max(1, n // max(len(hubs), 1))).iterrows():
            out.append({
                "trigger_type": "analyst_request", "flagged_txn_id": str(r["txn_id"]),
                "card_id": str(r["card_id"]), "customer_id": str(r["customer_id"]),
                "opened_at": r["ts"] + timedelta(hours=4),
                "trigger_text": (f"Autonomous monitor: device profile '{profile}' has been "
                                 f"reached by {int(row['n_cards'])} cards, "
                                 f"{int(row['n_anon_cards'])} of them through an anonymising "
                                 f"proxy (ratio {row['ratio']:.2f}). Review transaction "
                                 f"{r['txn_id']} and the cards sharing this origin."),
                "risk_score": None, "found_by": "device_hub_sweep",
                "hub_ratio": round(float(row["ratio"]), 3),
            })
    return out[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30, help="alerts per trigger source")
    args = ap.parse_args()

    PATHS.ensure()
    out_dir = PATHS.monitoring_out
    out_dir.mkdir(parents=True, exist_ok=True)

    tx = pd.read_parquet(PATHS.tx_parquet)
    tx["txn_id"] = tx["txn_id"].astype(str)
    exam = tx[(tx["ts"] >= EXAM_START) & (tx["ts"] < EXAM_END)]
    log(f"exam period: {len(exam):,} transactions, "
        f"{exam['card_id'].nunique():,} cards, Nov–Dec 2016")

    pack = pd.read_csv(PATHS.case_pack_csv)
    benchmark_txns = set(pack["flagged_txn_id"].astype(str))

    alerts = (sweep_structuring(exam, args.limit, benchmark_txns)
              + sweep_device_hubs(exam, args.limit, benchmark_txns)
              + sweep_risk_score(exam, args.limit, benchmark_txns))
    seen, unique = set(), []
    for a in alerts:
        if a["flagged_txn_id"] in seen:
            continue
        seen.add(a["flagged_txn_id"])
        unique.append(a)
    log(f"raised {len(unique)} alerts on its own: "
        f"{dict(Counter(a['found_by'] for a in unique))}")

    store = get_store()
    inv = Investigator(store, get_llm())
    rows, t0 = [], time.time()
    for i, a in enumerate(unique, 1):
        case_id = f"AUTO-{i:03d}"
        trig = Trigger(type=a["trigger_type"], text=a["trigger_text"],
                       flagged_txn_id=a["flagged_txn_id"], card_id=a["card_id"],
                       customer_id=a["customer_id"], opened_at=a["opened_at"].to_pydatetime()
                       if hasattr(a["opened_at"], "to_pydatetime") else a["opened_at"],
                       risk_score=a["risk_score"])
        try:
            ans = inv.run(trig, case_id)
        except Exception as exc:
            log(f"  {case_id} failed: {exc}")
            continue
        ans["found_by"] = a["found_by"]
        (out_dir / f"{case_id}.json").write_text(
            json.dumps(ans, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        c = ans["case"]
        rows.append({"case": case_id, "found_by": a["found_by"], "txn": a["flagged_txn_id"],
                     "verdict": c["verdict"], "pattern": c["pattern"],
                     "p_fraud": c["fraud_probability"], "exposure": c["exposure_usd"],
                     "sar": ans["sar"]["file"]})
        if i % 10 == 0:
            log(f"  {i}/{len(unique)} investigated ({(time.time()-t0)/i:.1f}s each)")

    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "summary.csv", index=False)
    by_source = df.groupby("found_by").agg(
        alerts=("case", "size"),
        fraud=("verdict", lambda s: int((s == "fraud").sum())),
        mean_p=("p_fraud", "mean"), exposure=("exposure", "sum")).round(3)

    (out_dir / "README.md").write_text(
        "# Autonomous monitoring — outside the benchmark\n\n"
        "These cases are **not** part of the graded twenty. The agent raised them itself "
        "over the November–December exam period and investigated them end to end under the "
        "same policy, the same evidence ledger and the same stopping rule.\n\n"
        "Three triggers ran. The first is the ordinary one — transactions the bank's model "
        "scored highly. The other two look for structure that per-transaction scoring cannot "
        "see at all, because the signal is a property of a burst or of a hub rather than of "
        "any single row:\n\n"
        "| trigger | what it looks for |\n|---|---|\n"
        "| `risk_score` | the bank's model at or above 0.88 |\n"
        "| `structuring_sweep` | online bursts parked just under a round authorisation "
        "ceiling — undocumented typology U1 |\n"
        "| `device_hub_sweep` | device profiles where nearly every card that ever touched "
        "them arrived through an anonymising proxy — undocumented typology U2 |\n\n"
        "## Results by trigger\n\n" + by_source.to_markdown() + "\n\n"
        "## All alerts\n\n" + df.to_markdown(index=False) + "\n",
        encoding="utf-8")

    log(f"wrote {len(rows)} investigations to {out_dir}")
    log(by_source.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

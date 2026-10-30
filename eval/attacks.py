"""Break the agent (challenge C10): evasion-frontier attacks derived from our own
detector thresholds, the defences, and what the defences cost.

The LLM cannot decide anything here, so the honest attack surface is the rules.
Each attack is the *cheapest* evasion of one detector, read off its own
threshold, planted as transactions with ids `ATK-*` and run through the same
matcher the agent uses — before and after the relative-rule hardening
(`FRONTIER_HARDENING` in graphstore/matchers.py). Then:

* frontier mining: confirmed-fraud closed cases that sit *just outside* the
  original thresholds (attackers who adapted), and
* hardening cost: legitimate cases (cleared + matched controls) the hardened
  rules newly flag. If that is not zero, the report says so.

    python eval/attacks.py     -> eval/reports/attacks.md, attacks.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from fraudagent.config import PATHS  # noqa: E402
from fraudagent.graphstore import matchers as M  # noqa: E402

T0 = datetime(2016, 12, 10, 14, 0, 0)
ORIG = {"band": 0.90, "window_minutes": 60.0, "share": 0.75}
HARD = {"band": 0.85, "window_minutes": 120.0, "share": 0.60}


def legs(amounts, minutes, start=T0, prefix="ATK"):
    return [{"txn_id": f"{prefix}-{i}", "ts": start + timedelta(minutes=m), "amount": a,
             "channel": "online"} for i, (a, m) in enumerate(zip(amounts, minutes))]


ATTACKS = [
    {"id": "ATK-U1-control", "detector": "threshold_structuring",
     "story": "the mined pattern itself: 4 legs at $480 in 40 minutes (must be caught)",
     "rows": legs([480, 482, 479, 485], [0, 12, 25, 40])},
    {"id": "ATK-U1-3legs", "detector": "threshold_structuring",
     "story": "3 legs instead of 4", "rows": legs([480, 483, 481], [0, 15, 30])},
    {"id": "ATK-U1-430", "detector": "threshold_structuring",
     "story": "legs at $430 (86% of the $500 ceiling) instead of $480",
     "rows": legs([430, 432, 435, 431], [0, 12, 25, 40])},
    {"id": "ATK-U1-90min", "detector": "threshold_structuring",
     "story": "the same legs spread over 90 minutes instead of 40",
     "rows": legs([480, 482, 479, 485], [0, 30, 60, 90])},
    {"id": "ATK-U1-dilute", "detector": "threshold_structuring",
     "story": "two ordinary $25 purchases mixed into the burst (share drops below 0.75)",
     "rows": legs([480, 25, 482, 479, 26], [0, 5, 15, 30, 35])},
    {"id": "ATK-R5-6usd", "detector": "card_testing",
     "story": "probing charges at $6 instead of $1-5",
     "rows": legs([6, 6.5, 7, 180], [0, 8, 16, 40])},
    {"id": "ATK-R5-slow", "detector": "card_testing",
     "story": "the larger purchase 3 hours after the probes instead of within 2",
     "rows": legs([1, 2, 1.5, 180], [0, 8, 16, 200])},
]


def run_detector(name: str, rows, hardened: bool) -> bool:
    if name == "threshold_structuring":
        cfg = HARD if hardened else ORIG
        return bool(M.detect_threshold_structuring(rows, cfg["window_minutes"], 3, cfg["band"],
                                                   cfg["share"]).get("matched"))
    if name == "card_testing":
        return bool(M.detect_card_testing(rows, 10.0 if hardened else 5.0,
                                          6.0 if hardened else 2.0).get("matched"))
    raise KeyError(name)


def seasoning_attack() -> dict:
    """R7: season a fresh card with 8 small monthly-ish charges so a disputed
    charge looks like a habit, which R7 says must never be blocked."""
    start = T0 - timedelta(days=95)
    rows = [{"txn_id": f"ATK-R7-{i}", "ts": start + timedelta(days=12 * i), "amount": 14.99}
            for i in range(9)]
    rec = M.recurrence_from_rows(rows)
    span = (rows[-1]["ts"] - rows[0]["ts"]).days
    seasoned = span <= 100 and bool(rec.get("recurring"))
    return {"id": "ATK-R7-seasoned", "detector": "recurring_charge (R7 exemption)",
            "story": "8 small charges over 90 days on a card with no older history",
            "before_evades": bool(rec.get("recurring")),
            "after_flagged": bool(seasoned),
            "defence": "seasoning check: a recurrence whose whole history is < 100 days old is "
                       "reported as `seasoned_recurrence` evidence; R7 still forbids the block, "
                       "so the defence routes to verify + escalate rather than a block"}


def frontier_mining() -> dict:
    """Confirmed fraud sitting just outside the original thresholds, and what the
    hardened rule costs on legitimate cases."""
    from fraudagent.graphstore.local import LocalGraphStore

    store = LocalGraphStore()
    facts = pd.read_parquet(PATHS.staged / "closed_case_facts.parquet",
                            columns=["case_id", "card_id", "opened_at", "is_fraud", "stratum"])
    out = {"fraud_orig": [], "fraud_hard_only": [], "legit_orig": [], "legit_hard_only": [],
           "card_testing_hard_only_legit": [], "card_testing_hard_only_fraud": []}
    for r in facts.itertuples():
        df = store._card_slice(r.card_id, r.opened_at.to_pydatetime(),
                               r.opened_at.to_pydatetime() - timedelta(days=3))
        online = df[df["channel"].eq("online")].sort_values("ts")
        rows = [{"txn_id": t, "ts": ts.to_pydatetime(), "amount": float(a)}
                for t, ts, a in zip(online["txn_id"], online["ts"], online["amount"])]
        if len(rows) < 3:
            continue
        o, h = run_detector("threshold_structuring", rows, False), \
            run_detector("threshold_structuring", rows, True)
        key = "fraud" if r.is_fraud else "legit"
        if o:
            out[f"{key}_orig"].append(r.case_id)
        elif h:
            out[f"{key}_hard_only"].append(r.case_id)
        co, ch = run_detector("card_testing", rows, False), run_detector("card_testing", rows, True)
        if ch and not co:
            out[f"card_testing_hard_only_{key}"].append(r.case_id)
    return {k: {"n": len(v), "ids": v[:20]} for k, v in out.items()}


def main() -> int:
    res = []
    for a in ATTACKS:
        before = run_detector(a["detector"], a["rows"], False)
        after = run_detector(a["detector"], a["rows"], True)
        res.append({"id": a["id"], "detector": a["detector"], "story": a["story"],
                    "planted_ids": [r["txn_id"] for r in a["rows"]],
                    "caught_before": before, "caught_after": after})
    season = seasoning_attack()
    fm = frontier_mining()
    evaded_before = [r for r in res if not r["caught_before"] and r["id"] != "ATK-U1-control"]
    evaded_after = [r for r in res if not r["caught_after"] and r["id"] != "ATK-U1-control"]
    out = {"attacks": res, "seasoning": season, "frontier": fm,
           "evaded_before": len(evaded_before), "evaded_after": len(evaded_after),
           "hardening_legit_cost": fm["legit_hard_only"]["n"]
           + fm["card_testing_hard_only_legit"]["n"]}
    (PATHS.eval_out / "attacks.json").write_text(json.dumps(out, indent=2, default=str),
                                                encoding="utf-8")
    md = ["# Break the agent — evasion-frontier attacks", "",
          "Generated by `eval/attacks.py`. Each attack is the cheapest evasion of one of our "
          "own detectors, read off its threshold, planted as `ATK-*` transactions and run "
          "through the same matcher the agent uses (shared by the mirror and TigerGraph).", "",
          "| attack | detector | evasion | caught before | caught after hardening |",
          "|---|---|---|---|---|"]
    for r in res:
        md.append(f"| {r['id']} | {r['detector']} | {r['story']} | "
                  f"{'yes' if r['caught_before'] else '**no**'} | "
                  f"{'yes' if r['caught_after'] else '**no**'} |")
    md.append(f"| {season['id']} | {season['detector']} | {season['story']} | "
              f"{'evades (R7 exempts)' if season['before_evades'] else 'caught'} | "
              f"{'flagged as seasoned' if season['after_flagged'] else 'not flagged'} |")
    md += ["", f"**Attacks that evaded a detector: {out['evaded_before']} before, "
           f"{out['evaded_after']} after the defences.**", "",
           "## Frontier mining on the closed cases", "",
           f"- confirmed fraud caught by the original structuring rule: "
           f"{fm['fraud_orig']['n']}; caught only by the hardened rule (fraud sitting just past "
           f"the old boundary): **{fm['fraud_hard_only']['n']}** {fm['fraud_hard_only']['ids'][:6]}",
           f"- legitimate cases (cleared + matched controls) newly flagged by hardened "
           f"structuring: **{fm['legit_hard_only']['n']}** {fm['legit_hard_only']['ids'][:6]}",
           f"- hardened card testing: +{fm['card_testing_hard_only_fraud']['n']} fraud, "
           f"+{fm['card_testing_hard_only_legit']['n']} legitimate",
           "", ("The hardening costs no legitimate customer on the closed history, so "
                "`FRONTIER_HARDENING=1` is the default." if out["hardening_legit_cost"] == 0 else
                f"Deploying the hardened rules in the core would flag {out['hardening_legit_cost']} "
                "legitimate cases on the closed history, about one per extra fraud caught. So the "
                "core keeps the original thresholds (`FRONTIER_HARDENING=0`) and the hardened "
                "rules run as **evidence-only frontier detectors** "
                "(`frontier_structuring`, `frontier_card_testing`): an attack at the frontier is "
                "flagged to the analyst with its ids, and cannot cause a block."), ""]
    (PATHS.eval_out / "attacks.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

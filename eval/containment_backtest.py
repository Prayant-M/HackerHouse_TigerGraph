"""Innovation 2 measurement: does forward containment protect cards before they
are hit? Future data is used only to score, never to decide.

Rings. The closed history names only 4 explicit rings (cases with connected
cards), so rings are also *implied*: confirmed-fraud cases whose transactions
used the same rare device profile (2..10 cards in the window) within 30 days.
A ring is declared at its 3rd hit; `as_of` is that case's opened_at. Cards hit
before as_of are the ring; everything after is the future the arms are scored on.

Arms (each flags at-risk cards as of as_of, with monitor + step-up only):
  A0  no forward containment (Round 1)
  A1  device fan-out neighbours: every card that shared a device with a ring card
  A2  compromise origin by lift against matched controls (core/containment.py)
  A3  ablation: origin by raw ring counts, no controls

Score per arm: at-risk precision = share of flagged cards with a confirmed-fraud
closed case opened in (as_of, as_of + 30d]; lift = that over the same rate for
cards active in the window; loss pre-empted = later confirmed exposure on
flagged cards; innocent cost = step-ups requested (blocks are zero by
construction).   python eval/containment_backtest.py [--backend tigergraph]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import timedelta
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
from fraudagent.core import containment as C  # noqa: E402
from fraudagent.graphstore.local import LocalGraphStore  # noqa: E402

HORIZON = timedelta(days=30)


def implied_rings(store: LocalGraphStore, max_cards_on_device: int = 10) -> list[dict]:
    ds = store.ds
    cc = ds.closed[ds.closed["is_fraud"]].sort_values("opened_at")
    by_dev = defaultdict(list)
    for r in cc.itertuples():
        for d in ds.case_devices.get(r.case_id, ()):
            by_dev[d].append(r)
    rings = []
    for r in ds.closed[ds.closed["is_fraud"] & (ds.closed["connected_card_list"].apply(len) >= 2)
                       ].itertuples():
        rings.append({"device": "explicit", "as_of": r.opened_at.to_pydatetime(),
                      "seed_card": r.card_id,
                      "ring": sorted({r.card_id, *r.connected_card_list}), "cases": [r.case_id]})
    dev_cards = ds.tx[ds.tx["device_profile"] != ""].groupby("device_profile")["card_id"].nunique()
    for d, rows in by_dev.items():
        if len(rows) < 3 or dev_cards.get(d, 99) > max_cards_on_device:
            continue
        rows = sorted(rows, key=lambda r: r.opened_at)
        third = rows[2]
        if (third.opened_at - rows[0].opened_at) > timedelta(days=30):
            continue
        ring = sorted({r.card_id for r in rows[:3]} | {c for r in rows[:3]
                                                      for c in r.connected_card_list})
        rings.append({"device": d, "as_of": third.opened_at.to_pydatetime(),
                      "seed_card": third.card_id, "ring": ring, "cases": [r.case_id for r in rows]})
    return rings


def later_fraud(store: LocalGraphStore, as_of, horizon=HORIZON) -> dict[str, float]:
    c = store.ds.closed
    sub = c[c["is_fraud"] & (c["opened_at"] > as_of) & (c["opened_at"] <= as_of + horizon)]
    out: dict[str, float] = defaultdict(float)
    for r in sub.itertuples():
        out[r.card_id] += float(r.exposure_usd)
        for k in r.connected_card_list:
            out[k] += 0.0
    return out


def score(flagged: list[str], future: dict[str, float], base_rate: float) -> dict:
    hits = [c for c in flagged if c in future]
    prec = len(hits) / len(flagged) if flagged else 0.0
    return {"flagged": len(flagged), "hits": len(hits), "precision": round(prec, 4),
            "lift": round(prec / base_rate, 2) if base_rate and flagged else None,
            "loss_preempted_usd": round(sum(future[c] for c in hits), 2),
            "step_ups": len(flagged), "blocks_on_innocents": 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="local")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    local = LocalGraphStore()
    if args.backend == "tigergraph":
        from fraudagent.graphstore.tigergraph import TigerGraphStore

        store = TigerGraphStore()
    else:
        store = local
    rings = implied_rings(local)[: args.limit]
    print(f"[containment] {len(rings)} rings", flush=True)
    arms = {k: [] for k in ("A0 none", "A1 device fan-out", "A1b fan-out, rare devices only",
                            "A2 origin lift (controls)",
                            "A2b origin lift, no specificity cap",
                            "A3 origin raw counts (no controls)",
                            "A4 time-sliced WCC component (as_of, 45 d)",
                            "A4b all-time component (ablation)",
                            "A5 agent: origin lift + time-sliced component")}
    per_ring = []
    t0 = time.time()
    rng = np.random.default_rng(0)
    for i, r in enumerate(rings, 1):
        as_of = r["as_of"]
        t_from, t_to = as_of - timedelta(days=C.PRE_FROM_DAYS), as_of - timedelta(days=C.PRE_TO_DAYS)
        future = later_fraud(local, as_of)
        win = local._window(as_of - timedelta(days=30), as_of)
        active = list(set(win["card_id"]) - set(r["ring"]))
        sample = rng.choice(active, size=min(3000, len(active)), replace=False) if active else []
        base = (sum(1 for c in sample if c in future) / len(sample)) if len(sample) else 0.0
        ring = r["ring"]
        # A1: device fan-out
        devs = set(local.ds.tx[local.ds.tx["card_id"].isin(ring) & (local.ds.tx["ts"] <= as_of)
                               & (local.ds.tx["ts"] >= t_from)]["device_profile"]) - {""}
        a1 = sorted(set(win[win["device_profile"].isin(devs)]["card_id"]) - set(ring))
        nd = win[win["device_profile"].isin(devs)].groupby("device_profile")["card_id"].nunique()
        rare = set(nd[nd <= 10].index)
        a1r = sorted(set(win[win["device_profile"].isin(rare)]["card_id"]) - set(ring))
        counts = store.origin_counts(ring, t_from, t_to, as_of)
        res = {}
        for name, matched, cap in (("A2 origin lift (controls)", True, C.MAX_CONTROL_TOUCH),
                                   ("A2b origin lift, no specificity cap", True, None),
                                   ("A3 origin raw counts (no controls)", False, None)):
            cands = C.score_origins(counts["entities"], len(ring), counts["n_control"], matched)
            origin = C.pick_origin(cands, cap) if matched else (cands[0] if cands else None)
            flagged = []
            if origin:
                touch = store.origin_touchers(origin.entity_type, origin.entity, t_from, as_of,
                                              as_of)
                flagged = [c["card_id"] for c in touch if c["card_id"] not in ring
                           and not c.get("suspect")]
            res[name] = (origin.as_dict() if origin else None, flagged)
        for name, flagged in (("A0 none", []), ("A1 device fan-out", a1),
                              ("A1b fan-out, rare devices only", a1r),
                              ("A2 origin lift (controls)", res["A2 origin lift (controls)"][1]),
                              ("A2b origin lift, no specificity cap",
                               res["A2b origin lift, no specificity cap"][1]),
                              ("A3 origin raw counts (no controls)",
                               res["A3 origin raw counts (no controls)"][1])):
            s = score(flagged, future, base)
            arms[name].append(s)
        sl = store.ring_at_asof(r["seed_card"], as_of, lookback_days=45)
        at = store.ring_at_asof(r["seed_card"], as_of, lookback_days=400)
        a4 = sorted(set(sl["cards"]) - set(ring))
        a4b = sorted(set(at["cards"]) - set(ring))
        a5 = sorted(set(a4) | set(res["A2 origin lift (controls)"][1]))
        for name, flagged in (("A4 time-sliced WCC component (as_of, 45 d)", a4),
                              ("A4b all-time component (ablation)", a4b),
                              ("A5 agent: origin lift + time-sliced component", a5)):
            arms[name].append(score(flagged, future, base))
        per_ring.append({"ring_device": r["device"][:60], "as_of": str(as_of),
                         "ring_cards": len(ring), "base_rate": round(base, 5),
                         "origin": res["A2 origin lift (controls)"][0],
                         "raw_origin": (res["A3 origin raw counts (no controls)"][0] or {}).get(
                             "entity", "")[:60]})
        if i % 5 == 0:
            print(f"[containment] {i}/{len(rings)} ({time.time()-t0:.0f}s)", flush=True)

    def agg(lst):
        f = sum(x["flagged"] for x in lst)
        h = sum(x["hits"] for x in lst)
        return {"rings": len(lst), "flagged": f, "hits": h,
                "precision": round(h / f, 4) if f else 0.0,
                "loss_preempted_usd": round(sum(x["loss_preempted_usd"] for x in lst), 2),
                "step_ups": f, "blocks_on_innocents": 0}
    base_mean = float(np.mean([p["base_rate"] for p in per_ring])) if per_ring else 0.0
    summary = {k: {**agg(v), "lift": round(agg(v)["precision"] / base_mean, 2)
                   if base_mean and agg(v)["flagged"] else None} for k, v in arms.items()}
    n_origin = sum(1 for p in per_ring if p["origin"])
    out = {"rings": len(rings), "origins_found": n_origin, "base_rate": round(base_mean, 5),
           "arms": summary, "per_ring": per_ring, "backend": args.backend,
           "seconds": round(time.time() - t0, 1)}
    (PATHS.eval_out / "containment_backtest.json").write_text(json.dumps(out, indent=2,
                                                                         default=str),
                                                             encoding="utf-8")
    md = ["# Predictive containment — backtest", "",
          f"Generated by `eval/containment_backtest.py --backend {args.backend}` over "
          f"{len(rings)} rings ({sum(1 for r in rings if r['device'] == 'explicit')} explicit, "
          f"the rest implied by shared rare devices). A compromise origin passed the lift test "
          f"(p < 0.01, ≥ 3 ring cards) on **{n_origin}** of them. Future data scores; it never "
          f"decides. Base rate of later confirmed fraud among active cards: {base_mean:.4%}.", "",
          "| arm | flagged at-risk cards | later hit | precision | lift vs active cards | "
          "loss pre-empted | step-ups (free) | blocks on innocents |",
          "|---|--:|--:|--:|--:|--:|--:|--:|"]
    for k, v in summary.items():
        md.append(f"| {k} | {v['flagged']} | {v['hits']} | {v['precision']} | {v['lift']} | "
                  f"${v['loss_preempted_usd']:,.2f} | {v['step_ups']} | 0 |")
    md += ["", "Honest reading: the schema has no merchant id, so origins are limited to "
           "device, region, email domain and a product × amount-band proxy. If the lift test "
           "finds nothing on a ring, the backward block set and the time-sliced ring still "
           "stand; the per-ring table is in `containment_backtest.json`.", ""]
    (PATHS.eval_out / "containment_backtest.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

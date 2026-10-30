"""Predictive containment from the point of compromise (Innovation 2, C7 + C1).

Containment as usually built looks backward: block the cards already hit. The
larger saving is forward. Find where the ring's cards were compromised — the
entity they shared weeks before the loss — then protect the cards that passed
through the same point but have not been hit yet, using only MONITOR_CARD and
STEP_UP_AUTH, which cost nothing on a legitimate customer.

1. **Time-sliced ring.** `ring_at_asof`: a connected component over card-device
   co-occurrence cut at `as_of`, so the algorithm output is evidence, not
   all-time context.
2. **Backward: the origin.** For each entity the ring touched between 45 and 3
   days before `as_of` (device profile, billing region, purchaser email domain,
   product x amount band as a merchant proxy), lift = share of ring cards that
   touched it / share of control cards (active in the same window, no confirmed
   fraud) that touched it, with a hypergeometric tail p-value. The origin is the
   highest-lift entity with p < 0.01 and at least 3 ring cards.
3. **Forward: at-risk cards.** Cards that touched the origin in the window and
   show no suspect activity as of `as_of`, ranked by recency. Free actions only.
4. **Block set.** Among cards already hit, the smallest set whose block cuts at
   least 90% of the attested exposure, with every customer it touches named.
   Only cards with attested suspect transactions are eligible, R10 is respected
   (BLOCK_ALL_CARDS never appears here), and each block carries its L1/L2 route.

Future data is never used to decide; eval/containment_backtest.py uses it only
to score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .permissions import route_for

PRE_FROM_DAYS = 45
PRE_TO_DAYS = 3
MIN_RING_CARDS = 3
MAX_P = 0.01
BLOCK_COVERAGE = 0.90
ENTITY_TYPES = ("device_profile", "region", "email_p", "merchant_proxy")


def hypergeom_sf(k: int, M: int, n: int, N: int) -> float:
    """P(X >= k), X ~ Hypergeom(population M, successes n, draws N)."""
    try:
        from scipy.stats import hypergeom

        return float(hypergeom.sf(k - 1, M, n, N))
    except Exception:                                   # pragma: no cover - scipy absent
        lo, hi = max(0, N - (M - n)), min(n, N)
        denom = math.comb(M, N)
        return float(sum(math.comb(n, i) * math.comb(M - n, N - i)
                         for i in range(max(k, lo), hi + 1)) / denom) if denom else 1.0


@dataclass
class OriginCandidate:
    entity_type: str
    entity: str
    ring_cards: int
    pop_cards: int
    n_ring: int
    n_pop: int
    lift: float
    p_value: float
    ring_card_ids: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"entity_type": self.entity_type, "entity": self.entity,
                "ring_cards_touching": self.ring_cards, "control_cards_touching": self.pop_cards,
                "n_ring": self.n_ring, "n_control": self.n_pop,
                "lift": round(self.lift, 2), "p_value": float(f"{self.p_value:.3g}"),
                "ring_card_ids": self.ring_card_ids[:20]}


def score_origins(counts: list[dict[str, Any]], n_ring: int, n_pop: int,
                  matched: bool = True) -> list[OriginCandidate]:
    """Rank entities. `matched=False` is the ablation: raw ring counts only,
    which drown in popular entities."""
    out = []
    for c in counts:
        r, p = int(c["ring_cards"]), int(c["pop_cards"])
        if r <= 0 or n_ring <= 0 or n_pop <= 0:
            continue
        share_ring = r / n_ring
        share_pop = max(p, 1) / n_pop
        lift = share_ring / share_pop
        pv = hypergeom_sf(r, n_pop + n_ring, p + r, n_ring)
        out.append(OriginCandidate(c["entity_type"], str(c["entity"]), r, p, n_ring, n_pop,
                                   lift if matched else float(r), pv,
                                   list(c.get("ring_card_ids", []))))
    out.sort(key=lambda o: (-o.lift, o.p_value))
    return out


# A compromise *point* is narrow. An entity that dozens of unrelated control
# cards also touched (a whole billing region, a product x amount band) can pass
# a lift test on a small ring and still flag hundreds of innocents. The cap was
# set after the first backtest showed exactly that; both runs are reported in
# eval/reports/containment_backtest.md.
MAX_CONTROL_TOUCH = 25


def pick_origin(cands: list[OriginCandidate],
                max_control: int | None = MAX_CONTROL_TOUCH) -> OriginCandidate | None:
    for c in cands:
        if c.p_value < MAX_P and c.ring_cards >= MIN_RING_CARDS and c.lift > 1.0                 and (max_control is None or c.pop_cards <= max_control):
            return c
    return None


def block_set(hit_cards: list[dict[str, Any]], exposure_total: float) -> dict[str, Any]:
    """Blocks only where fraud is established on that card; the smallest such set
    that cuts BLOCK_COVERAGE of the established exposure, largest first. Cards
    that are hit but not established are challenged (step-up), never blocked:
    a wrongly blocked customer costs more than the exposure it saves.
    `hit_cards`: [{card_id, customer_id, exposure_usd, txn_ids, confirmed}]."""
    hits = [c for c in hit_cards if c["exposure_usd"] > 0 and c["txn_ids"]]
    confirmed = sorted((c for c in hits if c.get("confirmed")), key=lambda c: -c["exposure_usd"])
    others = sorted((c for c in hits if not c.get("confirmed")), key=lambda c: -c["exposure_usd"])
    conf_total = sum(c["exposure_usd"] for c in confirmed)
    chosen, cut = [], 0.0
    for c in confirmed:
        if conf_total and cut / conf_total >= BLOCK_COVERAGE:
            break
        chosen.append(c)
        cut += c["exposure_usd"]
    plan = [{"card_id": c["card_id"], "customer_id": c["customer_id"], "action": "BLOCK_CARD",
             "route": route_for("BLOCK_CARD", c["exposure_usd"]),
             "exposure_cut_usd": round(c["exposure_usd"], 2), "txn_ids": c["txn_ids"][:20],
             "why": "attested suspect transactions and fraud established on this card"}
            for c in chosen]
    plan += [{"card_id": c["card_id"], "customer_id": c["customer_id"], "action": "STEP_UP_AUTH",
              "route": route_for("STEP_UP_AUTH"), "exposure_cut_usd": round(c["exposure_usd"], 2),
              "txn_ids": c["txn_ids"][:20],
              "why": "suspect transactions through a shared device, but fraud is not established "
                     "on this card: challenge, do not block (R1)"} for c in others]
    blocked = [p for p in plan if p["action"] == "BLOCK_CARD"]
    return {"plan": plan,
            "exposure_total_usd": round(sum(c["exposure_usd"] for c in hits) or exposure_total, 2),
            "exposure_cut_usd": round(sum(p["exposure_cut_usd"] for p in blocked), 2),
            "exposure_challenged_usd": round(sum(p["exposure_cut_usd"] for p in plan
                                                 if p["action"] != "BLOCK_CARD"), 2),
            "customers_touched_by_blocks": sorted({p["customer_id"] for p in blocked}),
            "n_blocks": len(blocked),
            "r10": "BLOCK_ALL_CARDS is never proposed by the planner; R10 is decided "
                   "per customer by the policy engine"}


def plan(store, case_card: str, case_customer: str, ring_cards: list[str], as_of: datetime,
         case_txn_ids: list[str], case_exposure: float, case_is_fraud: bool,
         matched: bool = True) -> dict[str, Any]:
    """Assemble the containment plan for one case. Pure apart from store reads."""
    t0 = as_of - timedelta(days=PRE_FROM_DAYS)
    t1 = as_of - timedelta(days=PRE_TO_DAYS)
    sliced = store.ring_at_asof(case_card, as_of, lookback_days=PRE_FROM_DAYS)
    # The ring for origin analysis is the cards already *hit* (the case card and
    # the connected cards the investigation attested). The time-sliced component
    # is wider — every card that co-occurred on a rare device — and is reported
    # as structure, not counted as compromised.
    ring = sorted({case_card, *ring_cards})
    out: dict[str, Any] = {
        "as_of": str(as_of), "pre_window": [str(t0), str(t1)],
        "ring_at_asof": sliced, "ring_cards": ring,
        "query": {"origin_counts": {"ring_cards": ring, "since": str(t0), "until": str(t1)},
                  "ring_at_asof": {"card_id": case_card, "as_of": str(as_of),
                                   "lookback_days": PRE_FROM_DAYS}},
    }
    if len(ring) < MIN_RING_CARDS:
        out.update(origin=None, at_risk=[], blocks=block_set(
            [{"card_id": case_card, "customer_id": case_customer, "exposure_usd": case_exposure,
              "txn_ids": case_txn_ids, "confirmed": case_is_fraud}], case_exposure),
            note=f"ring has {len(ring)} card(s); an origin needs at least {MIN_RING_CARDS}")
        return out
    counts = store.origin_counts(ring, t0, t1, as_of)
    cands = score_origins(counts["entities"], len(ring), counts["n_control"], matched)
    origin = pick_origin(cands)
    out["origin_candidates"] = [c.as_dict() for c in cands[:8]]
    out["origin"] = origin.as_dict() if origin else None
    if origin:
        risk = store.origin_touchers(origin.entity_type, origin.entity, t0, as_of, as_of)
        at_risk = [c for c in risk if c["card_id"] not in ring and not c.get("suspect")]
        at_risk.sort(key=lambda c: c["last_touch"], reverse=True)
        out["at_risk"] = [{**c, "actions": [{"action": "MONITOR_CARD", "route": "auto"},
                                            {"action": "STEP_UP_AUTH", "route": "auto",
                                             "when": "next card-not-present purchase"}]}
                          for c in at_risk[:50]]
        out["write_back"] = {"edge": "COMPROMISE_POINT", "to_type": origin.entity_type,
                             "to": origin.entity, "window": [str(t0), str(t1)],
                             "lift": round(origin.lift, 3), "p_value": origin.p_value}
    else:
        out["at_risk"] = []
        out["note"] = ("no entity passed the lift test (p < 0.01, >= 3 ring cards); "
                       "the backward block set stands on its own")
    # The time-sliced component changes the output: cards linked to the ring by
    # a rare device *as of now* are protected too (monitor + step-up only).
    # eval/containment_backtest.py ablates it against the all-time component.
    seen = {c["card_id"] for c in out["at_risk"]} | set(ring)
    for c in sliced.get("cards", []):
        if c not in seen:
            out["at_risk"].append({"card_id": c, "customer_id": "", "last_touch": "",
                                   "n_touches": 0, "suspect": False,
                                   "reason": "time-sliced ring component (rare shared device)",
                                   "actions": [{"action": "MONITOR_CARD", "route": "auto"},
                                               {"action": "STEP_UP_AUTH", "route": "auto",
                                                "when": "next card-not-present purchase"}]})
            seen.add(c)
    for c in out["at_risk"]:
        c.setdefault("reason", "touched the compromise origin")
    hits = store.ring_exposure(ring, as_of, lookback_days=PRE_FROM_DAYS)
    for h in hits:
        h["confirmed"] = bool(case_is_fraud and h["card_id"] == case_card)
    if case_card not in {h["card_id"] for h in hits}:
        hits.append({"card_id": case_card, "customer_id": case_customer,
                     "exposure_usd": case_exposure, "txn_ids": case_txn_ids,
                     "confirmed": case_is_fraud})
    out["blocks"] = block_set(hits, case_exposure)
    out["innocent_cost"] = {"blocks_on_at_risk_cards": 0,
                            "step_ups_requested": len(out["at_risk"]),
                            "note": "forward actions are monitor and step-up only"}
    return out

"""Detectors for patterns the policy does not name (challenge C1), plus the
registry through which discovered (C2) and policy-compiled (C3) detectors join
the toolkit after a human approves them.

Every detector is a pure function over one card's transactions up to `as_of`
(from `store.card_history`, so the read is recorded and attested) and returns
the transaction and card ids it matched. Detections are reported as evidence;
they never add a block on their own, so a new detector cannot raise the
number of legitimate customers acted against (brief C1 scoring).

  dormant_wake       a card silent for >= 30 days that wakes into activity
  micro_charges      >= 3 charges of <= $5 within 7 days (testing without a hit)
  recipient_fanin    >= 4 distinct cards paying one uncommon recipient domain
                     inside 24 hours (needs the window's other cards; graph-side)
  shared_origin      the compromise-origin test (core/containment.py)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from ..config import PATHS

COMMON_RECIPIENTS = frozenset({"", "gmail.com", "hotmail.com", "anonymous.com", "yahoo.com",
                               "aol.com", "outlook.com", "comcast.net", "icloud.com",
                               "msn.com", "live.com"})
REGISTRY = PATHS.repo / "data" / "detectors" / "registry.json"


def _rows(history) -> list[dict[str, Any]]:
    return [{"txn_id": t.txn_id, "ts": t.ts, "amount": float(t.amount), "channel": t.channel,
             "email_r": t.email_r, "card_id": t.card_id} for t in history]


def dormant_wake(history, as_of: datetime, gap_days: float = 30.0,
                 window_hours: float = 72.0) -> dict[str, Any]:
    rows = sorted(_rows(history), key=lambda r: r["ts"])
    recent = [r for r in rows if r["ts"] >= as_of - timedelta(hours=window_hours)]
    before = [r for r in rows if r["ts"] < as_of - timedelta(hours=window_hours)]
    if not recent or len(before) < 3:
        return {"fired": False}
    gap = (recent[0]["ts"] - before[-1]["ts"]).total_seconds() / 86400
    fired = gap >= gap_days
    return {"fired": fired, "gap_days": round(gap, 1),
            "txn_ids": [r["txn_id"] for r in recent] if fired else [],
            "card_ids": [recent[0]["card_id"]] if fired else [],
            "claim": f"card was silent for {gap:.0f} days, then made {len(recent)} transactions "
                     f"in {window_hours:.0f} hours"}


def micro_charges(history, as_of: datetime, cap: float = 5.0, days: float = 7.0,
                  min_n: int = 3) -> dict[str, Any]:
    rows = [r for r in _rows(history) if r["ts"] >= as_of - timedelta(days=days)
            and r["amount"] <= cap]
    fired = len(rows) >= min_n
    return {"fired": fired, "n": len(rows),
            "txn_ids": [r["txn_id"] for r in rows] if fired else [],
            "card_ids": [rows[0]["card_id"]] if fired else [],
            "claim": f"{len(rows)} charges of ${cap:.0f} or less in {days:.0f} days, each too "
                     f"small to trip a per-transaction threshold"}


def recipient_fanin(window_rows: list[dict[str, Any]], recipient: str,
                    min_cards: int = 4) -> dict[str, Any]:
    if recipient in COMMON_RECIPIENTS:
        return {"fired": False}
    hit = [r for r in window_rows if r.get("email_r") == recipient]
    cards = sorted({r["card_id"] for r in hit})
    fired = len(cards) >= min_cards
    return {"fired": fired, "n_cards": len(cards),
            "txn_ids": [r["txn_id"] for r in hit][:40] if fired else [],
            "card_ids": cards[:40] if fired else [],
            "claim": f"{len(cards)} distinct cards paid recipient domain {recipient} in 24 hours"}


def run_all(store, card_id: str, as_of: datetime, flagged,
            fired: set[str] | None = None) -> list[dict[str, Any]]:
    """The detectors the agent runs on every case. Evidence only."""
    hist = store.card_history(card_id, as_of, window_days=120)
    out = []
    for name, res in (("dormant_wake", dormant_wake(hist, as_of)),
                      ("micro_charges", micro_charges(hist, as_of))):
        if res.get("fired"):
            out.append({"detector": name, **res})
    # Evasion-frontier detectors (eval/attacks.py): the relative-rule versions
    # of structuring and card testing, evidence only.
    from ..graphstore import matchers as M

    recent = [r for r in _rows(hist) if r["ts"] >= as_of - timedelta(days=3)
              and r["channel"] == "online"]
    if len(recent) >= 3:
        orig = M.detect_threshold_structuring(recent, 60.0, 3, 0.90, 0.75)
        hard = M.detect_threshold_structuring(recent, 120.0, 3, 0.85, 0.60)
        if hard.get("matched") and not orig.get("matched"):
            out.append({"detector": "frontier_structuring", "fired": True,
                        "txn_ids": hard["txn_ids"], "card_ids": [card_id],
                        "claim": f"{hard['n_txns']} online legs within 15% below the "
                                 f"${hard['threshold_usd']:,.0f} ceiling in "
                                 f"{hard['window_minutes']:.0f} minutes: just outside the "
                                 f"structuring rule, where an adapted attacker would sit"})
        ct0, ct1 = M.detect_card_testing(recent, 5.0, 2.0), M.detect_card_testing(recent, 10.0, 6.0)
        if ct1.get("matched") and not ct0.get("matched"):
            out.append({"detector": "frontier_card_testing", "fired": True,
                        "txn_ids": list(ct1.get("small_txn_ids", [])), "card_ids": [card_id],
                        "claim": f"{ct1.get('n_small', 0)} probing charges under $10: just "
                                 f"outside the card-testing rule's $5 cut-off"})
    for det in approved():
        res = evaluate_spec(det["spec"], hist, as_of, fired or set(), flagged)
        if res.get("fired"):
            out.append({"detector": det["id"], "approved_by": det.get("approved_by"), **res})
    return out


# ------------------------------------------------------- registry (C2/C3) ----
def registry() -> list[dict[str, Any]]:
    if not REGISTRY.exists():
        return []
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def save_registry(items: list[dict[str, Any]]) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(items, indent=2, default=str), encoding="utf-8")


def approved() -> list[dict[str, Any]]:
    return [d for d in registry() if d.get("status") == "approved"]


def evaluate_spec(spec: dict[str, Any], history, as_of: datetime,
                  fired: set[str] | None = None, flagged=None) -> dict[str, Any]:
    """A declarative detector. `type: facts` is a conjunction of measured facts
    (what C2 discovers); otherwise windowed counts over one card:
    {"window_hours": h, "channel": "online"|None, "amount_min": a, "amount_max": b,
     "min_count": n, "min_total": t}"""
    if spec.get("type") == "facts":
        hit = all(f in (fired or set()) for f in spec.get("all_of", []))
        tid = getattr(flagged, "txn_id", "")
        return {"fired": hit, "txn_ids": [tid] if hit and tid else [],
                "card_ids": [getattr(flagged, "card_id", "")] if hit else [],
                "claim": spec.get("claim", "")}
    if spec.get("type") in {"card_testing", "shared_origin"}:
        return {"fired": False}          # compiled policy rules are run by the policy engine
    rows = [r for r in _rows(history)
            if r["ts"] >= as_of - timedelta(hours=float(spec.get("window_hours", 24)))
            and (spec.get("channel") in (None, "", r["channel"]))
            and float(spec.get("amount_min", 0)) <= r["amount"] <= float(spec.get("amount_max",
                                                                                1e12))]
    total = sum(r["amount"] for r in rows)
    fired = len(rows) >= int(spec.get("min_count", 1)) and total >= float(spec.get("min_total", 0))
    return {"fired": fired, "n": len(rows), "total": round(total, 2),
            "txn_ids": [r["txn_id"] for r in rows][:40] if fired else [],
            "card_ids": [rows[0]["card_id"]] if fired and rows else [],
            "claim": spec.get("claim", "") or f"{len(rows)} matching transactions totalling "
                                               f"${total:,.2f}"}

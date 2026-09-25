"""Sliding-window typology matchers, shared by both backends.

Two of the hard matchers need an ordered scan with carry over a card's recent
transactions. GSQL expresses that badly and Python expresses it in a dozen
lines, so the graph does the selective retrieval — which is what a graph is
good at — and the window logic lives here, once, used identically by the local
mirror and by the TigerGraph store. That is what keeps the two backends
answering the same question rather than merely similar ones.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta
from typing import Any, Sequence

ROUND_THRESHOLDS: tuple[float, ...] = (100.0, 200.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0)


def detect_card_testing(online_rows: Sequence[dict[str, Any]],
                        small_amount: float = 5.0,
                        follow_window_hours: float = 2.0) -> dict[str, Any]:
    """Documented typology 1 / policy R5.

    Three or more online authorisations under `small_amount` inside one hour,
    optionally followed by a materially larger purchase. Every window ending at
    or before the cutoff is scanned; the strongest match wins.
    """
    rows = sorted(online_rows, key=lambda r: r["ts"])
    small = [r for r in rows if float(r["amount"]) < small_amount]
    best: dict[str, Any] = {"matched": False, "n_small": 0, "small_txn_ids": [],
                            "follow_txn_id": "", "follow_amount": 0.0,
                            "window_minutes": 0.0, "small_amounts": []}
    larger = [r for r in rows if float(r["amount"]) >= 20.0]
    larger_ts = [r["ts"] for r in larger]
    # Two pointers, not a filter per anchor. Rebuilding the window by scanning
    # forward from every anchor is quadratic, which is invisible on one case and
    # fatal on the autonomous sweep, where a busy card carries thousands of
    # online transactions across the exam period.
    j = 0
    for i, anchor in enumerate(small):
        start = anchor["ts"]
        limit = start + timedelta(hours=1)
        if j < i:
            j = i
        while j < len(small) and small[j]["ts"] <= limit:
            j += 1
        group = small[i:j]
        if len(group) < 3:
            continue
        last_ts = group[-1]["ts"]
        lo = bisect_right(larger_ts, last_ts)
        hi = bisect_right(larger_ts, last_ts + timedelta(hours=follow_window_hours))
        follow = larger[lo:hi]
        cand = {
            "matched": True,
            "n_small": len(group),
            "small_txn_ids": [str(r["txn_id"]) for r in group],
            "small_amounts": [round(float(r["amount"]), 2) for r in group],
            "follow_txn_id": str(follow[0]["txn_id"]) if follow else "",
            "follow_amount": round(float(follow[0]["amount"]), 2) if follow else 0.0,
            "window_minutes": round((last_ts - start).total_seconds() / 60.0, 1),
        }
        better = (not best["matched"]
                  or cand["n_small"] > best["n_small"]
                  or (cand["follow_txn_id"] and not best["follow_txn_id"]))
        if better:
            best = cand
    return best


def detect_threshold_structuring(online_rows: Sequence[dict[str, Any]],
                                 window_minutes: float = 60.0,
                                 min_txns: int = 3) -> dict[str, Any]:
    """UNDOCUMENTED typology U1 — sub-threshold authorisation structuring.

    Mined from closed cases CC-3748, CC-3841, CC-3907, CC-4086 and CC-4124: a
    burst of online purchases inside roughly forty minutes, each amount parked
    just beneath a round authorisation ceiling, several thousand dollars in
    aggregate. Every leg looks ordinary to a per-transaction model, which is
    exactly why it survived long enough to become five confirmed cases the
    bank's analysts could not categorise.

    The test is deliberately strict: at least three legs in the band
    [0.90 * threshold, threshold), and at least three quarters of the burst
    sitting in that band, so an ordinary pair of purchases near a round number
    does not trip it.
    """
    rows = sorted(online_rows, key=lambda r: r["ts"])
    best: dict[str, Any] = {"matched": False}
    j = 0
    for i, anchor in enumerate(rows):
        start = anchor["ts"]
        limit = start + timedelta(minutes=window_minutes)
        if j < i:
            j = i
        while j < len(rows) and rows[j]["ts"] <= limit:
            j += 1
        group = rows[i:j]
        if len(group) < min_txns:
            continue
        amounts = [float(r["amount"]) for r in group]
        for thr in ROUND_THRESHOLDS:
            lo = thr * 0.90
            idx = [n for n, a in enumerate(amounts) if lo <= a < thr]
            if len(idx) < min_txns or len(idx) / len(amounts) < 0.75:
                continue
            picked = [group[n] for n in idx]
            total = sum(amounts[n] for n in idx)
            mean = total / len(idx)
            cand = {
                "matched": True,
                "threshold_usd": thr,
                "n_txns": len(idx),
                "txn_ids": [str(r["txn_id"]) for r in picked],
                "amounts": [round(amounts[n], 2) for n in idx],
                "total_usd": round(total, 2),
                "window_minutes": round(
                    (picked[-1]["ts"] - picked[0]["ts"]).total_seconds() / 60.0, 1),
                "headroom_pct": round(100.0 * (thr - mean) / thr, 2),
            }
            if not best["matched"] or cand["total_usd"] > best.get("total_usd", 0.0):
                best = cand
    return best


def recurrence_from_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Policy R7 — the customer's own repeat charge: same amount, same product.

    R7 says "monthly". Two cadences qualify: a monthly one (two or more gaps of
    26-35 days), and an established habit — at least eight earlier identical
    charges over a quarter or more, never more than 45 days apart, at a steady
    pace (median gap 5-35 days). HHG-018's $39.08 charge recurs every one to
    three weeks for 140 days.

    The habit bar is deliberately high. On the October holdout a looser rule
    (four charges over six weeks) fired on 15 disputes, 14 of them confirmed
    fraud: fraud episodes repeat an amount too, but in a burst (CC-4331: 21
    charges, median gap 2.8 days, over 82 days). A quarter of steady history is
    what a burst cannot fake."""
    ordered = sorted(rows, key=lambda r: r["ts"])
    gaps = [round((b["ts"] - a["ts"]).total_seconds() / 86400.0, 1)
            for a, b in zip(ordered, ordered[1:])]
    monthly = [g for g in gaps if 26.0 <= g <= 35.0]
    n_prior = max(len(ordered) - 1, 0)
    span = ((ordered[-1]["ts"] - ordered[0]["ts"]).total_seconds() / 86400.0
            if len(ordered) > 1 else 0.0)
    median_gap = sorted(gaps)[len(gaps) // 2] if gaps else 0.0
    regular = bool(n_prior >= 8 and span >= 90.0 and gaps and max(gaps) <= 45.0
                   and 5.0 <= median_gap <= 35.0)
    return {
        "n_prior_same_amount": n_prior,
        "gaps_days": gaps[-6:],
        "n_monthly_gaps": len(monthly),
        "median_gap_days": round(median_gap, 1),
        "span_days": round(span, 1),
        "cadence": "monthly" if len(monthly) >= 2 else "regular" if regular else "none",
        "recurring": bool((n_prior >= 2 and len(monthly) >= 2) or regular),
        "near_recurring": bool(n_prior >= 1 and len(monthly) >= 1),
        "matched_txn_ids": [str(r["txn_id"]) for r in ordered[-6:]],
    }

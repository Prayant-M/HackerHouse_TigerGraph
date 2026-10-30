"""Analyst in the loop (challenge C8).

Analysts accept or reject a finding (an evidence signal) on a case. Behaviour
changes from those decisions without retraining anything:

* **Entity-scoped:** a finding rejected on a card ("that new device is the
  customer's new phone") is suppressed on later investigations of the same
  card, so the agent does not repeat a mistake an analyst already corrected.
* **Signal-scoped:** a signal rejected on two or more more cases than it was
  accepted has its reliability damped (likelihood ratio shrunk toward 1), never
  below 0.3.

Every adjustment records the feedback ids that caused it, and the answer file
lists the adjustments it applied (`agent_record.feedback_applied`), so a change
in behaviour is always attributable to named analyst decisions. The ledger is
append-only and hash-chained like the approval ledger.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from ..config import PATHS

LEDGER = PATHS.repo / "data" / "feedback" / "ledger.jsonl"
GENESIS = "0" * 64
MIN_FACTOR = 0.3


def read() -> list[dict[str, Any]]:
    if not LEDGER.exists():
        return []
    return [json.loads(x) for x in LEDGER.read_text(encoding="utf-8").splitlines() if x.strip()]


def record(principal, answer: dict[str, Any], finding: str, accepted: bool,
           note: str = "") -> dict[str, Any]:
    fired = set(answer.get("agent_record", {}).get("signals_fired", []))
    if finding not in fired:
        raise ValueError(f"{finding!r} is not a finding on {answer['case_id']}; "
                         f"choose one of {sorted(fired)}")
    rows = read()
    trig = answer["agent_record"]["trigger"]
    rec = {"id": f"FB-{len(rows) + 1:05d}", "case_id": answer["case_id"],
           "graph_case_id": answer["case"].get("graph_case_id", ""), "target": finding,
           "card_id": trig["card_id"], "customer_id": trig["customer_id"],
           "accepted": bool(accepted), "analyst": principal.actor_id, "role": principal.role,
           "note": note[:400], "at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "prev_hash": rows[-1]["hash"] if rows else GENESIS}
    rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def adjustments(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = read() if rows is None else rows
    by_sig: dict[str, dict[str, list[str]]] = {}
    entity: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = by_sig.setdefault(r["target"], {"rejected": [], "accepted": []})
        d["accepted" if r["accepted"] else "rejected"].append(r["id"])
        key = f"{r['target']}|{r['card_id']}"
        if not r["accepted"]:
            entity[key] = {"signal": r["target"], "card_id": r["card_id"], "factor": 0.0,
                           "caused_by": entity.get(key, {}).get("caused_by", []) + [r["id"]]}
        elif key in entity:
            entity.pop(key)
    signal = {}
    for sig, d in by_sig.items():
        excess = len(d["rejected"]) - len(d["accepted"])
        if excess >= 2:
            signal[sig] = {"factor": max(MIN_FACTOR, 1.0 - 0.2 * excess),
                           "caused_by": d["rejected"]}
    return {"signal": signal, "entity": entity}


def factor(signal: str, card_id: str, adj: dict[str, Any] | None = None
           ) -> tuple[float, list[str]]:
    adj = adj if adj is not None else adjustments()
    e = adj["entity"].get(f"{signal}|{card_id}")
    if e:
        return 0.0, e["caused_by"]
    s = adj["signal"].get(signal)
    if s:
        return s["factor"], s["caused_by"]
    return 1.0, []

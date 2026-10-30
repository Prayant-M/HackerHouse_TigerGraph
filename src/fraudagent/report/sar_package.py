"""The SAR filing package (challenge C4): what an analyst reviews before sending.

The `sar` block in the answer is the filing itself (narrative, subjects, total,
dates), in the organisers' format. This builds the material around it that a
reviewer needs to send it with minor edits:

* **five W's** — who, what, when, where, why, the structure FinCEN's narrative
  guidance asks for, each item carrying the attestation ids behind it;
* **timeline** — every affected transaction in time order, read from the graph,
  with the attestations that cite it;
* **evidence graph** — the subjects, transactions, devices, connected cards and
  precedent cases as nodes and edges (what `case_chain` reads back);
* **review checklist** — machine checks a reviewer would otherwise do by hand:
  every sentence cited, total equals the attested exposure, the first
  transaction really is the earliest, no SAR wording in customer-facing text.
"""

from __future__ import annotations

from typing import Any

from .customer_text import scan


def _cites(ids: list[str], attestations: list[dict[str, Any]]) -> list[str]:
    s = set(map(str, ids))
    return [a["id"] for a in attestations if s & set(map(str, a.get("evidence_ids", [])))][:6]


def build(store, ctx, answer: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    sar = answer["sar"]
    if not sar.get("file"):
        return None
    rec = answer["agent_record"]
    atts = rec.get("attestations", [])
    case = answer["case"]
    rows = []
    for tid in case["affected_txn_ids"]:
        t = store.get_transaction(str(tid))
        if t is None:
            continue
        rows.append({"txn_id": t.txn_id, "ts": str(t.ts), "amount_usd": round(float(t.amount), 2),
                     "channel": t.channel, "card_id": t.card_id, "region": t.region,
                     "device_profile": t.device_profile, "proxy": t.proxy,
                     "attestations": _cites([t.txn_id], atts)})
    rows.sort(key=lambda r: r["ts"])
    total = round(sum(r["amount_usd"] for r in rows), 2)

    nodes = [{"id": ctx.flagged.customer_id, "type": "Customer"},
             {"id": ctx.card_id_safe(), "type": "Card"}]
    edges = []
    for r in rows:
        nodes.append({"id": r["txn_id"], "type": "Transaction", "amount_usd": r["amount_usd"],
                      "ts": r["ts"]})
        edges.append({"from": r["txn_id"], "to": r["card_id"], "type": "MADE_WITH"})
        if r["device_profile"]:
            edges.append({"from": r["txn_id"], "to": r["device_profile"], "type": "FROM_DEVICE"})
    for dev in sorted({r["device_profile"] for r in rows if r["device_profile"]}
                      | set(case["connected_device_profiles"])):
        nodes.append({"id": dev, "type": "DeviceProfile"})
    for c in case["connected_card_ids"]:
        nodes.append({"id": c, "type": "Card", "role": "connected"})
        edges.append({"from": ctx.card_id_safe(), "to": c, "type": "CONNECTED_CARD"})
    for p in (rec.get("prior_cases") or [])[:5]:
        nodes.append({"id": p["case_id"], "type": "ClosedCase", "outcome": p.get("outcome")})
        for e in p.get("shared_with", [])[:4]:
            edges.append({"from": p["case_id"], "to": e, "type": "PRECEDENT_SHARES"})
    origin = (rec.get("containment") or {}).get("origin")
    if origin:
        nodes.append({"id": origin["entity"], "type": "CompromiseOrigin",
                      "lift": origin["lift"], "p_value": origin["p_value"]})
        edges.append({"from": ctx.card_id_safe(), "to": origin["entity"],
                      "type": "COMPROMISE_POINT"})
    seen, uniq = set(), []
    for n in nodes:
        if n["id"] and n["id"] not in seen:
            seen.add(n["id"])
            uniq.append(n)

    top = [e for e in case.get("evidence", []) if e.get("source") == "graph"][:4]
    channels = sorted({r["channel"] for r in rows if r["channel"]})
    regions = sorted({str(r["region"]) for r in rows if r["region"] not in ("", None)})
    devices = sorted({r["device_profile"] for r in rows if r["device_profile"]})
    five = {
        "who": {"subjects": sar["subjects"], "attestations": _cites(sar["subjects"], atts)},
        "what": {"pattern": case["pattern"], "description": case.get("pattern_description", ""),
                 "n_transactions": len(rows), "total_usd": total},
        "when": {"first": rows[0]["ts"] if rows else "", "last": rows[-1]["ts"] if rows else "",
                 "first_suspicious_txn_id": case["first_suspicious_txn_id"]},
        "where": {"channels": channels, "regions": regions, "devices": devices},
        "why": {"reason": sar["reason"],
                "evidence": [{"claim": e.get("claim", ""), "ref": e.get("ref", ""),
                              "attestations": _cites(e.get("entity_ids", []), atts)}
                             for e in top],
                "fraud_probability": case["fraud_probability"],
                "proof_margin_k": (rec.get("proof") or {}).get("margin_k")},
    }
    cites = rec.get("sar_citations", [])
    customer_text = " ".join(
        [str(v) for r in answer.get("evidence_requests", []) for v in r.values()
         if isinstance(v, str)]
        + [str(m.get("text", m)) if isinstance(m, dict) else str(m)
           for m in rec.get("customer_messages", []) or []])
    checks = {
        "every_sentence_cited": bool(cites) and all(c.get("attestations") for c in cites),
        "total_equals_attested_exposure": abs(total - float(case["exposure_usd"])) < 0.02
        and abs(float(sar["total_amount_usd"]) - total) < 0.02,
        "first_txn_is_earliest": bool(rows) and rows[0]["txn_id"] == str(
            case["first_suspicious_txn_id"]),
        "no_tip_off_in_customer_text": not scan(customer_text),
        "unattested_claims": len(rec.get("unattested", []) or []),
    }
    return {"five_ws": five, "timeline": rows, "evidence_graph": {"nodes": uniq, "edges": edges},
            "review_checklist": checks,
            "ready_to_send": all(v for k, v in checks.items() if k != "unattested_claims")
            and not checks["unattested_claims"]}

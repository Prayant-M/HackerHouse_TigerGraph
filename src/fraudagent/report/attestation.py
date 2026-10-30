"""Attest everything an answer file asserts (brief §5), and cite every SAR
sentence (challenge C4)."""

from __future__ import annotations

import re
from typing import Any

from ..core.attest import Attestor

_IDS = re.compile(r"\b(C\d{5}-K\d|C\d{5}|CC-\d{4}|HH[GF]-\d{3}|\d{7})\b")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def attest_answer(state, answer: dict[str, Any]) -> dict[str, Any]:
    store = state.get("_store")
    calls = list(getattr(store, "calls", []) or [])
    att = Attestor(state["case_id"], calls)
    case = answer["case"]
    ev_ids: dict[str, str] = {}

    for e in answer["agent_record"].get("evidence_with_impact", []):
        kind = e.get("claim_type", "evidence")
        aid = att.add(e["claim"], e.get("entity_ids", []), e.get("ref", ""), kind=kind)
        ev_ids[e.get("ref", "")] = aid
        e["attestation_id"] = aid

    ep_calls = att.calls_for("episode_window")
    if case["affected_txn_ids"]:
        case_aid = att.add(
            f"Exposure ${case['exposure_usd']:,.2f} is the sum of the {len(case['affected_txn_ids'])} "
            f"affected transactions; the first is {case['first_suspicious_txn_id']}",
            case["affected_txn_ids"],
            f"query:episode_window(card_id={state['trigger'].card_id}, as_of={state['as_of']})",
            kind="exposure", extra_calls=ep_calls)
    else:
        case_aid = att.add("No transactions are attributed to fraud; exposure is $0.00",
                           [state["trigger"].flagged_txn_id],
                           f"query:episode_window(card_id={state['trigger'].card_id}, "
                           f"as_of={state['as_of']})", kind="exposure", extra_calls=ep_calls)
    if case["connected_card_ids"]:
        att.add(f"{len(case['connected_card_ids'])} other cards are connected through "
                f"{', '.join(d[:40] for d in case['connected_device_profiles'][:2]) or 'a shared origin'}",
                case["connected_card_ids"],
                f"query:shared_entity_ring(card_id={state['trigger'].card_id}, as_of={state['as_of']})",
                kind="connection", extra_calls=att.calls_for("shared_entity_ring"))

    rec = answer["agent_record"]
    pr = rec.get("proof") or {}
    if pr:
        att.add(f"Minimal sufficient facts {pr.get('minimal_sufficient_facts')} force action class "
                f"{pr.get('action_class')}; margin k={pr.get('margin_k')}",
                [state["trigger"].flagged_txn_id], "derived:proof(core.proof.build_proof)",
                kind="proof", params={"facts": pr.get("facts", [])})
        prec = pr.get("precedent") or {}
        if prec.get("n"):
            att.add(f"{prec['n']} closed cases share these facts: {prec.get('confirmed')} confirmed, "
                    f"{prec.get('cleared')} cleared", prec.get("case_ids", []),
                    f"query:precedent_by_facts(fact_mask={prec.get('params', {}).get('fact_mask')}, "
                    f"as_of={state['as_of']})", kind="precedent",
                    extra_calls=att.calls_for("precedent_by_facts"))
    plan = rec.get("containment") or {}
    if plan.get("origin"):
        o = plan["origin"]
        att.add(f"Compromise origin {o['entity_type']} {o['entity'][:60]}: {o['ring_cards_touching']} "
                f"of {o['n_ring']} ring cards vs {o['control_cards_touching']} of {o['n_control']} "
                f"controls, lift {o['lift']}, p={o['p_value']}", o.get("ring_card_ids", []),
                "query:origin_counts", kind="containment", params=plan["query"]["origin_counts"],
                extra_calls=att.calls_for("origin_counts"))
    if plan.get("at_risk"):
        att.add(f"{len(plan['at_risk'])} at-risk cards touched the origin and are not yet hit",
                [c["card_id"] for c in plan["at_risk"]], "query:origin_touchers",
                kind="containment", extra_calls=att.calls_for("origin_touchers"))
    if plan.get("blocks"):
        b = plan["blocks"]
        att.add(f"Block set cuts ${b['exposure_cut_usd']:,.2f} and touches customers "
                f"{b['customers_touched_by_blocks']}",
                [x["card_id"] for x in b["plan"]] + b["customers_touched_by_blocks"],
                "query:ring_exposure", kind="containment",
                extra_calls=att.calls_for("ring_exposure"))
    for det in rec.get("typology_detections") or []:
        det["attestation_id"] = att.add(
            f"Detector {det['detector']}: {det.get('claim', '')}",
            list(det.get("txn_ids", [])) + list(det.get("card_ids", [])),
            f"query:card_window(card_id={state['trigger'].card_id}, as_of={state['as_of']})",
            kind="typology", extra_calls=att.calls_for("card_history")[:2])
    for q in (rec.get("quality") or {}).get("issues", []):
        att.add(f"Data gap {q['kind']}: {q['detail']}", q["record_ids"],
                "query:data_gaps", kind="data_quality")

    citations = []
    sar = answer["sar"]
    if sar.get("file") and sar.get("narrative"):
        for sent in [x for x in _SENT.split(sar["narrative"].strip()) if x.strip()]:
            ids = sorted(set(_IDS.findall(sent)))
            if ids:
                aid = att.add(sent, ids, "derived:sar_sentence", kind="sar_sentence")
                cites = [aid]
            else:
                cites = [case_aid]
            citations.append({"sentence": sent, "attestations": cites, "ids": ids})
    unattested = att.unattested()
    return {"attestations": att.as_list(), "sar_citations": citations,
            "unattested": unattested, "data_snapshot": att.snapshot,
            "n_attestations": len(att.items)}

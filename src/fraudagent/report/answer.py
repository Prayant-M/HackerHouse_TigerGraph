"""Answer file construction.

One function builds both the submission JSON and the graph payload, from the
same state object, because the dataset asks for the case in the answer file
*and* in the graph and the two must not be able to disagree.

Everything here is schema discipline: the field names, types and enum values
come straight from the dataset README's Answer Format section, and
`validate()` fails loudly on anything that would score zero — a missing field,
an invented identifier, a SAR whose `file` flag disagrees with the final
actions, or a legitimate verdict carrying exposure.
"""

from __future__ import annotations

from typing import Any

from ..core import hypotheses as H
from ..core.policy_engine import sar_required, status_for
from ..core.signals import InvestigationContext
from ..graphstore.base import GraphStore
from .narrative import sar_narrative, template_sar

PATTERNS = {H.CARD_TESTING, H.CNP, H.CNP_NEW_DEVICE, H.OUT_OF_REGION, H.ATO,
            H.UNDOCUMENTED, H.NONE}
STATUSES = {"open", "closed_fraud", "closed_legitimate", "escalated"}
VERDICTS = {"fraud", "legitimate", "uncertain"}
ROUTES = {"auto", "L1", "L2"}
SOURCES = {"graph", "document", "customer", "external"}


def _transport(store: GraphStore) -> str:
    """How this case reached the graph: through the TigerGraph MCP server, a
    direct connection, or the local mirror."""
    gateway = getattr(store, "graph", None)
    return getattr(gateway, "transport", "") or getattr(store, "backend", "local")


def open_questions(state, evidence: list[dict[str, Any]], p_fraud: float) -> list[str]:
    """What the agent still does not know when it stops. Stated, not implied:
    an empty answer and an unavailable one are different things."""
    ctx = state["ctx"]
    f = ctx.flagged
    out: list[str] = []
    if not f.device_profile:
        out.append("No identity record for the flagged transaction, so device and proxy "
                   "evidence is unavailable rather than clean.")
    if any("simulated" in (r.channel + r.assumed_response).lower() for r in state["requests"]):
        out.append("The customer's reply was simulated (no real channel in this round); "
                   "a real reply could still change the outcome.")
    up = sum(1 for e in evidence if (e.get("delta_fraud_probability") or 0) > 0.005)
    down = sum(1 for e in evidence if (e.get("delta_fraud_probability") or 0) < -0.005)
    if up and down:
        out.append(f"Evidence conflicts: {up} items raised the fraud likelihood and {down} "
                   f"lowered it.")
    if 0.15 < p_fraud < 0.85:
        out.append(f"The probability ({p_fraud:.2f}) stopped short of the policy's 0.85 / 0.15 "
                   f"bounds; the decision rests on the §6 'further steps would not change it' "
                   f"rule.")
    if ctx.trigger_type == "customer_report":
        out.append("The dataset has no merchant field, so the R7 recurring-charge check uses "
                   "amount, product code and cadence only.")
    if not state["priors"]:
        out.append("No similar prior investigation was recalled.")
    return out


def build_answer(state, store: GraphStore) -> tuple[dict[str, Any], dict[str, Any]]:
    from ..agent.llm import get_llm
    from ..agent.nodes import _case_state, _evidence_entries

    import time

    ctx: InvestigationContext = state["ctx"]
    ledger = state["ledger"]
    ep = state["episode"]
    narrative = state["narrative"]
    p_fraud = round(ledger.fraud_probability, 3)

    initial = state["initial_decision"].as_list()
    final = state["final_decision"].as_list()
    evidence = _evidence_entries(state)

    # ---- SAR. `file` must agree with whether FILE_REPORT is in the final set.
    cs = _case_state(state, final=True)
    should_file, reason = sar_required(cs)
    file_sar = should_file and any(a["action"] == "FILE_REPORT" for a in final)
    if any(a["action"] == "FILE_REPORT" for a in final) and not should_file:
        final = [a for a in final if a["action"] != "FILE_REPORT"]
    if file_sar:
        narrative_text = sar_narrative(get_llm(), ctx, state["pattern"], p_fraud, ep,
                                       evidence, state["priors"], reason)
        subjects = _subjects(ctx, ep)
        sar = {"file": True, "reason": reason, "narrative": narrative_text,
               "subjects": subjects,
               "total_amount_usd": round(ep.exposure_usd, 2),
               "activity_dates": ep.activity_dates or []}
    else:
        sar = {"file": False, "reason": reason, "narrative": "", "subjects": [],
               "total_amount_usd": 0, "activity_dates": []}

    status = status_for(state["verdict"], [a["action"] for a in final],
                        evidence_pending=False)
    llm = get_llm()
    elapsed = round(time.time() - state["started_at"], 2)

    answer: dict[str, Any] = {
        "case_id": state["case_id"],
        "case": {
            "status": status,
            "verdict": state["verdict"],
            "fraud_probability": p_fraud,
            "pattern": state["pattern"],
            "pattern_description": narrative.get("pattern_description", ""),
            "affected_txn_ids": ep.affected_txn_ids,
            "first_suspicious_txn_id": ep.first_suspicious_txn_id,
            "connected_card_ids": ep.connected_card_ids,
            "connected_device_profiles": ep.connected_device_profiles,
            "exposure_usd": round(ep.exposure_usd, 2),
            "evidence": [
                {"claim": e["claim"], "source": e["source"], "ref": e["ref"],
                 "entity_ids": e["entity_ids"]} for e in evidence],
            "similar_prior_cases": [p.case_id for p in state["priors"]
                                    if p.fused_score >= 0.30][:8],
            "summary": narrative["summary"],
            "written_to_graph": False,          # set true by the case writer
            "graph_case_id": state["graph_case_id"],
        },
        "evidence_requests": [r.answer_entry() for r in state["requests"]],
        "next_best_actions": {
            "initial": [{"action": a["action"], "route": a["route"], "reason": a["reason"]}
                        for a in initial],
            "final": [{"action": a["action"], "route": a["route"], "reason": a["reason"]}
                      for a in final],
            "what_changed": narrative["what_changed"],
        },
        "sar": sar,
        "stop_reason": state["stop"].reason,
        "tool_calls": int(getattr(store, "call_count", 0)),
        "tokens": int(llm.case_usage()["tokens"]),
        "latency_s": elapsed,
    }

    # ---- everything beyond the required schema, for the console and the audit
    answer["agent_record"] = {
        "trigger": state["trigger"].as_dict(),
        "as_of": str(state["as_of"]),
        "posterior": ledger.snapshot(),
        "hypothesis_labels": H.LABELS,
        "prior": {k: round(v, 4) for k, v in ledger.prior.items()},
        "rounds": state["round"],
        "signals_fired": ctx.fired_names(),
        "evidence_with_impact": evidence,
        "evidence_requests_detail": [r.as_dict() for r in state["requests"]],
        "voi_ranking": state.get("voi_ranking", []),
        "decisions": state["decisions"].as_list(),
        "audit_chain": {"head": state["decisions"].head},
        "cited_policy_rules": sorted(
            set(state["initial_decision"].cited_rules) | set(state["final_decision"].cited_rules)),
        "policy_notes": state["final_decision"].notes,
        "forbidden_actions": sorted(set(state["final_decision"].forbidden)),
        "obligations": state["final_decision"].obligations,
        "explanation": narrative["explanation"],
        "prior_cases": [
            {"case_id": p.case_id, "outcome": p.outcome, "pattern": p.pattern,
             "fused_score": p.fused_score, "similarity": p.similarity,
             "shared_entities": p.shared_entities, "shared_with": p.shared_with}
            for p in state["priors"]],
        "executed_actions": state.get("result", {}).get("executed_actions", []),
        "pending_approval": state.get("result", {}).get("pending_approval", []),
        "episode_basis": ep.basis,
        "open_questions": open_questions(state, evidence, p_fraud),
        "graph_transport": _transport(store),
        "backend": getattr(store, "backend", "unknown"),
        "llm": {"available": llm.available, "provider": llm.cfg.provider,
                "model": llm.cfg.model if llm.available else "deterministic-templates",
                **llm.case_usage()},
        "prose_source": ("template" if not llm.available or llm.case_usage()[
            "template_fallbacks"] else "llm"),
        "transport_degraded": "degraded" in _transport(store),
        "january_regime": state["as_of"].year >= 2017,
        "text_facts": state.get("text_facts", {}),
        "quality": state.get("quality", {}),
        "conformal": state.get("conformal", {}),
        "proof": state.get("proof", {}),
        "gate": state.get("gate", {}),
        "containment": state.get("containment"),
        "compromise_watch": state.get("compromise_watch", []),
        "feedback_applied": state.get("feedback_applied", []),
        "typology_detections": state.get("typology_detections", []),
        "customer_messages": _customer_messages(state),
        "trace": state.get("trace", []),
    }

    from ..agent import final_round as FR
    from ..core.attest import answer_hash
    from .attestation import attest_answer

    rec = answer["agent_record"]
    rec["lifecycle"] = FR.lifecycle(state, answer)
    rec.update(attest_answer(state, answer))
    from .sar_package import build as sar_package

    rec["sar_package"] = sar_package(store, state["ctx"], answer, state)
    rec["handover"] = FR.handover(state, answer)
    rec["answer_hash"] = answer_hash(answer)
    plan = state.get("containment") or {}
    children = FR.watch_children(plan, state["graph_case_id"])
    rec["watch_children"] = children

    graph_payload = {
        "case_id": state["case_id"],
        "lifecycle_state": rec["lifecycle"][-1]["to"],
        "state_changes": rec["lifecycle"],
        "watch_children": children,
        "origin": plan.get("write_back"),
        "proof": state.get("proof", {}),
        "gate": state.get("gate", {}),
        "conformal": state.get("conformal", {}),
        "data_snapshot": rec["data_snapshot"],
        "answer_hash": rec["answer_hash"],
        "graph_case_id": state["graph_case_id"],
        "card_id": state["trigger"].card_id,
        "customer_id": state["trigger"].customer_id,
        "trigger_type": state["trigger"].type,
        "opened_at": str(state["trigger"].opened_at),
        "as_of": str(state["as_of"]),
        "status": status,
        "verdict": state["verdict"],
        "fraud_probability": p_fraud,
        "confidence": round(ledger.margin, 3),
        "pattern": state["pattern"],
        "pattern_description": narrative.get("pattern_description", ""),
        "exposure_usd": round(ep.exposure_usd, 2),
        "summary": narrative["summary"],
        "narrative": narrative["summary"],
        "stop_reason": state["stop"].reason,
        "ledger_head": state["decisions"].head,
        "tool_calls": int(getattr(store, "call_count", 0)),
        "latency_s": elapsed,
        "affected_txn_ids": ep.affected_txn_ids,
        "connected_card_ids": ep.connected_card_ids,
        "connected_device_profiles": ep.connected_device_profiles,
        "similar_prior_cases": answer["case"]["similar_prior_cases"],
        "cited_rules": answer["agent_record"]["cited_policy_rules"],
        "evidence": evidence,
        "decisions": [
            {**d, "p_fraud_before": round(sum(v for k, v in d["posterior_before"].items()
                                              if k != H.NONE), 4),
             "p_fraud_after": round(sum(v for k, v in d["posterior_after"].items()
                                        if k != H.NONE), 4)}
            for d in state["decisions"].as_list()],
        "actions": {"initial": initial, "final": final},
        "evidence_requests": [r.as_dict() for r in state["requests"]],
        "sar": sar,
        "entity_ids": ctx.entity_ids() + ep.affected_txn_ids + ep.connected_card_ids,
    }
    return answer, graph_payload


def _customer_messages(state) -> list[dict[str, Any]]:
    """Every string a customer would see, built from a CustomerView that has no
    case-internal field (report/customer_text.py)."""
    from .customer_text import render, view_from

    out = []
    flagged = state["ctx"].flagged
    for r in state.get("requests", []):
        if r.type in {"customer_validation", "step_up_auth"}:
            out.append({"request_type": r.type, "channel": r.channel,
                        "text": render(view_from(r.type, r.channel, flagged))})
    if any(a.action == "WARN_CUSTOMER" for a in state["final_decision"].actions):
        out.append({"request_type": "warn", "channel": "app message",
                    "text": render(view_from("warn", "app message", flagged))})
    return out


def _subjects(ctx: InvestigationContext, ep) -> list[str]:
    subs = [ctx.flagged.customer_id, ctx.card_id_safe()]
    subs += list(ep.connected_card_ids)[:10]
    if ctx.flagged.device_profile:
        subs.append(ctx.flagged.device_profile)
    seen, out = set(), []
    for s in subs:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# ----------------------------------------------------------------- validate --
REQUIRED_TOP = {"case_id", "case", "evidence_requests", "next_best_actions", "sar",
                "stop_reason", "tool_calls", "tokens", "latency_s"}
REQUIRED_CASE = {"status", "verdict", "fraud_probability", "pattern", "pattern_description",
                 "affected_txn_ids", "first_suspicious_txn_id", "connected_card_ids",
                 "connected_device_profiles", "exposure_usd", "evidence",
                 "similar_prior_cases", "summary", "written_to_graph", "graph_case_id"}
REQUIRED_SAR = {"file", "reason", "narrative", "subjects", "total_amount_usd",
                "activity_dates"}


def validate(answer: dict[str, Any], known_txn_ids: set[str] | None = None,
             known_card_ids: set[str] | None = None,
             known_case_ids: set[str] | None = None) -> list[str]:
    """Return every problem that would cost points. Empty list means clean.

    "Missing fields score zero for that part" and "made-up IDs score zero", so
    this runs over all twenty answers before anything is committed.
    """
    problems: list[str] = []
    missing = REQUIRED_TOP - set(answer)
    if missing:
        problems.append(f"missing top-level fields: {sorted(missing)}")
    case = answer.get("case", {})
    missing = REQUIRED_CASE - set(case)
    if missing:
        problems.append(f"missing case fields: {sorted(missing)}")
    sar = answer.get("sar", {})
    missing = REQUIRED_SAR - set(sar)
    if missing:
        problems.append(f"missing sar fields: {sorted(missing)}")

    if case.get("status") not in STATUSES:
        problems.append(f"bad status {case.get('status')!r}")
    if case.get("verdict") not in VERDICTS:
        problems.append(f"bad verdict {case.get('verdict')!r}")
    if case.get("pattern") not in PATTERNS:
        problems.append(f"bad pattern {case.get('pattern')!r}")
    p = case.get("fraud_probability")
    if not isinstance(p, (int, float)) or not 0.0 <= float(p) <= 1.0:
        problems.append(f"fraud_probability out of range: {p!r}")

    if case.get("pattern") == H.UNDOCUMENTED and not case.get("pattern_description"):
        problems.append("pattern is 'undocumented' but pattern_description is empty")
    if case.get("pattern") != H.UNDOCUMENTED and case.get("pattern_description"):
        problems.append("pattern_description must be empty unless pattern is 'undocumented'")

    if case.get("verdict") == "legitimate":
        if case.get("affected_txn_ids"):
            problems.append("legitimate verdict must carry no affected_txn_ids")
        if float(case.get("exposure_usd") or 0) != 0:
            problems.append("legitimate verdict must carry zero exposure")
        if sar.get("file"):
            problems.append("legitimate verdict must not file a SAR")

    nba = answer.get("next_best_actions", {})
    for phase in ("initial", "final"):
        for a in nba.get(phase, []):
            if a.get("route") not in ROUTES:
                problems.append(f"{phase} action {a.get('action')} has bad route {a.get('route')}")
            if not a.get("reason"):
                problems.append(f"{phase} action {a.get('action')} has no reason")
    if "what_changed" not in nba:
        problems.append("next_best_actions.what_changed is missing")
    if not nba.get("initial"):
        problems.append("next_best_actions.initial is empty")
    if not nba.get("final"):
        problems.append("next_best_actions.final is empty")

    files_report = any(a.get("action") == "FILE_REPORT" for a in nba.get("final", []))
    if bool(sar.get("file")) != files_report:
        problems.append("sar.file disagrees with whether FILE_REPORT is in the final actions")
    if sar.get("file") and len(str(sar.get("narrative", "")).split()) < 60:
        problems.append("sar.narrative is too short to stand on its own")
    if not sar.get("file"):
        if sar.get("narrative") or sar.get("subjects") or sar.get("total_amount_usd") \
                or sar.get("activity_dates"):
            problems.append("sar.file is false but the SAR fields are not empty")

    for e in case.get("evidence", []):
        if e.get("source") not in SOURCES:
            problems.append(f"evidence source {e.get('source')!r} is not in the allowed set")
    if not case.get("evidence"):
        problems.append("case.evidence is empty")

    if known_txn_ids is not None:
        for t in case.get("affected_txn_ids", []):
            if str(t) not in known_txn_ids:
                problems.append(f"affected_txn_id {t} is not in the dataset")
        if case.get("first_suspicious_txn_id") and \
                str(case["first_suspicious_txn_id"]) not in known_txn_ids:
            problems.append(f"first_suspicious_txn_id {case['first_suspicious_txn_id']} "
                            f"is not in the dataset")
    if known_card_ids is not None:
        for c in case.get("connected_card_ids", []):
            if str(c) not in known_card_ids:
                problems.append(f"connected_card_id {c} is not in the dataset")
    if known_case_ids is not None:
        for c in case.get("similar_prior_cases", []):
            if str(c) not in known_case_ids:
                problems.append(f"similar_prior_case {c} is not in the dataset")

    exposure = float(case.get("exposure_usd") or 0)
    if sar.get("file") and abs(float(sar.get("total_amount_usd") or 0) - exposure) > 0.02:
        problems.append("sar.total_amount_usd does not match case.exposure_usd")
    return problems

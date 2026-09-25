"""The investigation nodes.

Reading order matches the flow:

    trigger_intake -> case_opener -> evidence_planner -> graph_retrieval
      -> memory_recall -> policy_grounding -> ledger_update
      -> uncertainty_assessor
           |                         \\
           | not enough               \\ enough
           v                           v
      record_provisional          action_recommender
           |                           |
      evidence_gap_resolver -----------+
           ^                           |
           +--- (max 3 rounds) ---------
                                       v
                                 permission_gate -> explainer
                                   -> case_writer -> memory_consolidator

The loop cap lives in code, not in a prompt. An uncapped agentic loop is the
most common way a project like this dies on stage.

Which nodes may call an LLM: `evidence_planner` (tool plan) and `explainer`
(prose). Nothing else. Every number, verdict, action and route on this page
comes out of `core/`.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from ..config import AGENT, SIM
from ..core import episode as episode_mod
from ..core import hypotheses as H
from ..core import policy_engine, stopping, voi
from ..core.evidence_ledger import EvidenceLedger, trigger_prior
from ..core.ledger import DecisionLedger
from ..core.policy_engine import CaseState
from ..core.signals import extract
from ..graphstore.base import GraphStore
from .llm import LLMClient
from .simulator import respond
from .state import InvestigationState, RequestRecord, Trigger

PLANNER_SYSTEM = (
    "You are the evidence planner for a fraud investigation agent that reads a TigerGraph "
    "knowledge graph through a fixed toolkit of graph primitives.\n"
    "Given a trigger, choose which primitives to run and say briefly why. You are selecting "
    "tools, not reaching conclusions: you do not assess risk, you do not name a fraud pattern, "
    "and you do not recommend actions.\n"
    'Reply as JSON: {"tools": ["..."], "rationale": "one sentence"}.'
)

TOOLKIT = [
    "card_baseline", "episode_window", "velocity_burst", "device_first_use",
    "device_fanout", "region_profile", "out_of_region_probe", "card_testing_probe",
    "threshold_structuring_probe", "mixed_channel_probe", "recurring_charge_probe",
    "email_mismatch_profile", "shared_entity_ring", "fraud_proximity",
    "behavioural_neighbours", "hybrid_case_recall", "policy_retrieve",
]


# 4,665 of the 5,565 closed investigations were confirmed fraud. Retrieval that
# reproduces that mix is uninformative; only departure from it is evidence.
CLOSED_CASE_FRAUD_BASE_RATE = 0.838

# Policy R1 turns on whether the case "rests on a single signal". That means a
# single signal *pointing at fraud* — counting exculpatory observations like
# "the amount is typical" toward the total would quietly switch off the very
# protection R1 exists to provide, on exactly the quiet cases it was written for.
# `risk_score_high` is excluded because R1 names it: a risk score alone is a
# single signal. `fraud_proximity` is excluded because it is a property of the
# neighbourhood rather than of this transaction.
CORROBORATING_SIGNALS: frozenset[str] = frozenset({
    "amount_anomalous", "amount_extreme", "device_new_on_account",
    "device_shared_across_cards", "device_proxy_hub", "anonymising_proxy",
    "region_unseen", "out_of_region_card_present", "home_activity_continues",
    "velocity_burst", "online_burst_2_to_4", "card_testing_sequence",
    "threshold_structuring", "mixed_channel_shift", "match_flag_anomaly",
    "email_mismatch", "shared_origin_ring", "behavioural_fraud_neighbourhood",
    "customer_disputed",
})


def _trace(state: InvestigationState, node: str, detail: dict[str, Any]) -> None:
    state.setdefault("trace", []).append(
        {"node": node, "at": round(time.time() - state["started_at"], 3), **detail})


# --------------------------------------------------------------------------- 1
def trigger_intake(state: InvestigationState, store: GraphStore,
                   llm: LLMClient) -> InvestigationState:
    t: Trigger = state["trigger"]
    state["as_of"] = t.opened_at
    state["round"] = 0
    state["requests"] = []
    state["customer_response"] = ""
    state["step_up_result"] = ""
    state["analyst_response"] = ""
    _trace(state, "trigger_intake",
           {"trigger_type": t.type, "flagged_txn_id": t.flagged_txn_id,
            "as_of": str(t.opened_at)})
    return state


# --------------------------------------------------------------------------- 2
def case_opener(state: InvestigationState, store: GraphStore,
                llm: LLMClient) -> InvestigationState:
    """Open the case and set the temporal wall. `as_of` never advances again."""
    state["graph_case_id"] = f"CASE-{state['case_id']}"
    state["decisions"] = DecisionLedger(state["case_id"])
    prior = trigger_prior(state["trigger"].type)
    state["ledger"] = EvidenceLedger(prior)
    state["decisions"].record(
        "case_opener", prior, prior,
        f"Case opened from a {state['trigger'].type} trigger with the temporal cutoff fixed at "
        f"{state['as_of']}. Prior over hypotheses is conditioned on how the alert arrived, not "
        f"on the bank model's score.",
        {"prior": {k: round(v, 4) for k, v in prior.items()}})
    _trace(state, "case_opener", {"graph_case_id": state["graph_case_id"],
                                  "prior_fraud": round(H.fraud_probability(prior), 4)})
    return state


# --------------------------------------------------------------------------- 3
def evidence_planner(state: InvestigationState, store: GraphStore,
                     llm: LLMClient) -> InvestigationState:
    """The LLM picks the tools. The toolkit is small and cheap, so the plan is
    recorded and the full set runs regardless — a planner that can silently
    skip the ring query is a planner that can silently miss a ring."""
    t = state["trigger"]
    plan = llm.complete_json(
        PLANNER_SYSTEM,
        f"Trigger type: {t.type}\nTrigger text: {t.text}\n"
        f"Flagged transaction: {t.flagged_txn_id} on card {t.card_id}\n"
        f"Available primitives: {', '.join(TOOLKIT)}\n"
        f"Which do you want, and why?")
    tools = [x for x in plan.get("tools", []) if x in TOOLKIT] or TOOLKIT
    state["plan"] = tools
    _trace(state, "evidence_planner",
           {"planned_tools": tools, "rationale": plan.get("rationale", ""),
            "llm_used": bool(plan)})
    return state


# --------------------------------------------------------------------------- 4
def graph_retrieval(state: InvestigationState, store: GraphStore,
                    llm: LLMClient) -> InvestigationState:
    t = state["trigger"]
    ctx = extract(store, state["case_id"], t.flagged_txn_id, t.card_id, t.customer_id,
                  state["as_of"], t.type)
    state["ctx"] = ctx
    _trace(state, "graph_retrieval",
           {"signals_fired": ctx.fired_names(), "tool_calls": ctx.tool_calls,
            "baseline_txns": ctx.baseline.get("n_txns", 0)})
    return state


# --------------------------------------------------------------------------- 5
def memory_recall(state: InvestigationState, store: GraphStore,
                  llm: LLMClient) -> InvestigationState:
    """Hybrid graph + vector recall over the closed cases, then fold the outcome
    mix of what came back into belief. Retrieval alone is not memory; memory is
    retrieval that changes the answer."""
    ctx = state["ctx"]
    query = _recall_query(ctx)
    priors = store.hybrid_case_recall(query, ctx.entity_ids(), state["as_of"], k=5)
    state["priors"] = priors

    ledger: EvidenceLedger = state["ledger"]
    if priors:
        strong = [p for p in priors if p.fused_score >= 0.30]
        if strong:
            n_fraud = sum(1 for p in strong if p.outcome == "confirmed_fraud")
            share = n_fraud / len(strong)
            pattern_votes: dict[str, int] = {}
            for p in strong:
                if p.outcome == "confirmed_fraud":
                    pattern_votes[p.pattern] = pattern_votes.get(p.pattern, 0) + 1
            # The closed-case file is 84% confirmed fraud because it is a case
            # file, not a sample of alerts. Recalling five fraud cases is the
            # base rate, not evidence — so the likelihood ratio is driven by how
            # far the recalled mix departs from that base rate, in either
            # direction, and recall that merely reproduces it moves nothing.
            base_rate = CLOSED_CASE_FRAUD_BASE_RATE
            lift = share - base_rate
            lrs = {h: 1.0 for h in H.HYPOTHESES}
            lrs[H.NONE] = max(0.45, min(2.2, 1.0 - 1.9 * lift))
            for pat, n in pattern_votes.items():
                if pat in lrs and share >= base_rate:
                    lrs[pat] = 1.0 + 0.35 * n * max(lift, 0.0) / max(1 - base_rate, 1e-6)
            before = ledger.snapshot()
            ledger.add(
                "memory_recall", "memory", lrs, 0.8,
                claim=(f"{len(strong)} closely matching closed investigations were retrieved by "
                       f"fusing narrative similarity with shared-entity overlap; "
                       f"{n_fraud} of them were confirmed fraud"
                       + (f", most often {max(pattern_votes, key=pattern_votes.get)}"
                          if pattern_votes else "")),
                ref=f"query:hybrid_case_recall(k=5, as_of={state['as_of']})",
                entity_ids=[p.case_id for p in strong])
            _trace(state, "memory_recall",
                   {"recalled": [p.case_id for p in strong],
                    "fraud_share": round(share, 3),
                    "p_fraud_before": round(sum(v for k, v in before.items() if k != "none"), 4),
                    "p_fraud_after": round(ledger.fraud_probability, 4)})
            return state
    _trace(state, "memory_recall", {"recalled": [p.case_id for p in priors]})
    return state


def _recall_query(ctx) -> str:
    """The text put to the narrative vector index. Built from what was actually
    measured, so recall keys on the shape of the activity rather than on a
    restatement of the alert."""
    f = ctx.flagged
    bits = [
        f"{f.channel.replace('_', ' ')} transaction of ${f.amount:,.2f}",
        f"product code {f.product_cd}",
        f"billing region {f.region}" if f.region else "",
        "device not previously seen on this account" if ctx.fired("device_new_on_account") else "",
        "anonymous proxy" if ctx.fired("anonymising_proxy") else "",
        "shared device profile across several cards" if ctx.fired("device_proxy_hub") else "",
        "small online authorisations followed by a larger purchase"
        if ctx.fired("card_testing_sequence") else "",
        "several online purchases just under an authorisation threshold"
        if ctx.fired("threshold_structuring") else "",
        "card present in a billing region with no history"
        if ctx.fired("out_of_region_card_present") else "",
        "mixed channel activity inconsistent with the cardholder"
        if ctx.fired("mixed_channel_shift") else "",
        "amount far outside the cardholder's usual range"
        if ctx.fired("amount_anomalous") else "",
        "cardholder reported unrecognized activity" if ctx.fired("customer_disputed") else "",
    ]
    return ", ".join(b for b in bits if b)


# --------------------------------------------------------------------------- 6
def policy_grounding(state: InvestigationState, store: GraphStore,
                     llm: LLMClient) -> InvestigationState:
    """GraphRAG over the bank's own documents: retrieve the clauses that govern
    this shape of activity, so the explanation cites text rather than paraphrase."""
    ctx = state["ctx"]
    docs = store.policy_retrieve(_recall_query(ctx), k=6,
                                 kinds={"policy_rule", "typology", "guidance"})
    state["policy_docs"] = docs
    _trace(state, "policy_grounding", {"retrieved": [d.get("doc_id") for d in docs]})
    return state


# --------------------------------------------------------------------------- 7
def ledger_update(state: InvestigationState, store: GraphStore,
                  llm: LLMClient) -> InvestigationState:
    """Fold every extracted signal into the posterior. Deterministic."""
    ctx = state["ctx"]
    ledger: EvidenceLedger = state["ledger"]
    before = ledger.snapshot()
    folded = 0
    for name in ctx.signals:
        if name == "customer_disputed":
            continue                  # already carried by the trigger-conditioned prior
        if ledger.add_signal(ctx.signals[name]) is not None:
            folded += 1
    state["decisions"].record(
        "ledger_update", before, ledger.snapshot(),
        f"Folded {folded} measured observations into the posterior. Fraud probability moved "
        f"from {sum(v for k, v in before.items() if k != 'none'):.3f} to "
        f"{ledger.fraud_probability:.3f}; leading hypothesis is {ledger.top_pattern}.",
        {"signals_fired": ctx.fired_names()})
    _trace(state, "ledger_update",
           {"folded": folded, "p_fraud": round(ledger.fraud_probability, 4),
            "posterior": ledger.snapshot(), "top": ledger.top_pattern,
            "movers": [(e.label, round(e.delta_fraud, 4)) for e in ledger.top_movers(5)]})
    return state


# --------------------------------------------------------------------------- 8
def uncertainty_assessor(state: InvestigationState, store: GraphStore,
                         llm: LLMClient) -> InvestigationState:
    """Score the evidence actions, then apply the two-sided stopping rule."""
    ledger: EvidenceLedger = state["ledger"]
    ctx = state["ctx"]
    decision = _interim_policy(state)

    def permits(action: voi.EvidenceAction) -> tuple[bool, str]:
        # The policy constrains *asking*, not only acting. Contact fatigue is a
        # real control and it belongs here rather than in a prompt.
        if action.key == "customer_validation":
            if state["customer_response"]:
                return False, "the cardholder has already answered this case"
            if len([r for r in state["requests"] if r.type == "customer_validation"]) >= 2:
                return False, "contact-fatigue limit: two customer contacts in this window"
            if "VERIFY_WITH_CUSTOMER" not in decision.action_names() \
                    and "CLOSE_NO_FRAUD" in decision.action_names():
                return False, "policy already resolves this case without contacting the customer"
        if action.key == "step_up_auth" and state["step_up_result"]:
            return False, "step-up authentication has already been run on this case"
        if action.key == "analyst_info":
            if state["analyst_response"]:
                return False, "the analyst queue has already answered"
            if not (ctx.fired("shared_origin_ring") or ctx.fired("device_proxy_hub")):
                return False, "no shared origin to ask an analyst about"
        return True, ""

    best, ranking = voi.select(ledger.posterior, permits)
    state["voi_ranking"] = [s.as_dict() for s in ranking]
    best_ratio = best.ratio if best else 0.0

    n_independent = sum(1 for e in ledger.entries if abs(e.delta_fraud) >= 0.02)
    settled = state["customer_response"] in {"customer_confirmed", "customer_denied"}
    # The reported posterior, not the raw one: the confidence ceiling is part
    # of what the agent is willing to claim, so the reason it gives for stopping
    # must quote the same number the answer file reports.
    stop = stopping.evaluate(
        ledger.reported(), n_independent, state["round"], best_ratio,
        time.time() - state["started_at"], customer_settled=settled)
    state["stop"] = stop
    _trace(state, "uncertainty_assessor",
           {"p_fraud": round(ledger.fraud_probability, 4),
            "margin": round(ledger.margin, 4), "entropy": round(ledger.entropy(), 4),
            "independent_evidence": n_independent, "round": state["round"],
            "best_voi": round(best_ratio, 4), "stop": stop.as_dict(),
            "voi_ranking": state["voi_ranking"]})
    return state


# --------------------------------------------------------------------------- 9
def record_provisional(state: InvestigationState, store: GraphStore,
                       llm: LLMClient) -> InvestigationState:
    """The PROVISIONAL recommendation, recorded *before* any evidence is
    requested. The submission format demands this pair explicitly, and it can
    only be produced honestly by an agent that commits under uncertainty and
    then revises."""
    if state.get("initial_decision") is not None:
        return state
    decision = _interim_policy(state)

    # The provisional recommendation has to include the thing the agent is
    # about to do. Recording "escalate to an analyst" and then, in the next
    # breath, texting the cardholder leaves a case file whose actions and whose
    # evidence requests describe two different investigations. Policy §5 lets
    # the agent ask without approval, so the ask belongs in the recommendation
    # at route `auto`.
    pending = next((r for r in state.get("voi_ranking", []) if r["permitted"]), None)
    if pending:
        ask = {"customer_validation": ("VERIFY_WITH_CUSTOMER",
                                       "§5: ask the cardholder to validate the transaction "
                                       "before any action that would inconvenience them"),
               "step_up_auth": ("STEP_UP_AUTH",
                                "§5: challenge the session before acting on the alert"),
               "analyst_info": ("ESCALATE_TO_ANALYST",
                                "§5: request prior-relationship context from an analyst")
               }.get(pending["type"])
        if ask and ask[0] not in decision.action_names():
            from ..core.permissions import route as route_action
            decision.actions.insert(0, route_action(ask[0], ask[1]))

    state["initial_decision"] = decision
    ledger: EvidenceLedger = state["ledger"]
    state["decisions"].record(
        "record_provisional", ledger.snapshot(), ledger.snapshot(),
        "Provisional recommendation recorded before any additional evidence was requested: "
        + ", ".join(f"{a.action}({a.route})" for a in decision.actions),
        {"actions": decision.as_list(), "cited_rules": decision.cited_rules})
    _trace(state, "record_provisional",
           {"actions": decision.as_list(), "cited_rules": decision.cited_rules,
            "p_fraud": round(ledger.fraud_probability, 4)})
    return state


# -------------------------------------------------------------------------- 10
def evidence_gap_resolver(state: InvestigationState, store: GraphStore,
                          llm: LLMClient) -> InvestigationState:
    """Dispatch the single highest-value permitted evidence action, take the
    simulated response, and re-reason."""
    ledger: EvidenceLedger = state["ledger"]
    ranking = state["voi_ranking"]
    chosen = next((r for r in ranking if r["permitted"]), None)
    if chosen is None:
        state["round"] = AGENT.max_evidence_rounds
        return state
    action = next(a for a in voi.CATALOGUE if a.key == chosen["type"])

    before = ledger.snapshot()
    ctx = state["ctx"]
    recurring = (ctx.probes.get("recurring", {})
                 if ctx.trigger_type == "customer_report" and ctx.fired("recurring_charge")
                 else None)
    sim = respond(state["case_id"], action, ledger.posterior, recurring=recurring,
                  amount=ctx.flagged.amount)
    ledger.add_solicited(sim.outcome_key,
                         claim=sim.assumed_response,
                         ref=f"evidence_request:{len(state['requests']) + 1}",
                         reliability=action.reliability)

    if sim.outcome_key.startswith("customer_"):
        state["customer_response"] = sim.outcome_key
    elif sim.outcome_key.startswith("step_up"):
        state["step_up_result"] = "passed" if sim.outcome_key.endswith("passed") else "failed"
    else:
        state["analyst_response"] = sim.outcome_key

    record = RequestRecord(
        type=action.key, name=action.name, channel=action.channel,
        question=action.question, asked_after_step=len(state["decisions"].decisions),
        expected_info_gain=chosen["expected_info_gain"], cost=chosen["cost"],
        outcome=sim.outcome_key, assumed_response=sim.assumed_response,
        simulation_seed=sim.seed, posterior_before=before,
        posterior_after=ledger.snapshot())
    state["requests"].append(record)
    state["round"] += 1

    state["decisions"].record(
        "evidence_gap_resolver", before, ledger.snapshot(),
        f"Requested {action.name} via {action.channel}; response {sim.response_text}. "
        f"Fraud probability moved from "
        f"{sum(v for k, v in before.items() if k != 'none'):.3f} to "
        f"{ledger.fraud_probability:.3f}.",
        {"request": record.as_dict(), "simulation_seed": sim.seed,
         "global_seed": SIM.seed})
    _trace(state, "evidence_gap_resolver",
           {"requested": action.key, "response": sim.response_text,
            "p_fraud_before": round(sum(v for k, v in before.items() if k != "none"), 4),
            "p_fraud_after": round(ledger.fraud_probability, 4),
            "round": state["round"]})
    return state


# -------------------------------------------------------------------------- 11
def action_recommender(state: InvestigationState, store: GraphStore,
                       llm: LLMClient) -> InvestigationState:
    """The final recommendation, after everything that was going to arrive has."""
    ledger: EvidenceLedger = state["ledger"]
    ctx = state["ctx"]
    verdict = policy_engine.verdict_for(ledger.posterior, AGENT)
    pattern, sub = _pattern_for(state, verdict)
    state["verdict"] = verdict
    state["pattern"] = pattern
    state["sub_typology"] = sub
    state["episode"] = episode_mod.build(store, ctx, pattern, verdict)

    decision = _policy_for(state, final=True)
    state["final_decision"] = decision
    if state.get("initial_decision") is None:
        state["initial_decision"] = decision

    state["decisions"].record(
        "action_recommender", ledger.snapshot(), ledger.snapshot(),
        f"Final recommendation: " + ", ".join(
            f"{a.action}({a.route})" for a in decision.actions)
        + f". Verdict {verdict}, pattern {pattern}, exposure "
          f"${state['episode'].exposure_usd:,.2f}.",
        {"actions": decision.as_list(), "cited_rules": decision.cited_rules,
         "verdict": verdict, "pattern": pattern})
    _trace(state, "action_recommender",
           {"verdict": verdict, "pattern": pattern,
            "exposure": round(state["episode"].exposure_usd, 2),
            "actions": decision.as_list(), "cited_rules": decision.cited_rules})
    return state


# -------------------------------------------------------------------------- 12
def permission_gate(state: InvestigationState, store: GraphStore,
                    llm: LLMClient) -> InvestigationState:
    """Execute what the agent is allowed to execute; route the rest and wait.

    The gate is deterministic code with no LLM anywhere near it. An agent that
    can be *argued* into executing a block is not a control.
    """
    from ..core.permissions import may_execute
    from ..mcp_servers.simulated_actions import execute

    executed: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for a in state["final_decision"].actions:
        if may_execute(a.action):
            executed.append(execute(a.action, state["case_id"],
                                    state["trigger"].card_id, state["trigger"].customer_id))
        else:
            pending.append({"action": a.action, "route": a.route,
                            "awaiting": {"L1": "team lead", "L2": "fraud manager"}[a.route]})
    state.setdefault("result", {})["executed_actions"] = executed
    state["result"]["pending_approval"] = pending
    _trace(state, "permission_gate",
           {"executed": [e["action"] for e in executed],
            "pending_approval": pending})
    return state


# -------------------------------------------------------------------------- 13
def explainer(state: InvestigationState, store: GraphStore,
              llm: LLMClient) -> InvestigationState:
    """Prose. The only node besides the planner that may call a model, and it is
    handed a brief in which every figure is already fixed."""
    from ..report import narrative as narr

    ctx = state["ctx"]
    ledger: EvidenceLedger = state["ledger"]
    ep = state["episode"]
    evidence = _evidence_entries(state)
    actions = {"initial": state["initial_decision"].as_list(),
               "final": state["final_decision"].as_list()}
    what_changed = _what_changed(state)

    summary = narr.case_summary(llm, ctx, state["pattern"], state["verdict"],
                                ledger.fraud_probability, ep, evidence,
                                state["priors"], actions, what_changed,
                                state["stop"].reason)
    pattern_description = ""
    if state["pattern"] == H.UNDOCUMENTED and state["sub_typology"]:
        probe = (ctx.probes.get("threshold_structuring", {})
                 if state["sub_typology"] == "threshold_structuring"
                 else ctx.probes.get("device_fanout", {}))
        pattern_description = narr.pattern_description(llm, ctx, state["sub_typology"], probe)

    remaining, counterfactual = _uncertainty_text(state)
    state["narrative"] = {
        "summary": summary,
        "pattern_description": pattern_description,
        "explanation": narr.explanation(
            llm, ctx, ledger.fraud_probability, evidence,
            [r.as_dict() for r in state["requests"]], actions,
            state["stop"].reason, remaining, counterfactual),
        "what_changed": what_changed,
    }
    _trace(state, "explainer", {"summary_chars": len(summary),
                                "llm_used": bool(llm.available)})
    return state


# -------------------------------------------------------------------------- 14
def case_writer(state: InvestigationState, store: GraphStore,
                llm: LLMClient) -> InvestigationState:
    """Write the case to the graph and build the answer file from one payload.

    Same dict, both destinations. The dataset asks for the case in the answer
    file *and* in the graph; building them from one object is what stops them
    drifting apart on the run that matters.
    """
    from ..report.answer import build_answer

    answer, graph_payload = build_answer(state, store)
    gid = store.write_case(graph_payload)
    check = _verify_write(store, gid, answer)
    # A write that returned is not a write that happened: the case only counts
    # as written once it reads back from the graph.
    answer["case"]["written_to_graph"] = check["read_back"]
    answer.setdefault("agent_record", {})["write_verification"] = check
    answer["case"]["graph_case_id"] = gid
    state["graph_case_id"] = gid
    state.setdefault("result", {}).update(answer)
    _trace(state, "case_writer", {"graph_case_id": gid,
                                  "affected_txns": len(answer["case"]["affected_txn_ids"]),
                                  "sar_filed": answer["sar"]["file"]})
    return state


def _verify_write(store: GraphStore, gid: str, answer: dict[str, Any]) -> dict[str, Any]:
    """Read the case back with `case_chain` and compare what landed against what
    was sent: the affected transactions, the connected cards and the SAR."""
    try:
        chain = store.case_chain(gid) or {}
    except Exception as exc:                            # pragma: no cover - network
        return {"read_back": False, "error": str(exc)}
    if "investigation" not in chain:                    # local mirror: the case record itself
        return {"read_back": bool(chain), "checks": {}, "mismatches": []}
    count = lambda k: len(chain.get(k) or [])
    case = answer["case"]
    checks = {
        "case_vertex": count("investigation") == 1,
        "affected_transactions": count("affected_transactions") == len(case["affected_txn_ids"]),
        "connected_cards": count("connected_cards") == len(case["connected_card_ids"]),
        "sar_linked": (count("suspicious_activity_report") >= 1) if answer["sar"]["file"] else True,
        "evidence_linked": count("evidence") >= 1,
    }
    return {"read_back": checks["case_vertex"], "checks": checks,
            "mismatches": [k for k, ok in checks.items() if not ok],
            "counts": {k: count(k) for k in ("evidence", "decisions", "recommended_actions",
                                               "affected_transactions", "connected_cards",
                                               "prior_cases_used", "policy_cited")}}


# -------------------------------------------------------------------------- 15
def memory_consolidator(state: InvestigationState, store: GraphStore,
                        llm: LLMClient) -> InvestigationState:
    """Fold this case back into memory so the next investigation can find it,
    and verify the audit chain before the case leaves the agent."""
    ok, msg = state["decisions"].verify()
    state.setdefault("result", {})["audit_chain"] = {"intact": ok, "detail": msg,
                                                     "head": state["decisions"].head}
    _trace(state, "memory_consolidator",
           {"audit_chain_intact": ok, "decisions": len(state["decisions"].decisions)})
    return state


# ------------------------------------------------------------------ helpers --
def _pattern_for(state: InvestigationState, verdict: str) -> tuple[str, str]:
    """The reported pattern. `none` whenever the verdict is legitimate, so the
    answer file can never claim a typology it has just cleared."""
    ctx = state["ctx"]
    ledger: EvidenceLedger = state["ledger"]
    if verdict == "legitimate":
        return H.NONE, ""
    # hard matchers win over the posterior: their signature is near-deterministic
    if ctx.fired("threshold_structuring"):
        return H.UNDOCUMENTED, "threshold_structuring"
    ring = ctx.probes.get("ring", {})
    if ctx.fired("device_proxy_hub") and len(ring.get("connected_card_ids", [])) >= 3:
        return H.UNDOCUMENTED, "device_hub_ring"
    if ctx.fired("card_testing_sequence"):
        return H.CARD_TESTING, ""
    ranked = sorted(((h, p) for h, p in ledger.posterior.items() if h != H.NONE),
                    key=lambda kv: -kv[1])
    top = ranked[0][0] if ranked else H.CNP
    if verdict == "uncertain" and ledger.fraud_probability < AGENT.t_monitor:
        return H.NONE, ""
    return top, ""


def _case_state(state: InvestigationState, final: bool) -> CaseState:
    ctx = state["ctx"]
    ledger: EvidenceLedger = state["ledger"]
    ep = state.get("episode")
    exposure = ep.exposure_usd if (final and ep) else _interim_exposure(state)
    connected = list(ep.connected_card_ids) if (final and ep) else (
        list(ctx.probes.get("ring", {}).get("connected_card_ids", []))
        if ctx.fired("shared_origin_ring") else [])
    p_fraud = ledger.fraud_probability
    verdict = state.get("verdict") if final else policy_engine.verdict_for(
        ledger.posterior, AGENT)
    pattern = state.get("pattern") if final else _pattern_for(state, verdict)[0]
    testing = ctx.probes.get("card_testing", {})
    fired = set(ctx.fired_names())
    corroborating = fired & CORROBORATING_SIGNALS
    return CaseState(
        case_id=state["case_id"],
        trigger_type=state["trigger"].type,
        fraud_probability=p_fraud,
        verdict=verdict,
        pattern=pattern,
        exposure_usd=exposure,
        n_independent_evidence=sum(1 for e in ledger.entries if abs(e.delta_fraud) >= 0.02),
        single_signal_only=len(corroborating) <= 1,
        customer_response={"customer_denied": "denied", "customer_confirmed": "confirmed",
                           "customer_no_response": "no_response"}.get(
            state.get("customer_response", ""), ""),
        step_up_result=state.get("step_up_result", ""),
        connected_card_ids=connected,
        connected_device_profiles=(list(ep.connected_device_profiles) if (final and ep) else []),
        shares_origin_with_other_fraud=bool(
            ctx.fired("shared_origin_ring") or ctx.fired("device_proxy_hub")),
        card_testing_matched=ctx.fired("card_testing_sequence"),
        card_testing_cleared_over_100=bool(testing.get("follow_amount", 0.0) > 100.0),
        recurring_charge_match=ctx.fired("recurring_charge"),
        coordinated_or_undocumented=(pattern == H.UNDOCUMENTED),
        conflicting_evidence=bool(ledger.contradictions()),
        cards_with_confirmed_fraud=0,
        credentials_confirmed_compromised=(state.get("step_up_result") == "failed"),
        contacts_in_window=len([r for r in state["requests"]
                                if r.type == "customer_validation"]),
        evidence_requested=bool(state["requests"]),
        has_pending_authorisation=True,
    )


def _interim_exposure(state: InvestigationState) -> float:
    """Exposure before the episode is reconstructed: the suspect window's value,
    which is the most an analyst could reasonably be worried about at that point."""
    ctx = state["ctx"]
    ledger: EvidenceLedger = state["ledger"]
    if ledger.fraud_probability < AGENT.t_monitor:
        return 0.0
    ep = ctx.probes.get("episode", {})
    return float(ep.get("window_value_usd", ctx.flagged.amount) or ctx.flagged.amount)


def _interim_policy(state: InvestigationState):
    return policy_engine.evaluate(_case_state(state, final=False))


def _policy_for(state: InvestigationState, final: bool):
    return policy_engine.evaluate(_case_state(state, final=final))


def _evidence_entries(state: InvestigationState) -> list[dict[str, Any]]:
    """The answer file's evidence list: claim, source, ref, entity ids — plus the
    measured movement in belief, so a reader can see which evidence mattered."""
    ctx = state["ctx"]
    ledger: EvidenceLedger = state["ledger"]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in sorted(ledger.entries, key=lambda e: -abs(e.delta_fraud)):
        if not entry.claim or entry.claim.startswith("NOT observed"):
            continue
        if entry.label in seen:
            continue
        seen.add(entry.label)
        source = {"solicited": "customer", "memory": "graph",
                  "structural": "graph", "measured": "graph"}.get(entry.source, "graph")
        if entry.label.startswith("analyst"):
            source = "external"
        out.append({
            "claim": entry.claim,
            "source": source,
            "ref": entry.ref,
            "entity_ids": [str(e) for e in entry.entity_ids][:12],
            "delta_fraud_probability": round(entry.delta_fraud, 4),
            "reliability": entry.reliability,
            "claim_type": _claim_type(entry),
        })
        if len(out) >= 10:
            break
    for doc in state.get("policy_docs", [])[:2]:
        out.append({
            "claim": f"{doc.get('title', '')} governs this case: "
                     f"{str(doc.get('text', ''))[:240]}",
            "source": "document",
            "ref": f"policy:{doc.get('doc_id', '')}",
            "entity_ids": [],
            "claim_type": "policy_text",
        })
    return out


def _claim_type(entry: Any) -> str:
    """What kind of statement an evidence item is, so a reader never mistakes an
    inference for an observation: a fact retrieved from the graph, a conclusion a
    detector drew from several facts, the bank's model score, the customer's own
    statement, or a simulated reply."""
    label = entry.label or ""
    if entry.source == "solicited":
        return "simulated_response"
    if "risk_score" in label:
        return "model_score"
    if label == "customer_disputed":
        return "customer_statement"
    if entry.source == "memory":
        return "observed_fact"
    return "derived_inference"


def _what_changed(state: InvestigationState) -> str:
    if not state["requests"]:
        return "nothing"
    initial = {a.action for a in state["initial_decision"].actions}
    final = {a.action for a in state["final_decision"].actions}
    added, dropped = sorted(final - initial), sorted(initial - final)
    r = state["requests"][-1]
    p0 = sum(v for k, v in r.posterior_before.items() if k != H.NONE)
    p1 = state["ledger"].fraud_probability
    if not added and not dropped:
        return (f"{r.name} returned {r.outcome.replace('_', ' ')}, moving fraud probability from "
                f"{p0:.2f} to {p1:.2f}, which was not enough to change the recommended actions.")
    bits = []
    if added:
        bits.append("added " + ", ".join(added))
    if dropped:
        bits.append("dropped " + ", ".join(dropped))
    return (f"{r.name} returned {r.outcome.replace('_', ' ')}, moving fraud probability from "
            f"{p0:.2f} to {p1:.2f}; the recommendation " + " and ".join(bits) + ".")


def _uncertainty_text(state: InvestigationState) -> tuple[str, str]:
    ledger: EvidenceLedger = state["ledger"]
    (h1, p1), (h2, p2) = H.top_two(ledger.posterior)
    conflicts = ledger.contradictions()
    remaining = (f"{H.SHORT_LABELS.get(h1, h1)} leads {H.SHORT_LABELS.get(h2, h2)} by "
                 f"{p1 - p2:.2f}; the two are not fully separated.")
    if conflicts:
        remaining += (" Evidence conflicts: "
                      + "; ".join(f"{a} against {b}" for a, b in conflicts[:2]) + ".")
    if state["stop"].reason_code == stopping.EXHAUSTED:
        remaining += (" No further permitted evidence would repay its cost, so the residual "
                      "uncertainty is carried rather than resolved.")

    ranking = state.get("voi_ranking") or []
    top = next((r for r in ranking if r["permitted"]), None)
    if top is None:
        return remaining, "No permitted evidence action would move the decision."
    action = next(a for a in voi.CATALOGUE if a.key == top["type"])
    outcomes = list(action.outcome_distribution(ledger.posterior))
    if not outcomes:
        return remaining, "No counterfactual available."
    # Report the outcome that would move belief *most*, not the first two in
    # dictionary order — "either answer leaves it at 0.99" is a true statement
    # and a useless one.
    current = ledger.fraud_probability
    scored = []
    for outcome in outcomes:
        post = voi.counterfactual(ledger.posterior, action, outcome)
        p = H.fraud_probability(post)
        scored.append((abs(p - current), outcome, p))
    scored.sort(reverse=True)
    lines = [f"had {action.name.lower()} returned {o.replace('_', ' ')}, fraud probability "
             f"would move from {current:.2f} to {p:.2f}" for _, o, p in scored[:2]]
    return remaining, "What would change the decision: " + "; ".join(lines) + "."

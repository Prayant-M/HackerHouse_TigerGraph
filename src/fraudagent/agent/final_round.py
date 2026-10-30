"""The final-round decision layers, applied in a fixed order after the policy
core has produced its recommendation:

    policy core (threshold verdict)
      -> conformal abstention (widen-only; Innovation 4, C11 taint)
      -> proof object over the facts (Innovation 1)
      -> proof gate (one-way: may only remove harm)
      -> predictive containment for ring cases (Innovation 2, C7)

Every layer is deterministic, LLM-free, and records what it saw and what it
changed, so `what changed and why` is always stated in the answer file.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any

import numpy as np

from ..config import AGENT, PATHS
from ..core import conformal, containment, proof, quality
from ..core.policy_engine import CaseState, PolicyDecision
from ..core.signals import SIGNAL_NAMES

JANUARY = datetime(2017, 1, 1)

# Signals the bank's own alert history taught the agent to read as "a false
# alarm". That history came from a model which had seen the data; for January
# it has not, so in the January regime these carry no weight (LR = 1).
RISK_PRIOR_SIGNALS = frozenset({"matches_cleared_alert_template"})


def january(as_of: datetime) -> bool:
    return as_of >= JANUARY


def soften_prior(prior: dict[str, float], trigger_type: str, as_of: datetime) -> dict[str, float]:
    """For January risk-score alerts, the operating P(legitimate) of 0.62 was
    learned from a model that had seen the data. Soften it to 0.50: a low score
    is not evidence of innocence."""
    if not january(as_of) or trigger_type != "risk_score":
        return prior
    p_none = prior.get("none", 0.0)
    target = min(p_none, 0.50)
    if p_none <= 0 or p_none >= 1 or target == p_none:
        return prior
    scale = (1 - target) / (1 - p_none)
    out = {h: (v * scale if h != "none" else target) for h, v in prior.items()}
    return out


# ------------------------------------------------------------- support ----
@lru_cache(maxsize=1)
def _behaviour_table() -> tuple[dict[str, int], np.ndarray] | None:
    import pandas as pd

    if not PATHS.behaviour_parquet.exists():
        return None
    b = pd.read_parquet(PATHS.behaviour_parquet)
    idx = {t: i for i, t in enumerate(b["txn_id"].astype(str))}
    return idx, np.vstack(b["behaviour_emb"].to_numpy()).astype(np.float32)


def behaviour_vec(store, txn_id: str) -> np.ndarray | None:
    v = store.behaviour_vector(txn_id)
    return None if v is None else np.asarray(v, dtype=np.float32)


# ------------------------------------------------------------ conformal ----
def conformal_layer(state, store, verdict: str) -> tuple[str, dict[str, Any]]:
    ctx = state["ctx"]
    q = quality.assess(ctx)
    tf = (state.get("text_facts") or {}).get("facts", {})
    settled = (state.get("customer_response") in {"customer_confirmed", "customer_denied"}
               or (state["trigger"].type == "customer_report"
                   and bool(tf.get("text_denies_charge"))))
    rec = conformal.assess(float(state.get("p_graph_only", state["ledger"].fraud_probability)),
                           behaviour_vec(store, ctx.flagged.txn_id), q.tainted, settled)
    new, why = conformal.apply(verdict, rec)
    rec["verdict_before"], rec["verdict_after"], rec["reason"] = verdict, new, why
    state["quality"] = q.as_dict()
    state["conformal"] = rec
    return new, rec


# ---------------------------------------------------------------- proof ----
def fact_context(state, base: CaseState) -> tuple[list[str], proof.FactContext, dict[str, float]]:
    ctx = state["ctx"]
    ledger = state["ledger"]
    fired = [n for n in ctx.signals if ctx.signals[n].fired and n != "customer_disputed"]
    if january(state["as_of"]):
        fired = [n for n in fired if n not in RISK_PRIOR_SIGNALS]
    memory = {e.label: dict(e.likelihood_ratios) for e in ledger.entries if e.source == "memory"}
    solicited = {e.label: e.reliability for e in ledger.entries if e.source == "solicited"}
    deltas = {e.label: e.delta_fraud for e in ledger.entries}
    facts = fired + list(memory) + [k for k in solicited if k in proof.SOLICITED_FACTS]
    ep = state.get("episode")
    cr = state.get("conformal") or {}
    order = [n for n in ctx.signals if not (january(state["as_of"]) and n in RISK_PRIOR_SIGNALS)]
    fc = proof.FactContext(
        trigger_type=state["trigger"].type,
        signal_order=order,
        strengths={n: s.strength for n, s in ctx.signals.items()},
        memory_lrs=memory, solicited_reliability=solicited, base=base,
        exposure_usd=float(ep.exposure_usd if ep else 0.0),
        ring_size=len(ctx.probes.get("ring", {}).get("connected_card_ids", [])),
        connected_card_ids=list(ep.connected_card_ids) if ep else [],
        prior=ledger.prior,
        conformal=bool(cr.get("available")),
        widened=bool(set(cr.get("widened_by") or [])),
        feedback={a["signal"]: a["factor"] for a in state.get("feedback_applied", [])},
        text_denied=(state["trigger"].type == "customer_report" and bool(
            ((state.get("text_facts") or {}).get("facts") or {}).get("text_denies_charge"))),
    )
    proof.with_fired(fc, set(fired))
    return facts, fc, deltas


def proof_and_gate(state, decision: PolicyDecision, base: CaseState
                   ) -> tuple[PolicyDecision, dict[str, Any], dict[str, Any]]:
    facts, fc, deltas = fact_context(state, base)
    pr = proof.build_proof(facts, fc, decision.action_names(), state["as_of"], deltas)
    # Precedent from the graph when the backend can answer it (installed
    # precedent_by_facts), otherwise from the local replay table.
    store = state.get("_store")
    graph_prec = None
    if store is not None and pr["precedent"].get("matched_facts"):
        # Through the store, so the call is recorded and replayable. On
        # TigerGraph this is the installed precedent_by_facts query; it returns
        # n=0 until ClosedCase.fact_mask is loaded, in which case the local
        # replay table answers and the source says so.
        graph_prec = store.precedent_by_facts(
            proof.mask_of(pr["precedent"]["matched_facts"]), state["as_of"])
    if graph_prec is not None and (graph_prec.get("n") or getattr(store, "backend", "") != "tigergraph"):
        n = graph_prec["n"]
        pr["precedent"].update(n=n, confirmed=graph_prec["confirmed"],
                               cleared=graph_prec["cleared"],
                               cleared_share=round(graph_prec["cleared"] / n, 3) if n else None,
                               case_ids=graph_prec.get("case_ids", [])[-12:],
                               source=f"{getattr(store, 'backend', '?')}:precedent_by_facts")
    else:
        pr["precedent"].setdefault("source", "local:closed_case_facts")
    # R2: "the customer has denied the charge". A customer report whose text
    # denies it (the allow-listed extractor fact) is that denial, as much as a
    # denial in reply to our own question; policy then requires the block, so
    # the gate records the margin but does not remove it. An injected "it was
    # me" cannot revoke it: hostile spans are stripped before facts are read.
    tf = (state.get("text_facts") or {}).get("facts", {})
    denied = (state.get("customer_response") == "customer_denied"
              or (state["trigger"].type == "customer_report"
                  and bool(tf.get("text_denies_charge"))
                  and state.get("customer_response") != "customer_confirmed"))
    gated, gate_rec = proof.gate(pr, decision, customer_denied=denied,
                                 exposure_usd=base.exposure_usd)
    return gated, pr, gate_rec


# ---------------------------------------------------------- containment ----
def containment_layer(state, store) -> dict[str, Any] | None:
    ctx = state["ctx"]
    ep = state["episode"]
    ring = list(ep.connected_card_ids)
    if not ring and not (ctx.fired("shared_origin_ring") or ctx.fired("device_proxy_hub")):
        return None
    t = state["trigger"]
    plan = containment.plan(store, t.card_id, t.customer_id, ring, state["as_of"],
                            list(ep.affected_txn_ids), float(ep.exposure_usd),
                            state["verdict"] == "fraud")
    return plan


def watch_children(plan: dict[str, Any] | None, graph_case_id: str) -> list[dict[str, Any]]:
    if not plan:
        return []
    return [{"id": f"{graph_case_id}-WATCH-{c['card_id']}", "card_id": c["card_id"],
             "customer_id": c.get("customer_id", ""),
             "reason": (f"touched compromise origin {plan['origin']['entity_type']} "
                        f"{plan['origin']['entity'][:60]} (lift {plan['origin']['lift']}) on "
                        f"{c['last_touch']}; monitor and step up on next card-not-present")}
            for c in plan.get("at_risk", [])[:25]]


# ---------------------------------------------------------- lifecycle ----
def lifecycle(state, answer: dict[str, Any]) -> list[dict[str, Any]]:
    """C14: the case as a record with a life. Each transition names the evidence
    that caused it and who must approve what comes next."""
    at = str(state["as_of"])[:19]
    out = [{"from": "", "to": "OPENED", "at": at, "actor": "agent", "role": "agent",
            "reason": f"opened from a {state['trigger'].type} trigger",
            "evidence_ids": [state["trigger"].flagged_txn_id]}]
    for r in state.get("requests", []):
        out.append({"from": "OPENED" if len(out) == 1 else out[-1]["to"],
                    "to": "AWAITING_EVIDENCE", "at": at, "actor": "agent", "role": "agent",
                    "reason": f"requested {r.type}; simulated reply {r.outcome}",
                    "evidence_ids": [f"evidence_request:{r.asked_after_step}"]})
    final = answer["next_best_actions"]["final"]
    pending = [a for a in final if a["route"] != "auto"]
    status = answer["case"]["status"]
    to = {"escalated": "ESCALATED", "closed_fraud": "PENDING_APPROVAL" if pending else
          "CLOSED_FRAUD", "closed_legitimate": "CLOSED_LEGITIMATE", "open": "OPEN"}[status]
    ev_ids = [e["entity_ids"][0] for e in answer["case"]["evidence"] if e.get("entity_ids")][:8]
    out.append({"from": out[-1]["to"], "to": to, "at": at, "actor": "agent", "role": "agent",
                "reason": answer["next_best_actions"]["what_changed"] if state.get("requests")
                else answer["stop_reason"][:300], "evidence_ids": ev_ids})
    return out


def handover(state, answer: dict[str, Any]) -> dict[str, Any]:
    """What an analyst taking the case over cold needs: where it stands, what it
    waits on, what was decided and by whom."""
    final = answer["next_best_actions"]["final"]
    role = {"L1": "team lead", "L2": "fraud manager"}
    waiting = [f"{a['action']} needs {role[a['route']]} approval ({a['route']})"
               for a in final if a["route"] != "auto"]
    plan = answer["agent_record"].get("containment") or {}
    if plan.get("at_risk"):
        waiting.append(f"{len(plan['at_risk'])} WATCH child cases on at-risk cards")
    return {
        "state": answer["case"]["status"],
        "waiting_on": waiting,
        "decided_by_agent": [a["action"] for a in final if a["route"] == "auto"],
        "open_questions": answer["agent_record"].get("open_questions", []),
        "what_changed": answer["next_best_actions"]["what_changed"],
        "proof_margin": (answer["agent_record"].get("proof") or {}).get("margin_k"),
        "gate": (answer["agent_record"].get("gate") or {}).get("reason", ""),
    }


def signal_names() -> tuple[str, ...]:
    return SIGNAL_NAMES


__all__ = ["january", "soften_prior", "conformal_layer", "proof_and_gate",
           "containment_layer", "watch_children", "lifecycle", "handover", "AGENT"]

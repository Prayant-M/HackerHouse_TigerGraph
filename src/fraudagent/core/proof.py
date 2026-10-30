"""Proof-carrying verdicts.

The decision core is a pure function with no LLM, so the reason for an action
can be *computed* rather than written as prose. Every answer carries:

* **minimal sufficient facts** — the smallest subset of the case's attested
  facts that, with every other fact set to neutral (likelihood ratio 1), still
  yields the same action class (an abductive / prime-implicant explanation);
* **flip set and margin k** — the smallest set of facts whose removal changes
  the action class; k is its size;
* **precedent support** — closed cases whose replayed fact vector contains the
  minimal set, with how the bank ruled on them (as_of-bounded);
* **the gate** — a harmful action (block, block-all, report) resting on k = 1,
  or contradicted by precedent, is downgraded to the strongest free action plus
  ESCALATE_TO_ANALYST before anyone is wronged. R2 (cardholder denied) is
  exempt because policy requires the block. The gate is one-way: it can only
  remove harm, never add it.

`decide()` rebuilds the evidence ledger from a fact set using the *same*
`EvidenceLedger.add_signal` / `add_solicited` the agent used, in the same
order, so on the full fact set it reproduces the live decision; the proof
records whether it did (`reproduces_live`).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import combinations
from typing import Any, Iterable

from ..config import AGENT, PATHS
from . import hypotheses as H
from . import policy_engine
from .evidence_ledger import EvidenceLedger, trigger_prior
from .policy_engine import CaseState, PolicyDecision
from .signals import SIGNAL_NAMES, Signal

SOLICITED_FACTS: tuple[str, ...] = (
    "customer_denied", "customer_confirmed", "customer_no_response",
    "step_up_passed", "step_up_failed",
    "analyst_confirms_ring", "analyst_no_prior_relationship",
)
MEMORY_FACT = "precedent_recall"

# Bit positions are fixed by this tuple; ClosedCase.fact_mask in the graph uses them.
FACT_BITS: tuple[str, ...] = SIGNAL_NAMES

HARMFUL = ("BLOCK_ALL_CARDS", "BLOCK_CARD", "FILE_REPORT")
_SEVERITY = ["BLOCK_ALL_CARDS", "BLOCK_CARD", "FILE_REPORT", "DECLINE_TRANSACTION",
             "ESCALATE_TO_ANALYST", "STEP_UP_AUTH", "VERIFY_WITH_CUSTOMER",
             "MONITOR_CARD", "CLOSE_NO_FRAUD"]

# Gate cut-offs. Fitted on Jul-Oct by eval/proof_holdout.py, which writes them to
# data/staged/proof_gate.json; these are the fallbacks if that file is absent.
DEFAULT_GATE = {"min_margin": 2, "min_precedents": 10, "max_cleared_share": 0.70}

# Signals the policy reads directly, besides the posterior.
CORROBORATING = frozenset({
    "amount_anomalous", "amount_extreme", "device_new_on_account",
    "device_shared_across_cards", "device_proxy_hub", "anonymising_proxy",
    "region_unseen", "out_of_region_card_present", "home_activity_continues",
    "velocity_burst", "online_burst_2_to_4", "card_testing_sequence",
    "threshold_structuring", "mixed_channel_shift", "match_flag_anomaly",
    "email_mismatch", "shared_origin_ring", "behavioural_fraud_neighbourhood",
    "customer_disputed",
})


def mask_of(names: Iterable[str]) -> int:
    idx = {n: i for i, n in enumerate(FACT_BITS)}
    m = 0
    for n in names:
        if n in idx:
            m |= 1 << idx[n]
    return m


def names_of(mask: int) -> list[str]:
    return [n for i, n in enumerate(FACT_BITS) if mask >> i & 1]


@lru_cache(maxsize=1)
def gate_config() -> dict[str, float]:
    import json

    p = PATHS.staged / "proof_gate.json"
    if p.exists():
        try:
            return {**DEFAULT_GATE, **json.loads(p.read_text(encoding="utf-8")).get("gate", {})}
        except Exception:
            pass
    return dict(DEFAULT_GATE)


# ------------------------------------------------------------- inputs ----
@dataclass
class FactContext:
    """What the decision function needs beyond the facts themselves. Built once
    from the live case (or from a closed-case replay) and never mutated."""

    trigger_type: str
    signal_order: list[str]                    # extractor order, so the ledger replays exactly
    strengths: dict[str, float] = field(default_factory=dict)
    memory_lrs: dict[str, dict[str, float]] = field(default_factory=dict)
    solicited_reliability: dict[str, float] = field(default_factory=dict)
    base: CaseState | None = None              # the live CaseState, fact-dependent fields overridden
    exposure_usd: float = 0.0
    ring_size: int = 0
    connected_card_ids: list[str] = field(default_factory=list)
    prior: dict[str, float] | None = None
    # conformal layer: calibration present, and whether support / taint widen
    conformal: bool = False
    widened: bool = False
    feedback: dict[str, float] = field(default_factory=dict)   # signal -> reliability scale
    text_denied: bool = False      # customer report whose text denies the charge (R2)


@dataclass
class Outcome:
    p_fraud: float
    verdict: str
    pattern: str
    decision: PolicyDecision
    action_class: tuple[str, ...]


def action_class(actions: Iterable[str]) -> tuple[str, ...]:
    """Harmful actions present, or else the single most severe free action.
    Two decisions in the same class cost the customer the same."""
    acts = set(actions)
    harmful = tuple(a for a in HARMFUL if a in acts)
    if harmful:
        return harmful
    for a in _SEVERITY:
        if a in acts:
            return (a,)
    return ("NONE",)


def _pattern(facts: set[str], posterior: dict[str, float], verdict: str, p: float,
             ring_size: int) -> str:
    """Mirror of agent.nodes._pattern_for, over facts only."""
    if verdict == "legitimate":
        return H.NONE
    if verdict == "uncertain":
        ranked = sorted(((h, q) for h, q in posterior.items()
                         if h not in (H.NONE, H.UNDOCUMENTED)), key=lambda kv: -kv[1])
        return H.NONE if (p < AGENT.t_monitor or not ranked) else ranked[0][0]
    if "threshold_structuring" in facts:
        return H.UNDOCUMENTED
    if "device_proxy_hub" in facts and ring_size >= 3:
        return H.UNDOCUMENTED
    if "card_testing_sequence" in facts:
        return H.CARD_TESTING
    ranked = sorted(((h, q) for h, q in posterior.items() if h != H.NONE), key=lambda kv: -kv[1])
    if verdict == "uncertain" and p < AGENT.t_monitor:
        return H.NONE
    return ranked[0][0] if ranked else H.CNP


def decide(facts: set[str], fc: FactContext) -> Outcome:
    """The pure decision core as a function of the fact set."""
    ledger = EvidenceLedger(fc.prior or trigger_prior(fc.trigger_type))
    for name in fc.signal_order:
        if name == "customer_disputed":
            continue
        fired = name in facts
        if not fired and name in _ALL_FIRED_NAMES(fc):
            continue                     # a removed fact is neutral, not "absent"
        scale = fc.feedback.get(name, 1.0) if fired else 1.0
        if scale == 0.0:
            continue
        ledger.add_signal(Signal(name=name, fired=fired, claim="", ref="",
                                 strength=fc.strengths.get(name, 1.0)), scale=scale)
    for label, lrs in fc.memory_lrs.items():
        if label in facts:
            ledger.add(label, "memory", lrs, 0.8)
    p_graph = ledger.fraud_probability          # before any solicited evidence
    for key in SOLICITED_FACTS:
        if key in facts:
            ledger.add_solicited(key, claim="", ref="",
                                 reliability=fc.solicited_reliability.get(key))
    p = ledger.fraud_probability
    verdict = policy_engine.verdict_for(ledger.posterior, AGENT)
    settled = bool({"customer_denied", "customer_confirmed"} & facts) or fc.text_denied
    abstained = False
    if fc.conformal and verdict == "fraud" and not settled:
        from .conformal import calibration, prediction_set

        cal = calibration()
        if cal is not None:
            S = set(prediction_set(p_graph, cal))
            if fc.widened:
                S |= {"fraud", "legit"}
            if S != {"fraud"}:
                verdict, abstained = "uncertain", True
    pattern = _pattern(facts, ledger.posterior, verdict, p, fc.ring_size)
    shares_origin = bool({"shared_origin_ring", "device_proxy_hub"} & facts)
    base = fc.base or CaseState(case_id="", trigger_type=fc.trigger_type, fraud_probability=p,
                                verdict=verdict, pattern=pattern, exposure_usd=0.0,
                                n_independent_evidence=0, single_signal_only=True)
    customer = ("denied" if "customer_denied" in facts else
                "confirmed" if "customer_confirmed" in facts else
                "no_response" if "customer_no_response" in facts else "")
    step_up = ("failed" if "step_up_failed" in facts else
               "passed" if "step_up_passed" in facts else "")
    s = dataclasses.replace(
        base,
        fraud_probability=p, verdict=verdict, pattern=pattern,
        exposure_usd=0.0 if verdict == "legitimate" else fc.exposure_usd,
        n_independent_evidence=sum(1 for e in ledger.entries if abs(e.delta_fraud) >= 0.02),
        single_signal_only=len((facts | ({"customer_disputed"} if fc.trigger_type ==
                                         "customer_report" else set())) & CORROBORATING) <= 1,
        customer_response=customer, step_up_result=step_up,
        connected_card_ids=list(fc.connected_card_ids) if shares_origin else [],
        shares_origin_with_other_fraud=shares_origin,
        card_testing_matched="card_testing_sequence" in facts,
        recurring_charge_match="recurring_charge" in facts,
        coordinated_or_undocumented=(pattern == H.UNDOCUMENTED),
        conflicting_evidence=bool(ledger.contradictions()),
        credentials_confirmed_compromised=(step_up == "failed"),
        conformal_abstained=abstained,
    )
    d = policy_engine.evaluate(s)
    return Outcome(p, verdict, pattern, d, action_class(d.action_names()))


def _ALL_FIRED_NAMES(fc: FactContext) -> set[str]:     # noqa: N802 - cached attribute
    return getattr(fc, "_fired_cache", set())


def with_fired(fc: FactContext, fired: set[str]) -> FactContext:
    """Remember which signals fired in the live case: removing one of them makes
    it neutral, whereas a signal that never fired stays an observed absence."""
    object.__setattr__(fc, "_fired_cache", set(fired))
    return fc


# -------------------------------------------------------------- proof ----
def minimal_sufficient(facts: list[str], fc: FactContext, target: tuple[str, ...],
                       order: list[str]) -> tuple[list[str], int]:
    """Greedy deletion: drop each fact (weakest first) if the class survives.
    The result is irredundant: removing any one remaining fact changes the class."""
    keep = list(facts)
    calls = 0
    for f in order:
        trial = [x for x in keep if x != f]
        calls += 1
        if decide(set(trial), fc).action_class == target:
            keep = trial
    return [f for f in facts if f in keep], calls


def flip_set(facts: list[str], fc: FactContext, target: tuple[str, ...],
             max_size: int = 3, max_calls: int = 2500) -> tuple[list[str], dict[str, Any], int]:
    """Smallest subset whose removal changes the action class. Singles, then
    pairs, then triples while the call budget lasts."""
    full = set(facts)
    calls = 0
    for size in range(1, max_size + 1):
        for combo in combinations(facts, size):
            calls += 1
            if calls > max_calls:
                return [], {}, calls
            out = decide(full - set(combo), fc)
            if out.action_class != target:
                return list(combo), {"action_class": list(out.action_class),
                                     "actions": out.decision.action_names(),
                                     "p_fraud": round(out.p_fraud, 4),
                                     "verdict": out.verdict}, calls
    return [], {}, calls


def single_flips(facts: list[str], fc: FactContext, target: tuple[str, ...]) -> list[dict]:
    """For the examiner view: what each single fact's removal does."""
    out = []
    full = set(facts)
    for f in facts:
        o = decide(full - {f}, fc)
        out.append({"fact": f, "flips": o.action_class != target,
                    "action_class": list(o.action_class),
                    "p_fraud": round(o.p_fraud, 4), "verdict": o.verdict})
    return out


@lru_cache(maxsize=1)
def _precedent_table():
    import pandas as pd

    p = PATHS.staged / "closed_case_facts.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p, columns=["case_id", "stratum", "opened_at", "outcome",
                                     "is_fraud", "fact_mask"])
    df = df[df["stratum"] == "closed_case"].copy()
    df["fact_mask"] = df["fact_mask"].astype("int64")
    return df


def precedent_support(minimal: list[str], as_of, limit_ids: int = 12) -> dict[str, Any]:
    """Closed cases opened before `as_of` whose replayed fact vector contains
    every graph fact in the minimal set. Solicited facts are not in the replay
    (the bank's history records outcomes, not the conversation), so they are
    excluded from the match and listed."""
    import pandas as pd

    df = _precedent_table()
    graph_facts = [f for f in minimal if f in FACT_BITS]
    query = {"query": "precedent_by_facts",
             "params": {"fact_mask": mask_of(graph_facts), "as_of": str(as_of)}}
    if df is None:
        return {"available": False, "n": 0, **query,
                "note": "closed_case_facts.parquet not built (ingest/08_fact_vectors.py)"}
    if not graph_facts:
        return {"available": True, "n": 0, "confirmed": 0, "cleared": 0,
                "matched_facts": [], "unmatched_facts": minimal, **query,
                "note": "minimal set has no graph facts to match on"}
    m = mask_of(graph_facts)
    sub = df[(df["opened_at"] < pd.Timestamp(as_of)) & ((df["fact_mask"] & m) == m)]
    n_f = int(sub["is_fraud"].sum())
    return {"available": True, "n": int(len(sub)), "confirmed": n_f,
            "cleared": int(len(sub) - n_f),
            "cleared_share": round((len(sub) - n_f) / len(sub), 3) if len(sub) else None,
            "matched_facts": graph_facts,
            "unmatched_facts": [f for f in minimal if f not in FACT_BITS],
            "case_ids": sub.sort_values("opened_at")["case_id"].tail(limit_ids).tolist(),
            **query}


def build_proof(facts: list[str], fc: FactContext, live_actions: list[str], as_of,
                deltas: dict[str, float] | None = None) -> dict[str, Any]:
    deltas = deltas or {}
    full = decide(set(facts), fc)
    live_class = action_class(live_actions)
    target = full.action_class
    order = sorted(facts, key=lambda f: abs(deltas.get(f, 0.0)))
    minimal, c1 = minimal_sufficient(facts, fc, target, order)
    flips, flipped_to, c2 = flip_set(facts, fc, target)
    prec = precedent_support(minimal, as_of)
    return {
        "facts": facts,
        "action_class": list(target),
        "live_action_class": list(live_class),
        "reproduces_live": target == live_class,
        "minimal_sufficient_facts": minimal,
        "flip_set": flips,
        "margin_k": len(flips) if flips else None,
        "margin_note": ("" if flips else
                        "no subset of up to 3 facts flips the class; margin is at least 4"),
        "flips_to": flipped_to,
        "single_fact_flips": single_flips(facts, fc, target),
        "precedent": prec,
        "core_calls": c1 + c2 + len(facts) + 1,
    }


# --------------------------------------------------------------- gate ----
def gate(proof: dict[str, Any], decision: PolicyDecision, customer_denied: bool,
         exposure_usd: float) -> tuple[PolicyDecision, dict[str, Any]]:
    """Downgrade a harmful action that rests on a thin or contradicted proof."""
    from .permissions import route

    cfg = gate_config()
    names = decision.action_names()
    harmful = [a for a in names if a in HARMFUL]
    k = proof.get("margin_k")
    prec = proof.get("precedent", {})
    contradicted = bool(prec.get("n", 0) >= cfg["min_precedents"]
                        and (prec.get("cleared_share") or 0) >= cfg["max_cleared_share"])
    thin = k is not None and k < cfg["min_margin"]
    record = {"applied": False, "harmful_actions": harmful, "margin_k": k,
              "precedent_contradicts": contradicted, "thin_margin": thin,
              "exempt": "", "config": cfg, "removed": [], "added": []}
    if not harmful:
        record["reason"] = "no harmful action to gate"
        return decision, record
    if customer_denied:
        record["exempt"] = "R2"
        record["reason"] = ("R2: the cardholder denied the charge, so policy requires the block; "
                            f"margin recorded (k={k}) but not gated")
        return decision, record
    if not (thin or contradicted):
        record["reason"] = (f"kept: margin k={k if k is not None else '>=4'} meets the floor of "
                            f"{cfg['min_margin']} and precedent does not contradict")
        return decision, record

    why = []
    if thin:
        why.append(f"the action rests on a margin of {k} fact"
                   f"{'s' if k != 1 else ''} ({', '.join(proof.get('flip_set', []))})")
    if contradicted:
        why.append(f"{prec['cleared']} of {prec['n']} closed cases with the same facts were "
                   f"cleared")
    reason = "proof gate: " + " and ".join(why) + "; a harmful action needs a sturdier proof"
    kept = [a for a in decision.actions if a.action not in HARMFUL]
    names_kept = {a.action for a in kept}
    added = []
    for act, txt in (("VERIFY_WITH_CUSTOMER", "R1/proof gate: verify before any block"),
                     ("ESCALATE_TO_ANALYST", "R8/proof gate: " + reason)):
        if act not in names_kept:
            kept.append(route(act, txt, exposure_usd))
            added.append(act)
    if "CREATE_CASE" not in names_kept:
        kept.append(route("CREATE_CASE", "3a: a case is opened before anything is proven",
                          exposure_usd))
        added.append("CREATE_CASE")
    order = {n: i for i, n in enumerate([
        "DECLINE_TRANSACTION", "STEP_UP_AUTH", "VERIFY_WITH_CUSTOMER", "CREATE_CASE",
        "MONITOR_CONNECTED_CARDS", "MONITOR_CARD", "WARN_CUSTOMER", "ESCALATE_TO_ANALYST"])}
    kept.sort(key=lambda a: order.get(a.action, 99))
    out = PolicyDecision(kept, decision.cited_rules + ["proof_gate"], decision.obligations,
                         sorted(set(decision.forbidden) | set(harmful)),
                         decision.notes + [reason])
    record.update(applied=True, removed=harmful, added=added, reason=reason)
    return out, record

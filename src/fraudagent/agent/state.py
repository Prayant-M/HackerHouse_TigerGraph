"""Typed investigation state.

The state holds live objects — the evidence ledger, the hash-chained decision
log, the investigation context — rather than flattened dicts, because the nodes
need their methods. That rules out a serialising checkpointer, so the reasoning
trace the analyst console streams is built explicitly in `trace` as the run
proceeds, and it is the same record that ends up in the answer file's audit
section.

`as_of` is set once, by the Case Opener, and never advances. Every read in the
system is bounded by it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypedDict

from ..core.episode import Episode
from ..core.evidence_ledger import EvidenceLedger
from ..core.ledger import DecisionLedger
from ..core.policy_engine import PolicyDecision
from ..core.signals import InvestigationContext
from ..core.stopping import StopDecision
from ..graphstore.base import RecalledCase


@dataclass
class Trigger:
    type: str                      # risk_score | customer_report | analyst_request
    text: str
    flagged_txn_id: str
    card_id: str
    customer_id: str
    opened_at: datetime
    risk_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, "text": self.text, "flagged_txn_id": self.flagged_txn_id,
                "card_id": self.card_id, "customer_id": self.customer_id,
                "opened_at": self.opened_at.isoformat(sep=" "),
                "risk_score": self.risk_score}


@dataclass
class RequestRecord:
    type: str
    name: str
    channel: str
    question: str
    asked_after_step: int
    expected_info_gain: float
    cost: float
    outcome: str
    assumed_response: str
    simulation_seed: int
    posterior_before: dict[str, float] = field(default_factory=dict)
    posterior_after: dict[str, float] = field(default_factory=dict)

    def answer_entry(self) -> dict[str, Any]:
        """Exactly the three fields the dataset's answer format asks for."""
        return {"type": self.type, "asked_after_step": self.asked_after_step,
                "assumed_response": self.assumed_response}

    def as_dict(self) -> dict[str, Any]:
        d = self.answer_entry()
        d.update({"name": self.name, "channel": self.channel, "question": self.question,
                  "expected_info_gain": round(self.expected_info_gain, 4),
                  "cost": self.cost, "outcome": self.outcome,
                  "simulation_seed": self.simulation_seed, "simulated": True,
                  "p_fraud_before": round(sum(v for k, v in self.posterior_before.items()
                                              if k != "none"), 4),
                  "p_fraud_after": round(sum(v for k, v in self.posterior_after.items()
                                             if k != "none"), 4)})
        return d


class InvestigationState(TypedDict, total=False):
    case_id: str
    graph_case_id: str
    trigger: Trigger
    as_of: datetime
    started_at: float

    ctx: InvestigationContext
    ledger: EvidenceLedger
    decisions: DecisionLedger

    plan: list[str]
    priors: list[RecalledCase]
    policy_docs: list[dict[str, Any]]

    round: int
    requests: list[RequestRecord]
    voi_ranking: list[dict[str, Any]]

    pattern: str
    sub_typology: str
    verdict: str
    episode: Episode

    initial_decision: PolicyDecision
    final_decision: PolicyDecision
    stop: StopDecision

    customer_response: str
    step_up_result: str
    analyst_response: str

    narrative: dict[str, Any]
    result: dict[str, Any]
    trace: list[dict[str, Any]]

    # final-round layers (agent/final_round.py). LangGraph keeps only declared
    # keys between nodes, so every one of them is declared here.
    _store: Any
    text_facts: dict[str, Any]
    p_graph_only: float
    compromise_watch: list[dict[str, Any]]
    quality: dict[str, Any]
    conformal: dict[str, Any]
    proof: dict[str, Any]
    gate: dict[str, Any]
    containment: dict[str, Any] | None
    feedback_applied: list[dict[str, Any]]
    typology_detections: list[dict[str, Any]]

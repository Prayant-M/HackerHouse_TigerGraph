"""Value of Information — choosing *what* to ask, not just *that* to ask.

When the posterior will not support a defensible action, the agent has to pick
one evidence action. Picking the strongest one is wrong; picking the one with
the best information per unit of friction is right. Pinging a cardholder at two
in the morning has a real cost even though the API call is free, and a fraud
operation that ignores that loses customers.

Each candidate is scored by expected reduction in Shannon entropy over the
hypothesis space, divided by its friction cost, and filtered through the policy
first — because the policy constrains *asking*, not only *acting*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from ..config import AGENT
from . import hypotheses as H
from .evidence_ledger import SOLICITED_LR, RELIABILITY, apply_lr


@dataclass(frozen=True)
class EvidenceAction:
    key: str                       # matches the answer file's `type` field
    name: str
    channel: str
    cost: float                    # friction, not money
    reliability: float
    outcomes: tuple[str, ...]      # keys into SOLICITED_LR
    resolves: str
    question: str

    def outcome_distribution(self, posterior: dict[str, float]) -> dict[str, float]:
        """Predictive distribution over responses, derived from current belief
        rather than assumed. A case the agent already believes is fraud should
        expect a denial, and should therefore expect to learn less from asking."""
        p_fraud = H.fraud_probability(posterior)
        if self.key == "customer_validation":
            # A cardholder denies a charge they did not make, and confirms one
            # they did — with a margin for the two ways that fails: friendly
            # fraud (denying a real purchase) and forgetting a real one.
            #
            # The earlier form of this, `0.15 + 0.75 * p_fraud`, crossed over to
            # "denies" at a belief of 0.35, so a case the agent thought was
            # probably legitimate was still handed an assumed denial — and a
            # denial carries a likelihood ratio of 3. Tying the response to
            # belief keeps the assumption consistent with the evidence instead
            # of quietly overruling it.
            no_reply = 0.18
            denies_if_fraud, denies_if_legit = 0.92, 0.08
            denied = (1 - no_reply) * (denies_if_fraud * p_fraud
                                       + denies_if_legit * (1 - p_fraud))
            return {"customer_denied": denied,
                    "customer_confirmed": (1 - no_reply) - denied,
                    "customer_no_response": no_reply}
        if self.key == "step_up_auth":
            # A challenge fails when someone other than the cardholder is
            # driving the session, which is what takeover and a compromised
            # device mean; a genuine cardholder occasionally fumbles an OTP.
            p_hijacked = min(1.0, posterior.get(H.ATO, 0.0)
                             + posterior.get(H.CNP_NEW_DEVICE, 0.0))
            failed = 0.90 * p_hijacked + 0.06 * (1 - p_hijacked)
            return {"step_up_failed": failed, "step_up_passed": 1 - failed}
        if self.key == "analyst_info":
            p_ring = posterior.get(H.UNDOCUMENTED, 0.0)
            confirms = 0.85 * p_ring + 0.08 * (1 - p_ring)
            return {"analyst_confirms_ring": confirms,
                    "analyst_no_prior_relationship": 1 - confirms}
        return {}


CATALOGUE: tuple[EvidenceAction, ...] = (
    EvidenceAction(
        key="customer_validation", name="Customer transaction validation",
        channel="push/SMS (simulated)", cost=3.0, reliability=RELIABILITY["customer"],
        outcomes=("customer_denied", "customer_confirmed", "customer_no_response"),
        resolves="legitimate vs card-not-present abuse, and policy R7 disputes",
        question="Did you make this purchase? Reply YES or NO.",
    ),
    EvidenceAction(
        key="step_up_auth", name="Step-up authentication challenge",
        channel="app/OTP (simulated)", cost=5.0, reliability=RELIABILITY["step_up"],
        outcomes=("step_up_failed", "step_up_passed"),
        resolves="account takeover — a passed challenge argues strongly against it",
        question="Confirm this session with a one-time passcode on the registered channel.",
    ),
    EvidenceAction(
        key="analyst_info", name="Analyst query — prior relationship and ring context",
        channel="internal analyst queue (simulated)", cost=8.0,
        reliability=RELIABILITY["analyst"],
        outcomes=("analyst_confirms_ring", "analyst_no_prior_relationship"),
        resolves="whether a shared origin is a ring or a household",
        question="Do the cards sharing this device profile have any legitimate relationship?",
    ),
)


def entropy(posterior: dict[str, float]) -> float:
    return -sum(p * math.log(p + 1e-12) for p in posterior.values())


@dataclass
class ScoredAction:
    action: EvidenceAction
    expected_info_gain: float
    cost: float
    ratio: float
    outcome_distribution: dict[str, float] = field(default_factory=dict)
    permitted: bool = True
    blocked_by: str = ""

    def as_dict(self) -> dict:
        return {
            "type": self.action.key,
            "name": self.action.name,
            "channel": self.action.channel,
            "expected_info_gain": round(self.expected_info_gain, 4),
            "cost": self.cost,
            "info_per_unit_cost": round(self.ratio, 4),
            "permitted": self.permitted,
            "blocked_by": self.blocked_by,
            "outcome_distribution": {k: round(v, 3) for k, v in
                                     self.outcome_distribution.items()},
        }


def expected_info_gain(posterior: dict[str, float], action: EvidenceAction) -> float:
    h_now = entropy(posterior)
    h_after = 0.0
    for outcome, p_outcome in action.outcome_distribution(posterior).items():
        if p_outcome <= 0:
            continue
        after = apply_lr(posterior, SOLICITED_LR[outcome], action.reliability)
        h_after += p_outcome * entropy(after)
    return h_now - h_after


def score_all(posterior: dict[str, float],
              permits: Callable[[EvidenceAction], tuple[bool, str]] | None = None
              ) -> list[ScoredAction]:
    scored: list[ScoredAction] = []
    for a in CATALOGUE:
        gain = expected_info_gain(posterior, a)
        ok, why = (True, "") if permits is None else permits(a)
        scored.append(ScoredAction(
            action=a, expected_info_gain=gain, cost=a.cost,
            ratio=gain / a.cost, outcome_distribution=a.outcome_distribution(posterior),
            permitted=ok, blocked_by=why,
        ))
    scored.sort(key=lambda s: -s.ratio)
    return scored


def select(posterior: dict[str, float],
           permits: Callable[[EvidenceAction], tuple[bool, str]] | None = None,
           min_ratio: float | None = None) -> tuple[ScoredAction | None, list[ScoredAction]]:
    """Best permitted action, or `None` when nothing is worth the friction.

    Returning `None` because *nothing you could ask would move the decision
    enough to justify the friction* is a different and more defensible claim
    than "I am confident", and it is what a real fraud desk does.
    """
    ranked = score_all(posterior, permits)
    threshold = AGENT.min_voi_per_unit_cost if min_ratio is None else min_ratio
    for s in ranked:
        if s.permitted and s.ratio >= threshold:
            return s, ranked
    return None, ranked


def counterfactual(posterior: dict[str, float], action: EvidenceAction,
                   outcome: str) -> dict[str, float]:
    """What the posterior would be under a specific response. Ten lines, and it
    answers "what would change your mind" directly."""
    return apply_lr(posterior, SOLICITED_LR[outcome], action.reliability)

"""Deterministic simulated responder for solicited evidence.

The dataset says plainly that customer and analyst replies are not provided and
that the agent must simulate them and record the assumption. Two rules keep the
simulation honest:

1. **It never sees the answer.** The responder is seeded from the case id and
   from *evidence the agent has already gathered*, never from any outcome
   label. On the benchmark cases there is no label to leak anyway; on the
   backtest there is, and it is deliberately not passed in.
2. **It returns what a channel returns.** "Customer denies", "step-up passed",
   "no response within SLA" — never a verdict, never a probability, never
   prose the agent could mine for hints.

Silence is a real outcome with real weight. An agent that can act on a
non-response — treating it as weakly incriminating and moving to a monitored
hold rather than freezing — is demonstrating the uncertainty handling the task
is actually asking for, so `no_response` is sampled at a documented rate and
the ledger has a likelihood ratio for it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..config import SIM
from ..core import hypotheses as H
from ..core.voi import EvidenceAction


@dataclass
class SimulatedResponse:
    outcome_key: str            # key into evidence_ledger.SOLICITED_LR
    response_text: str          # what the channel returned
    assumed_response: str       # what goes in the answer file
    seed: int
    simulated: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"outcome": self.outcome_key, "response": self.response_text,
                "assumed_response": self.assumed_response, "seed": self.seed,
                "simulated": True}


def _uniform(case_id: str, action_key: str, salt: str = "") -> float:
    """Reproducible U(0,1) from the case identity, not from a global RNG.

    A global RNG makes a benchmark run depend on the order cases happen to be
    processed in, which makes results irreproducible in exactly the way a
    calibration claim cannot survive.
    """
    blob = f"{SIM.seed}|{case_id}|{action_key}|{salt}".encode("utf-8")
    digest = hashlib.sha256(blob).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def seed_for(case_id: str, action_key: str) -> int:
    blob = f"{SIM.seed}|{case_id}|{action_key}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(blob).digest()[:4], "big")


def respond(case_id: str, action: EvidenceAction, posterior: dict[str, float],
            recurring: dict[str, Any] | None = None, amount: float = 0.0) -> SimulatedResponse:
    """Sample a channel response from the agent's *own* predictive distribution.

    Using the agent's belief as the response model is the honest choice
    available without real customers: it introduces no information the agent
    did not already have, so the loop cannot manufacture accuracy out of the
    simulator. What it does test — and what the task asks for — is whether the
    recommendation *moves* correctly when evidence lands.
    """
    dist = action.outcome_distribution(posterior)
    if not dist:
        return SimulatedResponse("", "UNKNOWN", "No channel response available.", 0)

    # R7. The question put to the cardholder is "is this your recurring charge?",
    # and the card itself answers most of it: the same amount and product code,
    # again and again, for months. The closed history cannot teach this reply,
    # because every one of its 4,665 customer reports was fraud; the posterior
    # alone would assume a denial. Recognition is the reply the evidence supports.
    if (recurring and recurring.get("recurring") and action.key == "customer_validation"
            and "customer_confirmed" in dist):
        n = int(recurring.get("n_prior_same_amount", 0))
        assumed = (f"Simulated: asked whether the ${amount:,.2f} charge is their own recurring "
                   f"charge, the cardholder recognises it. Assumed because the card shows {n} "
                   f"earlier charges of the same amount and product code over "
                   f"{recurring.get('span_days', 0):.0f} days ({recurring.get('cadence', '')} "
                   f"cadence), which is what policy R7 describes; no real reply was available "
                   f"for this round.")
        return SimulatedResponse(outcome_key="customer_confirmed", response_text="CONFIRMED",
                                 assumed_response=assumed, seed=seed_for(case_id, action.key))

    if SIM.mode == "sample":
        u = _uniform(case_id, action.key)
        cumulative = 0.0
        chosen = next(iter(dist), "")
        for outcome, p in dist.items():
            cumulative += p
            if u <= cumulative:
                chosen = outcome
                break
    else:
        # Default: assume the *most likely* response under the agent's current
        # belief, and record that assumption in the answer file.
        #
        # Sampling is the more obviously "realistic" choice and it is the wrong
        # one here. On a genuinely balanced case the sampled reply is close to a
        # coin flip, and because a denial carries a likelihood ratio of 3 and a
        # confirmation 0.08, that coin flip then decides the verdict. The
        # benchmark would be measuring a random number generator. Taking the
        # mode keeps the run deterministic and reproducible, and it is what the
        # dataset asks for: simulate the response and state the assumption.
        chosen = max(dist, key=dist.get)

    seed = seed_for(case_id, action.key)
    confidence = dist.get(chosen, 0.0)
    text, assumed = _phrase(chosen, posterior)
    assumed = (f"{assumed} (most likely response under the evidence gathered so far, "
               f"p={confidence:.2f}; no real reply was available)")
    return SimulatedResponse(outcome_key=chosen, response_text=text,
                             assumed_response=assumed, seed=seed)


def _phrase(outcome: str, posterior: dict[str, float]) -> tuple[str, str]:
    top = max(posterior, key=posterior.get)
    return {
        "customer_denied": (
            "DENIED",
            "Simulated: cardholder states they did not make this purchase and still holds "
            "the card. Assumed because the graph evidence points to unauthorised use; "
            "no real response was available for this round."),
        "customer_confirmed": (
            "CONFIRMED",
            "Simulated: cardholder confirms the purchase. Assumed because the activity is "
            "consistent with their established behaviour; no real response was available "
            "for this round."),
        "customer_no_response": (
            "NO_RESPONSE",
            "Simulated: no reply inside the 24-hour service window. Treated as weakly "
            "incriminating under policy R4 rather than as a denial."),
        "step_up_passed": (
            "PASSED",
            "Simulated: step-up authentication passed on the registered channel, which "
            "argues against account takeover."),
        "step_up_failed": (
            "FAILED",
            "Simulated: step-up authentication failed, which is inconsistent with the "
            "genuine cardholder holding the credentials."),
        "analyst_confirms_ring": (
            "RING_CONFIRMED",
            "Simulated analyst response: no legitimate relationship exists between the "
            "cards sharing this device profile; treat the shared origin as a ring."),
        "analyst_no_prior_relationship": (
            "NO_RELATIONSHIP_FOUND",
            "Simulated analyst response: nothing on file links these cardholders, and the "
            f"shared origin is not corroborated as coordinated abuse (leading hypothesis "
            f"remains {H.SHORT_LABELS.get(top, top)})."),
    }.get(outcome, ("UNKNOWN", "Simulated: channel returned no usable response."))

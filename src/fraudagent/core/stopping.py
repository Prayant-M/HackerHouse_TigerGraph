"""The stopping rule.

Fraud Policy §6 asks the agent to stop "once enough evidence is available to
take a defensible action". That is answered with arithmetic, not with a feeling
that the case is done.

Two-sided, and the second side is the one that matters:

1. **Decisive** — belief clears the threshold the required action class demands,
   with enough separation from the runner-up, on at least two independent
   pieces of evidence (§6's own wording).
2. **Exhausted** — no permitted evidence action carries enough information per
   unit of friction to justify asking. Nothing further would change the
   decision, so say that and hand it to a human.

Plus the honest terminators: the round cap, the wall clock, the token budget.
Every one of them is recorded in `stop_reason` as what it actually was.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import AGENT
from . import hypotheses as H


@dataclass(frozen=True)
class StopDecision:
    stop: bool
    reason_code: str
    reason: str

    def as_dict(self) -> dict[str, str | bool]:
        return {"stop": self.stop, "code": self.reason_code, "reason": self.reason}


DECISIVE = "DECISIVE_POSTERIOR"
CLEARED = "DECISIVE_LEGITIMATE"
EXHAUSTED = "INFORMATION_EXHAUSTED"
SETTLED = "VERIFICATION_SETTLED"
ROUND_CAP = "ROUND_CAP_REACHED"
TIME_BUDGET = "WALL_CLOCK_EXCEEDED"
CONTINUE = "CONTINUE"


def evaluate(posterior: dict[str, float], n_independent_evidence: int, round_no: int,
             best_voi_ratio: float, elapsed_s: float,
             customer_settled: bool = False) -> StopDecision:
    p_fraud = H.fraud_probability(posterior)
    (top_h, top_p), (second_h, second_p) = H.top_two(posterior)
    margin = top_p - second_p
    cfg = AGENT

    if customer_settled:
        return StopDecision(True, SETTLED,
                            "A verification response settled the question outright (policy §6).")

    if elapsed_s > cfg.wall_clock_timeout_s:
        return StopDecision(True, TIME_BUDGET,
                            f"Wall-clock budget of {cfg.wall_clock_timeout_s:.0f}s exceeded; "
                            f"stopping with the belief reached so far.")

    if p_fraud >= 0.85 and n_independent_evidence >= 2:
        return StopDecision(
            True, DECISIVE,
            f"Fraud probability {p_fraud:.2f} is at or above the 0.85 ceiling in policy §6, "
            f"supported by {n_independent_evidence} independent pieces of evidence, with "
            f"{top_h} leading {second_h} by {margin:.2f}.")

    if p_fraud <= 0.15 and n_independent_evidence >= 2:
        return StopDecision(
            True, CLEARED,
            f"Fraud probability {p_fraud:.2f} is at or below the 0.15 floor in policy §6 on "
            f"{n_independent_evidence} independent pieces of evidence; the activity is "
            f"consistent with the cardholder.")

    if (p_fraud >= cfg.t_block_card and margin >= cfg.separation_floor
            and n_independent_evidence >= 2):
        return StopDecision(
            True, DECISIVE,
            f"Fraud probability {p_fraud:.2f} clears the {cfg.t_block_card:.2f} threshold for the "
            f"actions this case requires, and {top_h} is separated from {second_h} by "
            f"{margin:.2f}, above the {cfg.separation_floor:.2f} floor. The actions policy requires "
            f"at this probability are already fixed, so further steps are unlikely to change the "
            f"decision (policy §6).")

    if best_voi_ratio < cfg.min_voi_per_unit_cost:
        return StopDecision(
            True, EXHAUSTED,
            f"No permitted evidence action carries enough information per unit of customer "
            f"friction to justify it (best {best_voi_ratio:.4f} against a "
            f"{cfg.min_voi_per_unit_cost:.4f} floor). Further investigation would not change the "
            f"decision, so the case goes to a human with what is known.")

    if round_no >= cfg.max_evidence_rounds:
        return StopDecision(
            True, ROUND_CAP,
            f"Evidence-gathering round cap of {cfg.max_evidence_rounds} reached with fraud "
            f"probability at {p_fraud:.2f}; stopping rather than looping.")

    return StopDecision(False, CONTINUE,
                        f"Fraud probability {p_fraud:.2f} with a {margin:.2f} margin is not yet "
                        f"decisive and informative evidence remains available.")


def action_threshold_met(posterior: dict[str, float], action: str) -> bool:
    """Whether belief supports a given action class, per the §6 thresholds."""
    p = H.fraud_probability(posterior)
    return {
        "BLOCK_ALL_CARDS": p >= AGENT.t_block_all,
        "FILE_REPORT": p >= AGENT.t_block_all,
        "BLOCK_CARD": p >= AGENT.t_block_card,
        "DECLINE_TRANSACTION": p >= AGENT.t_decline,
        "MONITOR_CARD": p >= AGENT.t_monitor,
        "CLOSE_NO_FRAUD": posterior.get(H.NONE, 0.0) >= AGENT.t_clear,
    }.get(action, True)

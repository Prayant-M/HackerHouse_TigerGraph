"""Action catalogue and approval routing.

Transcribed verbatim from the bank's Fraud Policy §1 and §2. This module is the
only place in the system that may decide an approval route, and it is pure
data plus arithmetic — an LLM cannot reach it, cannot influence it, and cannot
talk its way past it. That property is the point: an agent that can be
*argued* into executing a block is not a control.
"""

from __future__ import annotations

from dataclasses import dataclass

AUTO = "auto"
L1 = "L1"
L2 = "L2"

# Fraud Policy §1 — Actions
ACTIONS: dict[str, dict[str, str]] = {
    "ALLOW_TRANSACTION": {"effect": "Let the flagged transaction stand",
                          "customer_impact": "none"},
    "DECLINE_TRANSACTION": {"effect": "Decline the flagged authorization only; card stays active",
                            "customer_impact": "low"},
    "MONITOR_CARD": {"effect": "Card stays active; raise monitoring sensitivity for 72 hours",
                     "customer_impact": "none"},
    "MONITOR_CONNECTED_CARDS": {"effect": "Monitor other cards linked by device, region or ring",
                                "customer_impact": "none"},
    "WARN_CUSTOMER": {"effect": "Send an informational message",
                      "customer_impact": "none"},
    "VERIFY_WITH_CUSTOMER": {"effect": "Ask the cardholder whether they made the transaction",
                             "customer_impact": "low"},
    "STEP_UP_AUTH": {"effect": "Require a one-time passcode or app confirmation",
                     "customer_impact": "low"},
    "BLOCK_CARD": {"effect": "Block this card and reissue", "customer_impact": "high"},
    "BLOCK_ALL_CARDS": {"effect": "Block every card the customer holds",
                        "customer_impact": "very high"},
    "GENERATE_REPORT": {"effect": "Write up the investigation for the internal record",
                        "customer_impact": "none"},
    "CREATE_CASE": {"effect": "Open an internal fraud case and write it to the graph",
                    "customer_impact": "none"},
    "FILE_REPORT": {"effect": "File a suspicious activity report with the regulator",
                    "customer_impact": "none"},
    "ESCALATE_TO_ANALYST": {"effect": "Hand the case to a human analyst with the evidence",
                            "customer_impact": "none"},
    "CLOSE_NO_FRAUD": {"effect": "Close the alert as legitimate", "customer_impact": "none"},
}

# Fraud Policy §2 — Approval routing
_AUTO_ACTIONS = {
    "ALLOW_TRANSACTION", "MONITOR_CARD", "MONITOR_CONNECTED_CARDS", "WARN_CUSTOMER",
    "VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH", "GENERATE_REPORT", "CREATE_CASE",
    "ESCALATE_TO_ANALYST", "CLOSE_NO_FRAUD",
}

# Actions the agent is permitted to execute on its own (policy §2: "Only `auto`
# actions may be executed by the agent").
EXECUTABLE = _AUTO_ACTIONS

BLOCK_CARD_L2_EXPOSURE_THRESHOLD = 2500.0


class PolicyViolation(ValueError):
    """Raised when something tries to execute an action it may only recommend."""


def route_for(action: str, exposure_usd: float = 0.0) -> str:
    """The approval route this action requires, per Fraud Policy §2."""
    if action not in ACTIONS:
        raise PolicyViolation(f"{action!r} is not in the bank's action catalogue")
    if action in _AUTO_ACTIONS:
        return AUTO
    if action == "DECLINE_TRANSACTION":
        return L1
    if action == "BLOCK_CARD":
        return L2 if exposure_usd > BLOCK_CARD_L2_EXPOSURE_THRESHOLD else L1
    if action in {"BLOCK_ALL_CARDS", "FILE_REPORT"}:
        return L2
    raise PolicyViolation(f"no route defined for {action!r}")


def approver_role(route: str) -> str:
    return {AUTO: "agent", L1: "team lead", L2: "fraud manager"}.get(route, "unknown")


def may_execute(action: str) -> bool:
    return action in EXECUTABLE


@dataclass(frozen=True)
class RoutedAction:
    action: str
    route: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"action": self.action, "route": self.route, "reason": self.reason}


def route(action: str, reason: str, exposure_usd: float = 0.0) -> RoutedAction:
    return RoutedAction(action=action, route=route_for(action, exposure_usd), reason=reason)

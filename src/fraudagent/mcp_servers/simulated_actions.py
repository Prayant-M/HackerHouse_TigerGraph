"""Simulated action service — customer outreach, step-up, blocks, filings.

The challenge brief permits these to be simulated, stubbed or mocked, and this
module is honest about being exactly that. It is not a pretend integration with
a real messaging provider: the IEEE-CIS data is anonymised, `card1` is a
surrogate integer, email domains are coarse categories and there are no real
phone numbers or IPs, so a real outreach API would have nothing to reach and a
real IP-reputation lookup would return noise dressed as evidence.

What it does provide is the part that matters for auditability: every action
the agent takes produces a receipt with a deterministic reference, a timestamp
and an explicit `simulated: true`, and the receipts are appended to an
execution log that the console reads.

Only `auto`-routed actions ever reach `execute()`; `permissions.may_execute`
is checked first by the permission gate and again here, because a control that
is only enforced at one call site is not a control.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from ..config import PATHS, SIM
from ..core.permissions import ACTIONS, may_execute, route_for

EXECUTION_LOG = "action_log.jsonl"


def _reference(action: str, case_id: str, entity: str) -> str:
    blob = f"{SIM.seed}|{action}|{case_id}|{entity}".encode("utf-8")
    return f"SIM-{hashlib.sha256(blob).hexdigest()[:10].upper()}"


def _effect(action: str, card_id: str, customer_id: str) -> str:
    return {
        "ALLOW_TRANSACTION": f"Authorisation released on card {card_id}.",
        "MONITOR_CARD": f"Monitoring sensitivity raised on card {card_id} for 72 hours.",
        "MONITOR_CONNECTED_CARDS": "Connected cards added to the heightened-monitoring list.",
        "WARN_CUSTOMER": f"Informational message queued to customer {customer_id}.",
        "VERIFY_WITH_CUSTOMER": f"Validation request dispatched to customer {customer_id}; "
                                f"card remains active pending reply.",
        "STEP_UP_AUTH": f"Step-up challenge armed on card {card_id}; further activity requires "
                        f"a one-time passcode.",
        "GENERATE_REPORT": "Internal investigation write-up generated.",
        "CREATE_CASE": "Fraud case opened and written to the graph.",
        "ESCALATE_TO_ANALYST": "Case handed to the analyst queue with the full evidence chain.",
        "CLOSE_NO_FRAUD": "Alert closed as legitimate activity.",
    }.get(action, f"{action} recorded.")


def execute(action: str, case_id: str, card_id: str, customer_id: str,
            **extra: Any) -> dict[str, Any]:
    """Run one auto-routed action and return its receipt."""
    if action not in ACTIONS:
        raise ValueError(f"{action!r} is not in the bank's action catalogue")
    if not may_execute(action):
        raise PermissionError(
            f"{action} routes to {route_for(action)} approval and may only be recommended. "
            f"The agent does not execute it.")
    receipt = {
        "action": action,
        "case_id": case_id,
        "card_id": card_id,
        "customer_id": customer_id,
        "route": "auto",
        "executed": True,
        "simulated": True,
        "reference": _reference(action, case_id, card_id or customer_id),
        "executed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "effect": _effect(action, card_id, customer_id),
        "customer_impact": ACTIONS[action]["customer_impact"],
    }
    receipt.update(extra)
    _append(receipt)
    return receipt


def recommend_only(action: str, case_id: str, reason: str,
                   exposure_usd: float = 0.0) -> dict[str, Any]:
    """Record an action the agent may not take, with the route it needs."""
    r = route_for(action, exposure_usd)
    receipt = {
        "action": action, "case_id": case_id, "route": r, "executed": False,
        "simulated": True, "reason": reason,
        "awaiting": {"L1": "team lead", "L2": "fraud manager"}.get(r, "human review"),
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _append(receipt)
    return receipt


def _append(receipt: dict[str, Any]) -> None:
    PATHS.staged.mkdir(parents=True, exist_ok=True)
    with (PATHS.staged / EXECUTION_LOG).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(receipt, ensure_ascii=False) + "\n")


def read_log(limit: int = 500) -> list[dict[str, Any]]:
    path = PATHS.staged / EXECUTION_LOG
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(x) for x in lines if x.strip()]

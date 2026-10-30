"""Case management across sittings (challenge C14).

A case is a record with a life: opened, awaiting evidence, escalated, pending
approval, approved or rejected, closed. Each run of the agent appends a new
version of the case's state changes; each human approval appends a transition.
Nothing is overwritten, so an analyst taking over cold sees the full history:
what changed, what it waits on, what was decided and by whom.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from ..config import PATHS

DIR = Path(os.environ.get("LIFECYCLE_DIR", "") or PATHS.repo / "data" / "lifecycle")


def _path(case_id: str):
    return DIR / f"{case_id}.jsonl"


def history(case_id: str) -> list[dict[str, Any]]:
    p = _path(case_id)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def append(case_id: str, event: dict[str, Any]) -> dict[str, Any]:
    DIR.mkdir(parents=True, exist_ok=True)
    rows = history(case_id)
    rec = {"version": len(rows) + 1, "logged_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                                                time.gmtime()), **event}
    with _path(case_id).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")
    return rec


def record_run(answer: dict[str, Any]) -> dict[str, Any]:
    rec = answer.get("agent_record", {})
    prev = history(answer["case_id"])
    last_hash = next((r.get("answer_hash") for r in reversed(prev) if r.get("kind") == "run"), None)
    return append(answer["case_id"], {
        "kind": "run", "answer_hash": rec.get("answer_hash"),
        "changed_since_last_run": last_hash is not None and last_hash != rec.get("answer_hash"),
        "state": answer["case"]["status"], "verdict": answer["case"]["verdict"],
        "transitions": rec.get("lifecycle", []), "handover": rec.get("handover", {})})


def record_approval(case_id: str, approval: dict[str, Any]) -> dict[str, Any]:
    to = "APPROVED" if approval.get("approved") else "REJECTED"
    return append(case_id, {"kind": "approval", "to": f"{approval['action']}_{to}",
                            "by": approval["actor_id"], "role": approval["actor_role"],
                            "approval_seq": approval["seq"], "approval_hash": approval["hash"]})


# ------------------------------------------------------- ownership + SLA ----
# How long a case may sit in each state before it is overdue. R4's 24 hours
# for a customer reply is policy; the others are bank-configurable defaults
# (CASE_SLA_HOURS="ESCALATED=24,PENDING_APPROVAL=8"), stated, not hidden.
SLA_HOURS = {"AWAITING_EVIDENCE": 24.0, "ESCALATED": 24.0, "PENDING_APPROVAL": 8.0,
             "OPENED": 4.0, "WATCH": 24.0 * 30}
SLA_SOURCE = {"AWAITING_EVIDENCE": "policy R4 (no reply within 24 hours)"}
ASSIGNERS = {"team_lead", "fraud_manager"}
_STATE_OF = {"escalated": "ESCALATED", "pending_approval": "PENDING_APPROVAL",
             "awaiting_evidence": "AWAITING_EVIDENCE", "open": "OPENED", "opened": "OPENED"}


def _sla_hours() -> dict[str, float]:
    out = dict(SLA_HOURS)
    for item in os.environ.get("CASE_SLA_HOURS", "").split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip().upper()] = float(v)
    return out


def assign(case_id: str, principal, to_actor: str, note: str = "") -> dict[str, Any]:
    """Take or hand over a case. Anyone may take an unowned case or one they
    own; only a team lead or fraud manager may assign it to someone else or
    take it from its owner. The record says who did it."""
    cur = owner(case_id)
    to_actor = (to_actor or principal.actor_id).strip()
    if (to_actor != principal.actor_id or (cur and cur != principal.actor_id)) \
            and principal.role not in ASSIGNERS:
        raise PermissionError(f"role {principal.role} may only take an unowned case for "
                              f"itself (owner: {cur or 'none'})")
    return append(case_id, {"kind": "assignment", "from": cur, "to": to_actor,
                            "by": principal.actor_id, "role": principal.role,
                            "note": note[:300]})


def owner(case_id: str) -> str:
    for r in reversed(history(case_id)):
        if r.get("kind") == "assignment":
            return r.get("to", "")
    return ""


def status(case_id: str, answer: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """Where the case stands for whoever picks it up: owner, state, how long it
    has been in that state, when it is due, and whether it is overdue."""
    now = time.time() if now is None else now
    hist = history(case_id)
    raw = answer["case"]["status"]
    state = _STATE_OF.get(raw, raw.upper())
    closed = raw.startswith("closed")
    entered = None
    for r in reversed(hist):
        if r.get("kind") in {"run", "approval"}:
            entered = r["logged_at"]
            break
    sla = _sla_hours().get(state)
    out = {"case_id": case_id, "state": state, "owner": owner(case_id) or None,
           "entered_state_at": entered, "sla_hours": None if closed else sla,
           "sla_source": SLA_SOURCE.get(state, "bank default (CASE_SLA_HOURS)") if sla else "",
           "due_at": None, "overdue": False, "hours_in_state": None}
    if entered and sla and not closed:
        t = time.mktime(time.strptime(entered, "%Y-%m-%d %H:%M:%S")) - time.timezone
        out["hours_in_state"] = round((now - t) / 3600, 1)
        out["due_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t + sla * 3600))
        out["overdue"] = now > t + sla * 3600
    return out

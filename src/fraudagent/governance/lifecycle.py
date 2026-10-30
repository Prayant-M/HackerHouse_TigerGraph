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

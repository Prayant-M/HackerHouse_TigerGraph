"""Hash-chained decision ledger.

Every decision the agent takes is appended with the hash of the one before it.
Tampering with a recorded decision — or quietly reordering them after the fact
— breaks the chain, and `verify()` says exactly where. A fraud investigation
that a bank has to defend to a regulator needs its audit trail to be checkable,
not merely present.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

GENESIS = "0" * 64


@dataclass
class Decision:
    decision_id: str
    step: int
    node: str
    posterior_before: dict[str, float]
    posterior_after: dict[str, float]
    rationale: str
    payload: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = GENESIS
    hash: str = ""

    def digest(self) -> str:
        body = {
            "decision_id": self.decision_id,
            "step": self.step,
            "node": self.node,
            "posterior_before": {k: round(v, 6) for k, v in self.posterior_before.items()},
            "posterior_after": {k: round(v, 6) for k, v in self.posterior_after.items()},
            "rationale": self.rationale,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
        }
        blob = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["posterior_before"] = {k: round(v, 4) for k, v in self.posterior_before.items()}
        d["posterior_after"] = {k: round(v, 4) for k, v in self.posterior_after.items()}
        return d


class DecisionLedger:
    def __init__(self, case_id: str) -> None:
        self.case_id = case_id
        self.decisions: list[Decision] = []

    def record(self, node: str, posterior_before: dict[str, float],
               posterior_after: dict[str, float], rationale: str,
               payload: dict[str, Any] | None = None) -> Decision:
        step = len(self.decisions) + 1
        prev = self.decisions[-1].hash if self.decisions else GENESIS
        d = Decision(
            decision_id=f"{self.case_id}-D{step:02d}",
            step=step, node=node,
            posterior_before=dict(posterior_before),
            posterior_after=dict(posterior_after),
            rationale=rationale, payload=payload or {}, prev_hash=prev,
        )
        d.hash = d.digest()
        self.decisions.append(d)
        return d

    def verify(self) -> tuple[bool, str]:
        prev = GENESIS
        for d in self.decisions:
            if d.prev_hash != prev:
                return False, f"chain break at {d.decision_id}: prev_hash mismatch"
            if d.hash != d.digest():
                return False, f"tampered content at {d.decision_id}"
            prev = d.hash
        return True, f"chain intact across {len(self.decisions)} decisions"

    @property
    def head(self) -> str:
        return self.decisions[-1].hash if self.decisions else GENESIS

    def as_list(self) -> list[dict[str, Any]]:
        return [d.as_dict() for d in self.decisions]

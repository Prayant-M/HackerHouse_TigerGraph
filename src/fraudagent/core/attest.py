"""Attestation: a claim nobody can check does not count.

Every evidence item, finding, SAR sentence, containment number and proof fact
becomes an `Attestation`:

    what           the claim, in one sentence
    evidence_ids   the exact transaction, card and customer ids behind it
    query, params  the graph query that produced it
    tool_calls     the recorded tool calls (agent/recorder.py) whose responses
                   carry those ids, each with the SHA-256 of what came back
    ran_at         when, and
    data_snapshot  which data: a hash of the raw-file manifest plus the graph
                   load version

`eval/attest_verify.py` re-runs every recorded call against the live store and
fails on any digest mismatch, then re-checks the claims that are arithmetic
(exposure = sum of affected amounts, first suspicious txn = earliest affected,
every id exists and sits before as_of).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from ..config import PATHS

MANIFEST = PATHS.repo / "data" / "manifest.json"


@lru_cache(maxsize=1)
def data_snapshot() -> str:
    """sha256(manifest || graph load version). The manifest hashes every raw file
    (ingest/00_manifest.py); the load version names the graph load."""
    man = MANIFEST.read_text(encoding="utf-8") if MANIFEST.exists() else "no-manifest"
    load = os.environ.get("TG_LOAD_VERSION", "") or _staged_version()
    return hashlib.sha256((man + "\n" + load).encode("utf-8")).hexdigest()[:32]


def _staged_version() -> str:
    parts = []
    for name in ("transactions.parquet", "closed_cases.parquet", "likelihood_ratios.json"):
        p = PATHS.staged / name
        if p.exists():
            parts.append(f"{name}:{p.stat().st_size}")
    return "staged:" + "|".join(parts)


@dataclass
class Attestation:
    id: str
    what: str
    evidence_ids: list[str]
    query: str
    params: dict[str, Any]
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    ran_at: str = ""
    data_snapshot: str = ""
    kind: str = "evidence"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_REF = re.compile(r"^(?:query|attribute|derived|trigger|evidence_request|policy):([\w.]+)"
                  r"(?:\((.*)\))?$")


def parse_ref(ref: str) -> tuple[str, dict[str, Any]]:
    """`query:card_baseline(card_id=C1, cutoff=...)` -> ("card_baseline", {...})."""
    m = _REF.match(ref or "")
    if not m:
        return ref or "", {}
    name, args = m.group(1), m.group(2) or ""
    params: dict[str, Any] = {}
    for part in re.split(r",\s*(?=\w+=)", args):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.strip()] = v.strip()
    return name, params


def _calls_touching(ids: list[str], calls: list[dict[str, Any]], limit: int = 6) -> list[dict]:
    """Recorded calls whose parameters mention any of the ids. Their response
    digests are what attest-verify re-checks."""
    out = []
    if not ids:
        return out
    needles = [str(i) for i in ids if i][:12]
    for c in calls:
        if not c.get("ok"):
            continue
        params = c.get("params", "")
        if any(n in params for n in needles):
            out.append({"seq": c["seq"], "method": c["method"], "key": c["key"],
                        "digest": c["digest"]})
            if len(out) >= limit:
                break
    return out


class Attestor:
    def __init__(self, case_id: str, calls: list[dict[str, Any]]) -> None:
        self.case_id = case_id
        self.calls = calls
        self.items: list[Attestation] = []
        self.ran_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.snapshot = data_snapshot()

    def add(self, what: str, ids: list[str], ref: str, kind: str = "evidence",
            params: dict[str, Any] | None = None, extra_calls: list[dict] | None = None) -> str:
        name, parsed = parse_ref(ref)
        aid = f"{self.case_id}-A{len(self.items) + 1:03d}"
        calls = _calls_touching([str(i) for i in ids], self.calls)
        for c in extra_calls or []:
            if c not in calls:
                calls.append(c)
        self.items.append(Attestation(
            id=aid, what=what, evidence_ids=[str(i) for i in ids], query=name,
            params=params if params is not None else parsed, tool_calls=calls,
            ran_at=self.ran_at, data_snapshot=self.snapshot, kind=kind))
        return aid

    def calls_for(self, method: str) -> list[dict[str, Any]]:
        return [{"seq": c["seq"], "method": c["method"], "key": c["key"], "digest": c["digest"]}
                for c in self.calls if c.get("ok") and c["method"] == method]

    def as_list(self) -> list[dict[str, Any]]:
        return [a.as_dict() for a in self.items]

    def unattested(self) -> list[str]:
        """Claims with neither ids nor a recorded call behind them."""
        return [a.id for a in self.items if not a.evidence_ids and not a.tool_calls
                and a.kind not in {"policy_text", "simulated_response"}]


def answer_hash(answer: dict[str, Any]) -> str:
    """Hash of the decision fields only, for `make twice` and the graph record."""
    c = answer.get("case", {})
    body = {"verdict": c.get("verdict"), "p": c.get("fraud_probability"),
            "pattern": c.get("pattern"), "exposure": c.get("exposure_usd"),
            "affected": c.get("affected_txn_ids"), "first": c.get("first_suspicious_txn_id"),
            "connected": c.get("connected_card_ids"),
            "initial": answer.get("next_best_actions", {}).get("initial"),
            "final": answer.get("next_best_actions", {}).get("final"),
            "sar": answer.get("sar", {}).get("file")}
    blob = json.dumps(body, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

"""Server-side approvals (policy §2, brief §9).

* **Token -> role on the server.** `APPROVAL_TOKENS` holds
  `actor_id:role:sha256(token)` triples (comma-separated) in the environment.
  The plaintext tokens are handed to people, never committed. A role read from
  the request body is ignored: the role is whatever the token hashes to.
* **Routes.** L1 actions need `team_lead` or `fraud_manager`; L2 actions need
  `fraud_manager`. `analyst` tokens can give feedback, not approvals.
* **No self-approval.** The proposer of an action (the agent, or the analyst who
  proposed it) cannot approve it.
* **Append-only, signed, chained.** Every decision *and every refusal* is a
  record in `data/approvals/ledger.jsonl` carrying the previous record's hash
  and an Ed25519 signature by the server key. There is no edit endpoint;
  `verify()` detects an edited, reordered or transplanted record. An approval
  binds the case id, the action index, the action name and the answer hash, so
  an old approval replayed against another case, or against a re-run whose
  decision changed, fails.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import PATHS

LEDGER = PATHS.repo / "data" / "approvals" / "ledger.jsonl"
KEY_FILE = PATHS.repo / ".cache" / "approval_signing_key"
GENESIS = "0" * 64
ROUTE_ROLES = {"L1": {"team_lead", "fraud_manager"}, "L2": {"fraud_manager"}}
ROLES = {"analyst", "team_lead", "fraud_manager"}
_lock = threading.Lock()


class AuthError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


@dataclass(frozen=True)
class Principal:
    actor_id: str
    role: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_table() -> dict[str, Principal]:
    out: dict[str, Principal] = {}
    for item in os.environ.get("APPROVAL_TOKENS", "").split(","):
        parts = item.strip().split(":")
        if len(parts) == 3 and parts[1] in ROLES:
            out[parts[2].lower()] = Principal(parts[0], parts[1])
    return out


def authenticate(authorization: str | None) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError(401, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    h = hash_token(token)
    for known, principal in _token_table().items():
        if hmac.compare_digest(known, h):
            return principal
    raise AuthError(401, "unknown token")


# ------------------------------------------------------------ signing ----
def _signing_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    seed_hex = os.environ.get("APPROVAL_SIGNING_KEY", "").strip()
    if seed_hex:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))
    if KEY_FILE.exists():
        return Ed25519PrivateKey.from_private_bytes(KEY_FILE.read_bytes())
    from cryptography.hazmat.primitives import serialization

    key = Ed25519PrivateKey.generate()
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_bytes(key.private_bytes(serialization.Encoding.Raw,
                                           serialization.PrivateFormat.Raw,
                                           serialization.NoEncryption()))
    return key


def public_key_hex() -> str:
    from cryptography.hazmat.primitives import serialization

    return _signing_key().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def _body(rec: dict[str, Any]) -> bytes:
    core = {k: v for k, v in rec.items() if k not in {"hash", "signature"}}
    return json.dumps(core, sort_keys=True, separators=(",", ":"), default=str).encode()


def _seal(rec: dict[str, Any]) -> dict[str, Any]:
    body = _body(rec)
    rec["hash"] = hashlib.sha256(body).hexdigest()
    rec["signature"] = _signing_key().sign(body).hex()
    return rec


# ------------------------------------------------------------- ledger ----
def read_ledger() -> list[dict[str, Any]]:
    if not LEDGER.exists():
        return []
    return [json.loads(x) for x in LEDGER.read_text(encoding="utf-8").splitlines() if x.strip()]


def _append(rec: dict[str, Any]) -> dict[str, Any]:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    rows = read_ledger()
    rec["seq"] = len(rows) + 1
    rec["prev_hash"] = rows[-1]["hash"] if rows else GENESIS
    _seal(rec)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")
    return rec


def verify() -> tuple[bool, str]:
    """Chain + signatures. Any edit, reorder or transplant breaks one of them."""
    from cryptography.exceptions import InvalidSignature

    pub = _signing_key().public_key()
    prev = GENESIS
    for rec in read_ledger():
        if rec.get("prev_hash") != prev:
            return False, f"chain break at seq {rec.get('seq')}"
        body = _body(rec)
        if hashlib.sha256(body).hexdigest() != rec.get("hash"):
            return False, f"edited record at seq {rec.get('seq')}"
        try:
            pub.verify(bytes.fromhex(rec.get("signature", "")), body)
        except (InvalidSignature, ValueError):
            return False, f"bad signature at seq {rec.get('seq')}"
        prev = rec["hash"]
    return True, f"{len(read_ledger())} records, chain and signatures intact"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def refuse(principal: Principal | None, case_id: str, index: int, status: int,
           why: str, claimed_role: str = "") -> dict[str, Any]:
    with _lock:
        return _append({"kind": "refusal", "case_id": case_id, "index": index,
                        "actor_id": principal.actor_id if principal else "",
                        "actor_role": principal.role if principal else "",
                        "claimed_role_in_body_ignored": claimed_role, "status": status,
                        "reason": why, "at": _now()})


def decide(principal: Principal, answer: dict[str, Any], index: int, approved: bool,
           note: str = "", proposed_by: str = "agent", body_role: str = "",
           presented: dict[str, Any] | None = None) -> dict[str, Any]:
    """Approve or reject one routed action. Raises AuthError (and logs the
    refusal) on any failure; returns the sealed record on success."""
    from ..core.attest import answer_hash

    case_id = answer["case_id"]
    finals = answer["next_best_actions"]["final"]
    if not 0 <= index < len(finals):
        refuse(principal, case_id, index, 404, "no such action", body_role)
        raise AuthError(404, f"{case_id} has no final action {index}")
    act = finals[index]
    route = act["route"]
    ahash = answer_hash(answer)
    if presented:
        # A record carried over from elsewhere: it must be for this exact case,
        # action and decision, or it is a replay.
        if (presented.get("case_id") != case_id or presented.get("index") != index
                or presented.get("answer_hash") != ahash):
            refuse(principal, case_id, index, 409, "replayed approval from another case or "
                   "an earlier decision", body_role)
            raise AuthError(409, "approval record does not match this case and decision")
    if route == "auto":
        refuse(principal, case_id, index, 400, "auto action needs no approval", body_role)
        raise AuthError(400, f"{act['action']} is an auto action")
    if principal.actor_id == proposed_by:
        refuse(principal, case_id, index, 403, "self-approval", body_role)
        raise AuthError(403, "the proposer of an action cannot approve it")
    if principal.role not in ROUTE_ROLES[route]:
        refuse(principal, case_id, index, 403,
               f"role {principal.role} cannot approve a {route} action", body_role)
        raise AuthError(403, f"{route} action {act['action']} needs "
                             f"{' or '.join(sorted(ROUTE_ROLES[route]))}; token is "
                             f"{principal.role}")
    with _lock:
        for rec in read_ledger():
            if (rec.get("kind") == "decision" and rec.get("case_id") == case_id
                    and rec.get("index") == index and rec.get("answer_hash") == ahash):
                _append({"kind": "refusal", "case_id": case_id, "index": index,
                         "actor_id": principal.actor_id, "actor_role": principal.role,
                         "status": 409, "reason": "already decided; decisions are not "
                         "editable", "at": _now(), "existing_seq": rec["seq"]})
                raise AuthError(409, f"already decided at seq {rec['seq']}; approvals are "
                                     "append-only and cannot be edited")
        return _append({"kind": "decision", "case_id": case_id, "index": index,
                        "graph_case_id": answer["case"].get("graph_case_id", ""),
                        "action": act["action"], "route": route, "approved": bool(approved),
                        "actor_id": principal.actor_id, "actor_role": principal.role,
                        "claimed_role_in_body_ignored": body_role, "proposed_by": proposed_by,
                        "answer_hash": ahash, "note": note[:500], "at": _now()})


def decisions_for(case_id: str) -> list[dict[str, Any]]:
    return [r for r in read_ledger() if r.get("case_id") == case_id]


def make_tokens(actors: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Generate plaintext tokens and the env line holding only their hashes."""
    import secrets

    out = []
    for actor, role in actors:
        tok = secrets.token_urlsafe(24)
        out.append({"actor_id": actor, "role": role, "token": tok, "hash": hash_token(tok)})
    return out


def env_line(tokens: list[dict[str, str]]) -> str:
    return "APPROVAL_TOKENS=" + ",".join(f"{t['actor_id']}:{t['role']}:{t['hash']}"
                                         for t in tokens)


def ledger_path() -> Path:
    return LEDGER

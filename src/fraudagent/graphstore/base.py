"""The investigation tool surface.

Every method here is one graph primitive. Each has a 1:1 counterpart in
`graph/queries/*.gsql` that runs inside TigerGraph, and a local mirror in
`local.py` that computes the identical answer from the staged parquet so the
pipeline is testable and reproducible without a live instance.

Two hard rules hold for every read:

* **`as_of` is a wall.** Nothing at or after the case's `as_of` may influence an
  answer. The closed-case history confirms this is the right discipline: in all
  5,565 closed investigations the last transaction in the episode precedes
  `opened_at`.
* **The graph decides, the LLM explains.** Everything returned here is computed,
  never generated.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Sequence


@dataclass
class TxnRow:
    txn_id: str
    ts: datetime
    amount: float
    product_cd: str
    channel: str
    risk_score: float
    customer_id: str
    card_id: str
    region: str
    country: str
    device_profile: str
    device_status: str
    proxy: str
    email_p: str
    email_r: str
    dist1: float | None = None
    dist2: float | None = None
    amt_zscore_card: float = 0.0
    gap_hours: float | None = None
    m_mismatch_count: int = 0
    has_identity: bool = False

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.isoformat(sep=" ")
        return d


@dataclass
class RecalledCase:
    case_id: str
    outcome: str
    pattern: str
    similarity: float
    shared_entities: int
    fused_score: float
    exposure_usd: float
    opened_at: str
    narrative: str
    shared_with: list[str] = field(default_factory=list)


def _dt19(v: Any) -> str:
    s = str(v or "")[:19]
    return s if len(s) == 19 else "1970-01-01 00:00:00"


def case_write_doc(gid: str, c: dict[str, Any]) -> dict[str, Any]:
    """The JSON document the installed `case_write` query accepts. Every key the
    query reads is always present, so a missing field fails here, in Python,
    with a clear message, rather than as an opaque GSQL runtime error."""
    sar = c.get("sar") or {}
    dates = sar.get("activity_dates") or ["", ""]
    proof = c.get("proof") or {}
    doc: dict[str, Any] = {
        "case_id": str(c.get("case_id", "")), "status": c.get("status", ""),
        "verdict": c.get("verdict", ""), "trigger_type": c.get("trigger_type", ""),
        "opened_at": _dt19(c.get("opened_at")), "as_of": _dt19(c.get("as_of")),
        "fraud_probability": float(c.get("fraud_probability", 0.0)),
        "confidence": float(c.get("confidence", 0.0)), "pattern": c.get("pattern", ""),
        "pattern_description": c.get("pattern_description", ""),
        "exposure_usd": float(c.get("exposure_usd", 0.0)), "summary": c.get("summary", ""),
        "narrative": c.get("narrative", ""), "stop_reason": c.get("stop_reason", ""),
        "ledger_head": c.get("ledger_head", ""), "tool_calls": int(c.get("tool_calls", 0)),
        "latency_s": float(c.get("latency_s", 0.0)),
        "lifecycle_state": c.get("lifecycle_state", ""), "parent_case": c.get("parent_case", ""),
        "proof_margin": int(proof.get("margin_k") or -1),
        "proof_minimal": ",".join(proof.get("minimal_sufficient_facts", [])),
        "gate_applied": bool((c.get("gate") or {}).get("applied", False)),
        "conformal_set": ",".join((c.get("conformal") or {}).get("set", []) or []),
        "data_snapshot": c.get("data_snapshot", ""), "answer_hash": c.get("answer_hash", ""),
        "card_id": c.get("card_id", ""), "customer_id": c.get("customer_id", ""),
        "evidence": [{"id": f"{gid}-E{i:02d}", "kind": e.get("source", "graph"),
                      "claim": e.get("claim", ""), "source_tool": e.get("ref", ""),
                      "reliability": float(e.get("reliability", 1.0) or 1.0),
                      "delta": float(e.get("delta_fraud_probability", 0.0) or 0.0)}
                     for i, e in enumerate(c.get("evidence", []), 1)],
        "decisions": [{"id": d["decision_id"], "step": int(d.get("step", 0)),
                       "node": d.get("node", ""), "before": float(d.get("p_fraud_before", 0.0)),
                       "after": float(d.get("p_fraud_after", 0.0)),
                       "rationale": d.get("rationale", ""), "prev_hash": d.get("prev_hash", ""),
                       "hash": d.get("hash", "")} for d in c.get("decisions", [])],
        "actions": [{"id": f"{gid}-{ph[:3].upper()}-{i:02d}", "action": a["action"],
                     "phase": ph, "route": a["route"], "reason": a.get("reason", ""),
                     "rule": a.get("reason", "").split(":", 1)[0],
                     "executed": bool(a.get("executed", False))}
                    for ph in ("initial", "final")
                    for i, a in enumerate((c.get("actions") or {}).get(ph, []), 1)],
        "requests": [{"id": f"{gid}-R{i:02d}", "type": r.get("type", ""),
                      "channel": r.get("channel", ""), "question": r.get("question", ""),
                      "gain": float(r.get("expected_info_gain", 0.0)),
                      "cost": float(r.get("cost", 0.0)),
                      "asked_after_step": int(r.get("asked_after_step", 0)),
                      "seed": int(r.get("simulation_seed", 0)) % 2147483647,
                      "response": r.get("assumed_response", "")}
                     for i, r in enumerate(c.get("evidence_requests", []), 1)],
        "sar": {"file": bool(sar.get("file")), "reason": sar.get("reason", ""),
                "narrative": sar.get("narrative", ""),
                "total_amount_usd": float(sar.get("total_amount_usd", 0.0) or 0.0),
                "activity_start": str(dates[0]) if dates else "",
                "activity_end": str(dates[-1]) if dates else ""},
        "state_changes": [{"id": f"{gid}-S{i:02d}", "from": s.get("from", ""),
                           "to": s.get("to", ""), "at": _dt19(s.get("at")),
                           "actor": s.get("actor", ""), "role": s.get("role", ""),
                           "reason": s.get("reason", ""),
                           "evidence_ids": ",".join(map(str, s.get("evidence_ids", [])))}
                          for i, s in enumerate(c.get("state_changes", []), 1)],
        "watch_children": [{"id": w["id"], "card_id": w.get("card_id", ""),
                            "reason": w.get("reason", "")}
                           for w in c.get("watch_children", [])],
        "links": {"txn_ids": [str(x) for x in c.get("affected_txn_ids", [])],
                  "connected_card_ids": list(c.get("connected_card_ids", [])),
                  "device_profiles": list(c.get("connected_device_profiles", [])),
                  "prior_case_ids": list(c.get("similar_prior_cases", [])),
                  "policy_doc_ids": [f"POLICY-{r}" for r in c.get("cited_rules", [])]},
    }
    origin = c.get("origin")
    if origin:
        doc["origin"] = {"type": origin["to_type"], "id": origin["to"],
                         "from": _dt19(origin["window"][0]), "to": _dt19(origin["window"][1]),
                         "lift": float(origin["lift"]), "p_value": float(origin["p_value"])}
    return doc


class GraphStore(ABC):
    """Read/write surface the agent and the MCP server both sit on."""

    backend: str = "abstract"

    # ------------------------------------------------------------ reads ----
    @abstractmethod
    def get_transaction(self, txn_id: str) -> TxnRow | None: ...

    @abstractmethod
    def card_history(self, card_id: str, as_of: datetime,
                     window_days: int | None = None, limit: int = 5000) -> list[TxnRow]: ...

    @abstractmethod
    def card_baseline(self, card_id: str, as_of: datetime) -> dict[str, Any]:
        """Distributional profile of the card strictly before `as_of`."""

    @abstractmethod
    def customer_cards(self, customer_id: str, as_of: datetime) -> list[str]: ...

    @abstractmethod
    def velocity_burst(self, card_id: str, as_of: datetime,
                       window_hours: float = 48.0) -> dict[str, Any]: ...

    @abstractmethod
    def card_testing_probe(self, card_id: str, as_of: datetime,
                           window_hours: float = 2.0,
                           small_amount: float = 5.0) -> dict[str, Any]: ...

    @abstractmethod
    def threshold_structuring_probe(self, card_id: str, as_of: datetime,
                                    window_minutes: float = 60.0) -> dict[str, Any]:
        """Undocumented typology U1 — a run of online purchases parked just under
        a round authorisation ceiling."""

    @abstractmethod
    def device_fanout(self, device_profile: str, as_of: datetime,
                      window_days: int = 30) -> dict[str, Any]: ...

    @abstractmethod
    def device_first_use(self, card_id: str, device_profile: str,
                         as_of: datetime, baseline_cutoff: datetime | None = None
                         ) -> dict[str, Any]: ...

    @abstractmethod
    def region_profile(self, card_id: str, as_of: datetime, region: str,
                       baseline_cutoff: datetime | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def out_of_region_probe(self, card_id: str, as_of: datetime, region: str,
                            baseline_cutoff: datetime | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def recurring_charge_probe(self, card_id: str, as_of: datetime, amount: float,
                               product_cd: str,
                               baseline_cutoff: datetime | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def episode_window(self, card_id: str, as_of: datetime,
                       window_hours: float = 72.0) -> dict[str, Any]:
        """The transactions in the suspect window, and the card's established
        behaviour strictly before it. Every anomaly signal is measured as
        window-against-baseline so that earlier legs of the same fraud episode
        cannot normalise the later ones."""

    @abstractmethod
    def email_mismatch_profile(self, txn_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def shared_entity_ring(self, card_id: str, as_of: datetime,
                           window_days: int = 30) -> dict[str, Any]: ...

    def peer_purchases(self, device_profile: str, card_id: str, amount: float,
                       as_of: datetime, window_days: int = 7) -> dict[str, Any]:
        """Purchases on *other* cards from the same device, near the flagged
        amount, inside the window. Rarity is judged by the caller."""
        return {"peers": [], "n_peer_cards": 0}

    def card_community(self, card_id: str) -> dict[str, Any]:
        """GDS algorithm output for a card (WCC component, PageRank position).
        Only the TigerGraph backend runs the algorithms; elsewhere it is empty."""
        return {}

    @abstractmethod
    def fraud_proximity(self, entity_ids: Sequence[str], as_of: datetime,
                        max_hops: int = 2) -> dict[str, Any]: ...

    @abstractmethod
    def hybrid_case_recall(self, query_text: str, entity_ids: Sequence[str],
                           as_of: datetime, k: int = 5) -> list[RecalledCase]:
        """The signature query: vector similarity over closed-case narratives
        fused with structural overlap on shared entities, in one call."""

    @abstractmethod
    def behavioural_neighbours(self, txn_id: str, as_of: datetime,
                               k: int = 10) -> dict[str, Any]: ...

    @abstractmethod
    def policy_retrieve(self, query_text: str, k: int = 5,
                        kinds: Iterable[str] | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def mixed_channel_probe(self, card_id: str, as_of: datetime,
                            window_hours: float = 48.0) -> dict[str, Any]: ...

    # ----------------------------------------------------------- writes ----
    @abstractmethod
    def write_case(self, case_doc: dict[str, Any]) -> str:
        """Persist the case as graph objects. Returns the case vertex id."""

    @abstractmethod
    def case_chain(self, graph_case_id: str) -> dict[str, Any]:
        """Reconstruct a written case: evidence -> findings -> decisions -> actions."""

    # ------------------------------------------ final-round primitives ----
    def ring_at_asof(self, card_id: str, as_of: datetime, lookback_days: int = 45,
                     max_cards: int = 60, rare_cards: int = 10) -> dict[str, Any]:
        return {"seed": card_id, "cards": [], "size": 1}

    def origin_counts(self, ring_cards: Sequence[str], since: datetime, until: datetime,
                      as_of: datetime) -> dict[str, Any]:
        return {"entities": [], "n_control": 0, "n_ring": len(ring_cards)}

    def origin_touchers(self, entity_type: str, entity: str, since: datetime,
                        until: datetime, as_of: datetime) -> list[dict[str, Any]]:
        return []

    def ring_exposure(self, ring_cards: Sequence[str], as_of: datetime,
                      lookback_days: int = 45, window_hours: float = 72.0) -> list[dict]:
        return []

    def precedent_by_facts(self, fact_mask: int, as_of: datetime) -> dict[str, Any] | None:
        """None means "answer from the local fact table" (core/proof.py)."""
        return None

    def compromise_watch(self, entity_ids: Sequence[str], as_of: datetime) -> list[dict]:
        return []

    def behaviour_vector(self, txn_id: str) -> list[float] | None:
        return None

    def data_gaps(self, txn_ids: Sequence[str]) -> dict[str, Any]:
        return {"n": 0, "no_identity": [], "empty_region": [], "placeholder_email": []}

    # ----------------------------------------------------------- health ----
    def health(self) -> dict[str, Any]:
        return {"backend": self.backend, "ok": True}

    def close(self) -> None:  # pragma: no cover - optional
        return None

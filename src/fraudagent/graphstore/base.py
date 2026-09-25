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

    # ----------------------------------------------------------- health ----
    def health(self) -> dict[str, Any]:
        return {"backend": self.backend, "ok": True}

    def close(self) -> None:  # pragma: no cover - optional
        return None

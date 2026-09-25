"""LangGraph assembly.

The topology is the product. A single-shot pipeline cannot honestly produce the
before/after pair of recommendations the submission format demands, because
there is no "before" — the recommendation has to be committed under uncertainty
*first*, then revised when the evidence lands, with the delta visible and
justified.

    trigger_intake -> case_opener -> evidence_planner -> graph_retrieval
      -> memory_recall -> policy_grounding -> ledger_update
      -> uncertainty_assessor --(enough)--> action_recommender
              |                                    ^
          (not enough)                             |
              v                                    |
      record_provisional -> evidence_gap_resolver --+
              ^                                     |
              +--------- re-assess (max 3) ---------+

    action_recommender -> permission_gate -> explainer -> case_writer
      -> memory_consolidator

If LangGraph is not installed the same topology runs through a small sequential
driver, so the repo has no hard dependency on it for reproducing the twenty
answer files.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable

from ..config import AGENT
from ..graphstore import get_store
from ..graphstore.base import GraphStore
from . import nodes
from .llm import LLMClient, get_llm
from .state import InvestigationState, Trigger

NODE_ORDER = [
    "trigger_intake", "case_opener", "evidence_planner", "graph_retrieval",
    "memory_recall", "policy_grounding", "ledger_update", "uncertainty_assessor",
]
TAIL = ["action_recommender", "permission_gate", "explainer", "case_writer",
        "memory_consolidator"]


def _bind(fn: Callable, store: GraphStore, llm: LLMClient):
    def wrapped(state: InvestigationState) -> InvestigationState:
        return fn(state, store, llm)
    wrapped.__name__ = fn.__name__
    return wrapped


def _route_after_assessment(state: InvestigationState) -> str:
    """The only branch in the graph. Continue gathering, or act."""
    if state["stop"].stop:
        return "act"
    if state["round"] >= AGENT.max_evidence_rounds:
        return "act"
    return "gather"


def build_graph(store: GraphStore | None = None, llm: LLMClient | None = None):
    """Compile the LangGraph. Returns `None` if LangGraph is unavailable."""
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception:                                    # pragma: no cover
        return None

    store = store or get_store()
    llm = llm or get_llm()
    g = StateGraph(InvestigationState)

    for name in NODE_ORDER + ["record_provisional", "evidence_gap_resolver"] + TAIL:
        g.add_node(name, _bind(getattr(nodes, name), store, llm))

    g.add_edge(START, "trigger_intake")
    for a, b in zip(NODE_ORDER, NODE_ORDER[1:]):
        g.add_edge(a, b)

    g.add_conditional_edges(
        "uncertainty_assessor", _route_after_assessment,
        {"gather": "record_provisional", "act": "action_recommender"})
    g.add_edge("record_provisional", "evidence_gap_resolver")
    g.add_edge("evidence_gap_resolver", "uncertainty_assessor")

    for a, b in zip(TAIL, TAIL[1:]):
        g.add_edge(a, b)
    g.add_edge(TAIL[-1], END)

    # No checkpointer: the state carries live objects (the evidence ledger, the
    # hash-chained decision log, the investigation context) that a msgpack
    # serialiser cannot round-trip, and flattening them to dicts purely to
    # satisfy a checkpointer would cost more than it buys. The reasoning trace
    # the console streams is built explicitly in `state["trace"]` instead, which
    # is also what ends up in the answer file's audit record.
    return g.compile()


class Investigator:
    """Runs one case end to end. Shares the store and the LLM cache across cases
    so a twenty-case benchmark pays the dataset load once."""

    def __init__(self, store: GraphStore | None = None, llm: LLMClient | None = None,
                 use_langgraph: bool = True) -> None:
        self.store = store or get_store()
        self.llm = llm or get_llm()
        self.app = build_graph(self.store, self.llm) if use_langgraph else None
        self.framework = "langgraph" if self.app is not None else "sequential-fallback"

    def run(self, trigger: Trigger, case_id: str) -> dict[str, Any]:
        start_calls = getattr(self.store, "call_count", 0)
        state: InvestigationState = {
            "case_id": case_id, "trigger": trigger, "started_at": time.time(),
            "trace": [], "requests": [], "round": 0,
        }
        if self.app is not None:
            final = self.app.invoke(
                state,
                config={"configurable": {"thread_id": case_id},
                        "recursion_limit": 60})
        else:
            final = self._run_sequential(state)
        result = final["result"]
        # per-case tool count, not the shared cumulative counter
        result["tool_calls"] = int(getattr(self.store, "call_count", 0) - start_calls)
        result["agent_record"]["framework"] = self.framework
        return result

    def _run_sequential(self, state: InvestigationState) -> InvestigationState:
        """Same topology, no dependency. Used when LangGraph is not installed."""
        for name in NODE_ORDER:
            state = getattr(nodes, name)(state, self.store, self.llm)
        while _route_after_assessment(state) == "gather":
            state = nodes.record_provisional(state, self.store, self.llm)
            state = nodes.evidence_gap_resolver(state, self.store, self.llm)
            state = nodes.uncertainty_assessor(state, self.store, self.llm)
        for name in TAIL:
            state = getattr(nodes, name)(state, self.store, self.llm)
        return state


def trigger_from_row(row: dict[str, Any]) -> Trigger:
    """Build a Trigger from one `case_pack.csv` row."""
    rs = row.get("risk_score")
    try:
        rs = float(rs) if rs not in (None, "", "nan") else None
    except (TypeError, ValueError):
        rs = None
    opened = row["opened_at"]
    if not isinstance(opened, datetime):
        opened = datetime.fromisoformat(str(opened))
    return Trigger(
        type=str(row["trigger_type"]), text=str(row.get("trigger_text", "")),
        flagged_txn_id=str(row["flagged_txn_id"]), card_id=str(row["card_id"]),
        customer_id=str(row["customer_id"]), opened_at=opened, risk_score=rs)

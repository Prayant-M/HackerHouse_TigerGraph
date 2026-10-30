"""Graph access layer: one interface, two backends."""

from __future__ import annotations

import os

from ..config import graph_backend
from .base import GraphStore, RecalledCase, TxnRow

__all__ = ["GraphStore", "TxnRow", "RecalledCase", "get_store"]

_CACHE: dict[str, GraphStore] = {}


def get_store(backend: str | None = None) -> GraphStore:
    """Return the configured store. `tigergraph` when credentials exist, else
    the local mirror (dev only). Fails closed by default (GRAPH_STRICT=1): a
    configured but unreachable TigerGraph raises instead of silently serving
    mirror data as if it were the graph. GRAPH_STRICT=0 restores the dev
    fallback, with a printed warning."""
    name = (backend or graph_backend()).lower()
    if name in _CACHE:
        return _CACHE[name]
    if name == "tigergraph":
        try:
            from .tigergraph import TigerGraphStore

            store: GraphStore = TigerGraphStore()
        except Exception as exc:  # pragma: no cover - depends on deployment
            # Fail closed on request: a demo should not present mirror results as
            # graph results because the workspace happened to be asleep.
            if os.environ.get("GRAPH_STRICT", "1").lower() in {"1", "true", "yes"}:
                raise RuntimeError(f"GRAPH_STRICT=1 and TigerGraph is unavailable: {exc}") from exc
            print(f"[graphstore] TigerGraph unavailable ({exc}); falling back to local mirror")
            from .local import LocalGraphStore

            store = LocalGraphStore()
            name = "local"
    else:
        from .local import LocalGraphStore

        store = LocalGraphStore()
    _CACHE[name] = store
    return store

"""Graph access layer: one interface, two backends."""

from __future__ import annotations

from ..config import graph_backend
from .base import GraphStore, RecalledCase, TxnRow

__all__ = ["GraphStore", "TxnRow", "RecalledCase", "get_store"]

_CACHE: dict[str, GraphStore] = {}


def get_store(backend: str | None = None) -> GraphStore:
    """Return the configured store. `tigergraph` when credentials exist, else
    the local mirror. Falls back to local with a warning if the live instance
    cannot be reached, so a demo never dies on a cold workspace."""
    name = (backend or graph_backend()).lower()
    if name in _CACHE:
        return _CACHE[name]
    if name == "tigergraph":
        try:
            from .tigergraph import TigerGraphStore

            store: GraphStore = TigerGraphStore()
        except Exception as exc:  # pragma: no cover - depends on deployment
            print(f"[graphstore] TigerGraph unavailable ({exc}); falling back to local mirror")
            from .local import LocalGraphStore

            store = LocalGraphStore()
            name = "local"
    else:
        from .local import LocalGraphStore

        store = LocalGraphStore()
    _CACHE[name] = store
    return store

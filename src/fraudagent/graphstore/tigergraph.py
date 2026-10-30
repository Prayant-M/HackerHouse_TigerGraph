"""TigerGraph-backed store — the production path.

Every read here calls an installed GSQL query from `graph/queries/`; every
write goes through the single installed `case_write` query. Both
travel through the TigerGraph MCP server (`mcp_client.py`) when it is running,
and over a direct pyTigerGraph connection when it is not.
The window matchers are the *same* functions the local mirror uses
(`graphstore/matchers.py`), so the two backends answer the same question rather
than merely similar ones, and `tests/test_backend_parity.py` asserts that on a
sample of cases when a live instance is configured.

Configuration comes from `.env` (see SETUP_REQUIRED_FROM_YOU.md). If the
workspace is asleep or unreachable, `graphstore.get_store()` falls back to the
local mirror with a printed warning rather than dying — a Savanna workspace
that auto-stopped should not be able to kill a demo.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

import numpy as np

from ..config import EMBED, PATHS, TG
from ..memory.embeddings import Embedder
from .base import GraphStore, RecalledCase, TxnRow, case_write_doc
from .matchers import (detect_card_testing, detect_threshold_structuring,
                       recurrence_from_rows)

DT = "%Y-%m-%d %H:%M:%S"


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.strptime(str(value)[:19], DT)


def _fmt(value: datetime) -> str:
    return value.strftime(DT)


class _Gateway:
    """The agent's route to the graph: the TigerGraph MCP server when it is up,
    the direct pyTigerGraph connection to the *same graph* otherwise.

    Least privilege: the gateway exposes reads and allow-listed installed
    queries only. There is no vertex or edge upsert on it; the one write path is
    the installed `case_write` query. A fallback from MCP to direct marks the
    run `transport_degraded`, and with MCP_STRICT=1 it stops instead."""

    def __init__(self, conn: Any, mcp: Any) -> None:
        self.conn, self.mcp = conn, mcp
        self.fallbacks = 0
        self.last_error = ""
        self.degraded = False

    @property
    def transport(self) -> str:
        if self.mcp is None:
            return "direct"
        return "mcp+direct(degraded)" if self.degraded else "mcp"

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if self.mcp is not None:
            try:
                return getattr(self.mcp, name)(*args, **{k: v for k, v in kwargs.items()
                                                         if k != "usePost"})
            except Exception as exc:
                self.fallbacks += 1
                self.degraded = True
                self.last_error = f"{name}: {exc}"
                if os.environ.get("MCP_STRICT", "0").lower() in {"1", "true", "yes"}:
                    raise
                if self.fallbacks in (1, 10, 100):
                    print(f"[graphstore] MCP {name} failed ({exc}); transport_degraded: "
                          "using the direct connection to the same graph")
        return getattr(self.conn, name)(*args, **kwargs)

    def runInstalledQuery(self, name: str, *a: Any, **k: Any) -> Any:
        if name not in allowed_queries():
            raise PermissionError(f"query {name!r} is not on the agent allow-list")
        return self._call("runInstalledQuery", name, *a, **k)

    def getVerticesById(self, *a: Any, **k: Any) -> Any:
        return self._call("getVerticesById", *a, **k)

    def getEdges(self, *a: Any, **k: Any) -> Any:
        return self._call("getEdges", *a, **k)


def allowed_queries() -> frozenset[str]:
    """TG_ALLOWED_QUERIES (comma list), else every query *defined* in
    graph/queries/*.gsql and graph/algorithms/05 (card_community), minus the
    console-only governance_write and the retired case_write_links. Projection
    builders and GDS installers are loader-only and never on the list."""
    import re

    raw = os.environ.get("TG_ALLOWED_QUERIES", "").strip()
    if raw:
        return frozenset(x.strip() for x in raw.split(",") if x.strip())
    names: set[str] = set()
    pat = re.compile(r"CREATE\s+OR\s+REPLACE\s+(?:DISTRIBUTED\s+)?QUERY\s+(\w+)", re.I)
    for f in list((PATHS.repo / "graph" / "queries").glob("*.gsql")) + list(
            (PATHS.repo / "graph" / "algorithms").glob("05_*.gsql")):
        names.update(pat.findall(f.read_text(encoding="utf-8")))
    return frozenset(n for n in names if n not in {"governance_write", "case_write_links"}
                     and not n.startswith(("build_", "GDBMS_")))


def _strict() -> bool:
    return os.environ.get("GRAPH_STRICT", "1").lower() in {"1", "true", "yes"}


class TigerGraphStore(GraphStore):
    backend = "tigergraph"

    def __init__(self) -> None:
        import pyTigerGraph as tg

        if not TG.configured:
            raise RuntimeError(
                "TigerGraph is not configured — set TG_HOST and TG_PASSWORD (or TG_SECRET) "
                "in .env. See SETUP_REQUIRED_FROM_YOU.md §2.")
        self.conn = tg.TigerGraphConnection(
            host=TG.host, graphname=TG.graph, username=TG.username,
            password=TG.password, restppPort=TG.restpp_port, gsPort=TG.gsql_port,
        )
        if TG.token:
            self.conn.apiToken = TG.token
        elif TG.secret:
            self.conn.getToken(TG.secret)
        else:
            try:
                self.conn.getToken(self.conn.createSecret())
            except Exception:
                pass                       # username/password auth is enough on CE
        self.conn.echo()                   # fails loudly if the workspace is asleep
        self._mcp = None
        if TG.via_mcp:
            try:
                from .mcp_client import TigerGraphMCPClient

                self._mcp = TigerGraphMCPClient()
            except Exception as exc:
                print(f"[graphstore] TigerGraph MCP unavailable ({exc}); "
                      "using the direct pyTigerGraph connection")
        self.graph = _Gateway(self.conn, self._mcp)
        self.call_count = 0
        self._embedder: Embedder | None = None

    # -------------------------------------------------------- internals ----
    def _run(self, name: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.call_count += 1
        return self._strip_set_prefix(
            self.graph.runInstalledQuery(name, params or {}, timeout=60_000))

    @classmethod
    def _strip_set_prefix(cls, value: Any) -> Any:
        """`PRINT window[window.ts]` comes back keyed "window.ts" on 4.x; the
        readers below expect the bare attribute name."""
        if isinstance(value, list):
            return [cls._strip_set_prefix(v) for v in value]
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if isinstance(v, dict) and k == "attributes":
                    v = {a.split(".", 1)[1] if "." in a else a: x for a, x in v.items()}
                out[k] = cls._strip_set_prefix(v)
            return out
        return value

    @staticmethod
    def _first(result: list[dict[str, Any]], key: str, default: Any = None) -> Any:
        for block in result or []:
            if key in block:
                return block[key]
        return default

    def _embedder_or_load(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder.load(PATHS.staged / "embedder.pkl")
        return self._embedder

    @staticmethod
    def _row_to_txn(attr: dict[str, Any]) -> TxnRow:
        return TxnRow(
            txn_id=str(attr["txn_id"]), ts=_dt(attr["ts"]), amount=float(attr["amount"]),
            product_cd=str(attr.get("product_cd", "")), channel=str(attr.get("channel", "")),
            risk_score=float(attr.get("risk_score") or 0.0),
            customer_id=str(attr.get("customer_id", "")), card_id=str(attr.get("card_id", "")),
            region=str(attr.get("region", "")), country=str(attr.get("country", "")),
            device_profile=str(attr.get("device_profile", "")),
            device_status=str(attr.get("device_status", "")),
            proxy=str(attr.get("proxy_type", attr.get("proxy", ""))),
            email_p=str(attr.get("email_p", "")), email_r=str(attr.get("email_r", "")),
            dist1=attr.get("dist1"), dist2=attr.get("dist2"),
            amt_zscore_card=float(attr.get("amt_zscore_card") or 0.0),
            m_mismatch_count=int(attr.get("m_mismatch_count") or 0),
            has_identity=bool(attr.get("device_profile")),
        )

    def _txn_rows(self, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for r in rows or []:
            a = r.get("attributes", r)
            out.append({"txn_id": str(a.get("txn_id") or r.get("v_id")),
                        "ts": _dt(a["ts"]), "amount": float(a["amount"]),
                        "product_cd": str(a.get("product_cd", "")),
                        "channel": str(a.get("channel", "")),
                        "region": str(a.get("region", "")),
                        "device_status": str(a.get("device_status", ""))})
        return out

    # ------------------------------------------------------------ reads ----
    def get_transaction(self, txn_id: str) -> TxnRow | None:
        self.call_count += 1
        try:
            rows = self.graph.getVerticesById("Transaction", str(txn_id))
        except Exception as exc:
            # TigerGraph answers an unknown id with error 601; that is "no such
            # transaction", not a failed dependency.
            if "601" in str(exc) or "not a valid vertex id" in str(exc):
                return None
            raise
        if not rows:
            return None
        attr = dict(rows[0].get("attributes", {}))
        attr["txn_id"] = str(txn_id)
        # the device profile lives on the edge target, not on Transaction
        try:
            self.call_count += 1
            devs = self.graph.getEdges("Transaction", str(txn_id), "FROM_DEVICE")
            if devs:
                attr["device_profile"] = str(devs[0]["to_id"])
        except Exception:
            if _strict():
                raise
            attr.setdefault("device_profile", "")
        for side, edge in (("email_p", "PURCHASER_EMAIL"), ("email_r", "RECIPIENT_EMAIL")):
            try:
                self.call_count += 1
                e = self.graph.getEdges("Transaction", str(txn_id), edge)
                attr[side] = str(e[0]["to_id"]) if e else ""
            except Exception:
                if _strict():
                    raise
                attr[side] = ""
        return self._row_to_txn(attr)

    def card_history(self, card_id: str, as_of: datetime,
                     window_days: int | None = None, limit: int = 5000) -> list[TxnRow]:
        since = as_of - timedelta(days=window_days) if window_days else datetime(1970, 1, 1)
        res = self._run("card_window", {"card_id": card_id, "as_of": _fmt(as_of),
                                        "since": _fmt(since), "limit_n": limit})
        rows = self._first(res, "window", []) or []
        out: list[TxnRow] = []
        for r in rows:
            attr = dict(r.get("attributes", r))
            attr.setdefault("txn_id", r.get("v_id"))
            attr.setdefault("device_profile", attr.get("device_profile", ""))
            out.append(self._row_to_txn(attr))
        return out

    def card_baseline(self, card_id: str, as_of: datetime) -> dict[str, Any]:
        res = self._run("card_baseline", {"card_id": card_id, "cutoff": _fmt(as_of)})
        n = int(self._first(res, "n_txns", 0) or 0)
        if not n:
            return {"card_id": card_id, "n_txns": 0, "known": False}
        amounts = np.asarray(self._first(res, "amounts", []) or [], dtype=float)
        regions = self._first(res, "region_counts", {}) or {}
        home = max(regions, key=regions.get) if regions else ""
        return {
            "card_id": card_id, "known": True, "n_txns": n,
            "first_seen": str(self._first(res, "first_seen", "")),
            "last_seen": str(self._first(res, "last_seen", "")),
            "amt_mean": round(float(amounts.mean()), 2) if amounts.size else 0.0,
            "amt_median": round(float(np.median(amounts)), 2) if amounts.size else 0.0,
            "amt_std": round(float(amounts.std(ddof=0)), 2) if amounts.size else 0.0,
            "amt_p95": round(float(np.percentile(amounts, 95)), 2) if amounts.size else 0.0,
            "amt_max": round(float(self._first(res, "amt_max", 0.0) or 0.0), 2),
            "online_share": round(float(self._first(res, "n_online", 0) or 0) / n, 3),
            "home_region": home,
            "home_region_share": round(regions.get(home, 0) / n, 3) if home else 0.0,
            "n_regions": len(regions),
            "product_mix": self._first(res, "product_mix", {}) or {},
            "known_devices": sorted(self._first(res, "known_devices", []) or [])[:25],
            "n_devices": len(self._first(res, "known_devices", []) or []),
        }

    def customer_cards(self, customer_id: str, as_of: datetime) -> list[str]:
        self.call_count += 1
        try:
            edges = self.graph.getEdges("Customer", customer_id, "OWNS")
            return sorted(str(e["to_id"]) for e in edges)
        except Exception:
            if _strict():
                raise
            return []

    def episode_window(self, card_id: str, as_of: datetime,
                       window_hours: float = 72.0) -> dict[str, Any]:
        res = self._run("episode_window", {"card_id": card_id, "as_of": _fmt(as_of),
                                           "window_seconds": int(window_hours * 3600)})
        return {
            "card_id": card_id, "as_of": str(as_of),
            "baseline_cutoff": str(self._first(res, "baseline_cutoff", "")),
            "window_hours": window_hours,
            "window_txn_ids": sorted(self._first(res, "window_txn_ids", []) or []),
            "n_window": int(self._first(res, "n_window", 0) or 0),
            "window_value_usd": round(float(self._first(res, "window_value_usd", 0.0) or 0.0), 2),
            "n_baseline": int(self._first(res, "n_baseline", 0) or 0),
            "window_online": int(self._first(res, "window_online", 0) or 0),
            "window_in_person": int(self._first(res, "window_in_person", 0) or 0),
            "window_regions": sorted(self._first(res, "window_regions", []) or []),
            "window_devices": sorted(self._first(res, "window_devices", []) or []),
        }

    def velocity_burst(self, card_id: str, as_of: datetime,
                       window_hours: float = 48.0) -> dict[str, Any]:
        ep = self.episode_window(card_id, as_of, window_hours)
        base = self.card_baseline(card_id, as_of - timedelta(hours=window_hours))
        days = 1.0
        if base.get("first_seen"):
            days = max((as_of - _dt(base["first_seen"])).total_seconds() / 86400.0, 1.0)
        baseline_per_window = (base.get("n_txns", 0) / days) * (window_hours / 24.0)
        n = ep["n_window"]
        return {
            "card_id": card_id, "window_hours": window_hours, "n_txns": n,
            "value_usd": ep["window_value_usd"], "n_online": ep["window_online"],
            "baseline_txns_per_window": round(baseline_per_window, 2),
            "velocity_ratio": round(n / baseline_per_window, 2)
            if baseline_per_window > 0.2 else None,
            "txn_ids": ep["window_txn_ids"],
        }

    def card_testing_probe(self, card_id: str, as_of: datetime,
                           window_hours: float = 2.0,
                           small_amount: float = 5.0) -> dict[str, Any]:
        res = self._run("card_testing_probe", {"card_id": card_id, "as_of": _fmt(as_of),
                                               "small_amount": small_amount,
                                               "lookback_days": 7})
        rows = self._txn_rows(self._first(res, "small_authorisations", []) or [])
        rows += self._txn_rows(self._first(res, "larger_purchases", []) or [])
        return {"card_id": card_id,
                **detect_card_testing(rows, small_amount, window_hours)}

    def threshold_structuring_probe(self, card_id: str, as_of: datetime,
                                    window_minutes: float | None = None) -> dict[str, Any]:
        res = self._run("threshold_structuring_probe",
                        {"card_id": card_id, "as_of": _fmt(as_of), "lookback_days": 3})
        rows = self._txn_rows(self._first(res, "online_window", []) or [])
        return {"card_id": card_id, **detect_threshold_structuring(rows, window_minutes)}

    def peer_purchases(self, device_profile: str, card_id: str, amount: float,
                       as_of: datetime, window_days: int = 7) -> dict[str, Any]:
        if not device_profile:
            return {"peers": [], "n_peer_cards": 0}
        res = self._run("peer_purchases", {
            "device_profile": device_profile, "exclude_card": card_id, "amount": amount,
            "tolerance": max(2.0, 0.05 * abs(amount)), "since": _fmt(as_of - timedelta(days=window_days)),
            "as_of": _fmt(as_of)})
        rows = self._first(res, "peers", []) or []
        peers = []
        for r in rows:
            a = r.get("attributes", r)
            peers.append({"txn_id": str(a.get("txn_id") or r.get("v_id")),
                          "card_id": str(a.get("card_id", "")), "amount": float(a.get("amount", 0.0)),
                          "ts": str(a.get("ts", ""))[:19], "channel": str(a.get("channel", ""))})
        return {"peers": peers, "n_peer_cards": len({p["card_id"] for p in peers})}

    def device_fanout(self, device_profile: str, as_of: datetime,
                      window_days: int = 30) -> dict[str, Any]:
        if not device_profile:
            return {"device_profile": "", "n_cards": 0, "n_customers": 0, "card_ids": [],
                    "n_cards_new_in_window": 0, "n_cards_anon_proxy": 0,
                    "n_cards_marked_new": 0, "n_cards_all_time": 0,
                    "new_card_ids": [], "anon_proxy_card_ids": [], "proxy_values": []}
        res = self._run("device_fanout", {"device_profile": device_profile,
                                          "as_of": _fmt(as_of), "window_days": window_days})
        self.call_count += 1
        node = self.graph.getVerticesById("DeviceProfile", device_profile)
        all_time = int(self._first(res, "n_cards_all_time", 0) or 0)
        anon_all = int(self._first(res, "n_cards_anon_all_time", 0) or 0)
        return {
            "device_profile": device_profile, "window_days": window_days,
            "n_txns_window": int(self._first(res, "n_txns_window", 0) or 0),
            "n_cards": int(self._first(res, "n_cards", 0) or 0),
            "n_customers": int(self._first(res, "n_customers", 0) or 0),
            "card_ids": list(self._first(res, "card_ids", []) or []),
            "n_cards_new_in_window": int(self._first(res, "n_cards_new_in_window", 0) or 0),
            "new_card_ids": list(self._first(res, "new_card_ids", []) or []),
            "n_cards_anon_proxy": int(self._first(res, "n_cards_anon_proxy", 0) or 0),
            "anon_proxy_card_ids": list(self._first(res, "anon_proxy_card_ids", []) or []),
            "n_cards_marked_new": int(self._first(res, "n_cards_marked_new", 0) or 0),
            "n_cards_all_time": all_time,
            "n_cards_anon_all_time": anon_all,
            "anon_proxy_ratio": round(anon_all / all_time, 3) if all_time else 0.0,
            "proxy_values": list(self._first(res, "proxy_values", []) or []),
            "device_type": str(node[0]["attributes"].get("device_type", "")) if node else "",
        }

    def device_first_use(self, card_id: str, device_profile: str, as_of: datetime,
                         baseline_cutoff: datetime | None = None) -> dict[str, Any]:
        if not device_profile:
            return {"known_on_card": None, "first_seen_on_card": "", "n_prior_txns": 0,
                    "n_devices_on_card": 0}
        cutoff = baseline_cutoff or as_of
        # From the card's own history, not card_baseline's known_devices: that
        # list is trimmed for display, and a busy card has hundreds of profiles.
        history = self.card_history(card_id, as_of)
        prior = [t for t in history if t.ts <= cutoff and t.device_profile == device_profile]
        in_window = [t for t in history if t.ts > cutoff and t.device_profile == device_profile]
        n_devices = len({t.device_profile for t in history if t.ts <= cutoff and t.device_profile})
        return {"card_id": card_id, "device_profile": device_profile,
                "known_on_card": bool(prior), "n_prior_txns": len(prior),
                "first_seen_on_card": str(min(t.ts for t in prior)) if prior else "",
                "n_txns_in_window": len(in_window),
                "n_devices_on_card": n_devices,
                "baseline_cutoff": str(cutoff)}

    def region_profile(self, card_id: str, as_of: datetime, region: str,
                       baseline_cutoff: datetime | None = None) -> dict[str, Any]:
        cutoff = baseline_cutoff or as_of
        res = self._run("card_baseline", {"card_id": card_id, "cutoff": _fmt(cutoff)})
        counts = self._first(res, "region_counts", {}) or {}
        n = int(self._first(res, "n_txns", 0) or 0)
        home = max(counts, key=counts.get) if counts else ""
        return {"card_id": card_id, "region": region,
                "n_prior_in_region": int(counts.get(region, 0)),
                "region_share": round(counts.get(region, 0) / max(n, 1), 4),
                "home_region": home, "n_regions_seen": len(counts),
                "n_baseline_txns": n,
                "top_regions": dict(sorted(counts.items(), key=lambda kv: -kv[1])[:8]),
                "baseline_cutoff": str(cutoff)}

    def out_of_region_probe(self, card_id: str, as_of: datetime, region: str,
                            baseline_cutoff: datetime | None = None) -> dict[str, Any]:
        # Computed from the card's history with the local mirror's exact window
        # semantics; the out_of_region_probe query drifted from them at the
        # window boundaries and on transactions with no billing region.
        cutoff = baseline_cutoff or as_of
        full = self.card_history(card_id, as_of)
        if not full or not region:
            return {"matched": False}
        base = [x for x in full if x.ts <= cutoff]
        counts: dict[str, int] = {}
        for x in base:
            counts[x.region] = counts.get(x.region, 0) + 1
        # value_counts order: count descending, first appearance on ties
        home = max(counts, key=lambda r: counts[r]) if counts else ""
        prior = counts.get(region, 0)
        window = [x for x in full if x.ts > cutoff]
        in_region = [x for x in window if x.region == region]
        home_same = [x for x in window if x.region == home and x.region != region]
        span = 0.0
        if len(in_region) > 1:
            span = (max(x.ts for x in in_region) - min(x.ts for x in in_region)).total_seconds() / 86400.0
        return {"card_id": card_id, "region": region, "home_region": home,
                "matched": bool(prior == 0 and region != home and region != ""),
                "n_prior_in_region": prior, "n_in_region_window": len(in_region),
                "in_region_span_days": round(span, 2),
                "home_activity_continues": bool(home_same),
                "n_home_txns_window": len(home_same),
                "interleaved": bool(home_same and in_region),
                "card_present_share": round(sum(x.channel == "in_person" for x in in_region)
                                            / len(in_region), 3) if in_region else 0.0}

    def recurring_charge_probe(self, card_id: str, as_of: datetime, amount: float,
                               product_cd: str,
                               baseline_cutoff: datetime | None = None) -> dict[str, Any]:
        res = self._run("recurring_charge_probe",
                        {"card_id": card_id, "amount": amount, "product_cd": product_cd,
                         "baseline_cutoff": _fmt(baseline_cutoff or as_of)})
        rows = self._txn_rows(self._first(res, "matching_charges", []) or [])
        return {"card_id": card_id, "amount": amount, **recurrence_from_rows(rows)}

    def mixed_channel_probe(self, card_id: str, as_of: datetime,
                            window_hours: float = 48.0) -> dict[str, Any]:
        res = self._run("mixed_channel_probe",
                        {"card_id": card_id, "as_of": _fmt(as_of),
                         "window_seconds": int(window_hours * 3600)})
        n_on = int(self._first(res, "n_online", 0) or 0)
        n_ip = int(self._first(res, "n_in_person", 0) or 0)
        b_on = int(self._first(res, "baseline_online", 0) or 0)
        b_tot = int(self._first(res, "baseline_total", 0) or 0)
        base_share = (b_on / b_tot) if b_tot else 0.0
        win_share = (n_on / (n_on + n_ip)) if (n_on + n_ip) else 0.0
        return {"card_id": card_id, "window_hours": window_hours,
                "n_online": n_on, "n_in_person": n_ip,
                "mixed": bool(n_on and n_ip),
                "baseline_online_share": round(base_share, 3),
                "window_online_share": round(win_share, 3),
                "channel_shift": round(abs(win_share - base_share), 3),
                "new_device_profiles": [],
                "match_flag_mismatches": int(self._first(res, "match_flag_mismatches", 0) or 0),
                "matched": bool(n_on and n_ip and abs(win_share - base_share) > 0.25)}

    def email_mismatch_profile(self, txn_id: str) -> dict[str, Any]:
        t = self.get_transaction(txn_id)
        if t is None:
            return {}
        free = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
                "live.com", "icloud.com", "mail.com", "protonmail.com"}
        return {"txn_id": str(txn_id), "purchaser_domain": t.email_p,
                "recipient_domain": t.email_r,
                "mismatch": bool(t.email_p and t.email_r and t.email_p != t.email_r),
                "purchaser_is_free": t.email_p in free,
                "recipient_is_free": t.email_r in free}

    def shared_entity_ring(self, card_id: str, as_of: datetime,
                           window_days: int = 30) -> dict[str, Any]:
        """Policy R6, with the same hub test as the local mirror: the card's
        most-used device profiles in the window, fanned out, and only a profile
        reached anonymously by most of its cards counts as a ring."""
        window = self.card_history(card_id, as_of, window_days=window_days)
        counts: dict[str, int] = {}
        for t in window:
            if t.device_profile:
                counts[t.device_profile] = counts.get(t.device_profile, 0) + 1
        devices = sorted(counts, key=lambda d: (-counts[d], d))[:8]
        members: dict[str, set[str]] = {}
        anon_members: dict[str, set[str]] = {}
        fanouts: dict[str, dict[str, Any]] = {}
        for d in devices:
            fan = self.device_fanout(d, as_of, window_days)
            fanouts[d] = fan
            others = {c for c in fan["card_ids"] if c != card_id}
            if others:
                members[d] = others
            anon_others = {c for c in fan["anon_proxy_card_ids"] if c != card_id}
            if anon_others:
                anon_members[d] = anon_others

        def is_ring(d: str) -> bool:
            return (len(anon_members.get(d, ())) >= 2
                    and float(fanouts[d].get("anon_proxy_ratio", 0.0)) >= 0.5)

        ring_devices = [d for d in members if is_ring(d)]
        all_members = sorted({c for d in ring_devices for c in members[d]})
        regions: dict[str, int] = {}
        for t in window:
            if t.region:
                regions[t.region] = regions.get(t.region, 0) + 1
        hub = max(ring_devices, key=lambda d: len(members[d])) if ring_devices else ""
        return {"card_id": card_id, "window_days": window_days,
                "shared_devices": {d: sorted(members[d])[:40] for d in ring_devices},
                "connected_card_ids": all_members[:60],
                "ring_size": len(all_members) + 1, "hub_device": hub,
                "hub_fanout": fanouts.get(hub, {}),
                "anon_proxy_ring": bool(hub and len(anon_members.get(hub, ())) >= 2),
                "all_shared_device_cards": sorted({c for s in members.values() for c in s})[:60],
                "home_region": max(regions, key=regions.get) if regions else "",
                "community": self.card_community(card_id) if ring_devices else {}}

    def card_community(self, card_id: str) -> dict[str, Any]:
        """WCC component and PageRank position over the anonymous-proxy card
        projection (graph/algorithms/05_graph_algorithms.gsql). All-time
        structure: cited as context, never folded into the probability."""
        try:
            res = self._run("card_community", {"card_id": card_id})
        except Exception:
            if _strict():
                raise
            return {}
        row = res[0] if res else {}
        if not row or int(row.get("community_size", 0) or 0) <= 1:
            return {}
        return {"community_id": row.get("community_id"),
                "community_size": int(row.get("community_size", 0)),
                "rank_in_community": int(row.get("rank_in_community", 0)),
                "hub_rank": round(float(row.get("hub_rank", 0.0)), 4),
                "top_hub_cards": list(row.get("top_hub_cards", []) or [])[:3],
                "algorithms": "GDBMS_ALGO.community.wcc + GDBMS_ALGO.centrality.pagerank"}

    def fraud_proximity(self, entity_ids: Sequence[str], as_of: datetime,
                        max_hops: int = 2) -> dict[str, Any]:
        res = self._run("fraud_proximity", {"entity_ids": list(entity_ids),
                                            "as_of": _fmt(as_of), "max_hops": max_hops})
        return {"proximity_score": round(float(self._first(res, "proximity_score", 0.0) or 0.0), 4),
                "n_confirmed_fraud_cases": int(
                    self._first(res, "n_confirmed_fraud_cases", 0) or 0),
                "evidence_cases": sorted(self._first(res, "evidence_cases", []) or [], key=str)[:25],
                "max_hops": max_hops}

    def hybrid_case_recall(self, query_text: str, entity_ids: Sequence[str],
                           as_of: datetime, k: int = 5) -> list[RecalledCase]:
        vec = self._embedder_or_load().encode([query_text])[0].tolist()
        res = self._run("hybrid_case_recall",
                        {"query_vec": vec, "entity_ids": list(entity_ids),
                         "as_of": _fmt(as_of), "k": k})
        rows = self._first(res, "result", []) or []
        out: list[RecalledCase] = []
        for r in rows:
            a = r.get("attributes", r)
            out.append(RecalledCase(
                case_id=str(a.get("case_id") or r.get("v_id")),
                outcome=str(a.get("outcome", "")), pattern=str(a.get("pattern", "")),
                similarity=round(float(a.get("fused_score", 0.0)), 4),
                shared_entities=int(a.get("shared_entities", 0) or 0),
                fused_score=round(float(a.get("fused_score", 0.0)), 4),
                exposure_usd=float(a.get("exposure_usd", 0.0) or 0.0),
                opened_at=str(a.get("opened_at", "")),
                narrative=str(a.get("narrative", "")),
                shared_with=list(a.get("shared_with", []) or []),
            ))
        return out

    def behavioural_neighbours(self, txn_id: str, as_of: datetime,
                               k: int = 10) -> dict[str, Any]:
        res = self._run("behavioural_neighbours",
                        {"txn_id": str(txn_id), "as_of": _fmt(as_of), "k": k})
        n_f = int(self._first(res, "n_fraud", 0) or 0)
        n_c = int(self._first(res, "n_cleared", 0) or 0)
        rows = self._first(res, "scored", []) or []
        sims = [float(r.get("attributes", r).get("similarity", 0.0)) for r in rows]
        total = n_f + n_c
        if total == 0:
            return {"available": False}
        return {"available": True, "k": total, "n_fraud": n_f, "n_cleared": n_c,
                "fraud_share": round(n_f / total, 3),
                "mean_similarity": round(sum(sims) / len(sims), 4) if sims else 0.0,
                "neighbours": [
                    {"txn_id": str(r.get("v_id")),
                     "similarity": round(float(r.get("attributes", {}).get("similarity", 0.0)), 4),
                     "confirmed_fraud": True}
                    for r in rows[:5]]}

    def policy_retrieve(self, query_text: str, k: int = 5,
                        kinds: Iterable[str] | None = None) -> list[dict[str, Any]]:
        vec = self._embedder_or_load().encode([query_text])[0].tolist()
        res = self._run("policy_retrieve",
                        {"query_vec": vec, "k": k, "kinds": list(kinds or [])})
        rows = self._first(res, "result", []) or []
        return [dict(r.get("attributes", r)) for r in rows]

    # ----------------------------------------------------------- writes ----
    def write_case(self, case_doc: dict[str, Any]) -> str:
        """One installed query, one JSON document: the agent's only write.

        Same input dict as the local mirror, and called from the same code path
        that emits the JSON answer file, so the graph and the file cannot
        diverge. POSTed, because a case document is larger than a URL."""
        self.call_count += 1
        gid = case_doc.get("graph_case_id") or f"CASE-{case_doc['case_id']}"
        doc = case_write_doc(gid, case_doc)
        self.last_write = self.graph.runInstalledQuery(
            "case_write", {"graph_case_id": gid, "case_json": json.dumps(doc, default=str)},
            timeout=120_000, usePost=True)
        return gid

    # ------------------------------------------- final-round queries ----
    def ring_at_asof(self, card_id: str, as_of: datetime, lookback_days: int = 45,
                     max_cards: int = 60, rare_cards: int = 10) -> dict[str, Any]:
        res = self._run("ring_at_asof", {"card_id": card_id, "as_of": _fmt(as_of),
                                         "lookback_days": lookback_days,
                                         "rare_cards": rare_cards, "max_cards": max_cards})
        cards = sorted(set(self._first(res, "cards", []) or []) - {card_id})
        return {"seed": card_id, "cards": cards, "size": len(cards) + 1,
                "devices": sorted(self._first(res, "devices", []) or [])[:20],
                "as_of": str(as_of), "lookback_days": lookback_days,
                "algorithm": "seeded WCC on the as_of-sliced card-device projection "
                             "(GSQL ring_at_asof)"}

    def origin_counts(self, ring_cards: Sequence[str], since: datetime, until: datetime,
                      as_of: datetime) -> dict[str, Any]:
        res = self._run("origin_counts", {"ring_cards": list(ring_cards), "since": _fmt(since),
                                          "until": _fmt(until), "as_of": _fmt(as_of)})
        ring_by = self._first(res, "ring_by", {}) or {}
        pop_n = self._first(res, "pop_n", {}) or {}
        rows = []
        for key, cards in ring_by.items():
            t, e = key.split("\t", 1)
            if len(cards) >= 2:
                rows.append({"entity_type": t, "entity": e, "ring_cards": len(cards),
                             "ring_card_ids": sorted(cards), "pop_cards": int(pop_n.get(key, 0))})
        return {"entities": rows, "n_control": int(self._first(res, "n_control", 0) or 0),
                "n_ring": len(ring_cards)}

    def origin_touchers(self, entity_type: str, entity: str, since: datetime,
                        until: datetime, as_of: datetime) -> list[dict[str, Any]]:
        res = self._run("origin_touchers", {"entity_type": entity_type, "entity": entity,
                                            "since": _fmt(since), "until": _fmt(until),
                                            "as_of": _fmt(as_of)})
        last = self._first(res, "last_touch", {}) or {}
        n = self._first(res, "n_touches", {}) or {}
        owner = self._first(res, "owner", {}) or {}
        fraud = set(self._first(res, "fraud_cards", []) or [])
        return [{"card_id": c, "customer_id": owner.get(c, ""), "last_touch": str(last[c]),
                 "n_touches": int(n.get(c, 0)), "suspect": c in fraud} for c in last]

    def ring_exposure(self, ring_cards: Sequence[str], as_of: datetime,
                      lookback_days: int = 45, window_hours: float = 72.0) -> list[dict]:
        res = self._run("ring_exposure", {"ring_cards": list(ring_cards), "as_of": _fmt(as_of),
                                          "window_hours": int(window_hours)})
        txns = self._first(res, "txns", {}) or {}
        amt = self._first(res, "amount", {}) or {}
        owner = self._first(res, "owner", {}) or {}
        return [{"card_id": c, "customer_id": owner.get(c, ""),
                 "exposure_usd": round(float(amt.get(c, 0.0)), 2),
                 "txn_ids": sorted(map(str, t))} for c, t in txns.items()]

    def precedent_by_facts(self, fact_mask: int, as_of: datetime) -> dict[str, Any]:
        res = self._run("precedent_by_facts", {"fact_mask": int(fact_mask), "as_of": _fmt(as_of)})
        return {"n": int(self._first(res, "n", 0) or 0),
                "confirmed": int(self._first(res, "confirmed", 0) or 0),
                "cleared": int(self._first(res, "cleared", 0) or 0),
                "case_ids": sorted(self._first(res, "case_ids", []) or [])}

    def compromise_watch(self, entity_ids: Sequence[str], as_of: datetime) -> list[dict]:
        res = self._run("compromise_watch", {"entity_ids": [e for e in entity_ids if e],
                                             "as_of": _fmt(as_of)})
        out = []
        for h in self._first(res, "hits", []) or []:
            case, ent, lift, p = (str(h).split("\t") + ["", "", "", ""])[:4]
            out.append({"graph_case_id": case, "entity": ent, "lift": float(lift or 0),
                        "p_value": float(p or 1)})
        return out

    def behaviour_vector(self, txn_id: str) -> list[float] | None:
        """The flagged transaction's behaviour vector for the conformal support
        check. Vectors are computed locally (no egress) and loaded into the
        graph; the calibration-space lookup reads the same staged table."""
        self.call_count += 1
        from ..agent.final_round import _behaviour_table

        tbl = _behaviour_table()
        if tbl is None:
            return None
        i = tbl[0].get(str(txn_id))
        return None if i is None else [float(x) for x in tbl[1][i]]

    def data_gaps(self, txn_ids: Sequence[str]) -> dict[str, Any]:
        res = self._run("data_gaps", {"txn_ids": [str(t) for t in txn_ids]})
        return {"n": int(self._first(res, "n", 0) or 0),
                "no_identity": sorted(self._first(res, "no_identity", []) or []),
                "empty_region": sorted(self._first(res, "empty_region", []) or []),
                "placeholder_email": sorted(self._first(res, "placeholder_email", []) or [])}

    def case_chain(self, graph_case_id: str) -> dict[str, Any]:
        res = self._run("case_chain", {"graph_case_id": graph_case_id})
        return {k: v for block in res for k, v in block.items()}

    # ----------------------------------------------------------- health ----
    def health(self) -> dict[str, Any]:
        self.call_count += 1
        try:
            stats = self.conn.getVertexCount("*")
        except Exception as exc:                       # pragma: no cover
            return {"backend": "tigergraph", "ok": False, "error": str(exc)}
        mcp = self._mcp
        return {"backend": "tigergraph", "ok": True, "host": TG.host,
                "transport": self.graph.transport,
                "mcp_tools": len(mcp.tools) if mcp else 0,
                "mcp_calls": mcp.calls if mcp else 0,
                "mcp_fallbacks": self.graph.fallbacks,
                "graph": TG.graph, "vertex_counts": stats,
                "embedding_dim": EMBED.dim}

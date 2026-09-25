"""TigerGraph-backed store — the production path.

Every read here calls an installed GSQL query from `graph/queries/`; every
write goes through RESTPP upserts plus `case_write_links` to stitch the edges.
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
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

import numpy as np

from ..config import EMBED, PATHS, TG
from ..memory.embeddings import Embedder
from .base import GraphStore, RecalledCase, TxnRow
from .matchers import (detect_card_testing, detect_threshold_structuring,
                       recurrence_from_rows)

DT = "%Y-%m-%d %H:%M:%S"


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.strptime(str(value)[:19], DT)


def _fmt(value: datetime) -> str:
    return value.strftime(DT)


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
        self.call_count = 0
        self._embedder: Embedder | None = None

    # -------------------------------------------------------- internals ----
    def _run(self, name: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.call_count += 1
        return self.conn.runInstalledQuery(name, params or {}, timeout=60_000)

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
            proxy=str(attr.get("proxy", "")),
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
        rows = self.conn.getVerticesById("Transaction", str(txn_id))
        if not rows:
            return None
        attr = dict(rows[0].get("attributes", {}))
        attr["txn_id"] = str(txn_id)
        # the device profile lives on the edge target, not on Transaction
        try:
            self.call_count += 1
            devs = self.conn.getEdges("Transaction", str(txn_id), "FROM_DEVICE")
            if devs:
                attr["device_profile"] = str(devs[0]["to_id"])
        except Exception:
            attr.setdefault("device_profile", "")
        for side, edge in (("email_p", "PURCHASER_EMAIL"), ("email_r", "RECIPIENT_EMAIL")):
            try:
                self.call_count += 1
                e = self.conn.getEdges("Transaction", str(txn_id), edge)
                attr[side] = str(e[0]["to_id"]) if e else ""
            except Exception:
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
            "known_devices": list(self._first(res, "known_devices", []) or [])[:25],
            "n_devices": len(self._first(res, "known_devices", []) or []),
        }

    def customer_cards(self, customer_id: str, as_of: datetime) -> list[str]:
        self.call_count += 1
        try:
            edges = self.conn.getEdges("Customer", customer_id, "OWNS")
            return sorted(str(e["to_id"]) for e in edges)
        except Exception:
            return []

    def episode_window(self, card_id: str, as_of: datetime,
                       window_hours: float = 72.0) -> dict[str, Any]:
        res = self._run("episode_window", {"card_id": card_id, "as_of": _fmt(as_of),
                                           "window_seconds": int(window_hours * 3600)})
        return {
            "card_id": card_id, "as_of": str(as_of),
            "baseline_cutoff": str(self._first(res, "baseline_cutoff", "")),
            "window_hours": window_hours,
            "window_txn_ids": list(self._first(res, "window_txn_ids", []) or []),
            "n_window": int(self._first(res, "n_window", 0) or 0),
            "window_value_usd": round(float(self._first(res, "window_value_usd", 0.0) or 0.0), 2),
            "n_baseline": int(self._first(res, "n_baseline", 0) or 0),
            "window_online": int(self._first(res, "window_online", 0) or 0),
            "window_in_person": int(self._first(res, "window_in_person", 0) or 0),
            "window_regions": list(self._first(res, "window_regions", []) or []),
            "window_devices": list(self._first(res, "window_devices", []) or []),
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
                                    window_minutes: float = 60.0) -> dict[str, Any]:
        res = self._run("threshold_structuring_probe",
                        {"card_id": card_id, "as_of": _fmt(as_of), "lookback_days": 3})
        rows = self._txn_rows(self._first(res, "online_window", []) or [])
        return {"card_id": card_id, **detect_threshold_structuring(rows, window_minutes)}

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
        node = self.conn.getVerticesById("DeviceProfile", device_profile)
        all_time = int(node[0]["attributes"].get("n_cards", 0)) if node else 0
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
            "proxy_values": list(self._first(res, "proxy_values", []) or []),
            "device_type": str(node[0]["attributes"].get("device_type", "")) if node else "",
        }

    def device_first_use(self, card_id: str, device_profile: str, as_of: datetime,
                         baseline_cutoff: datetime | None = None) -> dict[str, Any]:
        if not device_profile:
            return {"known_on_card": None, "first_seen_on_card": "", "n_prior_txns": 0,
                    "n_devices_on_card": 0}
        cutoff = baseline_cutoff or as_of
        base = self.card_baseline(card_id, cutoff)
        known = device_profile in set(base.get("known_devices", []))
        return {"card_id": card_id, "device_profile": device_profile,
                "known_on_card": known, "n_prior_txns": 1 if known else 0,
                "n_devices_on_card": int(base.get("n_devices", 0)),
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
        cutoff = baseline_cutoff or as_of
        res = self._run("out_of_region_probe",
                        {"card_id": card_id, "as_of": _fmt(as_of), "region": region,
                         "baseline_cutoff": _fmt(cutoff)})
        counts = self._first(res, "baseline_region_counts", {}) or {}
        home = max(counts, key=counts.get) if counts else ""
        prior = int(counts.get(region, 0))
        first = self._first(res, "region_first_ts", "")
        last = self._first(res, "region_last_ts", "")
        span = 0.0
        if first and last:
            span = (_dt(last) - _dt(first)).total_seconds() / 86400.0
        n_home = int(self._first(res, "n_home_txns_window", 0) or 0)
        n_in = int(self._first(res, "n_in_region_window", 0) or 0)
        n_cp = int(self._first(res, "n_card_present_in_region", 0) or 0)
        return {"card_id": card_id, "region": region, "home_region": home,
                "matched": bool(prior == 0 and region and region != home),
                "n_prior_in_region": prior, "n_in_region_window": n_in,
                "in_region_span_days": round(span, 2),
                "home_activity_continues": bool(n_home > 0),
                "n_home_txns_window": n_home,
                "interleaved": bool(n_home > 0 and n_in > 0),
                "card_present_share": round(n_cp / n_in, 3) if n_in else 0.0}

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
        res = self._run("shared_entity_ring", {"card_id": card_id, "as_of": _fmt(as_of),
                                               "window_days": window_days, "min_weight": 1})
        by_device = self._first(res, "shared_devices", {}) or {}
        members = sorted({c for v in by_device.values() for c in v})
        hub = max(by_device, key=lambda d: len(by_device[d])) if by_device else ""
        return {"card_id": card_id, "window_days": window_days,
                "shared_devices": by_device, "connected_card_ids": members,
                "ring_size": len(members) + 1, "hub_device": hub,
                "hub_fanout": self.device_fanout(hub, as_of, window_days) if hub else {},
                "anon_proxy_ring": bool(self._first(res, "anon_proxy_ring", False)),
                "all_shared_device_cards": members,
                "home_region": ""}

    def fraud_proximity(self, entity_ids: Sequence[str], as_of: datetime,
                        max_hops: int = 2) -> dict[str, Any]:
        res = self._run("fraud_proximity", {"entity_ids": list(entity_ids),
                                            "as_of": _fmt(as_of), "max_hops": max_hops})
        return {"proximity_score": round(float(self._first(res, "proximity_score", 0.0) or 0.0), 4),
                "n_confirmed_fraud_cases": int(
                    self._first(res, "n_confirmed_fraud_cases", 0) or 0),
                "evidence_cases": list(self._first(res, "evidence_cases", []) or [])[:25],
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
        """Upsert the whole case subgraph, then stitch the edges.

        Same input dict as the local mirror, and called from the same code path
        that emits the JSON answer file, so the graph and the file cannot
        diverge.
        """
        self.call_count += 1
        gid = case_doc.get("graph_case_id") or f"CASE-{case_doc['case_id']}"
        c = case_doc
        self.conn.upsertVertex("Case", gid, {
            "source_case_id": c.get("case_id", ""), "status": c.get("status", ""),
            "verdict": c.get("verdict", ""), "trigger_type": c.get("trigger_type", ""),
            "opened_at": c.get("opened_at", ""), "as_of": c.get("as_of", ""),
            "fraud_probability": float(c.get("fraud_probability", 0.0)),
            "confidence": float(c.get("confidence", 0.0)),
            "pattern": c.get("pattern", ""),
            "pattern_description": c.get("pattern_description", ""),
            "exposure_usd": float(c.get("exposure_usd", 0.0)),
            "summary": c.get("summary", ""), "narrative": c.get("narrative", ""),
            "stop_reason": c.get("stop_reason", ""),
            "ledger_head": c.get("ledger_head", ""),
            "tool_calls": int(c.get("tool_calls", 0)),
            "latency_s": float(c.get("latency_s", 0.0)),
        })
        if c.get("narrative_emb"):
            self.conn.upsertVertex("Case", gid, {"narrative_emb": c["narrative_emb"]})

        for i, ev in enumerate(c.get("evidence", []), 1):
            eid = f"{gid}-E{i:02d}"
            self.conn.upsertVertex("Evidence", eid, {
                "kind": ev.get("source", "graph"), "claim": ev.get("claim", ""),
                "source_tool": ev.get("ref", ""), "collected_at": c.get("as_of", ""),
                "reliability": float(ev.get("reliability", 1.0)),
                "delta_fraud_probability": float(ev.get("delta_fraud_probability", 0.0)),
            })
            self.conn.upsertEdge("Case", gid, "HAS_EVIDENCE", "Evidence", eid)
            for tid in ev.get("entity_ids", []):
                if str(tid).isdigit():
                    self.conn.upsertEdge("Evidence", eid, "EVIDENCE_ON", "Transaction", str(tid))

        for d in c.get("decisions", []):
            self.conn.upsertVertex("Decision", d["decision_id"], {
                "step": int(d.get("step", 0)), "node": d.get("node", ""),
                "posterior_before": float(d.get("p_fraud_before", 0.0)),
                "posterior_after": float(d.get("p_fraud_after", 0.0)),
                "rationale": d.get("rationale", ""),
                "prev_hash": d.get("prev_hash", ""), "hash": d.get("hash", ""),
            })
            self.conn.upsertEdge("Case", gid, "DECIDED", "Decision", d["decision_id"])

        for phase in ("initial", "final"):
            for i, a in enumerate(c.get("actions", {}).get(phase, []), 1):
                aid = f"{gid}-{phase[:3].upper()}-{i:02d}"
                self.conn.upsertVertex("RecommendedAction", aid, {
                    "action_type": a["action"], "phase": phase, "approval_route": a["route"],
                    "reason": a.get("reason", ""),
                    "policy_rule": a.get("reason", "").split(":", 1)[0],
                    "executed": bool(a.get("executed", False)),
                })
                self.conn.upsertEdge("Case", gid, "RECOMMENDS", "RecommendedAction", aid)

        for i, r in enumerate(c.get("evidence_requests", []), 1):
            rid = f"{gid}-R{i:02d}"
            self.conn.upsertVertex("EvidenceRequest", rid, {
                "request_type": r.get("type", ""), "channel": r.get("channel", ""),
                "question": r.get("question", ""),
                "expected_info_gain": float(r.get("expected_info_gain", 0.0)),
                "cost": float(r.get("cost", 0.0)),
                "asked_after_step": int(r.get("asked_after_step", 0)),
                "simulated": True, "simulation_seed": int(r.get("simulation_seed", 0)),
                "response": r.get("assumed_response", ""),
            })
            self.conn.upsertEdge("Case", gid, "REQUESTED", "EvidenceRequest", rid)

        sar = c.get("sar") or {}
        if sar.get("file"):
            sid = f"{gid}-SAR"
            self.conn.upsertVertex("SAR", sid, {
                "filed": True, "reason": sar.get("reason", ""),
                "narrative": sar.get("narrative", ""),
                "total_amount_usd": float(sar.get("total_amount_usd", 0.0)),
                "activity_start": (sar.get("activity_dates") or ["", ""])[0],
                "activity_end": (sar.get("activity_dates") or ["", ""])[-1],
            })
            self.conn.upsertEdge("Case", gid, "FILED", "SAR", sid)

        self._run("case_write_links", {
            "graph_case_id": gid, "card_id": c.get("card_id", ""),
            "customer_id": c.get("customer_id", ""),
            "txn_ids": list(c.get("affected_txn_ids", [])),
            "connected_card_ids": list(c.get("connected_card_ids", [])),
            "device_profiles": list(c.get("connected_device_profiles", [])),
            "prior_case_ids": list(c.get("similar_prior_cases", [])),
            "policy_doc_ids": [f"POLICY-{r}" for r in c.get("cited_rules", [])],
        })
        return gid

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
        return {"backend": "tigergraph", "ok": True, "host": TG.host,
                "graph": TG.graph, "vertex_counts": stats,
                "embedding_dim": EMBED.dim}

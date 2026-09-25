"""Local mirror of the GSQL investigation toolkit.

Every method computes the same answer as its `graph/queries/*.gsql` counterpart,
over the staged parquet instead of over TigerGraph. It exists for three
reasons: the benchmark stays reproducible without a live instance, the GSQL can
be differentially tested against it, and a judge can clone and run.

`TigerGraphStore` is the production path; this is the reference implementation.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from ..config import PATHS
from ..memory.embeddings import Embedder, cosine_top_k
from .matchers import recurrence_from_rows
from .base import GraphStore, RecalledCase, TxnRow

ROUND_THRESHOLDS = (100.0, 200.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0)


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


class _Dataset:
    """Loaded once per process; every store instance shares it."""

    _instance: "_Dataset | None" = None

    def __init__(self) -> None:
        if not PATHS.tx_parquet.exists():
            raise FileNotFoundError(
                f"{PATHS.tx_parquet} missing — run `python ingest/01_normalise.py` first")
        self.tx: pd.DataFrame = pd.read_parquet(PATHS.tx_parquet)
        # pandas 3 stores strings in Arrow by default; positional `take` on an
        # Arrow-backed column costs ~5ms per slice, which is 70 minutes across a
        # full calibration replay. NumPy-backed object columns make it ~0.1ms.
        for col, dtype in self.tx.dtypes.items():
            if dtype == "object" or str(dtype).startswith(("string", "large_string")):
                self.tx[col] = self.tx[col].astype(object).fillna("").to_numpy(dtype=object)
        self.tx["txn_id"] = self.tx["txn_id"].astype(str)
        self.tx = self.tx.sort_values(["card_id", "ts"]).reset_index(drop=True)

        self.by_txn: dict[str, int] = {t: i for i, t in enumerate(self.tx["txn_id"])}
        self.card_rows: dict[str, np.ndarray] = {
            c: g.to_numpy() for c, g in self.tx.groupby("card_id", sort=False).groups.items()
        }
        self.customer_cards_map: dict[str, list[str]] = (
            self.tx.groupby("customer_id")["card_id"].unique().apply(sorted).to_dict()
        )
        dev = self.tx[self.tx["device_profile"] != ""]
        self.device_rows: dict[str, np.ndarray] = {
            d: g.to_numpy() for d, g in dev.groupby("device_profile", sort=False).groups.items()
        }
        self.ts_values: np.ndarray = self.tx["ts"].to_numpy()

        # closed-case memory
        self.closed: pd.DataFrame = pd.read_parquet(PATHS.closed_cases_parquet)
        self.closed["case_id"] = self.closed["case_id"].astype(str)
        self.case_entities: dict[str, set[str]] = {}
        self.entity_cases: dict[str, list[str]] = defaultdict(list)
        for row in self.closed.itertuples():
            ents: set[str] = {row.customer_id, row.card_id}
            ents.update(str(t) for t in row.txn_id_list)
            ents.update(row.connected_card_list)
            self.case_entities[row.case_id] = ents
            for e in ents:
                self.entity_cases[e].append(row.case_id)
        # device profiles touched by each closed case (computed from its txns)
        self.case_devices: dict[str, set[str]] = {}
        for row in self.closed.itertuples():
            devs = set()
            for t in row.txn_id_list:
                i = self.by_txn.get(str(t))
                if i is not None:
                    d = self.tx.at[i, "device_profile"]
                    if d:
                        devs.add(d)
            self.case_devices[row.case_id] = devs
            for d in devs:
                self.entity_cases[d].append(row.case_id)

        # vector indexes (built by ingest/05_build_memory.py)
        self.case_vectors: np.ndarray | None = None
        self.case_vector_ids: list[str] = []
        self.doc_vectors: np.ndarray | None = None
        self.doc_meta: list[dict[str, Any]] = []
        self.embedder: Embedder | None = None
        self._load_vectors()

        # behaviour vectors
        self.behaviour: np.ndarray | None = None
        self.behaviour_index: dict[str, int] = {}
        if PATHS.behaviour_parquet.exists():
            b = pd.read_parquet(PATHS.behaviour_parquet)
            self.behaviour = np.vstack(b["behaviour_emb"].to_numpy()).astype(np.float32)
            self.behaviour_index = {t: i for i, t in enumerate(b["txn_id"].astype(str))}
            self.fraud_txn_ids = {
                str(t) for row in self.closed.itertuples() if row.is_fraud
                for t in row.txn_id_list
            }
        else:
            self.fraud_txn_ids = set()

        # Flattened closed-case transaction table, so `behavioural_neighbours`
        # is a masked matrix product instead of a 5,565-iteration Python loop.
        rows_, labels_, opened_, ids_ = [], [], [], []
        for row in self.closed.itertuples():
            for t in row.txn_id_list:
                t = str(t)
                j = self.behaviour_index.get(t)
                if j is not None:
                    rows_.append(j)
                    labels_.append(1 if row.is_fraud else 0)
                    opened_.append(row.opened_at.to_datetime64())
                    ids_.append(t)
        self.cc_rows = np.asarray(rows_, dtype=np.int64)
        self.cc_labels = np.asarray(labels_, dtype=np.int8)
        self.cc_opened = np.asarray(opened_, dtype="datetime64[ns]")
        self.cc_txn_ids = np.asarray(ids_, dtype=object)

        # dict lookups beat pandas indexing inside the proximity walk
        self.case_opened: dict[str, Any] = dict(
            zip(self.closed["case_id"], self.closed["opened_at"]))
        self.case_outcome: dict[str, str] = dict(
            zip(self.closed["case_id"], self.closed["outcome"]))

        # Indexes the recall path would otherwise rebuild on every call: a
        # 5,565-row reindex and a dict comprehension per investigation is pure
        # waste once, and 16,000 times across a backtest it is minutes.
        self.closed_by_id = self.closed.set_index("case_id")
        self.case_vector_pos: dict[str, int] = {
            c: i for i, c in enumerate(self.case_vector_ids)}

        # cases written by the agent during this run (append-only memory)
        self.agent_cases: list[dict[str, Any]] = []
        self.agent_case_vectors: list[np.ndarray] = []

    def _load_vectors(self) -> None:
        emb_path = PATHS.staged / "embedder.pkl"
        if emb_path.exists():
            self.embedder = Embedder.load(emb_path)
        if PATHS.memory_index_npz.exists():
            blob = np.load(PATHS.memory_index_npz, allow_pickle=False)
            self.case_vectors = blob["vectors"].astype(np.float32)
            meta = pd.read_parquet(PATHS.memory_meta_parquet)
            self.case_vector_ids = meta["case_id"].astype(str).tolist()
        if PATHS.doc_index_npz.exists():
            blob = np.load(PATHS.doc_index_npz, allow_pickle=False)
            self.doc_vectors = blob["vectors"].astype(np.float32)
            dm = pd.read_parquet(PATHS.doc_meta_parquet)
            self.doc_meta = dm.to_dict("records")

    @classmethod
    def get(cls) -> "_Dataset":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


class LocalGraphStore(GraphStore):
    backend = "local"

    def __init__(self) -> None:
        self.ds = _Dataset.get()
        self.call_count = 0
        self._slice_cache: dict[tuple, pd.DataFrame] = {}
        self._fanout_cache: dict[tuple, dict[str, Any]] = {}

    # -------------------------------------------------------- internals ----
    def _rows(self, idx: Iterable[int]) -> pd.DataFrame:
        return self.ds.tx.iloc[list(idx)]

    def _card_slice(self, card_id: str, as_of: datetime | None,
                    since: datetime | None = None) -> pd.DataFrame:
        # One investigation asks the same card for the same window a dozen times
        # over. Materialising the slice once per (card, as_of) is worth ~3x on a
        # full calibration replay.
        key = (card_id, as_of, since)
        hit = self._slice_cache.get(key)
        if hit is not None:
            return hit
        idx = self.ds.card_rows.get(card_id)
        if idx is None:
            out = self.ds.tx.iloc[0:0]
        else:
            base_key = (card_id, as_of, None)
            df = self._slice_cache.get(base_key)
            if df is None:
                df = self.ds.tx.iloc[idx]
                if as_of is not None:
                    df = df[df["ts"] <= as_of]
                if len(self._slice_cache) < 1024:
                    self._slice_cache[base_key] = df
            out = df[df["ts"] >= since] if since is not None else df
        if len(self._slice_cache) < 1024:
            self._slice_cache[key] = out
        return out

    @staticmethod
    def _to_txn(row: pd.Series) -> TxnRow:
        return TxnRow(
            txn_id=str(row["txn_id"]),
            ts=row["ts"].to_pydatetime() if hasattr(row["ts"], "to_pydatetime") else row["ts"],
            amount=float(row["amount"]),
            product_cd=str(row["product_cd"]),
            channel=str(row["channel"]),
            risk_score=float(row["risk_score"]),
            customer_id=str(row["customer_id"]),
            card_id=str(row["card_id"]),
            region=str(row["region"]),
            country=str(row["country"]),
            device_profile=str(row["device_profile"]),
            device_status=str(row["device_status"]),
            proxy=str(row["proxy"]),
            email_p=str(row["email_p"]),
            email_r=str(row["email_r"]),
            dist1=_f(row.get("dist1")),
            dist2=_f(row.get("dist2")),
            amt_zscore_card=float(row.get("amt_zscore_card") or 0.0),
            gap_hours=_f(row.get("gap_hours")),
            m_mismatch_count=int(row.get("m_mismatch_count") or 0),
            has_identity=bool(row.get("has_identity")),
        )

    def _count(self) -> None:
        self.call_count += 1

    # ------------------------------------------------------------ reads ----
    def get_transaction(self, txn_id: str) -> TxnRow | None:
        self._count()
        i = self.ds.by_txn.get(str(txn_id))
        return None if i is None else self._to_txn(self.ds.tx.iloc[i])

    def card_history(self, card_id: str, as_of: datetime,
                     window_days: int | None = None, limit: int = 5000) -> list[TxnRow]:
        self._count()
        since = as_of - timedelta(days=window_days) if window_days else None
        df = self._card_slice(card_id, as_of, since).tail(limit)
        return [self._to_txn(r) for _, r in df.iterrows()]

    def card_baseline(self, card_id: str, as_of: datetime) -> dict[str, Any]:
        self._count()
        df = self._card_slice(card_id, as_of)
        if df.empty:
            return {"card_id": card_id, "n_txns": 0, "known": False}
        amt = df["amount"].to_numpy(dtype=float)
        regions = df["region"].value_counts()
        products = df["product_cd"].value_counts()
        devices = [d for d in df["device_profile"].unique() if d]
        return {
            "card_id": card_id,
            "customer_id": str(df["customer_id"].iloc[0]),
            "known": True,
            "n_txns": int(len(df)),
            "first_seen": str(df["ts"].min()),
            "last_seen": str(df["ts"].max()),
            "amt_mean": round(float(amt.mean()), 2),
            "amt_median": round(float(np.median(amt)), 2),
            "amt_std": round(float(amt.std(ddof=0)), 2),
            "amt_p95": round(float(np.percentile(amt, 95)), 2),
            "amt_max": round(float(amt.max()), 2),
            "online_share": round(float(df["channel"].eq("online").mean()), 3),
            "home_region": str(regions.index[0]) if len(regions) else "",
            "home_region_share": round(float(regions.iloc[0] / len(df)), 3) if len(regions) else 0.0,
            "n_regions": int(df["region"].nunique()),
            "product_mix": {str(k): int(v) for k, v in products.head(6).items()},
            "known_devices": devices[:25],
            "n_devices": len(devices),
            "median_gap_hours": round(float(df["gap_hours"].median(skipna=True) or 0.0), 2),
        }

    def customer_cards(self, customer_id: str, as_of: datetime) -> list[str]:
        self._count()
        cards = self.ds.customer_cards_map.get(customer_id, [])
        return [c for c in cards if not self._card_slice(c, as_of).empty]

    def velocity_burst(self, card_id: str, as_of: datetime,
                       window_hours: float = 48.0) -> dict[str, Any]:
        self._count()
        since = as_of - timedelta(hours=window_hours)
        win = self._card_slice(card_id, as_of, since)
        base = self._card_slice(card_id, since)
        days = max((since - base["ts"].min()).total_seconds() / 86400.0, 1.0) if not base.empty else 1.0
        baseline_per_window = (len(base) / days) * (window_hours / 24.0) if len(base) else 0.0
        return {
            "card_id": card_id,
            "window_hours": window_hours,
            "n_txns": int(len(win)),
            "value_usd": round(float(win["amount"].sum()), 2),
            "n_online": int(win["channel"].eq("online").sum()),
            "baseline_txns_per_window": round(float(baseline_per_window), 2),
            "velocity_ratio": round(float(len(win) / baseline_per_window), 2)
            if baseline_per_window > 0.2 else None,
            "txn_ids": win["txn_id"].tolist(),
        }

    def card_testing_probe(self, card_id: str, as_of: datetime,
                           window_hours: float = 2.0,
                           small_amount: float = 5.0) -> dict[str, Any]:
        """Policy R5: >=3 small online authorisations inside one hour, then a
        larger purchase. We scan every window ending at or before `as_of`."""
        self._count()
        df = self._card_slice(card_id, as_of, as_of - timedelta(days=7))
        online = df[df["channel"].eq("online")].sort_values("ts")
        best: dict[str, Any] = {"matched": False, "n_small": 0, "small_txn_ids": [],
                                "follow_txn_id": "", "follow_amount": 0.0,
                                "window_minutes": 0.0}
        if online.empty:
            return {"card_id": card_id, **best}
        small = online[online["amount"] < small_amount]
        arr = small.sort_values("ts")
        for i in range(len(arr)):
            start = arr["ts"].iloc[i]
            grp = arr[(arr["ts"] >= start) & (arr["ts"] <= start + timedelta(hours=1))]
            if len(grp) < 3:
                continue
            last_ts = grp["ts"].max()
            follow = online[(online["ts"] > last_ts)
                            & (online["ts"] <= last_ts + timedelta(hours=window_hours))
                            & (online["amount"] >= 20.0)]
            cand = {
                "matched": True,
                "n_small": int(len(grp)),
                "small_txn_ids": grp["txn_id"].tolist(),
                "follow_txn_id": str(follow["txn_id"].iloc[0]) if len(follow) else "",
                "follow_amount": round(float(follow["amount"].iloc[0]), 2) if len(follow) else 0.0,
                "window_minutes": round(
                    float((last_ts - start).total_seconds() / 60.0), 1),
                "small_amounts": [round(float(a), 2) for a in grp["amount"]],
            }
            if not best["matched"] or cand["n_small"] > best["n_small"] or (
                    cand["follow_txn_id"] and not best["follow_txn_id"]):
                best = cand
        return {"card_id": card_id, **best}

    def threshold_structuring_probe(self, card_id: str, as_of: datetime,
                                    window_minutes: float = 60.0) -> dict[str, Any]:
        """Undocumented typology U1, mined from closed cases CC-3748/3841/3907/
        4086/4124: a burst of online purchases each parked just below a round
        authorisation ceiling."""
        self._count()
        df = self._card_slice(card_id, as_of, as_of - timedelta(days=3))
        online = df[df["channel"].eq("online")].sort_values("ts")
        best: dict[str, Any] = {"matched": False}
        for i in range(len(online)):
            start = online["ts"].iloc[i]
            grp = online[(online["ts"] >= start)
                         & (online["ts"] <= start + timedelta(minutes=window_minutes))]
            if len(grp) < 3:
                continue
            amounts = grp["amount"].to_numpy(dtype=float)
            for thr in ROUND_THRESHOLDS:
                lo = thr * 0.90
                under = (amounts >= lo) & (amounts < thr)
                if under.sum() >= 3 and under.mean() >= 0.75:
                    cand = {
                        "matched": True,
                        "threshold_usd": thr,
                        "n_txns": int(under.sum()),
                        "txn_ids": grp["txn_id"].to_numpy()[under].tolist(),
                        "amounts": [round(float(a), 2) for a in amounts[under]],
                        "total_usd": round(float(amounts[under].sum()), 2),
                        "window_minutes": round(float(
                            (grp["ts"].max() - grp["ts"].min()).total_seconds() / 60.0), 1),
                        "headroom_pct": round(float(
                            100.0 * (thr - amounts[under].mean()) / thr), 2),
                    }
                    if not best["matched"] or cand["total_usd"] > best.get("total_usd", 0):
                        best = cand
        return {"card_id": card_id, **best}

    def peer_purchases(self, device_profile: str, card_id: str, amount: float,
                       as_of: datetime, window_days: int = 7) -> dict[str, Any]:
        """Mirror of graph/queries/peer_purchases.gsql."""
        self._count()
        idx = self.ds.device_rows.get(device_profile) if device_profile else None
        if idx is None or not len(idx):
            return {"peers": [], "n_peer_cards": 0}
        df = self.ds.tx.iloc[idx]
        tol = max(2.0, 0.05 * abs(amount))
        hit = df[(df["ts"] >= as_of - timedelta(days=window_days)) & (df["ts"] <= as_of)
                 & (df["card_id"] != card_id) & ((df["amount"] - amount).abs() <= tol)]
        hit = hit.sort_values("ts").head(50)
        peers = [{"txn_id": str(r.txn_id), "card_id": str(r.card_id), "amount": float(r.amount),
                  "ts": str(r.ts)[:19], "channel": str(r.channel)} for r in hit.itertuples()]
        return {"peers": peers, "n_peer_cards": len({p["card_id"] for p in peers})}

    def device_fanout(self, device_profile: str, as_of: datetime,
                      window_days: int = 30) -> dict[str, Any]:
        self._count()
        if not device_profile:
            return {"device_profile": "", "n_cards": 0, "n_customers": 0, "card_ids": [],
                    "n_cards_new_in_window": 0, "n_cards_anon_proxy": 0,
                    "n_cards_marked_new": 0, "n_cards_all_time": 0,
                    "new_card_ids": [], "anon_proxy_card_ids": [], "proxy_values": []}
        ckey = (device_profile, as_of, window_days)
        hit = self._fanout_cache.get(ckey)
        if hit is not None:
            return hit
        idx = self.ds.device_rows.get(device_profile)
        if idx is None:
            return {"device_profile": device_profile, "n_cards": 0, "n_customers": 0,
                    "card_ids": [], "n_cards_new_in_window": 0, "n_cards_anon_proxy": 0,
                    "n_cards_marked_new": 0, "n_cards_all_time": 0,
                    "new_card_ids": [], "anon_proxy_card_ids": [], "proxy_values": []}
        df = self.ds.tx.iloc[idx]
        df = df[df["ts"] <= as_of]
        win = df[df["ts"] >= as_of - timedelta(days=window_days)]
        cards = sorted(win["card_id"].unique().tolist())

        # Raw fan-out is nearly meaningless here: 92% of online transactions sit
        # on a browser fingerprint shared by three or more cards, because a
        # device profile is a model/OS/browser/screen string, not a serial
        # number. Three sharper counts carry the actual signal.
        before = df[df["ts"] < as_of - timedelta(days=window_days)]
        established = set(before["card_id"].unique())
        new_cards = [c for c in cards if c not in established]
        anon = win[win["proxy"].str.contains("ANONYM|HIDDEN", case=False, na=False, regex=True)]
        anon_cards = sorted(anon["card_id"].unique().tolist())
        new_status = win[win["device_status"].eq("New")]
        # The decisive statistic is not how many cards reach the profile through
        # an anonymising proxy but what *share* of them do. The confirmed ring in
        # this dataset sits at 1.00 — every leg, every card, anonymous — while an
        # ordinary browser fingerprint that happens to collect a few proxied
        # sessions sits at 0.03-0.06. A raw count cannot tell those apart; a
        # ratio separates them completely.
        all_anon = df[df["proxy"].str.contains("ANONYM|HIDDEN", case=False, na=False,
                                               regex=True)]
        n_cards_all = int(df["card_id"].nunique())
        n_anon_all = int(all_anon["card_id"].nunique())
        out = {
            "device_profile": device_profile,
            "window_days": window_days,
            "n_txns_window": int(len(win)),
            "n_cards": len(cards),
            "n_customers": int(win["customer_id"].nunique()),
            "card_ids": cards[:80],
            "n_cards_new_in_window": len(new_cards),
            "new_card_ids": new_cards[:80],
            "n_cards_anon_proxy": len(anon_cards),
            "anon_proxy_card_ids": anon_cards[:80],
            "n_cards_marked_new": int(new_status["card_id"].nunique()),
            "n_cards_all_time": n_cards_all,
            "n_cards_anon_all_time": n_anon_all,
            "anon_proxy_ratio": round(n_anon_all / n_cards_all, 3) if n_cards_all else 0.0,
            "first_seen": str(df["ts"].min()) if len(df) else "",
            "proxy_values": sorted({p for p in win["proxy"].unique() if p}),
            "device_type": str(win["device_type"].iloc[0]) if len(win) else "",
        }
        if len(self._fanout_cache) < 1024:
            self._fanout_cache[ckey] = out
        return out

    def device_first_use(self, card_id: str, device_profile: str,
                         as_of: datetime,
                         baseline_cutoff: datetime | None = None) -> dict[str, Any]:
        """Was this device established on the card *before the suspect window*?

        Measuring against `as_of` instead would let the first leg of a fraud
        episode make the later legs look familiar.
        """
        self._count()
        if not device_profile:
            return {"known_on_card": None, "first_seen_on_card": "", "n_prior_txns": 0,
                    "n_devices_on_card": 0}
        cutoff = baseline_cutoff or as_of
        base = self._card_slice(card_id, cutoff)
        prior = base[base["device_profile"] == device_profile]
        full = self._card_slice(card_id, as_of)
        in_window = full[(full["ts"] > cutoff) & (full["device_profile"] == device_profile)]
        return {
            "card_id": card_id,
            "device_profile": device_profile,
            "known_on_card": bool(len(prior) > 0),
            "n_prior_txns": int(len(prior)),
            "first_seen_on_card": str(prior["ts"].min()) if len(prior) else "",
            "n_txns_in_window": int(len(in_window)),
            "n_devices_on_card": int(base[base["device_profile"] != ""]["device_profile"].nunique()),
            "baseline_cutoff": str(cutoff),
        }

    def region_profile(self, card_id: str, as_of: datetime, region: str,
                       baseline_cutoff: datetime | None = None) -> dict[str, Any]:
        self._count()
        cutoff = baseline_cutoff or as_of
        df = self._card_slice(card_id, cutoff)
        counts = df["region"].value_counts()
        return {
            "card_id": card_id,
            "region": region,
            "n_prior_in_region": int(counts.get(region, 0)),
            "region_share": round(float(counts.get(region, 0) / max(len(df), 1)), 4),
            "home_region": str(counts.index[0]) if len(counts) else "",
            "n_regions_seen": int(len(counts)),
            "n_baseline_txns": int(len(df)),
            "top_regions": {str(k): int(v) for k, v in counts.head(8).items()},
            "baseline_cutoff": str(cutoff),
        }

    def out_of_region_probe(self, card_id: str, as_of: datetime, region: str,
                            baseline_cutoff: datetime | None = None) -> dict[str, Any]:
        """Documented pattern 4. The discriminator between a clone and a trip is
        whether the cardholder's normal home activity *continues* while the
        out-of-region purchases happen (README: "several days of purchases in
        one new region is a trip, not a clone")."""
        self._count()
        cutoff = baseline_cutoff or as_of
        full = self._card_slice(card_id, as_of)
        base = self._card_slice(card_id, cutoff)
        if full.empty or not region:
            return {"matched": False}
        counts = base["region"].value_counts()
        home = str(counts.index[0]) if len(counts) else ""
        prior = int((base["region"] == region).sum())
        window = full[full["ts"] > cutoff]
        in_region = window[window["region"] == region]
        home_same_window = window[(window["region"] == home) & (window["region"] != region)]
        # how long has activity in this region been running?
        span_days = 0.0
        if len(in_region) > 1:
            span_days = float((in_region["ts"].max() - in_region["ts"].min()).total_seconds()
                              / 86400.0)
        return {
            "card_id": card_id,
            "region": region,
            "home_region": home,
            "matched": bool(prior == 0 and region != home and region != ""),
            "n_prior_in_region": prior,
            "n_in_region_window": int(len(in_region)),
            "in_region_span_days": round(span_days, 2),
            "home_activity_continues": bool(len(home_same_window) > 0),
            "n_home_txns_window": int(len(home_same_window)),
            "interleaved": bool(len(home_same_window) > 0 and len(in_region) > 0),
            "card_present_share": round(float(in_region["channel"].eq("in_person").mean()), 3)
            if len(in_region) else 0.0,
        }

    def recurring_charge_probe(self, card_id: str, as_of: datetime, amount: float,
                               product_cd: str,
                               baseline_cutoff: datetime | None = None) -> dict[str, Any]:
        """Policy R7 — the cadence rule lives in matchers.recurrence_from_rows,
        shared with the TigerGraph backend."""
        self._count()
        df = self._card_slice(card_id, baseline_cutoff or as_of)
        # A subscription bills the *same* amount, not a similar one. Loose
        # tolerance turns every busy card into a false recurrence.
        same = df[(df["product_cd"] == product_cd)
                  & ((df["amount"] - amount).abs() <= 0.011)].sort_values("ts")
        rows = [{"ts": r.ts.to_pydatetime(), "txn_id": str(r.txn_id)}
                for r in same.itertuples()]
        return {"card_id": card_id, "amount": amount, **recurrence_from_rows(rows)}

    def episode_window(self, card_id: str, as_of: datetime,
                       window_hours: float = 72.0) -> dict[str, Any]:
        self._count()
        cutoff = as_of - timedelta(hours=window_hours)
        full = self._card_slice(card_id, as_of)
        win = full[full["ts"] > cutoff]
        base = self._card_slice(card_id, cutoff)
        amt = base["amount"].to_numpy(dtype=float)
        return {
            "card_id": card_id,
            "as_of": str(as_of),
            "baseline_cutoff": str(cutoff),
            "window_hours": window_hours,
            "window_txn_ids": win["txn_id"].tolist(),
            "n_window": int(len(win)),
            "window_value_usd": round(float(win["amount"].sum()), 2),
            "n_baseline": int(len(base)),
            "baseline_amt_mean": round(float(amt.mean()), 2) if len(amt) else 0.0,
            "baseline_amt_std": round(float(amt.std(ddof=0)), 2) if len(amt) else 0.0,
            "baseline_amt_median": round(float(np.median(amt)), 2) if len(amt) else 0.0,
            "baseline_amt_p95": round(float(np.percentile(amt, 95)), 2) if len(amt) else 0.0,
            "baseline_amt_max": round(float(amt.max()), 2) if len(amt) else 0.0,
            "window_online": int(win["channel"].eq("online").sum()),
            "window_in_person": int(win["channel"].eq("in_person").sum()),
            "window_regions": sorted({r for r in win["region"] if r}),
            "window_devices": sorted({d for d in win["device_profile"] if d}),
        }

    def email_mismatch_profile(self, txn_id: str) -> dict[str, Any]:
        self._count()
        i = self.ds.by_txn.get(str(txn_id))
        if i is None:
            return {}
        row = self.ds.tx.iloc[i]
        p, r = str(row["email_p"]), str(row["email_r"])
        free = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
                "live.com", "icloud.com", "mail.com", "protonmail.com"}
        return {
            "txn_id": str(txn_id),
            "purchaser_domain": p,
            "recipient_domain": r,
            "mismatch": bool(p and r and p != r),
            "purchaser_is_free": p in free,
            "recipient_is_free": r in free,
        }

    def mixed_channel_probe(self, card_id: str, as_of: datetime,
                            window_hours: float = 48.0) -> dict[str, Any]:
        """Documented pattern 5 (account takeover) leans on mixed-channel
        activity that is inconsistent with the cardholder."""
        self._count()
        win = self._card_slice(card_id, as_of, as_of - timedelta(hours=window_hours))
        base = self._card_slice(card_id, as_of - timedelta(hours=window_hours))
        if win.empty:
            return {"matched": False}
        online = int(win["channel"].eq("online").sum())
        inperson = int(win["channel"].eq("in_person").sum())
        base_online_share = float(base["channel"].eq("online").mean()) if len(base) else 0.0
        win_online_share = float(win["channel"].eq("online").mean())
        new_devices = [d for d in win["device_profile"].unique()
                       if d and d not in set(base["device_profile"].unique())]
        return {
            "card_id": card_id,
            "window_hours": window_hours,
            "n_online": online,
            "n_in_person": inperson,
            "mixed": bool(online > 0 and inperson > 0),
            "baseline_online_share": round(base_online_share, 3),
            "window_online_share": round(win_online_share, 3),
            "channel_shift": round(abs(win_online_share - base_online_share), 3),
            "new_device_profiles": new_devices[:5],
            "match_flag_mismatches": int(win["m_mismatch_count"].sum()),
            "matched": bool(online > 0 and inperson > 0
                            and abs(win_online_share - base_online_share) > 0.25),
        }

    def shared_entity_ring(self, card_id: str, as_of: datetime,
                           window_days: int = 30) -> dict[str, Any]:
        """Policy R6. One hop out through shared device profiles, then back to
        every other card that touched them in the window."""
        self._count()
        df = self._card_slice(card_id, as_of, as_of - timedelta(days=window_days))
        # Busy cards touch dozens of browser fingerprints in a month; only the
        # most used ones can plausibly be a hub, and each fan-out is a real
        # traversal, so cap the expansion.
        devices = [d for d in df["device_profile"].value_counts().index.tolist() if d][:8]
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
        # A ring is a hub that is *both* shared and anomalous: either every leg
        # arrives through an anonymising proxy, or the device is rare overall yet
        # brand-new to a run of accounts inside one window.
        def is_ring(d: str) -> bool:
            """A hub, not a popular browser.

            The only test that survives contact with this dataset is the
            anonymising-proxy share: on the confirmed ring every card that ever
            touched the profile arrived anonymously (ratio 1.00) against 0.03
            for an ordinary shared fingerprint.

            The obvious alternative — a rare profile appearing brand new on a
            run of accounts inside one window — looks principled and is not. A
            browser version release does exactly that: `Windows | Windows 10 |
            chrome 65.0 | 1440x900` had 19 cards all-time, 14 of them first-seen
            inside the same 30 days, 6 flagged New by the identity record, and
            none of it is fraud. It is a Chrome update. That rule fired on a
            quarter of the benchmark before it was removed.
            """
            f = fanouts[d]
            return (len(anon_members.get(d, ())) >= 2
                    and float(f.get("anon_proxy_ratio", 0.0)) >= 0.5)

        ring_devices = [d for d in members if is_ring(d)]
        all_members = sorted({c for d in ring_devices for c in members[d]})
        regions = df["region"].value_counts().head(1)
        hub = max(ring_devices, key=lambda d: len(members[d])) if ring_devices else ""
        return {
            "card_id": card_id,
            "window_days": window_days,
            "shared_devices": {d: sorted(members[d])[:40] for d in ring_devices},
            "connected_card_ids": all_members[:60],
            "ring_size": len(all_members) + 1,
            "hub_device": hub,
            "hub_fanout": fanouts.get(hub, {}),
            "anon_proxy_ring": bool(hub and len(anon_members.get(hub, ())) >= 2),
            "all_shared_device_cards": sorted({c for s in members.values() for c in s})[:60],
            "home_region": str(regions.index[0]) if len(regions) else "",
        }

    def fraud_proximity(self, entity_ids: Sequence[str], as_of: datetime,
                        max_hops: int = 2) -> dict[str, Any]:
        """Distance-decayed count of confirmed-fraud closed cases around the
        entities under investigation. Turns four months of static history into a
        live graph signal."""
        self._count()
        opened = self.ds.case_opened
        outcome = self.ds.case_outcome
        score = 0.0
        contributing: list[str] = []
        seen: set[str] = set()
        frontier = {str(e) for e in entity_ids if e}
        visited: set[str] = set(frontier)
        for hop in range(1, max_hops + 1):
            next_frontier: set[str] = set()
            for ent in frontier:
                for cid in self.ds.entity_cases.get(ent, []):
                    if cid in seen:
                        continue
                    o = opened.get(cid)
                    if o is None or o >= as_of:
                        continue
                    seen.add(cid)
                    if outcome.get(cid) == "confirmed_fraud":
                        score += 0.5 ** hop
                        contributing.append(cid)
                    next_frontier |= self.ds.case_entities.get(cid, set())
            next_frontier -= visited
            visited |= next_frontier
            frontier = next_frontier
            if not frontier:
                break
        return {
            "proximity_score": round(score, 4),
            "n_confirmed_fraud_cases": len(contributing),
            "evidence_cases": contributing[:25],
            "max_hops": max_hops,
        }

    # ------------------------------------------------- hybrid recall ------
    def hybrid_case_recall(self, query_text: str, entity_ids: Sequence[str],
                           as_of: datetime, k: int = 5) -> list[RecalledCase]:
        self._count()
        ds = self.ds
        entity_set = {str(e) for e in entity_ids if e}
        closed = ds.closed
        opened = closed["opened_at"]
        eligible = (opened < as_of).to_numpy()

        vec_scores: dict[str, float] = {}
        q_vec = None
        if ds.case_vectors is not None and ds.embedder is not None and query_text:
            q = q_vec = ds.embedder.encode([query_text])[0]
            mask = np.array([eligible[i] for i in range(len(ds.case_vector_ids))])
            idx, sims = cosine_top_k(q, ds.case_vectors, k * 8, mask=mask)
            for i, s in zip(idx, sims):
                if np.isfinite(s):
                    vec_scores[ds.case_vector_ids[int(i)]] = float(s)

        # Shared entities are not equal. Landing on the same *device profile* as
        # a prior confirmed fraud is a far stronger claim than sharing a
        # customer id with a case on the same customer, which is nearly
        # tautological. Weighting by type is what lets the ring cases outrank a
        # merely well-phrased narrative.
        weights = {"device": 1.6, "txn": 2.0, "card": 1.0, "customer": 0.7}

        def _kind(ent: str) -> str:
            if "|" in ent:
                return "device"
            if ent.isdigit():
                return "txn"
            return "card" if "-K" in ent else "customer"

        shared: dict[str, float] = {}
        shared_n: dict[str, int] = {}
        for ent in entity_set:
            w = weights[_kind(ent)]
            for cid in ds.entity_cases.get(ent, []):
                shared[cid] = shared.get(cid, 0.0) + w
                shared_n[cid] = shared_n.get(cid, 0) + 1

        by_id = ds.closed_by_id
        # Score the *union*, not just the vector-search results. Taking the
        # semantic term as zero for a case the traversal found is what made the
        # ring cases — which share the hub device outright — rank below cases
        # that merely read similarly. Templated narratives all sit around 0.73
        # cosine, so an absent semantic term costs more than a present shared
        # entity gains.
        vec_index = ds.case_vector_pos

        fused: list[RecalledCase] = []
        for cid in set(vec_scores) | set(shared):
            if cid not in by_id.index:
                continue
            row = by_id.loc[cid]
            if row["opened_at"] >= as_of:
                continue
            v = vec_scores.get(cid)
            if v is None and q_vec is not None and cid in vec_index:
                v = float(ds.case_vectors[vec_index[cid]] @ q_vec)
            v = v or 0.0
            n_shared = shared_n.get(cid, 0)
            score = 0.55 * v + 0.45 * (1.0 - math.exp(-1.2 * shared.get(cid, 0.0)))
            # `case_entities` holds ids; device profiles are indexed separately,
            # so both have to be consulted or the citation loses the very thing
            # that linked the two cases.
            touched = ds.case_entities.get(cid, set()) | ds.case_devices.get(cid, set())
            overlap = sorted(entity_set & touched)
            fused.append(RecalledCase(
                case_id=cid,
                outcome=str(row["outcome"]),
                pattern=str(row["pattern"]),
                similarity=round(v, 4),
                shared_entities=n_shared,
                fused_score=round(score, 4),
                exposure_usd=float(row["exposure_usd"]),
                opened_at=str(row["opened_at"]),
                narrative=str(row["analyst_notes"]),
                shared_with=overlap[:6],
            ))
        fused.sort(key=lambda c: -c.fused_score)
        return fused[:k]

    def behavioural_neighbours(self, txn_id: str, as_of: datetime,
                               k: int = 10) -> dict[str, Any]:
        self._count()
        ds = self.ds
        if ds.behaviour is None:
            return {"available": False}
        i = ds.behaviour_index.get(str(txn_id))
        if i is None:
            return {"available": False}
        cutoff = np.datetime64(as_of)
        mask = (ds.cc_opened < cutoff) & (ds.cc_txn_ids != str(txn_id))
        if not mask.any():
            return {"available": False}
        rows = ds.cc_rows[mask]
        labels = ds.cc_labels[mask]
        ids = ds.cc_txn_ids[mask]
        sims = ds.behaviour[rows] @ ds.behaviour[i]
        k = int(min(k, sims.shape[0]))
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top])]
        lab = labels[top]
        # The candidate pool is the closed-case file, which is ~89% fraud by
        # transaction. A neighbourhood that is 90% fraud is therefore the base
        # rate, not a finding, and reporting the raw share would make this
        # signal fire on almost every transaction in the dataset. What carries
        # information is the *lift* over the pool.
        pool_rate = float(labels.mean())
        share = float(lab.mean())
        return {
            "available": True,
            "k": k,
            "n_fraud": int(lab.sum()),
            "n_cleared": int((1 - lab).sum()),
            "fraud_share": round(share, 3),
            "pool_fraud_rate": round(pool_rate, 3),
            "fraud_lift": round(share - pool_rate, 3),
            "mean_similarity": round(float(sims[top].mean()), 4),
            "neighbours": [
                {"txn_id": str(ids[int(j)]), "similarity": round(float(sims[int(j)]), 4),
                 "confirmed_fraud": bool(labels[int(j)])}
                for j in top[:5]
            ],
        }

    def policy_retrieve(self, query_text: str, k: int = 5,
                        kinds: Iterable[str] | None = None) -> list[dict[str, Any]]:
        self._count()
        ds = self.ds
        if ds.doc_vectors is None or ds.embedder is None:
            return []
        allow = set(kinds) if kinds else None
        mask = np.array([allow is None or m.get("kind") in allow for m in ds.doc_meta])
        q = ds.embedder.encode([query_text])[0]
        idx, sims = cosine_top_k(q, ds.doc_vectors, k, mask=mask)
        out = []
        for i, s in zip(idx, sims):
            if not np.isfinite(s):
                continue
            m = dict(ds.doc_meta[int(i)])
            m["similarity"] = round(float(s), 4)
            out.append(m)
        return out

    # ----------------------------------------------------------- writes ----
    def write_case(self, case_doc: dict[str, Any]) -> str:
        """Append the case to the in-process memory and to a durable JSONL so a
        later investigation can retrieve it, mirroring the Case subgraph write
        that `TigerGraphStore` performs."""
        self._count()
        graph_case_id = case_doc.get("graph_case_id") or f"CASE-{case_doc['case_id']}"
        case_doc = dict(case_doc)
        case_doc["graph_case_id"] = graph_case_id
        self.ds.agent_cases.append(case_doc)
        ents = set(case_doc.get("entity_ids") or [])
        self.ds.case_entities[graph_case_id] = ents
        for e in ents:
            self.ds.entity_cases[e].append(graph_case_id)
        PATHS.staged.mkdir(parents=True, exist_ok=True)
        with PATHS.agent_cases_jsonl.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(case_doc, ensure_ascii=False, default=str) + "\n")
        return graph_case_id

    def case_chain(self, graph_case_id: str) -> dict[str, Any]:
        self._count()
        for c in self.ds.agent_cases:
            if c.get("graph_case_id") == graph_case_id:
                return c
        if PATHS.agent_cases_jsonl.exists():
            for line in PATHS.agent_cases_jsonl.read_text(encoding="utf-8").splitlines():
                doc = json.loads(line)
                if doc.get("graph_case_id") == graph_case_id:
                    return doc
        return {}

    def health(self) -> dict[str, Any]:
        ds = self.ds
        return {
            "backend": "local",
            "ok": True,
            "transactions": int(len(ds.tx)),
            "cards": int(len(ds.card_rows)),
            "device_profiles": int(len(ds.device_rows)),
            "closed_cases": int(len(ds.closed)),
            "case_vectors": 0 if ds.case_vectors is None else int(ds.case_vectors.shape[0]),
            "doc_vectors": 0 if ds.doc_vectors is None else int(ds.doc_vectors.shape[0]),
            "behaviour_vectors": 0 if ds.behaviour is None else int(ds.behaviour.shape[0]),
        }

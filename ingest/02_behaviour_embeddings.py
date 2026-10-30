"""Stage 2 — behavioural embeddings on transactions.

`V1`-`V339` are real Vesta-engineered signal but unusable as LLM context and
mostly redundant. We compress the whole numeric block into a 64-dimensional
behaviour vector per transaction so that "which confirmed-fraud transactions
*act* like this one" becomes a vector query instead of an LLM impression.

Recipe (matches docs/ARCHITECTURE.md §5):
  1. rank-normalise C1-C14, D1-D15, M1-M9 trinary, amount, hour sin/cos, dist1/2
  2. incremental PCA of V1-V339 down to 24 components
  3. concatenate -> 64 dims -> L2 normalise -> cosine similarity

Run:  python ingest/02_behaviour_embeddings.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import IncrementalPCA

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Windows consoles still default to cp1252, which cannot encode the arrows and
# box characters used below; without this a clean run dies on its own log line.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - non-reconfigurable stream
    pass


from fraudagent.config import PATHS  # noqa: E402

V_COLS = [f"V{i}" for i in range(1, 340)]
C_COLS = [f"C{i}" for i in range(1, 15)]
D_COLS = [f"D{i}" for i in range(1, 16)]
M_TRI = [f"M{i}_tri" for i in range(1, 10)]
N_PCA = 24
CHUNK = 60_000


def log(msg: str) -> None:
    print(f"[behaviour] {msg}", flush=True)


def rank_normalise(a: np.ndarray) -> np.ndarray:
    """Rank -> [-1, 1]. IEEE-CIS outliers destroy z-scores; ranks survive them."""
    out = np.zeros_like(a, dtype=np.float32)
    for j in range(a.shape[1]):
        col = a[:, j]
        mask = np.isfinite(col)
        if mask.sum() < 2:
            continue
        order = np.argsort(col[mask], kind="stable")
        ranks = np.empty(mask.sum(), dtype=np.float32)
        ranks[order] = np.arange(mask.sum(), dtype=np.float32)
        ranks /= max(mask.sum() - 1, 1)
        out[mask, j] = ranks * 2.0 - 1.0
    return out


def main() -> None:
    t0 = time.time()
    PATHS.ensure()

    log("pass 1/2 — incremental PCA over V1..V339")
    ipca = IncrementalPCA(n_components=N_PCA)
    reader = pd.read_csv(PATHS.transactions_csv, usecols=["TransactionID"] + V_COLS,
                         chunksize=CHUNK)
    medians = None
    chunks_meta = []
    for i, chunk in enumerate(reader):
        vals = chunk[V_COLS].to_numpy(dtype=np.float32, na_value=np.nan)
        if medians is None:
            medians = np.nanmedian(vals, axis=0)
            medians = np.where(np.isfinite(medians), medians, 0.0).astype(np.float32)
        vals = np.where(np.isfinite(vals), vals, medians)
        vals = np.sign(vals) * np.log1p(np.abs(vals))      # tame the tails
        ipca.partial_fit(vals)
        chunks_meta.append(len(chunk))
        log(f"  chunk {i+1} fitted ({sum(chunks_meta):,} rows)")
    log(f"explained variance (24 comps): {ipca.explained_variance_ratio_.sum():.3f}")

    log("pass 2/2 — transform")
    pieces = []
    reader = pd.read_csv(PATHS.transactions_csv, usecols=["TransactionID"] + V_COLS,
                         chunksize=CHUNK)
    for chunk in reader:
        vals = chunk[V_COLS].to_numpy(dtype=np.float32, na_value=np.nan)
        vals = np.where(np.isfinite(vals), vals, medians)
        vals = np.sign(vals) * np.log1p(np.abs(vals))
        comp = ipca.transform(vals).astype(np.float32)
        pieces.append(pd.DataFrame(comp, index=chunk["TransactionID"].to_numpy()))
    v_emb = pd.concat(pieces)
    v_emb = rank_normalise(v_emb.to_numpy(dtype=np.float32))
    v_index = np.concatenate([p.index.to_numpy() for p in pieces])
    log(f"V block -> {v_emb.shape}")

    log("assembling behaviour features")
    tx = pd.read_parquet(
        PATHS.tx_parquet,
        columns=["TransactionID", "txn_id", "amount_log", "hour", "dist1", "dist2",
                 "risk_score", "amt_zscore_card", "gap_hours", "m_mismatch_count",
                 "m_missing_count"] + C_COLS + D_COLS + M_TRI,
    )
    tx = tx.set_index("TransactionID").loc[v_index].reset_index()

    hour = tx["hour"].to_numpy(dtype=np.float32)
    base_cols = np.column_stack([
        tx["amount_log"].to_numpy(dtype=np.float32),
        tx["amt_zscore_card"].to_numpy(dtype=np.float32),
        np.log1p(tx["gap_hours"].fillna(-1).clip(lower=-1).to_numpy(dtype=np.float32) + 1),
        tx["risk_score"].to_numpy(dtype=np.float32),
        tx["dist1"].to_numpy(dtype=np.float32, na_value=np.nan),
        tx["dist2"].to_numpy(dtype=np.float32, na_value=np.nan),
        tx["m_mismatch_count"].to_numpy(dtype=np.float32),
        tx["m_missing_count"].to_numpy(dtype=np.float32),
    ])
    base_cols = rank_normalise(base_cols)
    cyc = np.column_stack([np.sin(2 * np.pi * hour / 24.0), np.cos(2 * np.pi * hour / 24.0)])

    cd = tx[C_COLS + D_COLS].to_numpy(dtype=np.float32, na_value=np.nan)
    cd = rank_normalise(cd)                    # 29 dims
    mtri = tx[M_TRI].to_numpy(dtype=np.float32) / 1.0   # 9 dims, already -1/0/1

    feat = np.column_stack([base_cols, cyc, cd[:, :14], mtri, v_emb]).astype(np.float32)
    # 8 + 2 + 14 + 9 + 24 = 57 -> pad the D-block summary to reach 64
    d_summary = rank_normalise(cd[:, 14:])[:, :7]
    feat = np.column_stack([feat, d_summary]).astype(np.float32)
    feat = np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)
    norms = np.linalg.norm(feat, axis=1, keepdims=True)
    feat = feat / np.where(norms == 0, 1.0, norms)
    log(f"behaviour vector dim = {feat.shape[1]}")

    out = pd.DataFrame({"txn_id": tx["txn_id"].to_numpy()})
    out["behaviour_emb"] = list(feat.astype(np.float32))
    out.to_parquet(PATHS.behaviour_parquet, index=False)
    log(f"wrote {PATHS.behaviour_parquet} ({len(out):,} rows) in {time.time()-t0:.1f}s")


def rank_against(ref: np.ndarray, new: np.ndarray) -> np.ndarray:
    """Rank-normalise `new` against the reference distribution `ref`, column by
    column, so a new month is placed on the old scale instead of re-scaling it."""
    out = np.zeros_like(new, dtype=np.float32)
    for j in range(new.shape[1]):
        r = ref[:, j]
        r = np.sort(r[np.isfinite(r)])
        if r.size < 2:
            continue
        col = new[:, j]
        mask = np.isfinite(col)
        pos = np.searchsorted(r, col[mask], side="left").astype(np.float32) / (r.size - 1)
        out[mask, j] = np.clip(pos, 0.0, 1.0) * 2.0 - 1.0
    return out


def append() -> None:
    """Final round: January arrives. Do NOT refit: refitting the PCA and the
    rank scales would move every existing vector, invalidating the behaviour
    index in the graph, the conformal support set and the closed-case fact
    replays. Instead re-derive the Round 1 fit exactly (same chunks, same
    medians), project only the new transactions through it, and rank them
    against the Round 1 distribution. Existing vectors are kept byte-identical."""
    t0 = time.time()
    old = pd.read_parquet(PATHS.behaviour_parquet)
    have = set(old["txn_id"].astype(str))
    files = PATHS.transaction_files()
    base_file, new_files = files[0], files[1:]
    if not new_files:
        log("no new transaction files; nothing to append")
        return
    log(f"refitting the Round 1 PCA on {base_file.name} (identical chunks)")
    ipca = IncrementalPCA(n_components=N_PCA)
    medians = None
    for chunk in pd.read_csv(base_file, usecols=["TransactionID"] + V_COLS, chunksize=CHUNK):
        vals = chunk[V_COLS].to_numpy(dtype=np.float32, na_value=np.nan)
        if medians is None:
            medians = np.nanmedian(vals, axis=0)
            medians = np.where(np.isfinite(medians), medians, 0.0).astype(np.float32)
        vals = np.where(np.isfinite(vals), vals, medians)
        ipca.partial_fit(np.sign(vals) * np.log1p(np.abs(vals)))

    def project(path):
        parts = []
        for chunk in pd.read_csv(path, usecols=["TransactionID"] + V_COLS, chunksize=CHUNK):
            vals = chunk[V_COLS].to_numpy(dtype=np.float32, na_value=np.nan)
            vals = np.where(np.isfinite(vals), vals, medians)
            comp = ipca.transform(np.sign(vals) * np.log1p(np.abs(vals))).astype(np.float32)
            parts.append(pd.DataFrame(comp, index=chunk["TransactionID"].to_numpy()))
        return pd.concat(parts)

    ref_v = project(base_file)
    new_v = pd.concat([project(f) for f in new_files])
    log(f"projected {len(new_v):,} new transactions through the Round 1 PCA")

    cols = ["TransactionID", "txn_id", "amount_log", "hour", "dist1", "dist2", "risk_score",
            "amt_zscore_card", "gap_hours", "m_mismatch_count", "m_missing_count"] \
        + C_COLS + D_COLS + M_TRI
    tx = pd.read_parquet(PATHS.tx_parquet, columns=cols).set_index("TransactionID")

    def raw_blocks(t: pd.DataFrame):
        base = np.column_stack([
            t["amount_log"].to_numpy(dtype=np.float32),
            t["amt_zscore_card"].to_numpy(dtype=np.float32),
            np.log1p(t["gap_hours"].fillna(-1).clip(lower=-1).to_numpy(dtype=np.float32) + 1),
            t["risk_score"].to_numpy(dtype=np.float32),
            t["dist1"].to_numpy(dtype=np.float32, na_value=np.nan),
            t["dist2"].to_numpy(dtype=np.float32, na_value=np.nan),
            t["m_mismatch_count"].to_numpy(dtype=np.float32),
            t["m_missing_count"].to_numpy(dtype=np.float32)])
        cd = t[C_COLS + D_COLS].to_numpy(dtype=np.float32, na_value=np.nan)
        return base, cd

    ref_t = tx.loc[ref_v.index]
    new_t = tx.loc[new_v.index]
    rb, rcd = raw_blocks(ref_t)
    nb, ncd = raw_blocks(new_t)
    base_cols = rank_against(rb, nb)
    rcd_ranked = rank_normalise(rcd)
    cd = rank_against(rcd, ncd)
    v_emb = rank_against(ref_v.to_numpy(dtype=np.float32), new_v.to_numpy(dtype=np.float32))
    hour = new_t["hour"].to_numpy(dtype=np.float32)
    cyc = np.column_stack([np.sin(2 * np.pi * hour / 24.0), np.cos(2 * np.pi * hour / 24.0)])
    mtri = new_t[M_TRI].to_numpy(dtype=np.float32)
    d_summary = rank_against(rcd_ranked[:, 14:], cd[:, 14:])[:, :7]
    feat = np.column_stack([base_cols, cyc, cd[:, :14], mtri, v_emb, d_summary]).astype(np.float32)
    feat = np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)
    norms = np.linalg.norm(feat, axis=1, keepdims=True)
    feat = feat / np.where(norms == 0, 1.0, norms)
    add = pd.DataFrame({"txn_id": new_t["txn_id"].astype(str).to_numpy()})
    add["behaviour_emb"] = list(feat)
    add = add[~add["txn_id"].isin(have)]
    out = pd.concat([old, add], ignore_index=True)
    out.to_parquet(PATHS.behaviour_parquet, index=False)
    log(f"appended {len(add):,} vectors (kept {len(old):,} unchanged) in {time.time()-t0:.0f}s")


if __name__ == "__main__" and "--append" in sys.argv:
    append()
    raise SystemExit(0)


if __name__ == "__main__":
    main()

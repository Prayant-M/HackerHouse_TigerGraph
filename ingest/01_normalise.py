"""Stage 1 — normalise the raw HHGOA CSVs into typed parquet.

What this does that a naive load does not:

1. **Recovers `card_id`.** `transactions.csv` has no `card_id`, but the case pack
   and the closed cases are expressed in terms of `C01234-K1`. A card is the
   `(customer_id, card2..card6)` tuple; the `K` index is *pinned* from the
   ground-truth labels in `closed_cases_history.csv` and `case_pack.csv`
   wherever they exist, and derived heuristically elsewhere. Rows whose card
   attributes are partially missing are folded into the card the labels say
   they belong to. Verified at 100% on the case pack.
2. **Builds the device profile** exactly as the dataset README spells it:
   `DeviceInfo | OS | browser | screen`.
3. **Keeps missingness as signal.** `M1`-`M9` become trinary, and presence
   flags are materialised rather than imputed away.
4. Derives per-card baselines used by every downstream detector.

Run:  python ingest/01_normalise.py
"""

from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Windows consoles still default to cp1252, which cannot encode the arrows and
# box characters used below; without this a clean run dies on its own log line.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - non-reconfigurable stream
    pass


from fraudagent.config import PATHS  # noqa: E402

CARD_FIELDS = ["card2", "card3", "card4", "card5", "card6"]
C_COLS = [f"C{i}" for i in range(1, 15)]
D_COLS = [f"D{i}" for i in range(1, 16)]
M_COLS = [f"M{i}" for i in range(1, 10)]

CORE_COLS = (
    ["TransactionID", "TransactionDT", "TransactionAmt", "ProductCD",
     "card1", "card2", "card3", "card4", "card5", "card6",
     "addr1", "addr2", "dist1", "dist2", "P_emaildomain", "R_emaildomain"]
    + C_COLS + D_COLS + M_COLS
    + ["customer_id", "ts", "channel", "risk_score"]
)

IDENTITY_KEEP = [
    "TransactionID", "id_01", "id_02", "id_05", "id_06", "id_11",
    "id_12", "id_15", "id_16", "id_17", "id_19", "id_20", "id_23",
    "id_28", "id_29", "id_30", "id_31", "id_32", "id_33", "id_34",
    "id_35", "id_36", "id_37", "id_38", "DeviceType", "DeviceInfo",
]


def log(msg: str) -> None:
    print(f"[normalise] {msg}", flush=True)


# --------------------------------------------------------------- card id ----
def card_key(df: pd.DataFrame) -> pd.Series:
    parts = []
    for c in CARD_FIELDS:
        s = df[c].astype("object")
        s = s.where(df[c].notna(), "")
        parts.append(s.astype(str))
    out = parts[0]
    for p in parts[1:]:
        out = out + "|" + p
    return out


def collect_pins(paths) -> dict[int, str]:
    """txn_id -> card_id, taken from the dataset's own labelled files."""
    pins: dict[int, str] = {}
    cc = pd.read_csv(paths.closed_cases_csv)
    for txn_ids, card_id in zip(cc["txn_ids"].fillna("").astype(str), cc["card_id"].astype(str)):
        for piece in txn_ids.split("|"):
            piece = piece.strip()
            if piece.isdigit():
                pins[int(piece)] = card_id
    cp = pd.concat([pd.read_csv(f) for f in paths.case_pack_files()], ignore_index=True)
    for txn_id, card_id in zip(cp["flagged_txn_id"], cp["card_id"].astype(str)):
        pins[int(txn_id)] = card_id
    return pins


def assign_card_ids(tx: pd.DataFrame, pins: dict[int, str]) -> pd.Series:
    """Assign `customer-Kn` to every transaction.

    Pinned keys keep the index the dataset gives them; unpinned keys are ordered
    by (most-missing-card-attributes first, then first-seen) which matches the
    labels on 94% of unpinned closed-case rows.
    """
    n_missing = tx[CARD_FIELDS].isna().sum(axis=1)
    key = card_key(tx)
    tx = tx.assign(_key=key, _nmiss=n_missing)

    # votes: (customer, key) -> Counter(card_id)
    votes: dict[tuple[str, str], Counter] = defaultdict(Counter)
    pin_series = tx["TransactionID"].map(pins)
    mask = pin_series.notna()
    for cust, k, cid in zip(tx.loc[mask, "customer_id"], tx.loc[mask, "_key"],
                            pin_series[mask]):
        votes[(cust, k)][cid] += 1

    grouped = (
        tx.groupby(["customer_id", "_key"], as_index=False)
        .agg(first_ts=("ts", "min"), n=("ts", "size"), nmiss=("_nmiss", "max"))
        .sort_values(["customer_id", "nmiss", "first_ts"], ascending=[True, False, True])
    )

    mapping: dict[tuple[str, str], str] = {}
    for cust, sub in grouped.groupby("customer_id", sort=False):
        keys = list(sub["_key"])
        pinned = {}
        used: set[int] = set()
        for k in keys:
            v = votes.get((cust, k))
            if v:
                cid = v.most_common(1)[0][0]
                pinned[k] = cid
                suffix = cid.rsplit("-K", 1)[-1]
                if suffix.isdigit():
                    used.add(int(suffix))
        nxt = 1
        for k in keys:
            if k in pinned:
                mapping[(cust, k)] = pinned[k]
                continue
            while nxt in used:
                nxt += 1
            used.add(nxt)
            mapping[(cust, k)] = f"{cust}-K{nxt}"
    return pd.Series([mapping[(c, k)] for c, k in zip(tx["customer_id"], tx["_key"])],
                     index=tx.index)


# ------------------------------------------------------------------ main ----
def main() -> None:
    t0 = time.time()
    PATHS.ensure()
    files = PATHS.transaction_files()
    log(f"reading {', '.join(f.name for f in files)} "
        f"({sum(f.stat().st_size for f in files)/1e6:.0f} MB)")
    # A foreign dataset (ingest/byo.py) may carry an explicit card id; keep it.
    tx = pd.concat([pd.read_csv(f, usecols=lambda c: c in CORE_COLS or c == "card_id",
                                low_memory=False) for f in files], ignore_index=True)
    given_card = tx.pop("card_id") if "card_id" in tx.columns else None
    tx = tx.drop_duplicates("TransactionID", keep="last")
    log(f"transactions: {tx.shape} in {time.time()-t0:.1f}s")

    tx["ts"] = pd.to_datetime(tx["ts"])
    tx["TransactionID"] = tx["TransactionID"].astype("int64")
    tx["amount"] = tx["TransactionAmt"].astype("float64")
    tx["risk_score"] = tx["risk_score"].astype("float32")

    log("recovering card_id from labelled files")
    pins = collect_pins(PATHS)
    tx["card_id"] = assign_card_ids(tx, pins)
    if given_card is not None and given_card.notna().mean() > 0.95:
        tx["card_id"] = given_card.astype(str).to_numpy()
        log("using the dataset's own card ids (explicit card column)")
    # The case pack is authoritative for its own flagged transaction. When the
    # history labels that card tuple differently (HHF-011: 21 closed cases say
    # K2, the final pack says K1), keep the pack's id for that transaction and
    # record the conflict for the data-quality report (C11).
    conflicts = []
    for f in PATHS.case_pack_files():
        cp = pd.read_csv(f)
        for r in cp.itertuples():
            m = tx["TransactionID"] == int(r.flagged_txn_id)
            if m.any() and tx.loc[m, "card_id"].iloc[0] != r.card_id:
                conflicts.append({"case_id": r.case_id, "txn_id": str(r.flagged_txn_id),
                                  "history_card_id": tx.loc[m, "card_id"].iloc[0],
                                  "pack_card_id": r.card_id})
                tx.loc[m, "card_id"] = r.card_id
    if conflicts:
        import json as _json
        (PATHS.staged / "card_label_conflicts.json").write_text(
            _json.dumps(conflicts, indent=2), encoding="utf-8")
        log(f"card label conflicts (pack wins for its flagged txn): {conflicts}")

    # verification against the labels we pinned from
    pinned = tx["TransactionID"].map(pins)
    m = pinned.notna()
    agree = float((tx.loc[m, "card_id"] == pinned[m]).mean())
    log(f"card_id agreement with labelled rows: {agree:.4f} over {int(m.sum())} rows")

    log(f"reading {', '.join(f.name for f in PATHS.identity_files())}")
    idf = pd.concat([pd.read_csv(f, usecols=IDENTITY_KEEP) for f in PATHS.identity_files()],
                    ignore_index=True).drop_duplicates("TransactionID", keep="last")
    idf["TransactionID"] = idf["TransactionID"].astype("int64")

    def clean(s: pd.Series) -> pd.Series:
        return s.astype("object").where(s.notna(), "").astype(str).str.strip()

    idf["device_info"] = clean(idf["DeviceInfo"])
    idf["os"] = clean(idf["id_30"])
    idf["browser"] = clean(idf["id_31"])
    idf["screen"] = clean(idf["id_33"])
    idf["device_type"] = clean(idf["DeviceType"])
    idf["device_status"] = clean(idf["id_15"])          # New / Found / Unknown
    idf["proxy"] = clean(idf["id_23"])                   # IP_PROXY:* when present
    idf["match_status"] = clean(idf["id_34"])
    # device profile string exactly as the dataset README formats it
    idf["device_profile"] = (
        idf["device_info"] + " | " + idf["os"] + " | " + idf["browser"] + " | " + idf["screen"]
    ).str.replace(r"\s*\|\s*", " | ", regex=True).str.strip(" |")
    idf.loc[idf["device_profile"].str.replace("|", "").str.strip() == "", "device_profile"] = ""

    keep_id = ["TransactionID", "device_profile", "device_info", "os", "browser", "screen",
               "device_type", "device_status", "proxy", "match_status",
               "id_01", "id_02", "id_05", "id_06", "id_11", "id_12", "id_16", "id_17",
               "id_19", "id_20", "id_28", "id_29", "id_32", "id_35", "id_36", "id_37", "id_38"]
    idf = idf[keep_id]

    log("joining identity")
    tx = tx.merge(idf, on="TransactionID", how="left")
    tx["has_identity"] = tx["device_profile"].notna()
    tx["device_profile"] = tx["device_profile"].fillna("")
    for c in ["device_status", "proxy", "device_type", "os", "browser", "screen",
              "device_info", "match_status"]:
        tx[c] = tx[c].fillna("")

    # ------------------------------------------------ derived attributes ----
    log("deriving attributes")
    tx["txn_id"] = tx["TransactionID"].astype(str)
    tx["product_cd"] = tx["ProductCD"].astype(str)
    tx["email_p"] = tx["P_emaildomain"].astype("object").where(
        tx["P_emaildomain"].notna(), "").astype(str)
    tx["email_r"] = tx["R_emaildomain"].astype("object").where(
        tx["R_emaildomain"].notna(), "").astype(str)
    tx["email_mismatch"] = (
        (tx["email_r"] != "") & (tx["email_p"] != "") & (tx["email_r"] != tx["email_p"])
    )
    tx["region"] = tx["addr1"].apply(lambda v: "" if pd.isna(v) else str(float(v)))
    tx["country"] = tx["addr2"].apply(lambda v: "" if pd.isna(v) else str(float(v)))
    tx["hour"] = tx["ts"].dt.hour.astype("int16")
    tx["dow"] = tx["ts"].dt.dayofweek.astype("int16")
    tx["date"] = tx["ts"].dt.date.astype(str)
    tx["is_online"] = tx["channel"].eq("online")
    tx["amount_log"] = np.log1p(tx["amount"])

    # M flags -> trinary (1 match / 0 mismatch / -1 missing)
    for c in M_COLS:
        col = tx[c]
        tri = pd.Series(-1, index=tx.index, dtype="int8")
        tri[col.eq("T")] = 1
        tri[col.eq("F")] = 0
        if col.dtype.kind in "fi":
            tri[col.eq(1)] = 1
            tri[col.eq(0)] = 0
        tx[f"{c}_tri"] = tri
    known = tx[[f"{c}_tri" for c in M_COLS]]
    tx["m_mismatch_count"] = (known == 0).sum(axis=1).astype("int8")
    tx["m_missing_count"] = (known == -1).sum(axis=1).astype("int8")

    tx = tx.sort_values(["card_id", "ts"]).reset_index(drop=True)

    # per-card rolling context
    g = tx.groupby("card_id", sort=False)
    tx["card_seq"] = g.cumcount().astype("int32")
    tx["prev_ts"] = g["ts"].shift(1)
    tx["gap_hours"] = (tx["ts"] - tx["prev_ts"]).dt.total_seconds() / 3600.0
    exp_mean = g["amount"].transform(lambda s: s.expanding().mean().shift(1))
    exp_std = g["amount"].transform(lambda s: s.expanding().std().shift(1))
    tx["amt_zscore_card"] = ((tx["amount"] - exp_mean) / exp_std.replace(0, np.nan)).fillna(0.0)
    tx["amt_pct_of_card_max"] = tx["amount"] / g["amount"].transform("max")

    keep = [
        "txn_id", "TransactionID", "ts", "date", "hour", "dow", "amount", "amount_log",
        "product_cd", "channel", "is_online", "risk_score", "customer_id", "card_id",
        "card1", "card2", "card3", "card4", "card5", "card6",
        "region", "country", "dist1", "dist2", "email_p", "email_r", "email_mismatch",
        "device_profile", "device_info", "os", "browser", "screen", "device_type",
        "device_status", "proxy", "match_status", "has_identity",
        "card_seq", "gap_hours", "amt_zscore_card", "amt_pct_of_card_max",
        "m_mismatch_count", "m_missing_count",
    ] + C_COLS + D_COLS + [f"{c}_tri" for c in M_COLS] + [
        "id_01", "id_02", "id_05", "id_06", "id_11", "id_17", "id_19", "id_20", "id_32"
    ]
    out = tx[keep].copy()
    PATHS.staged.mkdir(parents=True, exist_ok=True)
    out.to_parquet(PATHS.tx_parquet, index=False)
    log(f"wrote {PATHS.tx_parquet} ({len(out):,} rows)")

    # ------------------------------------------------------ card profiles ----
    log("building card profiles")
    prof = out.groupby("card_id").agg(
        customer_id=("customer_id", "first"),
        n_txns=("txn_id", "size"),
        first_seen=("ts", "min"),
        last_seen=("ts", "max"),
        amt_mean=("amount", "mean"),
        amt_median=("amount", "median"),
        amt_std=("amount", "std"),
        amt_max=("amount", "max"),
        amt_p95=("amount", lambda s: float(np.percentile(s, 95))),
        total_amt=("amount", "sum"),
        n_online=("is_online", "sum"),
        brand=("card4", "first"),
        card_type=("card6", "first"),
    ).reset_index()
    prof["amt_std"] = prof["amt_std"].fillna(0.0)
    prof["online_share"] = prof["n_online"] / prof["n_txns"]
    prof.to_parquet(PATHS.card_profile_parquet, index=False)
    log(f"wrote {PATHS.card_profile_parquet} ({len(prof):,} cards)")

    # ---------------------------------------------------- device index -----
    log("building device index")
    dev = out[out["device_profile"] != ""]
    didx = dev.groupby("device_profile").agg(
        n_txns=("txn_id", "size"),
        n_cards=("card_id", "nunique"),
        n_customers=("customer_id", "nunique"),
        first_seen=("ts", "min"),
        last_seen=("ts", "max"),
    ).reset_index()
    didx.to_parquet(PATHS.device_index_parquet, index=False)
    log(f"wrote {PATHS.device_index_parquet} ({len(didx):,} device profiles)")

    # --------------------------------------------------- closed cases ------
    log("normalising closed cases")
    cc = pd.read_csv(PATHS.closed_cases_csv)
    cc["opened_at"] = pd.to_datetime(cc["opened_at"])
    cc["closed_at"] = pd.to_datetime(cc["closed_at"])
    cc["txn_id_list"] = cc["txn_ids"].fillna("").astype(str).apply(
        lambda s: [x.strip() for x in s.split("|") if x.strip().isdigit()])
    cc["connected_card_list"] = cc["connected_card_ids"].fillna("").astype(str).apply(
        lambda s: [x.strip() for x in s.split("|") if x.strip()])
    cc["action_list"] = cc["actions_taken"].fillna("").astype(str).apply(
        lambda s: [x.strip() for x in s.split("|") if x.strip()])
    cc["is_fraud"] = cc["outcome"].eq("confirmed_fraud")
    cc.to_parquet(PATHS.closed_cases_parquet, index=False)
    log(f"wrote {PATHS.closed_cases_parquet} ({len(cc):,} closed cases)")

    log(f"done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

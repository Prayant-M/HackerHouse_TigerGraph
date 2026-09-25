"""Stage 6 — write the CSVs the TigerGraph loading jobs consume.

Staging in Python rather than pointing loading jobs at the raw files is not
ceremony. Three things have to happen before anything can be keyed correctly,
and none of them can happen inside GSQL:

* `card_id` has to be recovered (it is not a column in `transactions.csv`),
* the device profile string has to be assembled from four identity fields,
* vectors have to arrive as bare comma-separated floats — nested built-in token
  functions inside `SPLIT()` will not compile, so brackets must be stripped
  here, not there.

Output: data/staged/graph_csv/*.csv, ready for `graph/install.py --step load`.

Run:  python ingest/06_stage_graph_csv.py
"""

from __future__ import annotations

import json
import sys
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
from fraudagent.core.hypotheses import SUB_TYPOLOGIES  # noqa: E402

OUT = PATHS.staged / "graph_csv"
FREE_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
                "live.com", "icloud.com", "mail.com", "protonmail.com"}

DOCUMENTED = {
    "card_testing": ("Card testing",
                     "A stolen card number is checked before use: three or more tiny online "
                     "authorizations, often under $5, then a larger purchase."),
    "card_not_present_fraud": ("Card-not-present fraud",
                               "The number is used online without the card. Amounts and "
                               "products that do not fit the cardholder's history, often in a "
                               "burst of two to four within 48 hours."),
    "card_not_present_new_device": ("Card-not-present fraud from a new device",
                                    "As above, with the identity record marking the device New "
                                    "for this account, sometimes behind a proxy."),
    "out_of_region_use": ("Out-of-region use",
                          "Card-present purchases in a billing region the cardholder has no "
                          "history in, while their normal activity continues at home."),
    "account_takeover": ("Account takeover",
                         "Mixed-channel activity inconsistent with the cardholder, often with "
                         "device and match-flag anomalies, pointing to stolen credentials."),
}


def log(msg: str) -> None:
    print(f"[stage] {msg}", flush=True)


def vec_str(v) -> str:
    return ",".join(f"{x:.6f}" for x in np.asarray(v, dtype=np.float32))


def main() -> None:
    PATHS.ensure()
    OUT.mkdir(parents=True, exist_ok=True)
    tx = pd.read_parquet(PATHS.tx_parquet)
    tx["txn_id"] = tx["txn_id"].astype(str)

    # ------------------------------------------------------ transactions --
    cols = ["txn_id", "ts", "amount", "product_cd", "channel", "risk_score", "card_id",
            "customer_id", "region", "country", "dist1", "dist2", "device_status",
            "proxy", "match_status", "m_mismatch_count", "amt_zscore_card", "hour", "dow",
            "device_profile", "email_p", "email_r"]
    t = tx[cols].copy()
    t["ts"] = t["ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    for c in ("dist1", "dist2"):
        t[c] = t[c].fillna(-1.0)
    t.to_csv(OUT / "transactions.csv", index=False)
    log(f"transactions.csv  {len(t):,}")

    # ------------------------------------------------------------- cards --
    prof = pd.read_parquet(PATHS.card_profile_parquet)
    home = (tx.groupby(["card_id", "region"]).size().reset_index(name="n")
              .sort_values(["card_id", "n"], ascending=[True, False])
              .drop_duplicates("card_id").set_index("card_id")["region"])
    issuer = tx.groupby("card_id")["card1"].first()
    cards = pd.DataFrame({
        "card_id": prof["card_id"], "customer_id": prof["customer_id"],
        "brand": prof["brand"].fillna(""), "card_type": prof["card_type"].fillna(""),
        "issuer_code": prof["card_id"].map(issuer).astype(str),
        "first_seen": prof["first_seen"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        "last_seen": prof["last_seen"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        "n_txns": prof["n_txns"], "amt_mean": prof["amt_mean"].round(2),
        "amt_median": prof["amt_median"].round(2), "amt_std": prof["amt_std"].round(2),
        "amt_p95": prof["amt_p95"].round(2), "online_share": prof["online_share"].round(4),
        "home_region": prof["card_id"].map(home).fillna(""),
    })
    cards.to_csv(OUT / "cards.csv", index=False)
    log(f"cards.csv         {len(cards):,}")

    # --------------------------------------------------------- customers --
    cust = tx.groupby("customer_id").agg(
        n_cards=("card_id", "nunique"), first_seen=("ts", "min"), last_seen=("ts", "max"),
    ).reset_index()
    cust["home_region"] = cust["customer_id"].map(
        tx.groupby("customer_id")["region"].agg(
            lambda s: s.value_counts().index[0] if len(s.value_counts()) else ""))
    cust["first_seen"] = cust["first_seen"].dt.strftime("%Y-%m-%d %H:%M:%S")
    cust["last_seen"] = cust["last_seen"].dt.strftime("%Y-%m-%d %H:%M:%S")
    cust.to_csv(OUT / "customers.csv", index=False)
    log(f"customers.csv     {len(cust):,}")

    # ----------------------------------------------------------- devices --
    dev = tx[tx["device_profile"] != ""]
    devices = dev.groupby("device_profile").agg(
        device_info=("device_info", "first"), os=("os", "first"),
        browser=("browser", "first"), screen=("screen", "first"),
        device_type=("device_type", "first"), n_txns=("txn_id", "size"),
        n_cards=("card_id", "nunique"), n_customers=("customer_id", "nunique"),
        first_seen=("ts", "min"), last_seen=("ts", "max"),
    ).reset_index()
    devices["first_seen"] = devices["first_seen"].dt.strftime("%Y-%m-%d %H:%M:%S")
    devices["last_seen"] = devices["last_seen"].dt.strftime("%Y-%m-%d %H:%M:%S")
    devices.to_csv(OUT / "devices.csv", index=False)
    log(f"devices.csv       {len(devices):,}")

    # ----------------------------------------------------------- regions --
    reg = tx[tx["region"] != ""].groupby("region").agg(
        country=("country", "first"), n_txns=("txn_id", "size"), n_cards=("card_id", "nunique"),
    ).reset_index()
    reg.to_csv(OUT / "regions.csv", index=False)

    dom = pd.unique(pd.concat([tx["email_p"], tx["email_r"]]).dropna())
    dom = [d for d in dom if d]
    pd.DataFrame({"domain": dom, "is_free": [d in FREE_DOMAINS for d in dom]}).to_csv(
        OUT / "email_domains.csv", index=False)
    log(f"regions.csv {len(reg):,}   email_domains.csv {len(dom):,}")

    # ---------------------------------------------------------- NEXT_TXN --
    s = tx.sort_values(["card_id", "ts"])[["card_id", "txn_id", "ts"]]
    nxt = s.assign(to_txn=s.groupby("card_id")["txn_id"].shift(-1),
                   to_ts=s.groupby("card_id")["ts"].shift(-1))
    nxt = nxt.dropna(subset=["to_txn"])
    nxt["gap_hours"] = ((nxt["to_ts"] - nxt["ts"]).dt.total_seconds() / 3600).round(4)
    nxt.rename(columns={"txn_id": "from_txn"})[["from_txn", "to_txn", "gap_hours"]].to_csv(
        OUT / "next_txn.csv", index=False)
    log(f"next_txn.csv      {len(nxt):,}")

    # ------------------------------------------------------ closed cases --
    cc = pd.read_parquet(PATHS.closed_cases_parquet)
    vectors = np.load(PATHS.memory_index_npz)["vectors"]
    meta = pd.read_parquet(PATHS.memory_meta_parquet)
    vec_by_case = dict(zip(meta["case_id"].astype(str), (vec_str(v) for v in vectors)))

    ccout = pd.DataFrame({
        "case_id": cc["case_id"], "customer_id": cc["customer_id"], "card_id": cc["card_id"],
        "opened_at": cc["opened_at"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        "closed_at": cc["closed_at"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        "outcome": cc["outcome"], "pattern": cc["pattern"], "n_txns": cc["n_txns"],
        "exposure_usd": cc["exposure_usd"], "actions_taken": cc["actions_taken"].fillna(""),
        "report_filed": cc["report_filed"].fillna(""),
        "analyst_notes": cc["analyst_notes"].fillna("").str.replace("\n", " ", regex=False),
        "narrative_emb": cc["case_id"].map(vec_by_case).fillna(""),
    })
    ccout.to_csv(OUT / "closed_cases.csv", index=False)

    pairs = [(r.case_id, str(t)) for r in cc.itertuples() for t in r.txn_id_list]
    pd.DataFrame(pairs, columns=["case_id", "txn_id"]).to_csv(
        OUT / "closed_case_txns.csv", index=False)
    conn = [(r.case_id, c) for r in cc.itertuples() for c in r.connected_card_list]
    pd.DataFrame(conn, columns=["case_id", "card_id"]).to_csv(
        OUT / "closed_case_connected.csv", index=False)

    by_txn = tx.set_index("txn_id")["device_profile"]
    devpairs = set()
    for r in cc.itertuples():
        for t in r.txn_id_list:
            d = by_txn.get(str(t), "")
            if d:
                devpairs.add((r.case_id, d))
    pd.DataFrame(sorted(devpairs), columns=["case_id", "device_profile"]).to_csv(
        OUT / "closed_case_devices.csv", index=False)
    log(f"closed_cases.csv  {len(ccout):,}  (+{len(pairs):,} txn links, "
        f"{len(conn):,} connected, {len(devpairs):,} device links)")

    # ----------------------------------------------- policy and patterns --
    docs = [json.loads(l) for l in
            (PATHS.policy / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    dvec = np.load(PATHS.doc_index_npz)["vectors"]
    dmeta = pd.read_parquet(PATHS.doc_meta_parquet)
    dmap = {d: vec_str(v) for d, v in zip(dmeta["doc_id"].astype(str), dvec)}
    pd.DataFrame([{
        "doc_id": d["doc_id"], "kind": d["kind"], "section": d["section"],
        "title": d["title"], "text": d["text"].replace("\n", " "),
        "url": d.get("url", ""), "issuer": d.get("issuer", ""),
        "text_emb": dmap.get(d["doc_id"], ""),
    } for d in docs]).to_csv(OUT / "policy_docs.csv", index=False)

    # Pattern vertices carry the *measured* precision of each typology, so the
    # graph itself records how often a match turned out to be fraud.
    counts = cc[cc["outcome"] == "confirmed_fraud"]["pattern"].value_counts()
    total_fraud = int(counts.sum()) or 1
    rows = []
    from fraudagent.memory.embeddings import Embedder
    emb = Embedder.load(PATHS.staged / "embedder.pkl")
    for pid, (name, desc) in DOCUMENTED.items():
        n = int(counts.get(pid, 0))
        rows.append({"pattern_id": pid, "name": name, "description": desc,
                     "source": "DOCUMENTED", "base_rate": round(n / total_fraud, 5),
                     "historical_precision": round((n + 1) / (n + 2), 4), "n_observed": n})
    for key, sub in SUB_TYPOLOGIES.items():
        rows.append({"pattern_id": key, "name": sub.name, "description": sub.description,
                     "source": "DISCOVERED",
                     "base_rate": round(len(sub.seed_cases) / total_fraud, 5),
                     "historical_precision": round(
                         (len(sub.seed_cases) + 1) / (len(sub.seed_cases) + 2), 4),
                     "n_observed": len(sub.seed_cases)})
    pdf = pd.DataFrame(rows)
    pdf["desc_emb"] = [vec_str(v) for v in emb.encode(list(pdf["description"]))]
    pdf.to_csv(OUT / "patterns.csv", index=False)
    log(f"policy_docs.csv {len(docs)}   patterns.csv {len(pdf)} "
        f"({int((pdf['source'] == 'DISCOVERED').sum())} discovered)")

    pd.DataFrame([
        {"analyst_id": "ANALYST-01", "role": "L1", "approval_ceiling": 2500.0},
        {"analyst_id": "MANAGER-01", "role": "L2", "approval_ceiling": 1_000_000.0},
        {"analyst_id": "COMPLIANCE-01", "role": "COMPLIANCE", "approval_ceiling": 0.0},
    ]).to_csv(OUT / "analysts.csv", index=False)

    # ------------------------------------------------ behaviour vectors ---
    beh = pd.read_parquet(PATHS.behaviour_parquet)
    beh["behaviour_emb"] = [vec_str(v) for v in beh["behaviour_emb"]]
    beh.to_csv(OUT / "behaviour_emb.csv", index=False)
    log(f"behaviour_emb.csv {len(beh):,}")
    log(f"staged to {OUT}")


if __name__ == "__main__":
    main()

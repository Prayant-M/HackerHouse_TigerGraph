"""Someone else's schema (challenge C13): work out the mapping yourself.

Given a CSV whose columns are renamed and reshaped, propose a mapping onto the
canonical schema the agent reads, with the sample records that justify each
choice. Matching uses three independent kinds of evidence per column pair, so
a renamed column is found even when its name says nothing:

  name     token similarity after splitting camelCase / snake_case and expanding
           common abbreviations (txn, amt, cust, ts ...)
  type     numeric vs categorical vs timestamp vs id-shaped
  values   overlap of distinct values (ids, categories) or of quantiles
           (amounts, scores), and recognisable shapes (C01234-K1, epochs)

It also detects reshapes: an amount in cents (scale 100), a timestamp split
into date + time columns or given as epoch seconds, a card id split into
customer + suffix. Each mapping entry carries its score, its reasons and the
sample values from both sides.

    python ingest/schema_mapper.py --variant path/to/variant.csv [--reference Datasets/transactions.csv]
    python ingest/schema_mapper.py --rehearse      # build a renamed + reshaped variant of our own data and map it
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ABBREV = {"txn": "transaction", "tx": "transaction", "trx": "transaction", "amt": "amount",
          "cust": "customer", "ts": "timestamp", "dt": "date", "tm": "time", "id": "id",
          "acct": "account", "dev": "device", "addr": "address", "prob": "probability",
          "score": "score", "rs": "risk score", "chan": "channel", "prod": "product",
          "cd": "code", "num": "number", "no": "number", "email": "email", "mail": "email"}
SYNONYMS = {"timestamp": {"time", "date", "datetime", "when", "ts", "created", "event"},
            "amount": {"value", "sum", "total", "price", "usd", "money"},
            "customer": {"client", "holder", "account", "user", "party"},
            "transaction": {"payment", "purchase", "event", "txn"},
            "risk": {"fraud", "model", "score", "alert"},
            "device": {"browser", "handset", "agent", "fingerprint"},
            "address": {"region", "zip", "postal", "billing"}}


def tokens(name: str) -> set[str]:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name))
    out = set()
    for t in re.split(r"[^A-Za-z0-9]+", s.lower()):
        if not t:
            continue
        t = ABBREV.get(t, t)
        out.update(t.split())
    for k, syn in SYNONYMS.items():
        if out & syn:
            out.add(k)
    return out


def kind(s: pd.Series) -> str:
    v = s.dropna()
    if v.empty:
        return "empty"
    if pd.api.types.is_numeric_dtype(v):
        if v.between(9e8, 2e9).mean() > 0.9:
            return "epoch"
        return "numeric"
    sv = v.astype(str)
    if sv.str.match(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$").mean() > 0.9:
        return "timestamp" if sv.str.len().median() > 10 else "date"
    if sv.str.match(r"^\d{2}:\d{2}(:\d{2})?$").mean() > 0.9:
        return "time"
    if sv.str.match(r"^C\d{5}(-K\d)?$").mean() > 0.9:
        return "card_or_customer_id"
    return "categorical"


def value_score(a: pd.Series, b: pd.Series, ka: str) -> tuple[float, str, float]:
    """(similarity, reason, scale) — scale is the multiplier a -> b if numeric."""
    a, b = a.dropna(), b.dropna()
    if a.empty or b.empty:
        return 0.0, "no values", 1.0
    if ka in {"numeric", "epoch"} and pd.api.types.is_numeric_dtype(b):
        qa = np.quantile(a.astype(float), [0.1, 0.5, 0.9])
        qb = np.quantile(b.astype(float), [0.1, 0.5, 0.9])
        best, best_scale = 0.0, 1.0
        for scale in (1.0, 0.01, 100.0, 0.001, 1000.0):
            qa2 = qa * scale
            rel = np.abs(qa2 - qb) / (np.abs(qb) + 1e-9)
            sim = float(np.clip(1 - rel.mean(), 0, 1))
            if sim > best:
                best, best_scale = sim, scale
        return best, f"quantiles match at scale x{best_scale:g}", best_scale
    sa, sb = set(a.astype(str).head(5000)), set(b.astype(str).head(5000))
    j = len(sa & sb) / max(1, min(len(sa), len(sb)))
    return float(j), f"{len(sa & sb)} shared distinct values", 1.0


def propose_mapping(variant: pd.DataFrame, reference: pd.DataFrame) -> dict:
    """Greedy assignment of variant columns onto reference columns."""
    scored = []
    kinds_r = {c: kind(reference[c]) for c in reference.columns}
    for vc in variant.columns:
        kv = kind(variant[vc])
        for rc in reference.columns:
            tn = tokens(vc) & tokens(rc)
            name = len(tn) / max(1, len(tokens(rc)))
            kr = kinds_r[rc]
            type_ok = kv == kr or {kv, kr} <= {"numeric", "epoch"} or \
                {kv, kr} <= {"timestamp", "date", "epoch"}
            vs, why, scale = value_score(variant[vc], reference[rc], kv) if type_ok else (
                0.0, "type mismatch", 1.0)
            score = 0.35 * name + 0.15 * float(type_ok) + 0.5 * vs
            if score > 0.25:
                scored.append((score, vc, rc, name, kv, kr, vs, why, scale))
    scored.sort(reverse=True)
    used_v, used_r, mapping = set(), set(), []
    for score, vc, rc, name, kv, kr, vs, why, scale in scored:
        if vc in used_v or rc in used_r:
            continue
        used_v.add(vc)
        used_r.add(rc)
        mapping.append({"from": vc, "to": rc, "score": round(score, 3),
                        "evidence": {"name_overlap": round(name, 2), "types": [kv, kr],
                                     "values": why, "value_similarity": round(vs, 3)},
                        "transform": (f"multiply by {scale:g}" if scale != 1.0 else
                                      "epoch seconds -> timestamp" if kv == "epoch"
                                      and kr in {"timestamp", "date"} else "identity"),
                        "samples": {"variant": variant[vc].dropna().astype(str).head(3).tolist(),
                                    "reference": reference[rc].dropna().astype(str).head(3)
                                    .tolist()}})
    unmapped = [c for c in variant.columns if c not in used_v]
    reshapes = detect_reshapes(variant, mapping)
    return {"mapping": mapping, "unmapped_variant_columns": unmapped, "reshapes": reshapes}


def detect_reshapes(variant: pd.DataFrame, mapping: list[dict]) -> list[dict]:
    out = []
    kinds = {c: kind(variant[c]) for c in variant.columns}
    dates = [c for c, k in kinds.items() if k == "date"]
    times = [c for c, k in kinds.items() if k == "time"]
    if dates and times:
        out.append({"reshape": "timestamp split", "columns": [dates[0], times[0]],
                    "transform": f"ts = {dates[0]} + ' ' + {times[0]}"})
    for c, k in kinds.items():
        if k == "card_or_customer_id" and variant[c].astype(str).str.contains("-K").mean() < 0.1:
            suf = [x for x in variant.columns if re.search(r"(suffix|seq|k_?index|card_?no)",
                                                           x, re.I)]
            if suf:
                out.append({"reshape": "card id split", "columns": [c, suf[0]],
                            "transform": f"card_id = {c} + '-K' + {suf[0]}"})
    return out


def rehearse(n: int = 20000) -> dict:
    """Build a renamed and reshaped variant from our own data, map it, and score
    the mapping against the truth we know."""
    from fraudagent.config import PATHS

    ref = pd.read_csv(PATHS.transactions_csv, nrows=n, usecols=[
        "TransactionID", "customer_id", "ts", "TransactionAmt", "ProductCD", "channel",
        "risk_score", "addr1", "P_emaildomain", "R_emaildomain", "card4", "card6"],
        low_memory=False)
    v = pd.DataFrame({
        "paymentRef": ref["TransactionID"], "clientNo": ref["customer_id"],
        "eventDate": ref["ts"].astype(str).str[:10], "eventTime": ref["ts"].astype(str).str[11:19],
        "valueCents": (ref["TransactionAmt"] * 100).round(0), "prodCode": ref["ProductCD"],
        "chan": ref["channel"], "modelAlertScore": ref["risk_score"],
        "billingZip": ref["addr1"], "buyerMailDomain": ref["P_emaildomain"],
        "payeeMailDomain": ref["R_emaildomain"], "network": ref["card4"],
        "fundingType": ref["card6"]})
    truth = {"paymentRef": "TransactionID", "clientNo": "customer_id", "valueCents":
             "TransactionAmt", "prodCode": "ProductCD", "chan": "channel",
             "modelAlertScore": "risk_score", "billingZip": "addr1",
             "buyerMailDomain": "P_emaildomain", "payeeMailDomain": "R_emaildomain",
             "network": "card4", "fundingType": "card6"}
    m = propose_mapping(v, ref.drop(columns=["ts"]))
    got = {x["from"]: x["to"] for x in m["mapping"]}
    correct = sum(1 for k, t in truth.items() if got.get(k) == t)
    m["rehearsal"] = {"columns": len(truth), "correct": correct,
                      "wrong": {k: got.get(k) for k, t in truth.items() if got.get(k) != t},
                      "timestamp_split_detected": any(r["reshape"] == "timestamp split"
                                                      for r in m["reshapes"]),
                      "cents_detected": any(x["from"] == "valueCents" and "0.01" in x["transform"]
                                            for x in m["mapping"])}
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="")
    ap.add_argument("--reference", default="")
    ap.add_argument("--rehearse", action="store_true")
    args = ap.parse_args()
    from fraudagent.config import PATHS

    if args.rehearse:
        m = rehearse()
    else:
        ref = pd.read_csv(args.reference or PATHS.transactions_csv, nrows=20000, low_memory=False)
        var = pd.read_csv(args.variant, nrows=20000, low_memory=False)
        m = propose_mapping(var, ref)
    out = PATHS.eval_out / ("schema_mapping_rehearsal.json" if args.rehearse
                            else "schema_mapping.json")
    out.write_text(json.dumps(m, indent=2, default=str), encoding="utf-8")
    for x in m["mapping"]:
        print(f"{x['from']:<18} -> {x['to']:<16} score {x['score']:.2f}  {x['transform']:<22} "
              f"{x['evidence']['values']}")
    print("reshapes:", m["reshapes"])
    if "rehearsal" in m:
        print("rehearsal:", m["rehearsal"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build a judge-style variant dataset from our own data, for the end-to-end
BYO rehearsal: a subset of customers, every column renamed, amounts in cents,
timestamps split into date + time, numbered families renamed, and the closed
cases and case pack reshaped too. Never used to decide anything; it is a test
input for ingest/byo.py.

    python eval/make_variant.py --cases HHF-009,HHF-012,HHF-017 --extra 400 --out build/variant
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fraudagent.config import PATHS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="HHF-009,HHF-012,HHF-017")
    ap.add_argument("--extra", type=int, default=400)
    ap.add_argument("--out", default="build/variant")
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    pack = pd.read_csv(PATHS.case_pack_csv)
    pack = pack[pack["case_id"].isin(a.cases.split(","))]
    custs = set(pack["customer_id"])
    rng = np.random.default_rng(7)
    tx = pd.concat([pd.read_csv(f, low_memory=False) for f in PATHS.transaction_files()])
    allc = sorted(set(tx["customer_id"]) - custs)
    custs |= set(rng.choice(allc, size=a.extra, replace=False))
    tx = tx[tx["customer_id"].isin(custs)].copy()
    ident = pd.concat([pd.read_csv(f, low_memory=False) for f in PATHS.identity_files()])
    ident = ident[ident["TransactionID"].isin(tx["TransactionID"])]
    ren = {"TransactionID": "paymentRef", "TransactionAmt": "valueCents", "customer_id": "clientNo",
           "ProductCD": "prodCode", "channel": "chan", "risk_score": "modelAlertScore",
           "addr1": "billingZip", "addr2": "billingCountry", "P_emaildomain": "buyerMailDomain",
           "R_emaildomain": "payeeMailDomain", "dist1": "distanceA", "dist2": "distanceB",
           "card1": "card_issuer", "card2": "card_bin2", "card3": "card_bin3", "card4": "network",
           "card5": "card_bin5", "card6": "fundingType", "TransactionDT": "secondsSinceStart"}
    ren.update({f"V{i}": f"vesta_{i:03d}" for i in range(1, 340)})
    ren.update({f"C{i}": f"cnt_{i:02d}" for i in range(1, 15)})
    ren.update({f"D{i}": f"delta_{i:02d}" for i in range(1, 16)})
    ren.update({f"M{i}": f"match_{i}" for i in range(1, 10)})
    tx["valueCents"] = (tx.pop("TransactionAmt") * 100).round(0)
    ts = pd.to_datetime(tx.pop("ts"))
    tx["eventDate"], tx["eventTime"] = ts.dt.strftime("%Y-%m-%d"), ts.dt.strftime("%H:%M:%S")
    tx = tx.rename(columns=ren)
    tx.sample(frac=1, random_state=1).to_csv(out / "payments_export.csv", index=False)
    iren = {"TransactionID": "paymentRef", "DeviceInfo": "deviceModel", "DeviceType": "deviceClass"}
    iren.update({f"id_{i:02d}": f"ident_{i}" for i in range(1, 39)})
    ident.rename(columns=iren).to_csv(out / "device_sessions.csv", index=False)
    cc = pd.read_csv(PATHS.closed_cases_csv)
    cc = cc[cc["customer_id"].isin(custs)].rename(columns={
        "case_id": "caseRef", "customer_id": "clientNo", "card_id": "cardRef",
        "opened_at": "openedTime", "closed_at": "closedTime", "outcome": "result",
        "pattern": "typology", "first_fraud_txn_id": "firstBadPayment", "txn_ids": "payments",
        "n_txns": "paymentCount", "exposure_usd": "lossAmount", "connected_card_ids": "linkedCards",
        "actions_taken": "actions", "report_filed": "sarFiled", "analyst_notes": "notes"})
    cc.to_csv(out / "investigations.csv", index=False)
    pack.rename(columns={"case_id": "caseRef", "opened_at": "openedTime",
                         "trigger_type": "trigger_type", "trigger_text": "message",
                         "flagged_txn_id": "flaggedPayment", "card_id": "cardRef",
                         "customer_id": "clientNo", "risk_score": "alertScore"}).to_csv(
        out / "alerts_to_review.csv", index=False)
    print(f"variant: {len(tx):,} txns, {len(ident):,} identity, {len(cc)} closed cases, "
          f"{len(pack)} cases, {len(custs)} customers -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build a judge-style variant dataset from our own data, for the end-to-end
BYO rehearsal: a subset of customers, every column renamed, amounts in cents,
timestamps split into date + time, numbered families renamed, and the closed
cases and case pack reshaped too. Never used to decide anything; it is a test
input for ingest/byo.py.

    python eval/make_variant.py --cases HHF-009,HHF-012,HHF-017 --extra 400 --out build/variant
    python eval/make_variant.py --style b --cases all --out build/variant_b

Style b is a second, differently-shaped bank: other names, epoch-second
timestamps instead of date + time, amounts kept in dollars, and no file names
that hint at their role.
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
    ap.add_argument("--style", default="a", choices=["a", "b", "control"])
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    pack = pd.read_csv(PATHS.case_pack_csv)
    if a.cases != "all":
        pack = pack[pack["case_id"].isin(a.cases.split(","))]
    custs = set(pack["customer_id"])
    rng = np.random.default_rng(7)
    tx = pd.concat([pd.read_csv(f, low_memory=False) for f in PATHS.transaction_files()])
    allc = sorted(set(tx["customer_id"]) - custs)
    custs |= set(rng.choice(allc, size=a.extra, replace=False))
    tx = tx[tx["customer_id"].isin(custs)].copy()
    ident = pd.concat([pd.read_csv(f, low_memory=False) for f in PATHS.identity_files()])
    ident = ident[ident["TransactionID"].isin(tx["TransactionID"])]
    if a.style == "b":
        return style_b(out, pack, custs, tx, ident)
    if a.style == "control":
        return style_control(out, pack, custs, tx, ident)
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


def style_control(out: Path, pack: pd.DataFrame, custs: set, tx: pd.DataFrame,
                  ident: pd.DataFrame) -> int:
    """The same customer subset as a variant, with the original column names
    and shapes. Running it through byo.py separates what the mapping changes
    from what the smaller dataset changes."""
    tx.to_csv(out / "transactions.csv", index=False)
    ident.to_csv(out / "identity.csv", index=False)
    cc = pd.read_csv(PATHS.closed_cases_csv)
    cc[cc["customer_id"].isin(custs)].to_csv(out / "closed_cases_history.csv", index=False)
    pack.to_csv(out / "case_pack.csv", index=False)
    print(f"control: {len(tx):,} txns, {len(pack)} cases, {len(custs)} customers -> {out}")
    return 0


def style_b(out: Path, pack: pd.DataFrame, custs: set, tx: pd.DataFrame,
            ident: pd.DataFrame) -> int:
    ren = {"TransactionID": "txn_ref", "TransactionAmt": "amt_usd", "customer_id": "party_no",
           "ProductCD": "prd", "channel": "pay_channel", "risk_score": "score_rt",
           "addr1": "bill_area", "addr2": "bill_ctry", "P_emaildomain": "mail_from",
           "R_emaildomain": "mail_to", "dist1": "geo_d1", "dist2": "geo_d2",
           "card1": "pan_a", "card2": "pan_b", "card3": "pan_c", "card4": "scheme",
           "card5": "pan_e", "card6": "pan_kind", "TransactionDT": "dt_offset"}
    ren.update({f"V{i}": f"x{i}" for i in range(1, 340)})
    ren.update({f"C{i}": f"k{i}" for i in range(1, 15)})
    ren.update({f"D{i}": f"t{i}" for i in range(1, 16)})
    ren.update({f"M{i}": f"flag{i}" for i in range(1, 10)})
    tx["posted_epoch"] = ((pd.to_datetime(tx.pop("ts")) - pd.Timestamp("1970-01-01"))
                          // pd.Timedelta(seconds=1)).astype("int64")
    tx = tx.rename(columns=ren)
    cols = list(tx.columns)
    np.random.default_rng(3).shuffle(cols)
    tx[cols].sample(frac=1, random_state=2).to_csv(out / "extract_01.csv", index=False)
    iren = {"TransactionID": "txn_ref", "DeviceInfo": "hw_string", "DeviceType": "hw_kind"}
    iren.update({f"id_{i:02d}": f"sig{i}" for i in range(1, 39)})
    ident.rename(columns=iren).to_csv(out / "extract_02.csv", index=False)
    cc = pd.read_csv(PATHS.closed_cases_csv)
    cc = cc[cc["customer_id"].isin(custs)].rename(columns={
        "case_id": "inv_no", "customer_id": "party_no", "card_id": "card_ref",
        "opened_at": "opened", "closed_at": "closed", "outcome": "disposition",
        "pattern": "scheme_type", "first_fraud_txn_id": "first_txn", "txn_ids": "txn_list",
        "n_txns": "txn_n", "exposure_usd": "loss_usd", "connected_card_ids": "related_cards",
        "actions_taken": "steps_taken", "report_filed": "sar", "analyst_notes": "remarks"})
    cc.to_csv(out / "extract_03.csv", index=False)
    pack.rename(columns={"case_id": "alert_no", "opened_at": "raised", "trigger_type": "source",
                         "trigger_text": "body", "flagged_txn_id": "txn_ref",
                         "card_id": "card_ref", "customer_id": "party_no",
                         "risk_score": "score_rt"}).to_csv(out / "extract_04.csv", index=False)
    print(f"variant b: {len(tx):,} txns, {len(ident):,} identity, {len(cc)} closed cases, "
          f"{len(pack)} cases, {len(custs)} customers -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

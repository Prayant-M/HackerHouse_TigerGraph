"""Stage 0 — the schema-drift gate (challenge C12) and the data manifest.

Before anything new is loaded, compare it with what is already loaded:

* columns added / removed / renamed (a renamed column is proposed when a new
  column's values match a missing old column's profile — see ingest/schema_mapper.py);
* dtype changes, null-rate shifts, value-domain changes (categorical levels
  appearing or disappearing, numeric ranges moving);
* key overlaps: transaction ids that collide with already-loaded ones, closed
  cases that replace earlier rows, case ids that already exist as agent cases;
* what each change *breaks* downstream, named concretely (which query, which
  signal, which calibration).

It then writes a proposal with sample records and **waits for approval**. The
load proceeds only with a fraud-manager approval token; the approval is signed
into the approval ledger and written to the graph as a SchemaChange vertex.

    python ingest/00_drift.py --old Datasets/transactions.csv --new Datasets/transactions_2017q1.csv
    python ingest/00_drift.py --auto                       # every known old/new pair present
    python ingest/00_drift.py --auto --approve --token $L2  # approve the pending proposal
    python ingest/00_drift.py --manifest                   # (re)hash raw files -> data/manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ingest"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from fraudagent.config import PATHS  # noqa: E402

OUT = ROOT / "data" / "drift"
PAIRS = [("transactions.csv", "transactions_2017q1.csv", "TransactionID"),
         ("identity.csv", "identity_2017q1.csv", "TransactionID"),
         ("closed_cases_history.csv", "closed_cases_history.csv", "case_id"),
         ("case_pack.csv", "case_pack_final.csv", "case_id")]
BREAKS = {
    "TransactionID": "every txn lookup, case_write links, attestation ids",
    "customer_id": "card-id recovery (card_key) and OWNS edges",
    "ts": "every as_of-bounded query; the temporal wall",
    "risk_score": "the trigger prior and the January neutralisation",
    "amount": "exposure, baselines, structuring and card-testing matchers",
    "card1": "card-id recovery", "card2": "card-id recovery", "card3": "card-id recovery",
    "card4": "card-id recovery", "card5": "card-id recovery", "card6": "card-id recovery",
    "addr1": "region signals and BILLED_IN edges", "P_emaildomain": "email_mismatch",
    "R_emaildomain": "recipient fan-in detector", "DeviceInfo": "device profile key",
    "id_15": "device_new_on_account", "id_23": "anonymising_proxy, device_proxy_hub",
    "outcome": "calibration, precedent, conformal labels",
    "txn_ids": "closed-case links (CC_INVOLVES) and fraud_proximity",
    "trigger_type": "the trigger-conditioned prior", "flagged_txn_id": "the investigation seed",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest() -> dict:
    files = sorted({p for p in PATHS.raw.rglob("*.csv")}, key=lambda p: str(p))
    man = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "files": {str(p.relative_to(PATHS.repo)).replace("\\", "/"):
                     {"sha256": sha256(p), "bytes": p.stat().st_size} for p in files}}
    out = PATHS.repo / "data" / "manifest.json"
    out.write_text(json.dumps(man, indent=2), encoding="utf-8")
    print(f"[drift] manifest: {len(files)} files hashed -> {out.relative_to(PATHS.repo)}")
    return man


def profile(df: pd.DataFrame) -> dict:
    prof = {}
    for c in df.columns:
        s = df[c]
        p = {"dtype": str(s.dtype), "null_rate": round(float(s.isna().mean()), 4)}
        if pd.api.types.is_numeric_dtype(s):
            q = s.dropna()
            if len(q):
                p.update(min=float(q.min()), max=float(q.max()), median=float(q.median()))
        else:
            vc = s.astype(str).value_counts()
            p.update(n_levels=int(vc.size), top=vc.head(5).index.tolist())
        prof[c] = p
    return prof


def diff(old: Path, new: Path, key: str, nrows: int | None = 200_000) -> dict:
    a = pd.read_csv(old, nrows=nrows, low_memory=False)
    b = pd.read_csv(new, nrows=nrows, low_memory=False)
    pa, pb = profile(a), profile(b)
    added = [c for c in b.columns if c not in a.columns]
    removed = [c for c in a.columns if c not in b.columns]
    changes = []
    for c in sorted(set(a.columns) & set(b.columns)):
        x, y = pa[c], pb[c]
        notes = []
        if x["dtype"] != y["dtype"]:
            notes.append(f"dtype {x['dtype']} -> {y['dtype']}")
        if abs(x["null_rate"] - y["null_rate"]) >= 0.05:
            notes.append(f"null rate {x['null_rate']:.2f} -> {y['null_rate']:.2f}")
        if "max" in x and "max" in y and x["max"] and (y["max"] > 2 * x["max"] or
                                                       y["min"] < x["min"] - abs(x["min"])):
            notes.append(f"range [{x['min']:.2f}, {x['max']:.2f}] -> [{y['min']:.2f}, {y['max']:.2f}]")
        if "median" in x and "median" in y and abs(x["median"]) > 1e-9 and                 abs(y["median"] - x["median"]) / abs(x["median"]) > 0.25:
            notes.append(f"median {x['median']:.3f} -> {y['median']:.3f}")
        if "n_levels" in x and "n_levels" in y:
            new_levels = [v for v in y["top"] if v not in x["top"]]
            if new_levels:
                notes.append(f"new frequent values {new_levels[:3]}")
        if notes:
            changes.append({"column": c, "changes": notes,
                            "breaks": BREAKS.get(c, "no known downstream consumer")})
    overlap: list[str] = []
    n_overlap = 0
    if key in a.columns and key in b.columns:
        ids = set(a[key].astype(str)) & set(b[key].astype(str))
        n_overlap = len(ids)
        overlap = sorted(ids)[:20]
    renames = []
    if removed and added:
        from schema_mapper import propose_mapping

        m = propose_mapping(b[added].head(5000), a[removed].head(5000))
        renames = m["mapping"]
    return {"old": old.name, "new": new.name, "rows_sampled": [len(a), len(b)],
            "added": added, "removed": removed, "renames_proposed": renames,
            "changes": changes, "key": key, "key_overlap_count": n_overlap,
            "key_overlap_sample": overlap,
            "samples": {"old": a.head(3).astype(str).to_dict("records"),
                        "new": b.head(3).astype(str).to_dict("records")}}


def proposal_id(reports: list[dict]) -> str:
    return "DRIFT-" + hashlib.sha256(json.dumps(reports, sort_keys=True, default=str)
                                     .encode()).hexdigest()[:12]


def approve(pid: str, token: str) -> dict:
    from fraudagent.governance import approvals as gov

    principal = gov.authenticate(f"Bearer {token}")
    if principal.role != "fraud_manager":
        gov.refuse(principal, pid, -1, 403, "schema change needs a fraud manager")
        raise SystemExit("403: only a fraud manager may approve a schema change")
    rec = gov._append({"kind": "schema_change", "case_id": pid, "index": -1, "approved": True,
                       "actor_id": principal.actor_id, "actor_role": principal.role,
                       "at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())})
    try:                                               # pragma: no cover - network
        from fraudagent.graphstore import get_store

        store = get_store()
        if store.backend == "tigergraph":
            prop = json.loads((OUT / f"{pid}.json").read_text(encoding="utf-8"))
            store.conn.runInstalledQuery("governance_write", {
                "kind": "schema_change", "record_json": json.dumps({
                    "id": pid, "created_at": prop["created_at"].replace("T", " ")[:19],
                    "summary": prop["summary"], "mapping": json.dumps(prop["mapping"]),
                    "approved_by": principal.actor_id, "approved_at": rec["at"],
                    "signature": rec["signature"]})}, usePost=True)
    except Exception as exc:
        print(f"[drift] graph write skipped: {exc}")
    (OUT / f"{pid}.approved").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def gate_open() -> bool:
    """Loaders call this: True when no proposal is pending approval."""
    pending = [p for p in OUT.glob("DRIFT-*.json") if not p.with_suffix(".approved").exists()]
    return not pending


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="")
    ap.add_argument("--new", default="")
    ap.add_argument("--key", default="TransactionID")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--token", default=os.environ.get("APPROVAL_TOKEN", ""))
    ap.add_argument("--manifest", action="store_true")
    ap.add_argument("--nrows", type=int, default=200_000)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.manifest:
        manifest()
        return 0
    pairs = []
    if args.old and args.new:
        pairs = [(Path(args.old), Path(args.new), args.key)]
    elif args.auto:
        for o, n, k in PAIRS:
            po = PATHS.raw / o
            pn = next((b / n for b in (PATHS.round2, PATHS.round2 / "cases", PATHS.raw / "final",
                                        PATHS.raw) if (b / n).exists() and (b / n) != po), None)
            if po.exists() and pn is not None:
                pairs.append((po, pn, k))
    if not pairs:
        print("[drift] no new files to compare (January files not present in Datasets/ or "
              "Datasets/final/); nothing to gate")
        return 0
    t0 = time.time()
    reports = [diff(o, n, k, args.nrows) for o, n, k in pairs]
    pid = proposal_id(reports)
    mapping = {r["new"]: r["renames_proposed"] for r in reports}
    summary = "; ".join(f"{r['new']}: +{len(r['added'])} -{len(r['removed'])} cols, "
                        f"{len(r['changes'])} changed, {r['key_overlap_count']} key overlaps"
                        for r in reports)
    prop = {"id": pid, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "summary": summary, "mapping": mapping, "reports": reports,
            "detect_seconds": round(time.time() - t0, 1)}
    (OUT / f"{pid}.json").write_text(json.dumps(prop, indent=2, default=str), encoding="utf-8")
    md = [f"# Schema drift proposal {pid}", "", summary, ""]
    for r in reports:
        md += [f"## {r['old']} → {r['new']}", "",
               f"- added: {r['added'] or 'none'}", f"- removed: {r['removed'] or 'none'}",
               f"- renames proposed: {r['renames_proposed'] or 'none'}",
               f"- key overlap on `{r['key']}`: {r['key_overlap_count']}", ""]
        for c in r["changes"]:
            md.append(f"- `{c['column']}`: {'; '.join(c['changes'])} — breaks: {c['breaks']}")
        md.append("")
    (PATHS.eval_out / "drift.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    if args.approve:
        if not args.token:
            raise SystemExit("--approve needs --token (a fraud-manager approval token)")
        rec = approve(pid, args.token)
        print(f"[drift] {pid} approved by {rec['actor_id']} ({rec['actor_role']}); "
              f"ledger seq {rec['seq']}")
        manifest()
    else:
        print(f"[drift] proposal {pid} is waiting for approval; loaders will not run until "
              f"`python ingest/00_drift.py --auto --approve --token <fraud-manager token>`")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

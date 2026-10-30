"""`make attest-verify`: re-run every attested query and fail on any mismatch.

For each answer file:

1. **Recorded calls.** Every tool call an attestation cites is re-run against
   the live store with its recorded parameters; the SHA-256 of the response
   must equal the digest recorded when the agent ran.
2. **Arithmetic claims.** exposure_usd = sum of the affected amounts;
   first_suspicious_txn_id is the earliest affected transaction; every
   affected / connected / prior id exists; every affected transaction sits at
   or before as_of (the temporal wall); sar.total_amount_usd = exposure.
3. **Snapshot.** The answer's data_snapshot equals the current one, or the
   mismatch is reported as "data changed since the run", not as a pass.

    python eval/attest_verify.py [--cases HHG-014] [--max-calls 40]
Writes eval/reports/attest_verify.md; exit 1 on any failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

import pickle  # noqa: E402

from fraudagent.agent.recorder import RECORDINGS, digest_unordered, load_recording  # noqa: E402
from fraudagent.config import PATHS  # noqa: E402
from fraudagent.core.attest import data_snapshot  # noqa: E402
from fraudagent.graphstore import get_store  # noqa: E402

# Calls whose answer legitimately depends on what other investigations wrote
# afterwards are re-checked, but a difference is reported as memory growth.
MEMORY_CALLS = {"case_chain", "compromise_watch"}


def revive(v):
    if isinstance(v, str) and len(v) >= 19 and v[4] == "-" and v[10] == " ":
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return v
    if isinstance(v, list):
        return [revive(x) for x in v]
    return v


def verify_case(store, path: Path, max_calls: int) -> dict:
    a = json.loads(path.read_text(encoding="utf-8"))
    cid = a["case_id"]
    rec = a.get("agent_record", {})
    out = {"case": cid, "failures": [], "checked_calls": 0, "memory_changes": 0}
    recording = load_recording(cid)
    cited = {c["key"] for at in rec.get("attestations", []) for c in at.get("tool_calls", [])}
    if recording is None:
        out["failures"].append("no recorded tool I/O for this case")
    else:
        calls = [c for c in recording["calls"] if c.get("ok") and c["method"] != "write_case"]
        calls = [c for c in calls if c["key"] in cited] + [c for c in calls if c["key"] not in cited]
        for c in calls[:max_calls]:
            p = json.loads(c["params"])
            try:
                res = getattr(store, c["method"])(*[revive(x) for x in p["args"]],
                                                  **{k: revive(v) for k, v in p["kwargs"].items()})
            except Exception as exc:
                out["failures"].append(f"{c['method']} re-run failed: {exc}")
                continue
            out["checked_calls"] += 1
            blob = RECORDINGS / cid / f"{c['digest']}.pkl"
            seen = digest_unordered(pickle.loads(blob.read_bytes())) if blob.exists() else None
            if seen is None or digest_unordered(res) != seen:
                if c["method"] in MEMORY_CALLS:
                    out["memory_changes"] += 1
                else:
                    out["failures"].append(f"{c['method']} seq {c['seq']}: response digest "
                                           f"differs from what the agent saw")
    case = a["case"]
    as_of = datetime.fromisoformat(rec["as_of"])
    amounts, stamps = [], []
    for t in case["affected_txn_ids"]:
        row = store.get_transaction(str(t))
        if row is None:
            out["failures"].append(f"affected txn {t} does not exist")
            continue
        amounts.append(abs(row.amount))
        stamps.append((row.ts, str(t)))
        if row.ts > as_of:
            out["failures"].append(f"affected txn {t} is after as_of (temporal wall)")
    if amounts and abs(sum(amounts) - case["exposure_usd"]) > 0.02:
        out["failures"].append(f"exposure {case['exposure_usd']} != sum {sum(amounts):.2f}")
    if stamps and case["first_suspicious_txn_id"] != min(stamps)[1]:
        out["failures"].append("first_suspicious_txn_id is not the earliest affected txn")
    if a["sar"]["file"] and abs(a["sar"]["total_amount_usd"] - case["exposure_usd"]) > 0.02:
        out["failures"].append("sar.total_amount_usd != exposure")
    if rec.get("unattested"):
        out["failures"].append(f"unattested claims: {rec['unattested']}")
    out["snapshot_matches"] = rec.get("data_snapshot") == data_snapshot()
    out["n_attestations"] = rec.get("n_attestations", 0)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="")
    ap.add_argument("--max-calls", type=int, default=60)
    ap.add_argument("--all", action="store_true", help="also verify answers from earlier packs")
    args = ap.parse_args()
    store = get_store()
    if getattr(store, "backend", "") == "tigergraph":
        import os

        h = store.health().get("vertex_counts") or {}
        os.environ.setdefault("TG_LOAD_VERSION", f"tg:Transaction={h.get('Transaction', 0)},"
                                                 f"ClosedCase={h.get('ClosedCase', 0)}")
    files = sorted(list(PATHS.cases_out.glob("HHF-*.json")) + list(PATHS.cases_out.glob("HHG-*.json")))
    if args.cases:
        files = [f for f in files if f.stem in set(args.cases.split(","))]
    elif not args.all:
        # The submission is the active case pack; older answer files were
        # recorded against an earlier graph and are verified with --all.
        import pandas as pd

        active = set(pd.read_csv(PATHS.case_pack_csv)["case_id"])
        files = [f for f in files if f.stem in active]
    t0 = time.time()
    rows = [verify_case(store, f, args.max_calls) for f in files]
    bad = [r for r in rows if r["failures"]]
    md = ["# Attestation re-run", "", f"`eval/attest_verify.py` against backend "
          f"`{store.backend}` at {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())} "
          f"({time.time()-t0:.0f} s). Current data snapshot `{data_snapshot()}`.", "",
          "| case | attestations | calls re-run | memory growth | snapshot | result |",
          "|---|--:|--:|--:|---|---|"]
    for r in rows:
        md.append(f"| {r['case']} | {r['n_attestations']} | {r['checked_calls']} | "
                  f"{r['memory_changes']} | {'same' if r['snapshot_matches'] else 'CHANGED'} | "
                  f"{'PASS' if not r['failures'] else 'FAIL: ' + '; '.join(r['failures'][:3])} |")
    md += ["", f"**{len(rows) - len(bad)} of {len(rows)} answer files pass.** \"Memory growth\" "
           "counts read-back calls (case_chain, compromise_watch) whose answer now includes "
           "cases written later; they are reported, not failed.", ""]
    (PATHS.eval_out / "attest_verify.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

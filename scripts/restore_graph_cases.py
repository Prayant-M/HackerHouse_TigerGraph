"""Restore answered cases that are missing from TigerGraph, from their saved
answer files, through the agent's single write path (`case_write`).

The decision is not re-run: the graph document is rebuilt from the answer
file exactly as it was submitted, so a restored case says what the answer
says. Each write is read back with `case_chain`; only then is the case
counted as restored.

    python scripts/restore_graph_cases.py                # dry run: what is missing
    python scripts/restore_graph_cases.py --check HHG-014 # rebuild a case that IS in
                                                          # the graph and diff it
    python scripts/restore_graph_cases.py --write         # write the missing ones
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from fraudagent.graphstore.base import case_write_doc  # noqa: E402
from fraudagent.graphstore.tigergraph import TigerGraphStore  # noqa: E402

CASES = ROOT / "cases"
REPORT = ROOT / "eval" / "reports" / "graph_restore.md"


def payload_from_answer(d: dict) -> dict:
    """The same dict build_answer() hands to write_case, rebuilt from the file."""
    c, ar = d["case"], d.get("agent_record", {})
    trig = ar.get("trigger", {}) or {}
    executed = {a["action"] for a in d.get("executed_actions", []) if a.get("executed")}
    nba = d.get("next_best_actions") or {}

    def acts(phase: str) -> list[dict]:
        return [{**a, "executed": phase == "final" and a["action"] in executed}
                for a in nba.get(phase, [])]

    def p_fraud(post: dict) -> float:
        return round(sum(v for k, v in (post or {}).items() if k != "none"), 4)

    lifecycle = ar.get("lifecycle") or []
    top = sorted((ar.get("posterior") or {}).values(), reverse=True)
    return {
        "case_id": d["case_id"],
        "graph_case_id": c.get("graph_case_id") or f"CASE-{d['case_id']}",
        "lifecycle_state": lifecycle[-1]["to"] if lifecycle else "",
        "state_changes": lifecycle,
        "watch_children": ar.get("watch_children") or [],
        "origin": (ar.get("containment") or {}).get("write_back"),
        "proof": ar.get("proof") or {}, "gate": ar.get("gate") or {},
        "conformal": ar.get("conformal") or {},
        "data_snapshot": ar.get("data_snapshot", ""), "answer_hash": ar.get("answer_hash", ""),
        "card_id": trig.get("card_id", ""), "customer_id": trig.get("customer_id", ""),
        "trigger_type": trig.get("type", ""), "opened_at": str(trig.get("opened_at", "")),
        "as_of": str(ar.get("as_of", "")),
        "status": c["status"], "verdict": c["verdict"],
        "fraud_probability": c["fraud_probability"],
        # the ledger margin (top two hypotheses) the agent wrote as confidence
        "confidence": round(top[0] - top[1], 3) if len(top) > 1 else 0.0,
        "pattern": c["pattern"], "pattern_description": c.get("pattern_description", ""),
        "exposure_usd": c["exposure_usd"], "summary": c["summary"], "narrative": c["summary"],
        "stop_reason": d.get("stop_reason", ""),
        "ledger_head": (d.get("audit_chain") or {}).get("head", ""),
        "tool_calls": int(d.get("tool_calls", 0)), "latency_s": float(d.get("latency_s", 0.0)),
        "affected_txn_ids": c["affected_txn_ids"],
        "connected_card_ids": c["connected_card_ids"],
        "connected_device_profiles": c["connected_device_profiles"],
        "similar_prior_cases": c.get("similar_prior_cases", []),
        "cited_rules": ar.get("cited_policy_rules", []),
        "evidence": ar.get("evidence_with_impact") or [],
        "decisions": [{**x, "p_fraud_before": p_fraud(x.get("posterior_before")),
                       "p_fraud_after": p_fraud(x.get("posterior_after"))}
                      for x in ar.get("decisions", [])],
        "actions": {"initial": acts("initial"), "final": acts("final")},
        "evidence_requests": ar.get("evidence_requests_detail") or d.get("evidence_requests") or [],
        "sar": d.get("sar") or {},
    }


def graph_case_ids(store: TigerGraphStore) -> dict[str, dict]:
    return {v["v_id"]: v["attributes"] for v in store.conn.getVertices("FraudCase", limit=5000)}


def answers() -> dict[str, dict]:
    out = {}
    for p in sorted(CASES.glob("HH*-*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if "case" in d and "case_id" in d:
            out[d["case_id"]] = d
    return out


def chain_counts(store: TigerGraphStore, gid: str) -> dict:
    ch = store.case_chain(gid) or {}
    return {k: len(ch.get(k) or []) for k in ("investigation", "evidence", "decisions",
                                               "recommended_actions", "affected_transactions",
                                               "connected_cards", "suspicious_activity_report")}


def expected_counts(doc: dict) -> dict:
    return {"investigation": 1, "affected_transactions": len(doc["links"]["txn_ids"]),
            "connected_cards": len(doc["links"]["connected_card_ids"]),
            "suspicious_activity_report": 1 if doc["sar"]["file"] else 0}


def check(store: TigerGraphStore, cid: str, d: dict) -> list[str]:
    """Rebuild a case that is in the graph and compare with what is there."""
    gid = f"CASE-{cid}"
    doc = case_write_doc(gid, payload_from_answer(d))
    have = graph_case_ids(store).get(gid)
    if have is None:
        return [f"{gid} not in graph"]
    diffs = []
    for k, v in have.items():
        if k in doc and not isinstance(doc[k], (list, dict)):
            a, b = doc[k], v
            if isinstance(a, float) or isinstance(b, float):
                same = abs(float(a or 0) - float(b or 0)) < 1e-6
            else:
                same = str(a)[:19] == str(b)[:19]
            if not same:
                diffs.append(f"{k}: rebuilt {str(a)[:60]!r} vs graph {str(b)[:60]!r}")
    got, want = chain_counts(store, gid), expected_counts(doc)
    for k, n in want.items():
        if got.get(k) != n:
            diffs.append(f"read-back {k}: graph {got.get(k)} vs answer {n}")
    for k in ("evidence", "decisions", "recommended_actions"):
        n = {"evidence": len(doc["evidence"]), "decisions": len(doc["decisions"]),
             "recommended_actions": len(doc["actions"])}[k]
        if got.get(k) != n:
            diffs.append(f"read-back {k}: graph {got.get(k)} vs rebuilt {n}")
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", default="")
    args = ap.parse_args()
    store = TigerGraphStore()
    ans = answers()
    if args.check:
        diffs = check(store, args.check, ans[args.check])
        print(f"{args.check}: {'identical' if not diffs else str(len(diffs)) + ' differences'}")
        for x in diffs:
            print("  ", x)
        return 0 if not diffs else 1
    in_graph = graph_case_ids(store)
    missing = [cid for cid in ans if f"CASE-{cid}" not in in_graph]
    print(f"answers {len(ans)}; in graph {len(ans) - len(missing)}; missing {len(missing)}: "
          f"{', '.join(missing) or 'none'}")
    if not args.write or not missing:
        return 0
    rows = []
    for cid in missing:
        payload = payload_from_answer(ans[cid])
        gid = store.write_case(payload)
        doc = case_write_doc(gid, payload)
        got, want = chain_counts(store, gid), expected_counts(doc)
        ok = all(got.get(k) == n for k, n in want.items())
        rows.append((cid, gid, ok, got, want))
        print(f"{cid}: {'restored, read back' if ok else 'MISMATCH'} {got}")
    in_graph = graph_case_ids(store)
    still = [cid for cid in ans if f"CASE-{cid}" not in in_graph]
    md = ["# Graph restore", "",
          "Cases whose answer files say `written_to_graph: true` but which were missing from "
          "TigerGraph (the graph was wiped and reloaded after Round 1) were written back from "
          "their saved answer files through `case_write`, the agent's single write path. "
          "Decisions were not re-run. Each write was read back with `case_chain`. "
          "`tool_calls` is the answer file's own count (the live write recorded the store's "
          "internal call counter, which the answer file does not keep).", "",
          "| case | graph id | read back | transactions | cards | SAR |", "|---|---|---|--:|--:|--:|"]
    for cid, gid, ok, got, want in rows:
        md.append(f"| {cid} | {gid} | {'yes' if ok else 'NO'} | {got['affected_transactions']}"
                  f"/{want['affected_transactions']} | {got['connected_cards']}/"
                  f"{want['connected_cards']} | {got['suspicious_activity_report']}/"
                  f"{want['suspicious_activity_report']} |")
    md += ["", f"After restore: {len(ans) - len(still)} of {len(ans)} answered cases are in the "
           f"graph{'; still missing: ' + ', '.join(still) if still else ''}."]
    REPORT.write_text("\n".join(md) + "\n", encoding="utf-8")
    return 0 if not still and all(r[2] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Audit every answer file against the raw data and the Fraud Policy.

There is no answer key, so correctness cannot be proven here. What can be
checked is everything that is mechanically true or false:

  data      every transaction, card and prior case cited exists; nothing an
            answer relies on postdates the alert; affected transactions belong
            to the case's card or its connected cards
  §4        exposure equals the sum of the affected amounts
  §2        every approval route matches the routing table
  §3a       a case is opened when probability reaches 0.30, evidence is
            requested, or the customer disputes; a SAR is filed exactly when
            fraud meets one of the filing conditions, and FILE_REPORT agrees
  R1        no block on a single weak signal below 0.70
  R2        a customer denial that ends in fraud blocks the card and opens a case
  R3        closing on customer confirmation is only cited when a customer
            was actually asked
  R7        a disputed charge that matches the card's own recurring pattern is
            never blocked
  §6        the stop reason is one the policy allows
  graph     the case was read back from the graph after it was written

    python eval/audit_answers.py              # cases/ -> eval/reports/answer_audit.md
    python eval/audit_answers.py path/to/dir  # audit another directory
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from fraudagent.config import PATHS  # noqa: E402
from fraudagent.report.answer import validate  # noqa: E402

ROUTE = {"DECLINE_TRANSACTION": "L1", "BLOCK_ALL_CARDS": "L2", "FILE_REPORT": "L2"}
ANSWER_GLOBS = ("HHF-*.json", "HHG-*.json")


def load_packs() -> dict[str, dict]:
    """Every case pack present, keyed by case id. The final-round pack holds only
    the HHF cases, so a Round 1 answer may have no pack row on this machine."""
    frames = [pd.read_csv(f, dtype=str) for f in PATHS.case_pack_files()]
    if not frames:
        return {}
    return pd.concat(frames).drop_duplicates("case_id", keep="last").set_index(
        "case_id").to_dict("index")


def alert_for(case_id: str, packs: dict[str, dict], rec: dict) -> tuple[dict, str]:
    """The alert to audit against: the case pack when it has this case, otherwise
    the trigger saved in the answer file, and which of the two was used."""
    if case_id in packs:
        return packs[case_id], "case pack"
    t = rec["trigger"]
    return {"opened_at": t["opened_at"], "card_id": t["card_id"],
            "flagged_txn_id": t["flagged_txn_id"], "trigger_type": t["type"]}, "answer file"


def audit(case_dir: Path, graph_ids: set[str] | None = None) -> tuple[list[dict], int]:
    """graph_ids: FraudCase ids read from the live graph now. When given, the
    graph check is against the graph, not the flag the answer recorded."""
    tx = pd.read_parquet(PATHS.staged / "transactions.parquet",
                         columns=["txn_id", "ts", "amount", "card_id"])
    tx["txn_id"] = tx["txn_id"].astype(str)
    txns = tx.set_index("txn_id")
    cards = set(tx["card_id"])
    closed = pd.read_parquet(PATHS.staged / "closed_cases.parquet").set_index("case_id")
    packs = load_packs()

    rows, total = [], 0
    for path in sorted(f for pattern in ANSWER_GLOBS for f in case_dir.glob(pattern)):
        d = json.loads(path.read_text(encoding="utf-8"))
        cid, c = d["case_id"], d["case"]
        rec = d.get("agent_record", {})
        p, alert_source = alert_for(cid, packs, rec)
        issues = list(validate(d, set(txns.index), cards, set(closed.index)))
        opened = pd.Timestamp(p["opened_at"])
        aff = c["affected_txn_ids"]

        for t in aff:                                                       # data
            if t not in txns.index:
                issues.append(f"affected {t} not in dataset")
                continue
            r = txns.loc[t]
            if r["ts"] > opened:
                issues.append(f"affected {t} is after the alert")
            if r["card_id"] != p["card_id"] and r["card_id"] not in c["connected_card_ids"]:
                issues.append(f"affected {t} is on unrelated card {r['card_id']}")
        for x in c["similar_prior_cases"]:
            if x in closed.index and closed.loc[x, "opened_at"] >= opened:
                issues.append(f"prior case {x} opened after the alert")

        exposure = round(sum(abs(txns.loc[t, "amount"]) for t in aff if t in txns.index), 2)
        if abs(exposure - c["exposure_usd"]) > 0.02:                        # §4
            issues.append(f"exposure {c['exposure_usd']} != {exposure}")
        if c["verdict"] == "fraud" and aff and p["flagged_txn_id"] not in aff:
            issues.append("flagged transaction missing from affected")

        initial, final = d["next_best_actions"]["initial"], d["next_best_actions"]["final"]
        acts = [a["action"] for a in final]
        every = acts + [a["action"] for a in initial]
        for a in initial + final:                                           # §2
            want = ROUTE.get(a["action"], "auto")
            if a["action"] == "BLOCK_CARD":
                want = "L2" if c["exposure_usd"] > 2500 else "L1"
            if a["route"] != want:
                issues.append(f"{a['action']} routed {a['route']}, policy says {want}")

        pr = c["fraud_probability"]
        disputed = p["trigger_type"] == "customer_report"
        if (pr >= 0.30 or d["evidence_requests"] or disputed) and "CREATE_CASE" not in every:
            issues.append("§3a: no CREATE_CASE despite p>=0.30 / evidence request / dispute")
        sar_due = c["verdict"] == "fraud" and (c["exposure_usd"] > 1000 or c["connected_card_ids"]
                                               or c["pattern"] == "undocumented")
        if bool(sar_due) != bool(d["sar"]["file"]):
            issues.append(f"§3a: SAR file={d['sar']['file']} but the filing conditions say {bool(sar_due)}")
        if ("FILE_REPORT" in acts) != bool(d["sar"]["file"]):
            issues.append("§3a: FILE_REPORT and sar.file disagree")

        if "BLOCK_CARD" in acts and pr < 0.70 and len(rec.get("signals_fired", [])) <= 1:
            issues.append("R1: block on a single weak signal")                 # R1
        if disputed and c["verdict"] == "fraud" and not {"BLOCK_CARD", "CREATE_CASE"} <= set(acts):
            issues.append("R2: denial ending in fraud without BLOCK_CARD + CREATE_CASE")
        if any(a["action"] == "CLOSE_NO_FRAUD" and a["reason"].startswith("R3")
               for a in final) and not d["evidence_requests"]:
            issues.append("R3 cited with no customer contact")
        if disputed and "recurring_charge" in rec.get("signals_fired", []) \
                and "BLOCK_CARD" in acts:
            issues.append("R7: recurring disputed charge was blocked")

        if not (pr >= 0.85 or pr <= 0.15) and not any(                      # §6
                k in d["stop_reason"].lower() for k in ("unlikely", "settle", "verification")):
            issues.append(f"§6: stopped at p={pr} without a permitted reason")
        if not c.get("written_to_graph"):                                    # graph
            issues.append("case not confirmed written to the graph")
        elif graph_ids is not None and (c.get("graph_case_id") or f"CASE-{cid}") not in graph_ids:
            issues.append("answer says written to the graph, but the case is not in the graph now")

        total += len(issues)
        rows.append({"case": cid, "trigger": p["trigger_type"], "verdict": c["verdict"],
                     "p": pr, "pattern": c["pattern"], "exposure": c["exposure_usd"],
                     "sar": d["sar"]["file"], "final": " → ".join(acts),
                     "alert_source": alert_source, "issues": issues})
    return rows, total


def main() -> int:
    case_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else PATHS.cases_out
    rows, total = audit(case_dir)
    from_pack = sum(r["alert_source"] == "case pack" for r in rows)
    lines = ["# Answer audit", "",
             f"{len(rows)} answer files in `{case_dir.name}/`, **{total} issue(s)**. "
             "Checks: data integrity, §2 routing, §3a case/SAR, §4 exposure, R1, R2, R3, R7, "
             "§6 stopping, graph read-back. There is no answer key; this proves consistency, "
             "not correctness.",
             "", f"Alert details came from the case pack for {from_pack} file(s) and from the "
             f"trigger saved in the answer file for {len(rows) - from_pack}.", "",
             "| case | trigger | verdict | p | pattern | exposure | SAR | final actions | audit |",
             "|---|---|---|---:|---|---:|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['case']} | {r['trigger']} | {r['verdict']} | {r['p']:.2f} | "
                     f"{r['pattern']} | ${r['exposure']:,.2f} | {'yes' if r['sar'] else 'no'} | "
                     f"{r['final']} | {'✅' if not r['issues'] else '⚠ ' + '; '.join(r['issues'])} |")
    out = PATHS.eval_out / "answer_audit.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for r in rows:
        print(f"{r['case']} {r['verdict']:<10} p={r['p']:<5} "
              f"{'OK' if not r['issues'] else 'ISSUES: ' + ' | '.join(r['issues'])}")
    print(f"\n{total} issue(s) across {len(rows)} files -> {out}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())

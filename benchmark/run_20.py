"""Run the agent over the twenty benchmark cases and write `cases/HHG-0xx.json`.

This is the submission artefact. Every case is also written into the graph from
the same code path, and every answer file is validated against the dataset's
Answer Format before anything is written — missing fields score zero for that
part and invented identifiers score zero outright, so both are checked here
rather than discovered by a judge.

    python benchmark/run_20.py                      # all twenty
    python benchmark/run_20.py --case HHG-014       # one case, verbose
    python benchmark/run_20.py --no-llm             # deterministic prose only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Windows consoles still default to cp1252, which cannot encode the arrows and
# box characters used below; without this a clean run dies on its own log line.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - non-reconfigurable stream
    pass


from fraudagent.agent.graph import Investigator, trigger_from_row  # noqa: E402
from fraudagent.agent.llm import get_llm  # noqa: E402
from fraudagent.config import PATHS  # noqa: E402
from fraudagent.graphstore import get_store  # noqa: E402
from fraudagent.report.answer import validate  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def known_ids() -> tuple[set[str], set[str], set[str]]:
    tx = pd.read_parquet(PATHS.tx_parquet, columns=["txn_id", "card_id"])
    cc = pd.read_parquet(PATHS.closed_cases_parquet, columns=["case_id"])
    return (set(tx["txn_id"].astype(str)), set(tx["card_id"].astype(str)),
            set(cc["case_id"].astype(str)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="", help="run a single case id, e.g. HHG-014")
    ap.add_argument("--no-llm", action="store_true",
                    help="deterministic templates only; verdicts are unchanged")
    ap.add_argument("--out", default="", help="override the output directory")
    ap.add_argument("--no-langgraph", action="store_true")
    args = ap.parse_args()

    if args.no_llm:
        os.environ["AGENT_USE_LLM"] = "0"

    PATHS.ensure()
    out_dir = Path(args.out) if args.out else PATHS.cases_out
    out_dir.mkdir(parents=True, exist_ok=True)

    store = get_store()
    llm = get_llm()
    log(f"backend      : {store.backend}")
    log(f"llm          : {llm.cfg.provider}/{llm.cfg.model}" if llm.available
        else "llm          : none configured — deterministic templates")
    inv = Investigator(store, llm, use_langgraph=not args.no_langgraph)
    log(f"orchestration: {inv.framework}")

    pack = pd.read_csv(PATHS.case_pack_csv)
    pack["opened_at"] = pd.to_datetime(pack["opened_at"])
    if args.case:
        pack = pack[pack["case_id"] == args.case]
        if pack.empty:
            log(f"no such case: {args.case}")
            return 2

    txn_ids, card_ids, case_ids = known_ids()
    summary: list[dict] = []
    all_problems: dict[str, list[str]] = {}
    t0 = time.time()

    for row in pack.to_dict("records"):
        case_id = row["case_id"]
        started = time.time()
        answer = inv.run(trigger_from_row(row), case_id)
        problems = validate(answer, txn_ids, card_ids, case_ids)
        if problems:
            all_problems[case_id] = problems

        path = out_dir / f"{case_id}.json"
        path.write_text(json.dumps(answer, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")

        c = answer["case"]
        rec = {
            "case": case_id, "trigger": row["trigger_type"],
            "verdict": c["verdict"], "pattern": c["pattern"],
            "p_fraud": c["fraud_probability"], "status": c["status"],
            "exposure": c["exposure_usd"], "n_txns": len(c["affected_txn_ids"]),
            "connected": len(c["connected_card_ids"]),
            "sar": answer["sar"]["file"],
            "initial": "|".join(a["action"] for a in answer["next_best_actions"]["initial"]),
            "final": "|".join(a["action"] for a in answer["next_best_actions"]["final"]),
            "changed": answer["next_best_actions"]["what_changed"] != "nothing",
            "requests": len(answer["evidence_requests"]),
            "tools": answer["tool_calls"],
            "secs": round(time.time() - started, 1),
            "problems": len(problems),
        }
        summary.append(rec)
        flag = "  ✗" if problems else ""
        log(f"{case_id}  {rec['verdict']:<10} {rec['pattern']:<28} "
            f"p={rec['p_fraud']:.2f} exp=${rec['exposure']:>9,.2f} "
            f"sar={'Y' if rec['sar'] else 'n'} "
            f"final={rec['final'][:52]:<52} {rec['secs']:>5.1f}s{flag}")
        for p in problems:
            log(f"           ! {p}")

    df = pd.DataFrame(summary)
    log("")
    log(f"wrote {len(summary)} answer files to {out_dir} in {time.time()-t0:.1f}s")
    log(f"verdicts : {df['verdict'].value_counts().to_dict()}")
    log(f"patterns : {df['pattern'].value_counts().to_dict()}")
    log(f"SAR filed: {int(df['sar'].sum())}/{len(df)}")
    log(f"recommendation changed after evidence: {int(df['changed'].sum())}/{len(df)}")
    log(f"evidence requests raised: {int(df['requests'].sum())}")
    log(f"mean tool calls/case: {df['tools'].mean():.1f}   "
        f"mean latency: {df['secs'].mean():.1f}s")
    if llm.available:
        log(f"llm tokens: {llm.usage.total_tokens:,} across {llm.usage.calls} calls "
            f"({llm.usage.cached} served from cache)")
        if llm.usage.errors:
            # Failed calls fall back to template prose silently; say so here.
            first = dict.fromkeys(e[:200] for e in llm.usage.errors)
            log(f"llm errors: {len(llm.usage.errors)} calls fell back to templates")
            for e in list(first)[:3]:
                log(f"  {e}")

    report = PATHS.eval_out / "benchmark_summary.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "# Benchmark run summary\n\n"
        f"Backend `{store.backend}` · orchestration `{inv.framework}` · "
        f"{len(summary)} cases · {time.time()-t0:.0f}s\n\n"
        + df.drop(columns=["problems"]).to_markdown(index=False) + "\n",
        encoding="utf-8")
    log(f"wrote {report}")

    if all_problems:
        log("")
        log("SCHEMA PROBLEMS FOUND — these would lose points:")
        for cid, probs in all_problems.items():
            for p in probs:
                log(f"  {cid}: {p}")
        return 1
    log("all answer files validate against the dataset Answer Format")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

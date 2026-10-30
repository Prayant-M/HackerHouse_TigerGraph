"""Speed and autonomy (challenge C9): an alert triggers the investigation, so the
case is ready before anyone opens it.

    alerts/inbox/<alert_id>.json  ->  worker  ->  cases/ready/<alert_id>.json
                                              ->  eval/reports/pipeline.md (p95, cost)

An alert is the same record as a case-pack row. The worker runs it through the
*same* `Runner` as `benchmark/run_case.py`, so a pre-investigation carries the
same attested evidence, proof and recorded tool I/O as one run by hand. Fails
closed per alert: a dependency failure leaves a FAILED_DEPENDENCY record and the
next alert proceeds.

    python benchmark/alert_pipeline.py --enqueue-pack     # turn the pack into alerts
    python benchmark/alert_pipeline.py --drain            # investigate everything queued
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmark"))
os.environ.setdefault("GRAPH_STRICT", "1")

import pandas as pd  # noqa: E402

from fraudagent.agent.telemetry import p95  # noqa: E402
from fraudagent.config import PATHS  # noqa: E402
from run_case import Runner, atomic_write, load_row, pack_path  # noqa: E402

INBOX = ROOT / "alerts" / "inbox"
DONE = ROOT / "alerts" / "done"
READY = PATHS.cases_out / "ready"


def enqueue_pack() -> int:
    INBOX.mkdir(parents=True, exist_ok=True)
    pack = pd.read_csv(pack_path(), dtype=str)
    for r in pack.to_dict("records"):
        r["received_at"] = time.time()
        (INBOX / f"{r['case_id']}.json").write_text(json.dumps(r), encoding="utf-8")
    print(f"enqueued {len(pack)} alerts in {INBOX.relative_to(ROOT)}")
    return 0


def drain(dev: bool) -> int:
    READY.mkdir(parents=True, exist_ok=True)
    DONE.mkdir(parents=True, exist_ok=True)
    runner = Runner(dev=dev)
    stats = []
    for f in sorted(INBOX.glob("*.json")):
        alert = json.loads(f.read_text(encoding="utf-8"))
        received = float(alert.pop("received_at", time.time()))
        tmp = Path(f"{f}.pack.csv")
        pd.DataFrame([alert]).to_csv(tmp, index=False)
        row = load_row(tmp, alert["case_id"])
        tmp.unlink()
        t0 = time.time()
        code, ans = runner.run(row, write=False)
        ready_at = time.time()
        if code == 0 and ans is not None:
            ans["agent_record"]["pipeline"] = {"received_at": received, "ready_at": ready_at,
                                               "queue_wait_s": round(t0 - received, 2),
                                               "investigate_s": round(ready_at - t0, 2)}
            atomic_write(READY / f"{alert['case_id']}.json", ans)
        f.rename(DONE / f.name)
        stats.append({"alert": alert["case_id"], "code": code,
                      "investigate_s": round(ready_at - t0, 2),
                      "end_to_end_s": round(ready_at - received, 2),
                      "tokens": (ans or {}).get("tokens", 0),
                      "cost_usd": ((ans or {}).get("agent_record", {}).get("telemetry", {})
                                   .get("llm_cost_usd", 0.0))})
        print(f"{alert['case_id']}: exit {code} in {ready_at - t0:.1f}s", flush=True)
    if not stats:
        print("inbox empty")
        return 0
    inv = [s["investigate_s"] for s in stats if s["code"] == 0]
    e2e = [s["end_to_end_s"] for s in stats if s["code"] == 0]
    md = ["# Alert-to-ready pipeline", "", f"`benchmark/alert_pipeline.py --drain`, "
          f"backend `{runner.backend}`, {len(stats)} alerts, "
          f"{sum(1 for s in stats if s['code'] == 0)} ready, "
          f"{sum(1 for s in stats if s['code'] == 2)} failed closed.", "",
          f"- p95 investigation latency: **{p95(inv)} s** (mean {sum(inv)/max(len(inv),1):.1f} s)",
          f"- p95 alert-to-ready (incl. queue wait): **{p95(e2e)} s**",
          f"- tokens per case: {sum(s['tokens'] for s in stats)/len(stats):.0f}; cost per case: "
          f"${sum(s['cost_usd'] for s in stats)/len(stats):.4f}", "",
          pd.DataFrame(stats).to_markdown(index=False), ""]
    (PATHS.eval_out / "pipeline.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:7]))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enqueue-pack", action="store_true")
    ap.add_argument("--drain", action="store_true")
    ap.add_argument("--dev", action="store_true")
    a = ap.parse_args()
    if a.enqueue_pack:
        enqueue_pack()
    if a.drain:
        return drain(a.dev)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

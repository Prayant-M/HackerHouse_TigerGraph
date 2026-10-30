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
    python benchmark/alert_pipeline.py --drain --workers 4
    python benchmark/alert_pipeline.py --watch --workers 4 --idle-exit 600
                                                          # streaming: investigate each alert
                                                          # the moment it lands in the inbox

Workers are separate processes, each with its own Runner and graph connection,
so one slow case does not hold the queue.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
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


_RUNNER = None


def _init_worker(dev: bool) -> None:
    global _RUNNER
    _RUNNER = Runner(dev=dev)


def _investigate(path: str) -> dict:
    """One alert, in a worker process. Fails closed per alert."""
    f = Path(path)
    claimed = f.with_suffix(f".{os.getpid()}.work")
    try:
        f.rename(claimed)                      # claim it: no other worker takes it
    except OSError:
        return {}
    alert = json.loads(claimed.read_text(encoding="utf-8"))
    received = float(alert.pop("received_at", time.time()))
    tmp = Path(f"{claimed}.pack.csv")
    pd.DataFrame([alert]).to_csv(tmp, index=False)
    row = load_row(tmp, alert["case_id"])
    tmp.unlink()
    t0 = time.time()
    code, ans = _RUNNER.run(row, write=False)
    ready_at = time.time()
    if code == 0 and ans is not None:
        ans["agent_record"]["pipeline"] = {"received_at": received, "ready_at": ready_at,
                                           "queue_wait_s": round(t0 - received, 2),
                                           "investigate_s": round(ready_at - t0, 2),
                                           "worker_pid": os.getpid()}
        atomic_write(READY / f"{alert['case_id']}.json", ans)
    claimed.rename(DONE / f.name)
    tel = (ans or {}).get("agent_record", {}).get("telemetry", {})
    llm = (ans or {}).get("agent_record", {}).get("llm", {})
    return {"alert": alert["case_id"], "code": code, "worker": os.getpid(),
            "investigate_s": round(ready_at - t0, 2),
            "end_to_end_s": round(ready_at - received, 2),
            "graph_calls": tel.get("graph_calls", 0), "tokens": (ans or {}).get("tokens", 0),
            "template_fallbacks": llm.get("template_fallbacks", 0),
            "cost_usd": tel.get("llm_cost_usd", 0.0)}


def _report(stats: list[dict], backend: str, workers: int, wall: float, mode: str) -> None:
    inv = [s["investigate_s"] for s in stats if s["code"] == 0]
    e2e = [s["end_to_end_s"] for s in stats if s["code"] == 0]
    md = ["# Alert-to-ready pipeline", "", f"`benchmark/alert_pipeline.py --{mode} --workers "
          f"{workers}`, backend `{backend}`, {len(stats)} alerts, "
          f"{sum(1 for s in stats if s['code'] == 0)} ready, "
          f"{sum(1 for s in stats if s['code'] == 2)} failed closed.", "",
          f"- p95 investigation latency: **{p95(inv)} s** (mean {sum(inv)/max(len(inv),1):.1f} s)",
          f"- p95 alert-to-ready (incl. queue wait): **{p95(e2e)} s**",
          f"- wall clock for the whole queue: **{wall:.0f} s** with {workers} worker(s)",
          f"- tokens per case: {sum(s['tokens'] for s in stats)/max(len(stats),1):.0f}; cost per "
          f"case: ${sum(s['cost_usd'] for s in stats)/max(len(stats),1):.4f}; template prose "
          f"fallbacks: {sum(s['template_fallbacks'] for s in stats)}", "",
          pd.DataFrame(stats).to_markdown(index=False), ""]
    (PATHS.eval_out / "pipeline.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:8]))


def drain(dev: bool, workers: int = 1, watch: bool = False, idle_exit: float = 600.0) -> int:
    READY.mkdir(parents=True, exist_ok=True)
    DONE.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(parents=True, exist_ok=True)
    stats: list[dict] = []
    t0 = time.time()
    with cf.ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                                initargs=(dev,)) as pool:
        submitted: set[str] = set()
        futures = []
        last_new = time.time()
        while True:
            for f in sorted(INBOX.glob("*.json")):
                if str(f) not in submitted:
                    submitted.add(str(f))
                    futures.append(pool.submit(_investigate, str(f)))
                    last_new = time.time()
            for fut in [x for x in futures if x.done()]:
                futures.remove(fut)
                r = fut.result()
                if r:
                    stats.append(r)
                    print(f"{r['alert']}: exit {r['code']} in {r['investigate_s']:.1f}s "
                          f"(worker {r['worker']})", flush=True)
            if not watch and not futures:
                break
            if watch and not futures and time.time() - last_new > idle_exit:
                break
            time.sleep(0.5)
    if not stats:
        print("inbox empty")
        return 0
    from fraudagent.graphstore import get_store

    _report(stats, get_store().backend, workers, time.time() - t0,
            "watch" if watch else "drain")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enqueue-pack", action="store_true")
    ap.add_argument("--drain", action="store_true")
    ap.add_argument("--dev", action="store_true")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--watch", action="store_true", help="keep polling the inbox (streaming)")
    ap.add_argument("--idle-exit", type=float, default=600.0,
                    help="--watch stops after this many seconds with no new alert")
    a = ap.parse_args()
    if a.enqueue_pack:
        enqueue_pack()
    if a.drain or a.watch:
        return drain(a.dev, a.workers, a.watch, a.idle_exit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

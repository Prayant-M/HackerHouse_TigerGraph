"""Analyst console — FastAPI back end.

Deliberately dependency-light: no build step, no bundler, no node_modules. The
page is served as static HTML and talks to this API, so `python ui/server.py`
is the whole deployment story and a judge can be looking at it forty seconds
after cloning.

    python ui/server.py            → http://127.0.0.1:8080

Endpoints:
    GET  /api/health                  backend, dataset and index status
    GET  /api/cases                   the twenty answer files, summarised
    GET  /api/cases/{case_id}         one full investigation record
    GET  /api/graph/{case_id}         the case subgraph, for the canvas
    GET  /api/investigate/{case_id}   re-run the agent live (SSE reasoning trace)
    GET  /api/approvals               actions waiting on L1/L2 sign-off
    POST /api/approvals/{case}/{n}    approve or reject one, writing the edge
    GET  /api/calibration             the measured likelihood-ratio table
    GET  /api/policy                  the compiled policy rules with clause text
    GET  /api/audit                   eval/audit_answers.py over the answer files
    GET  /api/autonomous              alerts the agent raised itself (benchmark/monitor.py)
    GET  /api/autonomous/{case_id}    one of those investigations in full

Read-only mode (CONSOLE_READONLY=1) is for public hosting: it serves the
answer files and a snapshot of the graph health and audit taken from the last
live run, needs no TigerGraph credentials, no LLM key and none of the staged
data, and refuses live re-runs. Approvals are kept in memory and never written
to a graph. `python deploy/build_space.py` assembles such a bundle.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Windows consoles still default to cp1252, which cannot encode the arrows and
# box characters used below; without this a clean run dies on its own log line.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - non-reconfigurable stream
    pass


import pandas as pd  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from fraudagent.config import PATHS  # noqa: E402
from fraudagent.core.policy_engine import clause_text  # noqa: E402
from fraudagent.graphstore import get_store  # noqa: E402
from fraudagent.mcp_servers.simulated_actions import read_log  # noqa: E402

STATIC = Path(__file__).parent / "static"
SNAPSHOT = Path(__file__).parent / "snapshot"
READONLY = os.environ.get("CONSOLE_READONLY", "").strip().lower() in {"1", "true", "yes"}
app = FastAPI(title="TigerGraph Agentic Fraud Investigation — Analyst Console")

_approvals: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _case_files() -> list[Path]:
    return sorted(PATHS.cases_out.glob("HHG-*.json"))


def _load(case_id: str) -> dict[str, Any]:
    path = PATHS.cases_out / f"{case_id}.json"
    if not path.exists():
        raise HTTPException(404, f"{case_id} has not been investigated yet — "
                                 f"run `python benchmark/run_20.py`")
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot(name: str) -> dict[str, Any] | None:
    path = SNAPSHOT / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@app.get("/api/health")
def health() -> dict[str, Any]:
    if READONLY:
        snap = _snapshot("health") or {}
        return {"ok": True, "readonly": True,
                "graph": {**snap.get("graph", {}), "backend": "snapshot"},
                "captured_at": snap.get("captured_at"),
                "answer_files": len(_case_files()),
                "calibration": PATHS.lr_table_json.exists()}
    store = get_store()
    return {"ok": True, "readonly": False, "graph": store.health(),
            "answer_files": len(_case_files()),
            "calibration": PATHS.lr_table_json.exists(),
            "cases_dir": str(PATHS.cases_out)}


@app.get("/api/cases")
def cases() -> list[dict[str, Any]]:
    out = []
    for p in _case_files():
        d = json.loads(p.read_text(encoding="utf-8"))
        c, rec = d["case"], d.get("agent_record", {})
        out.append({
            "case_id": d["case_id"],
            "trigger": rec.get("trigger", {}).get("type", ""),
            "trigger_text": rec.get("trigger", {}).get("text", ""),
            "status": c["status"], "verdict": c["verdict"],
            "pattern": c["pattern"], "fraud_probability": c["fraud_probability"],
            "exposure_usd": c["exposure_usd"],
            "n_affected": len(c["affected_txn_ids"]),
            "n_connected": len(c["connected_card_ids"]),
            "sar": d["sar"]["file"],
            "initial": [a["action"] for a in d["next_best_actions"]["initial"]],
            "final": [a["action"] for a in d["next_best_actions"]["final"]],
            "changed": d["next_best_actions"]["what_changed"] != "nothing",
            "requests": len(d["evidence_requests"]),
            "summary": c["summary"],
            "latency_s": d.get("latency_s"), "tool_calls": d.get("tool_calls"),
        })
    return out


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str) -> dict[str, Any]:
    return _load(case_id)


@app.get("/api/graph/{case_id}")
def case_graph(case_id: str) -> dict[str, Any]:
    """The case subgraph as nodes and edges, for the canvas.

    Built from the written case rather than invented for display, so what the
    analyst sees on screen is the same object `case_chain` walks in TigerGraph.
    """
    d = _load(case_id)
    c, rec = d["case"], d.get("agent_record", {})
    trig = rec.get("trigger", {})
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    def node(nid: str, label: str, kind: str, **extra) -> None:
        if nid in seen or not nid:
            return
        seen.add(nid)
        nodes.append({"id": nid, "label": label, "kind": kind, **extra})

    node(c["graph_case_id"], case_id, "case",
         verdict=c["verdict"], p=c["fraud_probability"])
    node(trig.get("customer_id", ""), trig.get("customer_id", ""), "customer")
    node(trig.get("card_id", ""), trig.get("card_id", ""), "card")
    edges.append({"from": c["graph_case_id"], "to": trig.get("card_id", ""),
                  "label": "INVESTIGATES_CARD"})
    edges.append({"from": trig.get("card_id", ""), "to": trig.get("customer_id", ""),
                  "label": "OWNED_BY"})

    for t in c["affected_txn_ids"][:24]:
        node(t, t, "transaction",
             flagged=(t == trig.get("flagged_txn_id")))
        edges.append({"from": c["graph_case_id"], "to": t, "label": "INVESTIGATES_TXN"})
        edges.append({"from": t, "to": trig.get("card_id", ""), "label": "MADE_WITH"})
    if trig.get("flagged_txn_id") and trig["flagged_txn_id"] not in seen:
        node(trig["flagged_txn_id"], trig["flagged_txn_id"], "transaction", flagged=True)
        edges.append({"from": c["graph_case_id"], "to": trig["flagged_txn_id"],
                      "label": "INVESTIGATES_TXN"})

    for dp in c["connected_device_profiles"][:4]:
        node(dp, dp[:40], "device")
        edges.append({"from": c["graph_case_id"], "to": dp, "label": "INVESTIGATES_DEVICE"})
        for other in c["connected_card_ids"][:18]:
            node(other, other, "connected_card")
            edges.append({"from": dp, "to": other, "label": "DEVICE_USED_IN"})
    if not c["connected_device_profiles"]:
        for other in c["connected_card_ids"][:18]:
            node(other, other, "connected_card")
            edges.append({"from": c["graph_case_id"], "to": other, "label": "CONNECTED_CARD"})

    for p in c["similar_prior_cases"][:6]:
        node(p, p, "closed_case")
        edges.append({"from": c["graph_case_id"], "to": p, "label": "RECALLED_CASE"})

    return {"nodes": nodes, "edges": edges}


@app.get("/api/investigate/{case_id}")
async def investigate(case_id: str) -> StreamingResponse:
    """Re-run the agent and stream its reasoning trace as it happens.

    This is what makes the console a console rather than a JSON viewer: the
    posterior moves on screen, the provisional recommendation lands before the
    evidence request goes out, and the revision arrives after it.
    """
    if READONLY:
        raise HTTPException(403, "Live re-runs are disabled on this read-only deployment. "
                                 "Clone the repository and run `python ui/server.py` "
                                 "to watch the agent investigate against TigerGraph.")
    pack = pd.read_csv(PATHS.case_pack_csv)
    pack["opened_at"] = pd.to_datetime(pack["opened_at"])
    row = pack[pack["case_id"] == case_id]
    if row.empty:
        raise HTTPException(404, f"{case_id} is not in the case pack")
    record = row.to_dict("records")[0]

    async def stream():
        from fraudagent.agent.graph import Investigator, trigger_from_row

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def worker() -> None:
            try:
                store = get_store()
                inv = Investigator(store)
                state_trace: list[dict] = []

                import fraudagent.agent.nodes as nodes_mod
                original = nodes_mod._trace

                def hooked(state, node, detail):
                    original(state, node, detail)
                    event = state["trace"][-1]
                    state_trace.append(event)
                    loop.call_soon_threadsafe(queue.put_nowait,
                                              {"type": "step", "data": event})

                nodes_mod._trace = hooked
                try:
                    answer = inv.run(trigger_from_row(record), case_id)
                finally:
                    nodes_mod._trace = original
                loop.call_soon_threadsafe(queue.put_nowait,
                                          {"type": "done", "data": answer})
            except Exception as exc:                       # pragma: no cover
                loop.call_soon_threadsafe(queue.put_nowait,
                                          {"type": "error", "data": str(exc)})

        threading.Thread(target=worker, daemon=True).start()
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event, default=str)}\n\n"
            if event["type"] in {"done", "error"}:
                break

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/approvals")
def approvals() -> list[dict[str, Any]]:
    """Everything the agent recommended but may not execute.

    The queue is real: an approval writes an `APPROVED_BY` edge, and a rejection
    is recorded too — a recommendation an analyst overruled is the most useful
    training signal the memory layer gets.
    """
    out: list[dict[str, Any]] = []
    for p in _case_files():
        d = json.loads(p.read_text(encoding="utf-8"))
        for i, a in enumerate(d["next_best_actions"]["final"]):
            if a["route"] == "auto":
                continue
            key = f"{d['case_id']}:{i}"
            with _lock:
                decided = _approvals.get(key)
            out.append({
                "key": key, "case_id": d["case_id"], "index": i,
                "action": a["action"], "route": a["route"], "reason": a["reason"],
                "approver": {"L1": "team lead", "L2": "fraud manager"}[a["route"]],
                "exposure_usd": d["case"]["exposure_usd"],
                "fraud_probability": d["case"]["fraud_probability"],
                "decision": decided,
            })
    return out


@app.post("/api/approvals/{case_id}/{index}")
def decide(case_id: str, index: int, payload: dict[str, Any]) -> dict[str, Any]:
    approved = bool(payload.get("approved"))
    analyst = str(payload.get("analyst") or "ANALYST-01")
    record = {"approved": approved, "analyst": analyst,
              "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "note": str(payload.get("note") or "")}
    with _lock:
        _approvals[f"{case_id}:{index}"] = record

    if READONLY:
        record["graph_write"] = "skipped: read-only deployment"
        return record
    store = get_store()
    if getattr(store, "backend", "") == "tigergraph":
        try:                                               # pragma: no cover
            d = _load(case_id)
            aid = f"{d['case']['graph_case_id']}-FIN-{index + 1:02d}"
            store.graph.upsertVertex("Analyst", analyst,
                                    {"role": d["next_best_actions"]["final"][index]["route"],
                                     "approval_ceiling": 0.0})
            store.graph.upsertEdge("RecommendedAction", aid, "APPROVED_BY",
                                  "Analyst", analyst,
                                  {"approved": approved, "approved_at": record["at"]})
        except Exception as exc:
            record["graph_write_error"] = str(exc)
    return record


@app.get("/api/actions")
def action_log() -> list[dict[str, Any]]:
    return read_log(400)


@app.get("/api/calibration")
def calibration() -> dict[str, Any]:
    if not PATHS.lr_table_json.exists():
        raise HTTPException(404, "run `python ingest/05_calibrate.py` first")
    blob = json.loads(PATHS.lr_table_json.read_text(encoding="utf-8"))
    lrs = blob.get("empirical_likelihood_ratios", {})
    ranked = sorted(lrs.items(), key=lambda kv: -kv[1]["lr_fired"])
    return {"holdout": blob.get("holdout"), "damping": blob.get("damping"),
            "n_cases": blob.get("n_cases_replayed"),
            "operating_priors": blob.get("operating_priors"),
            "likelihood_ratios": [{"signal": k, **v} for k, v in ranked]}


@app.get("/api/policy")
def policy() -> list[dict[str, Any]]:
    return [{"rule": k, "text": v} for k, v in sorted(clause_text().items())]


_audit_cache: dict[str, Any] = {}


@app.get("/api/audit")
def answer_audit() -> dict[str, Any]:
    """The policy and data audit over the answer files, cached until they change."""
    if READONLY and (snap := _snapshot("audit")) is not None:
        return snap
    files = _case_files()
    stamp = str(max((p.stat().st_mtime for p in files), default=0)) + str(len(files))
    if _audit_cache.get("stamp") != stamp:
        sys.path.insert(0, str(ROOT / "eval"))
        from audit_answers import audit  # noqa: WPS433 - local tool, imported lazily
        rows, total = audit(PATHS.cases_out)
        _audit_cache.update(stamp=stamp, data={"rows": rows, "issues": total})
    return _audit_cache["data"]


AUTONOMOUS = ROOT / "benchmark" / "autonomous"


@app.get("/api/autonomous")
def autonomous() -> list[dict[str, Any]]:
    """Alerts nobody raised: the agent's own sweep of the exam period."""
    out = []
    for p in sorted(AUTONOMOUS.glob("AUTO-*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        c = d["case"]
        out.append({"case_id": d["case_id"], "found_by": d.get("found_by", ""),
                    "verdict": c["verdict"], "pattern": c["pattern"],
                    "fraud_probability": c["fraud_probability"],
                    "exposure_usd": c["exposure_usd"], "sar": d["sar"]["file"],
                    "n_connected": len(c["connected_card_ids"]),
                    "flagged_txn_id": d.get("agent_record", {}).get("trigger", {}).get("flagged_txn_id", ""),
                    "summary": c["summary"],
                    "final": [a["action"] for a in d["next_best_actions"]["final"]]})
    return out


@app.get("/api/autonomous/{case_id}")
def autonomous_detail(case_id: str) -> dict[str, Any]:
    path = AUTONOMOUS / f"{case_id}.json"
    if not path.exists():
        raise HTTPException(404, f"{case_id} not found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    print(f"Analyst console → http://{host}:{port}" + ("  (read-only)" if READONLY else ""))
    uvicorn.run(app, host=host, port=port, log_level="warning")

"""Analyst console — FastAPI back end.

Deliberately dependency-light: no build step, no bundler, no node_modules. The
page is served as static HTML and talks to this API, so `python ui/server.py`
is the whole deployment story and a judge can be looking at it forty seconds
after cloning.

    python ui/server.py            → http://127.0.0.1:8080

Endpoints:
    GET  /api/health                  backend, dataset and index status
    GET  /api/cases                   every answer file (HHF final round, HHG Round 1), summarised
    GET  /api/cases/{case_id}         one full investigation record
    GET  /api/graph/{case_id}         the case subgraph, for the canvas
    GET  /api/investigate/{case_id}   re-run the agent live (SSE reasoning trace)
    GET  /api/approvals               actions waiting on L1/L2 sign-off
    POST /api/approvals/{case}/{n}    approve or reject one (Bearer token -> role, server-side)
    GET  /api/approvals/verify        verify the signed, hash-chained approval ledger
    GET  /api/proof/{case_id}         proof-first examiner view (C6)
    POST /api/proof/{case_id}/flip    remove facts and recompute the decision live
    GET  /api/replay/{case_id}        recorded tool I/O per step (C6)
    POST /api/replay/{case}/rerun/{n} re-run one recorded call against the live graph
    GET  /api/ring/{case_id}          ring replay frames from attested txns (C5)
    GET  /api/lifecycle/{case_id}     state changes, approvals, handover (C14)
    POST /api/feedback/{case_id}      accept / reject a finding (C8)
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
from fastapi import FastAPI, Header, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from fraudagent.config import PATHS  # noqa: E402
from fraudagent.core.policy_engine import clause_text  # noqa: E402
from fraudagent.graphstore import get_store  # noqa: E402
from fraudagent.mcp_servers.simulated_actions import read_log  # noqa: E402

STATIC = Path(__file__).parent / "static"
SNAPSHOT = Path(__file__).parent / "snapshot"
OPENAPI_SPEC = ROOT / "docs" / "openapi.yaml"
READONLY = os.environ.get("CONSOLE_READONLY", "").strip().lower() in {"1", "true", "yes"}
app = FastAPI(title="TigerGraph Agentic Fraud Investigation — Analyst Console")

_lock = threading.Lock()


def _case_files() -> list[Path]:
    return sorted(list(PATHS.cases_out.glob("HHF-*.json")) + list(PATHS.cases_out.glob("HHG-*.json")))


def _load(case_id: str) -> dict[str, Any]:
    path = PATHS.cases_out / f"{case_id}.json"
    if not path.exists():
        raise HTTPException(404, f"{case_id} has not been investigated yet — "
                                 f"run `make case CASE=<id>`")
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
    ids = graph_case_ids()
    return {"ok": True, "readonly": False, "graph": store.health(),
            "graph_case_ids": sorted(ids) if ids is not None else None,
            "answer_files": len(_case_files()),
            "calibration": PATHS.lr_table_json.exists(),
            "cases_dir": str(PATHS.cases_out)}


_GRAPH_IDS: dict[str, Any] = {"at": 0.0, "ids": None}


def graph_case_ids() -> set[str] | None:
    """FraudCase ids actually in the graph now (cached 60 s), so the "In graph"
    badge reports the graph, not the flag the answer file recorded when it was
    written. None when unknown (local backend, or the graph unreachable)."""
    import time
    if READONLY:
        ids = (_snapshot("health") or {}).get("graph_case_ids")
        return set(ids) if ids is not None else None
    if time.time() - _GRAPH_IDS["at"] < 60:
        return _GRAPH_IDS["ids"]
    ids = None
    try:
        store = get_store()
        conn = getattr(store, "conn", None)
        if conn is not None:
            ids = {v["v_id"] for v in conn.getVertices("FraudCase", select="status", limit=10000)}
    except Exception:  # noqa: BLE001 - unknown, not "missing"
        ids = None
    _GRAPH_IDS.update(at=time.time(), ids=ids)
    return ids


def _in_graph(d: dict[str, Any], ids: set[str] | None) -> bool | None:
    if ids is None:
        return None
    return (d["case"].get("graph_case_id") or f"CASE-{d['case_id']}") in ids


@app.get("/api/cases")
def cases() -> list[dict[str, Any]]:
    ids = graph_case_ids()
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
            "round": "final" if d["case_id"].startswith("HHF") else "round1",
            "margin_k": (rec.get("proof") or {}).get("margin_k"),
            "minimal_facts": (rec.get("proof") or {}).get("minimal_sufficient_facts", []),
            "gate_applied": bool((rec.get("gate") or {}).get("applied")),
            "conformal_set": (rec.get("conformal") or {}).get("set", []),
            "hostile_text": bool((rec.get("text_facts") or {}).get("hostile_text_detected")),
            "tainted": bool((rec.get("quality") or {}).get("tainted")),
            "origin": ((rec.get("containment") or {}).get("origin") or {}).get("entity_type"),
            "at_risk": len((rec.get("containment") or {}).get("at_risk") or []),
            "in_graph": _in_graph(d, ids),
        })
    return out


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str) -> dict[str, Any]:
    d = _load(case_id)
    d["in_graph"] = _in_graph(d, graph_case_ids())
    return d


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
    pack = _pack()
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
    """Everything the agent recommended but may not execute, with the decision
    (if any) read from the signed, append-only approval ledger."""
    from fraudagent.governance.approvals import read_ledger

    decided = {(r["case_id"], r["index"]): r for r in read_ledger()
               if r.get("kind") == "decision"}
    out: list[dict[str, Any]] = []
    for p in _case_files():
        d = json.loads(p.read_text(encoding="utf-8"))
        for i, a in enumerate(d["next_best_actions"]["final"]):
            if a["route"] == "auto":
                continue
            out.append({
                "key": f"{d['case_id']}:{i}", "case_id": d["case_id"], "index": i,
                "action": a["action"], "route": a["route"], "reason": a["reason"],
                "approver": {"L1": "team lead", "L2": "fraud manager"}[a["route"]],
                "exposure_usd": d["case"]["exposure_usd"],
                "fraud_probability": d["case"]["fraud_probability"],
                "decision": decided.get((d["case_id"], i)),
            })
    return out


@app.post("/api/approvals/{case_id}/{index}")
def decide(case_id: str, index: int, payload: dict[str, Any],
           authorization: str | None = Header(default=None)) -> JSONResponse:
    """Approve or reject one routed action.

    The approver's role comes from the bearer token, looked up server-side
    against hashed tokens. Anything the body says about role is ignored (and
    recorded as ignored). Self-approval, wrong-role, replayed and duplicate
    approvals are refused with 4xx, and every refusal enters the hash chain.
    There is no endpoint that edits or deletes an approval."""
    from fraudagent.governance import approvals as gov

    body_role = str(payload.get("role") or payload.get("analyst_role") or "")
    try:
        principal = gov.authenticate(authorization)
    except gov.AuthError as exc:
        gov.refuse(None, case_id, index, exc.status, exc.message, body_role)
        return JSONResponse({"error": exc.message, "status": exc.status}, status_code=exc.status)
    if READONLY:
        return JSONResponse({"error": "read-only deployment"}, status_code=403)
    try:
        answer = _load(case_id)
    except HTTPException as exc:
        gov.refuse(principal, case_id, index, 404, "unknown case", body_role)
        return JSONResponse({"error": exc.detail}, status_code=404)
    try:
        rec = gov.decide(principal, answer, index, bool(payload.get("approved")),
                         note=str(payload.get("note") or ""),
                         proposed_by=str(payload.get("proposed_by") or "agent"),
                         body_role=body_role, presented=payload.get("record"))
    except gov.AuthError as exc:
        return JSONResponse({"error": exc.message, "status": exc.status}, status_code=exc.status)
    from fraudagent.governance import lifecycle as lc
    lc.record_approval(case_id, rec)
    # Mirror the sealed record into the graph through the console's own write
    # path (governance_write); the agent's credentials cannot reach it.
    store = get_store()
    if getattr(store, "backend", "") == "tigergraph":            # pragma: no cover - network
        try:
            store.conn.runInstalledQuery(
                "governance_write", {"kind": "approval", "record_json": json.dumps(
                    {**rec, "id": f"APR-{rec['seq']:05d}"}, default=str)}, usePost=True)
            rec["graph_write"] = "governance_write"
        except Exception as exc:
            rec["graph_write_error"] = str(exc)[:200]
    return JSONResponse(rec)


@app.get("/api/approvals/verify")
def approvals_verify() -> dict[str, Any]:
    from fraudagent.governance import approvals as gov

    ok, msg = gov.verify()
    return {"ok": ok, "detail": msg, "public_key": gov.public_key_hex(),
            "records": len(gov.read_ledger())}


@app.get("/api/ledger")
def approval_ledger() -> list[dict[str, Any]]:
    from fraudagent.governance.approvals import read_ledger

    return read_ledger()[-200:]


@app.post("/api/feedback/{case_id}")
def feedback(case_id: str, payload: dict[str, Any],
             authorization: str | None = Header(default=None)) -> JSONResponse:
    """C8: accept or reject one finding. Any authenticated role may give feedback;
    the record names who, and later behaviour cites it."""
    from fraudagent.governance import approvals as gov
    from fraudagent.governance import feedback as fb

    try:
        principal = gov.authenticate(authorization)
    except gov.AuthError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status)
    answer = _load(case_id)
    try:
        rec = fb.record(principal, answer, str(payload.get("finding", "")),
                        bool(payload.get("accepted")), str(payload.get("note") or ""))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(rec)


@app.get("/api/feedback")
def feedback_list() -> dict[str, Any]:
    from fraudagent.governance import feedback as fb

    return {"records": fb.read(), "effective": fb.adjustments()}


@app.get("/api/detectors")
def detectors() -> list[dict[str, Any]]:
    from fraudagent.detectors.typologies import registry

    return registry()


@app.post("/api/detectors/{detector_id}")
def decide_detector(detector_id: str, payload: dict[str, Any],
                    authorization: str | None = Header(default=None)) -> JSONResponse:
    """C2/C3: a proposed detector joins the toolkit only when a fraud manager
    approves it. Same token auth, same signed ledger."""
    from fraudagent.detectors import typologies as T
    from fraudagent.governance import approvals as gov

    try:
        principal = gov.authenticate(authorization)
    except gov.AuthError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status)
    reg = T.registry()
    det = next((d for d in reg if d["id"] == detector_id), None)
    if det is None:
        return JSONResponse({"error": "no such detector"}, status_code=404)
    if principal.role != "fraud_manager":
        gov.refuse(principal, detector_id, -1, 403, "only a fraud manager approves detectors")
        return JSONResponse({"error": "only a fraud manager may approve a detector"},
                            status_code=403)
    if det.get("status") in {"approved", "rejected"}:
        return JSONResponse({"error": f"already {det['status']}"}, status_code=409)
    approved = bool(payload.get("approved"))
    with _lock:
        rec = gov._append({"kind": "detector_decision", "case_id": detector_id, "index": -1,
                           "approved": approved, "actor_id": principal.actor_id,
                           "actor_role": principal.role, "backtest": det.get("backtest_october")
                           or det.get("backtest"), "at": time.strftime("%Y-%m-%d %H:%M:%S",
                                                                       time.gmtime())})
        det["status"] = "approved" if approved else "rejected"
        det["approved_by"] = principal.actor_id
        det["approval_seq"] = rec["seq"]
        T.save_registry(reg)
    store = get_store()
    if getattr(store, "backend", "") == "tigergraph":            # pragma: no cover - network
        try:
            store.conn.runInstalledQuery("governance_write", {"kind": "detector", "record_json":
                json.dumps({"id": det["id"], "name": det["name"], "origin": det["origin"],
                            "spec": json.dumps(det["spec"]), "status": det["status"],
                            "backtest": json.dumps(det.get("backtest_october") or
                                                   det.get("backtest") or {}),
                            "approved_by": principal.actor_id})}, usePost=True)
        except Exception as exc:
            rec["graph_write_error"] = str(exc)[:200]
    return JSONResponse({"detector": det, "ledger": rec})


@app.get("/api/proof/{case_id}")
def proof_view(case_id: str) -> dict[str, Any]:
    """C6 examiner view, proof first."""
    d = _load(case_id)
    rec = d.get("agent_record", {})
    return {"case_id": case_id, "proof": rec.get("proof", {}), "gate": rec.get("gate", {}),
            "conformal": rec.get("conformal", {}), "quality": rec.get("quality", {}),
            "final": d["next_best_actions"]["final"], "verdict": d["case"]["verdict"],
            "attestations": rec.get("attestations", [])}


@app.get("/api/replay/{case_id}")
def regulator_replay(case_id: str) -> dict[str, Any]:
    """C6: what the agent saw at each step — the trace joined to the recorded
    tool I/O, each call with its stored response digest and a preview."""
    import pickle

    from fraudagent.agent.recorder import RECORDINGS, canonical, load_recording

    d = _load(case_id)
    rec = load_recording(case_id) or {"calls": []}
    calls = []
    for c in rec.get("calls", []):
        preview = ""
        blob = RECORDINGS / case_id / f"{c.get('digest', '')}.pkl"
        if c.get("ok") and blob.exists():
            try:
                preview = canonical(pickle.loads(blob.read_bytes()))[:600]
            except Exception:
                preview = "(unreadable)"
        calls.append({**{k: c.get(k) for k in ("seq", "method", "params", "digest",
                                                  "latency_ms", "ok", "error", "bytes")},
                      "response_preview": preview})
    return {"case_id": case_id, "trace": d.get("agent_record", {}).get("trace", []),
            "decisions": d.get("agent_record", {}).get("decisions", []),
            "tool_calls": calls, "n_calls": len(calls),
            "proof": d.get("agent_record", {}).get("proof", {})}


@app.post("/api/replay/{case_id}/rerun/{seq}")
def rerun_call(case_id: str, seq: int) -> dict[str, Any]:
    """Challenge one step: re-run that recorded tool call against the live
    store and compare the response digest with what the agent saw."""
    from fraudagent.agent.recorder import digest, load_recording

    if READONLY:
        raise HTTPException(403, "read-only deployment")
    rec = load_recording(case_id) or {"calls": []}
    call = next((c for c in rec["calls"] if c.get("seq") == seq), None)
    if call is None or not call.get("ok") or call["method"] == "write_case":
        raise HTTPException(404, "no re-runnable call with that sequence number")
    params = json.loads(call["params"])
    args = [_revive(a) for a in params["args"]]
    kwargs = {k: _revive(v) for k, v in params["kwargs"].items()}
    store = get_store()
    result = getattr(store, call["method"])(*args, **kwargs)
    now = digest(result)
    return {"seq": seq, "method": call["method"], "recorded_digest": call["digest"],
            "live_digest": now, "matches": now == call["digest"]}


def _revive(v: Any) -> Any:
    from datetime import datetime

    if isinstance(v, str) and len(v) >= 19 and v[4] == "-" and v[10] == " ":
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return v
    return v


@app.post("/api/proof/{case_id}/flip")
def flip_fact(case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Flip one fact live: rebuild the decision with the named facts removed.
    Served from the recording, so it needs no graph and no model."""
    from fraudagent.agent.graph import Investigator, trigger_from_row
    from fraudagent.agent.recorder import RecordingStore, load_recording
    from fraudagent.agent import final_round as FR
    from fraudagent.core import proof as P

    remove = set(payload.get("remove") or [])
    rec = load_recording(case_id)
    if rec is None:
        raise HTTPException(404, "no recording for this case; run it first")
    pack = _pack()
    row = pack[pack["case_id"] == case_id].to_dict("records")[0]

    class _Base:
        backend = "replay"
        call_count = 0
    store = RecordingStore(_Base(), case_id, mode="replay", recording=rec)
    inv = Investigator(store)
    inv.run(trigger_from_row(row), case_id)
    st = inv.last_state
    facts, fc, _ = FR.fact_context(st, FR_base(st))
    full = P.decide(set(facts), fc)
    out = P.decide(set(facts) - remove, fc)
    return {"removed": sorted(remove), "facts": facts,
            "before": {"action_class": list(full.action_class), "verdict": full.verdict,
                       "p_fraud": round(full.p_fraud, 4),
                       "actions": full.decision.action_names()},
            "after": {"action_class": list(out.action_class), "verdict": out.verdict,
                      "p_fraud": round(out.p_fraud, 4), "actions": out.decision.action_names()},
            "flips": out.action_class != full.action_class}


def FR_base(state):  # noqa: N802 - mirrors the agent's helper name
    from fraudagent.agent.nodes import _case_state

    return _case_state(state, final=True)


@app.get("/api/ring/{case_id}")
def ring_replay(case_id: str) -> dict[str, Any]:
    """C5: the ring forming, frame by frame, built from attested transactions:
    which cards joined when, through what, and how the loss accumulated."""
    d = _load(case_id)
    plan = d.get("agent_record", {}).get("containment") or {}
    cards = sorted(set(plan.get("ring_cards") or []) | set(d["case"]["connected_card_ids"])
                   | {d["agent_record"]["trigger"]["card_id"]})
    if len(cards) < 2:
        return {"case_id": case_id, "frames": [], "note": "not a ring case"}
    from datetime import datetime

    as_of = datetime.fromisoformat(d["agent_record"]["as_of"])
    store = get_store()
    shared = set(d["case"]["connected_device_profiles"]) | set(
        (plan.get("ring_at_asof") or {}).get("devices", []))
    origin = (plan.get("origin") or {}).get("entity")
    rows = []
    for c in cards[:40]:
        for t in store.card_history(c, as_of, window_days=45):
            if t.device_profile and (t.device_profile in shared or t.device_profile == origin):
                rows.append({"txn_id": t.txn_id, "ts": str(t.ts), "card_id": c,
                             "amount": t.amount, "device": t.device_profile,
                             "proxy": t.proxy})
    rows.sort(key=lambda r: r["ts"])
    joined: dict[str, str] = {}
    frames, loss = [], 0.0
    for r in rows:
        if r["card_id"] not in joined:
            joined[r["card_id"]] = r["ts"]
        loss += r["amount"]
        frames.append({**r, "cards_in_ring": len(joined), "cumulative_usd": round(loss, 2),
                       "new_card": joined[r["card_id"]] == r["ts"]})
    return {"case_id": case_id, "origin": origin, "cards": cards, "joined_at": joined,
            "frames": frames, "attested_txn_ids": [r["txn_id"] for r in rows]}


@app.get("/api/lifecycle/{case_id}")
def lifecycle_view(case_id: str) -> dict[str, Any]:
    from fraudagent.governance import lifecycle as lc
    from fraudagent.governance.approvals import decisions_for

    d = _load(case_id)
    rec = d.get("agent_record", {})
    return {"case_id": case_id, "state_changes": rec.get("lifecycle", []),
            "history": lc.history(case_id), "approvals": decisions_for(case_id),
            "handover": rec.get("handover", {}), "watch_children": rec.get("watch_children", [])}


def _pack() -> pd.DataFrame:
    sys.path.insert(0, str(ROOT / "benchmark"))
    from run_case import pack_path  # noqa: WPS433

    pack = pd.read_csv(pack_path(), dtype={"flagged_txn_id": str})
    pack["opened_at"] = pd.to_datetime(pack["opened_at"])
    return pack


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


_generated_openapi = app.openapi


def _published_openapi() -> dict[str, Any]:
    """Serve docs/openapi.yaml at /openapi.json, /docs and /redoc. It carries the
    bearer auth, refusals and response shapes the generated schema cannot see.
    Hosted bundles ship without docs/ and keep the generated one."""
    if app.openapi_schema is None and OPENAPI_SPEC.exists():
        import yaml

        app.openapi_schema = yaml.safe_load(OPENAPI_SPEC.read_text(encoding="utf-8"))
    return app.openapi_schema or _generated_openapi()


app.openapi = _published_openapi


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    print(f"Analyst console → http://{host}:{port}" + ("  (read-only)" if READONLY else ""))
    uvicorn.run(app, host=host, port=port, log_level="warning")

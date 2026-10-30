"""One command, one case, from a clean clone. Fails closed.

    python benchmark/run_case.py --case HHF-007            # investigate, write cases/HHF-007.json
    python benchmark/run_case.py --all                     # every case in the pack
    python benchmark/run_case.py --case HHF-007 --twice    # run twice, diff decision fields
    python benchmark/run_case.py --case HHF-007 --replay   # offline, from recorded tool I/O
    python benchmark/run_case.py --case HHF-007 --diff     # rerun live; data or code changed?

Exit codes: 0 ok · 1 answer failed validation (nothing written) · 2 a dependency
failed (FAILED_DEPENDENCY record written, no verdict, previous answer untouched)
· 3 invalid input.

Fail closed means: if the graph, the tool layer or the model's structured output
fails, the run stops. The local mirror is never used in place of TigerGraph
when TigerGraph is configured (GRAPH_STRICT=1 is the default), and an answer is
written to a temp file and renamed only once it has validated, so a crash can
never leave a half-written "saved" file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("GRAPH_STRICT", "1")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

import pandas as pd  # noqa: E402

from fraudagent.config import PATHS, TG, graph_backend  # noqa: E402

EXIT_OK, EXIT_INVALID_ANSWER, EXIT_DEPENDENCY, EXIT_INPUT = 0, 1, 2, 3
FAILURES = PATHS.cases_out / "failures"
REQUIRED_PACK_COLUMNS = ("case_id", "opened_at", "trigger_type", "trigger_text",
                         "flagged_txn_id", "card_id", "customer_id")
TRIGGERS = {"risk_score", "customer_report", "analyst_request"}


def log(msg: str) -> None:
    print(msg, flush=True)


def pack_path(explicit: str = "") -> Path:
    if explicit:
        return Path(explicit)
    if os.environ.get("CASE_PACK"):
        return Path(os.environ["CASE_PACK"])
    return PATHS.case_pack_csv            # case_pack_final.csv when the final drop is present


def load_row(pack: Path, case_id: str) -> dict:
    """Validate the input before anything runs. A clear error naming the field,
    and no answer file."""
    if not pack.exists():
        raise ValueError(f"case pack not found: {pack}")
    df = pd.read_csv(pack, dtype={"flagged_txn_id": str})
    missing = [c for c in REQUIRED_PACK_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"case pack is missing column(s): {missing}")
    row = df[df["case_id"] == case_id]
    if row.empty:
        raise ValueError(f"unknown case id {case_id!r}: not in {pack.name}")
    r = row.to_dict("records")[0]
    for col in ("flagged_txn_id", "card_id", "customer_id", "opened_at"):
        if pd.isna(r.get(col)) or not str(r.get(col)).strip():
            raise ValueError(f"{case_id}: required field {col!r} is empty")
    if r["trigger_type"] not in TRIGGERS:
        raise ValueError(f"{case_id}: trigger_type {r['trigger_type']!r} is not one of "
                         f"{sorted(TRIGGERS)}")
    try:
        r["opened_at"] = pd.to_datetime(r["opened_at"])
    except Exception as exc:
        raise ValueError(f"{case_id}: opened_at {r['opened_at']!r} is not a timestamp") from exc
    r["trigger_text"] = "" if pd.isna(r.get("trigger_text")) else str(r["trigger_text"])
    return r


def _sign(rec: dict) -> dict:
    try:
        from fraudagent.governance.approvals import _seal

        return _seal(rec)
    except Exception as exc:                            # pragma: no cover
        rec["signature_error"] = str(exc)
        return rec


def failed_dependency(case_id: str, exc: BaseException, store=None) -> int:
    """No verdict, a named step, the last good attestation, exit 2."""
    from fraudagent.agent.recorder import DependencyFailure, TemporalWallBreach
    from fraudagent.agent.telemetry import log_run

    calls = list(getattr(store, "calls", []) or [])
    good = [c for c in calls if c.get("ok")]
    rec = {
        "case_id": case_id, "status": "FAILED_DEPENDENCY", "verdict": None,
        "dependency": getattr(exc, "dependency", "temporal_wall" if isinstance(
            exc, TemporalWallBreach) else "tigergraph-mcp" if "MCP" in str(exc) or
            "MCPToolError" in type(exc).__name__ else "graph" if any(
            k in str(exc) for k in ("HTTPSConnectionPool", "ConnectionError", "TigerGraph"))
            else "agent"),
        "step": getattr(exc, "step", ""), "error": str(exc)[:500],
        "error_type": type(exc).__name__,
        "last_good_call": ({k: good[-1][k] for k in ("seq", "method", "digest")} if good else None),
        "calls_before_failure": len(good),
        "previous_answer_untouched": (PATHS.cases_out / f"{case_id}.json").exists(),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "is_dependency_failure": isinstance(exc, (DependencyFailure, TemporalWallBreach)),
    }
    rec = _sign(rec)
    FAILURES.mkdir(parents=True, exist_ok=True)
    path = FAILURES / f"{case_id}-{time.strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    log_run({"event": "FAILED_DEPENDENCY", **{k: rec[k] for k in
                                              ("case_id", "dependency", "step", "error")}})
    log(f"FAILED_DEPENDENCY  {case_id}: {rec['dependency']} at {rec['step'] or '?'} — "
        f"{rec['error'][:200]}")
    try:
        shown = path.relative_to(PATHS.repo)
    except ValueError:
        shown = path
    log(f"  no verdict produced; record written to {shown}; "
        f"previous answer file left untouched")
    return EXIT_DEPENDENCY


def atomic_write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")
    os.replace(tmp, path)


def decision_fields(a: dict) -> dict:
    c = a["case"]
    return {"verdict": c["verdict"], "fraud_probability": c["fraud_probability"],
            "pattern": c["pattern"], "status": c["status"], "exposure_usd": c["exposure_usd"],
            "affected_txn_ids": c["affected_txn_ids"],
            "first_suspicious_txn_id": c["first_suspicious_txn_id"],
            "connected_card_ids": c["connected_card_ids"],
            "initial": a["next_best_actions"]["initial"],
            "final": a["next_best_actions"]["final"], "sar_file": a["sar"]["file"]}


def fields_hash(a: dict) -> str:
    return hashlib.sha256(json.dumps(decision_fields(a), sort_keys=True,
                                     default=str).encode()).hexdigest()


class Runner:
    def __init__(self, replay: bool = False, dev: bool = False) -> None:
        from fraudagent.agent.graph import Investigator
        from fraudagent.agent.llm import get_llm
        from fraudagent.graphstore import get_store

        self.replay = replay
        self.llm = get_llm()
        self.inner = None
        if not replay:
            backend = graph_backend()
            if backend == "local" and TG.configured and not dev:
                raise RuntimeError("GRAPH_BACKEND=local while TigerGraph is configured: the "
                                   "mirror is dev-only; pass --dev to use it")
            self.inner = self._wake(get_store)  # raises under GRAPH_STRICT=1 if TG is down
            self.graph_fingerprint = self._precondition()
        self.Investigator = Investigator

    @staticmethod
    def _wake(factory):
        """Savanna auto-stops an idle workspace and auto-starts it on the first
        request, answering 'Starting workspace' until it is up. Wait for that,
        bounded by GRAPH_WAKE_TIMEOUT_S (default 600 s); anything else, or a
        workspace still down at the deadline, fails closed as before."""
        deadline = time.time() + float(os.environ.get("GRAPH_WAKE_TIMEOUT_S", "600"))
        while True:
            try:
                return factory()
            except Exception as exc:
                msg = str(exc).lower()
                waking = any(k in msg for k in ("starting workspace", "parse json",
                                                "max retries", "connection", "502", "503", "504"))
                if not waking or time.time() > deadline:
                    raise
                log(f"graph not ready ({str(exc)[:80]}); waiting for the workspace to start")
                time.sleep(20)

    def _precondition(self) -> str:
        """A reachable graph with nothing loaded is a failed dependency, not a
        case with no evidence: every lookup would come back empty and the run
        would look like 'unknown transaction'. Check it before any case runs,
        and fold the counts into the data snapshot every attestation carries."""
        from fraudagent.agent.recorder import DependencyFailure

        h = self.inner.health()
        if not h.get("ok", True):
            raise DependencyFailure("graph", "health", str(h.get("error", "unhealthy")))
        counts = h.get("vertex_counts") or {}
        if self.inner.backend == "tigergraph":
            n_tx, n_cc = int(counts.get("Transaction", 0)), int(counts.get("ClosedCase", 0))
            if n_tx == 0 or n_cc == 0:
                raise DependencyFailure("graph", "health",
                                        f"graph is reachable but not loaded (Transaction={n_tx}, "
                                        f"ClosedCase={n_cc}); run graph/install.py --step load")
            fp = f"tg:Transaction={n_tx},ClosedCase={n_cc}"
            os.environ.setdefault("TG_LOAD_VERSION", fp)
            return fp
        return "local-mirror"

    @property
    def backend(self) -> str:
        return "replay" if self.replay else getattr(self.inner, "backend", "?")

    def run(self, row: dict, write: bool = True) -> tuple[int, dict | None]:
        from fraudagent.agent.graph import trigger_from_row
        from fraudagent.agent.recorder import RecordingStore, load_recording
        from fraudagent.agent.telemetry import cost_usd, egress, log_run
        from fraudagent.core.attest import answer_hash
        from fraudagent.report.answer import validate

        case_id = row["case_id"]
        if self.replay:
            rec = load_recording(case_id)
            if rec is None:
                log(f"no recording for {case_id}; run it live first")
                return EXIT_INPUT, None
            store = RecordingStore(_ReplayBase(), case_id, mode="replay", recording=rec)
        else:
            store = RecordingStore(self.inner, case_id)
        self.llm.begin_case(case_id)
        if not self.replay:
            try:
                # Savanna may have auto-stopped between cases: wait for it, bounded.
                self._wake(lambda: self._precondition() and self.inner)
                exists = self.inner.get_transaction(str(row["flagged_txn_id"])) is not None
                if not exists:
                    # "Not found" during an outage is not evidence the id is
                    # invalid. Only a healthy, loaded graph may say so.
                    self._precondition()
                    exists = self.inner.get_transaction(str(row["flagged_txn_id"])) is not None
            except Exception as exc:
                return failed_dependency(case_id, exc, store), None
            if not exists:
                log(f"INVALID INPUT: {case_id}: flagged_txn_id {row['flagged_txn_id']} is not in "
                    f"the graph; no answer file written")
                return EXIT_INPUT, None
        inv = self.Investigator(store, self.llm)
        t0 = time.time()
        try:
            answer = inv.run(trigger_from_row(row), case_id)
        except Exception as exc:
            if os.environ.get("RUN_CASE_TRACEBACK"):
                traceback.print_exc()
            return failed_dependency(case_id, exc, store), None
        problems = validate(answer)
        unattested = answer["agent_record"].get("unattested", [])
        if problems:
            log(f"{case_id}: answer failed validation, nothing written:")
            for p in problems:
                log(f"   ! {p}")
            return EXIT_INVALID_ANSWER, answer
        usage = self.llm.case_usage()
        answer["agent_record"]["telemetry"] = {
            "wall_s": round(time.time() - t0, 2), "graph_calls": len(store.calls),
            "graph_errors": sum(1 for c in store.calls if not c.get("ok")),
            "llm_calls": usage["calls"], "tokens": usage["tokens"],
            "llm_cost_usd": cost_usd(usage["input_tokens"], usage["output_tokens"]),
            "template_fallbacks": usage["template_fallbacks"], "backend": self.backend,
            "unattested_claims": len(unattested),
        }
        if write and not self.replay:
            store.save_index()
            atomic_write(PATHS.cases_out / f"{case_id}.json", answer)
            from fraudagent.governance import lifecycle as lc
            lc.record_run(answer)
            egress({"dependency": "tigergraph", "host": TG.host if self.backend ==
                    "tigergraph" else "local-mirror", "case_id": case_id,
                    "calls": len(store.calls), "contains": "graph queries and the case write"})
        log_run({"event": "case", "case_id": case_id, "backend": self.backend,
                 "verdict": answer["case"]["verdict"], "answer_hash": answer_hash(answer),
                 **answer["agent_record"]["telemetry"]})
        return EXIT_OK, answer


class _ReplayBase:
    """Stand-in for the graph during replay. Every tool call is served from the
    recording; anything not recorded fails closed."""

    backend = "replay"
    call_count = 0

    def health(self) -> dict:
        return {"backend": "replay", "ok": True}


def summarise(a: dict) -> str:
    c = a["case"]
    fin = "|".join(x["action"] for x in a["next_best_actions"]["final"])
    pr = a["agent_record"].get("proof") or {}
    g = a["agent_record"].get("gate") or {}
    return (f"{a['case_id']}  {c['verdict']:<10} {c['pattern']:<28} p={c['fraud_probability']:.2f} "
            f"exp=${c['exposure_usd']:>9,.2f} sar={'Y' if a['sar']['file'] else 'n'} "
            f"k={pr.get('margin_k')} gate={'Y' if g.get('applied') else 'n'} "
            f"final={fin[:60]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--case", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--pack", default="")
    ap.add_argument("--twice", action="store_true")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--dev", action="store_true", help="allow the local mirror")
    args = ap.parse_args()
    if args.no_llm:
        os.environ["AGENT_USE_LLM"] = "0"
    if sys.version_info < (3, 10):
        log("Python 3.10+ is required")
        return EXIT_INPUT
    PATHS.ensure()
    pack = pack_path(args.pack)
    if not (args.case or args.all):
        log("give --case <id> or --all")
        return EXIT_INPUT
    try:
        ids = [args.case] if args.case else pd.read_csv(pack)["case_id"].tolist()
        rows = [load_row(pack, cid) for cid in ids]
        # Chronological: an investigation may read what earlier investigations
        # wrote (COMPROMISE_POINT, as_of-bounded), so running in as_of order makes
        # a later single-case rerun see exactly the memory the batch run saw.
        rows.sort(key=lambda r: (r["opened_at"], r["case_id"]))
    except ValueError as exc:
        log(f"INVALID INPUT: {exc}")
        return EXIT_INPUT

    try:
        runner = Runner(replay=args.replay, dev=args.dev)
    except Exception as exc:
        return failed_dependency(args.case or "ALL", exc)
    log(f"backend {runner.backend} · pack {pack.name} · strict={os.environ.get('GRAPH_STRICT')}")

    worst = EXIT_OK
    rows_out = []
    for row in rows:
        cid = row["case_id"]
        if args.diff:
            from fraudagent.agent.recorder import load_recording
            old = load_recording(cid)
            prev = json.loads((PATHS.cases_out / f"{cid}.json").read_text(encoding="utf-8"))
            code, ans = runner.run(row, write=False)
            if code:
                return code
            from fraudagent.agent.recorder import RECORDINGS  # noqa: F401
            new_calls = runner_last_calls(cid, ans)
            data_changed = _data_changed(old, ans)
            same = fields_hash(prev) == fields_hash(ans)
            log(f"{cid}: decision {'unchanged' if same else 'CHANGED'}; "
                f"tool responses {'changed' if data_changed else 'identical'} → "
                + ("no change" if same else ("DATA changed" if data_changed else "CODE changed")))
            del new_calls
            continue
        code, ans = runner.run(row)
        worst = max(worst, code)
        if code == EXIT_DEPENDENCY and not args.all:
            return code
        if ans is None or code:
            continue
        log(summarise(ans))
        rows_out.append(ans)
        if args.replay:
            prev_p = PATHS.cases_out / f"{cid}.json"
            if prev_p.exists():
                prev = json.loads(prev_p.read_text(encoding="utf-8"))
                same = fields_hash(prev) == fields_hash(ans)
                log(f"   replay {'reproduces' if same else 'DIFFERS FROM'} the saved answer "
                    f"bit-for-bit on decision fields")
                worst = max(worst, 0 if same else EXIT_INVALID_ANSWER)
        if args.twice:
            code2, ans2 = runner.run(row)
            if code2:
                return code2
            a, b = decision_fields(ans), decision_fields(ans2)
            diff = [k for k in a if a[k] != b[k]]
            log(f"   twice: {'identical decision fields' if not diff else 'DIFFERENT: ' + str(diff)}"
                f" (hash {fields_hash(ans)[:16]})")
            worst = max(worst, 0 if not diff else EXIT_INVALID_ANSWER)
    if args.all and rows_out:
        write_summary(rows_out, runner.backend)
    return worst


def runner_last_calls(case_id: str, ans: dict) -> int:
    return int(ans.get("tool_calls", 0))


def _data_changed(old: dict | None, ans: dict) -> bool:
    """Compare tool-response digests of the saved recording with the new run."""
    if not old:
        return True
    from fraudagent.agent.recorder import RECORDINGS

    p = RECORDINGS / ans["case_id"] / "index.json"
    new = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"calls": []}
    a = [(c["method"], c.get("key"), c.get("digest")) for c in old.get("calls", [])
         if c.get("method") != "write_case"]
    b = [(c["method"], c.get("key"), c.get("digest")) for c in new.get("calls", [])
         if c.get("method") != "write_case"]
    return a != b


def write_summary(answers: list[dict], backend: str) -> None:
    from fraudagent.agent.telemetry import p95

    recs = []
    for a in answers:
        c, t = a["case"], a["agent_record"].get("telemetry", {})
        recs.append({"case": a["case_id"], "trigger": a["agent_record"]["trigger"]["type"],
                     "verdict": c["verdict"], "pattern": c["pattern"],
                     "p_fraud": c["fraud_probability"], "status": c["status"],
                     "exposure": c["exposure_usd"], "sar": a["sar"]["file"],
                     "final": "|".join(x["action"] for x in a["next_best_actions"]["final"]),
                     "margin_k": (a["agent_record"].get("proof") or {}).get("margin_k"),
                     "gate": bool((a["agent_record"].get("gate") or {}).get("applied")),
                     "conformal_set": ",".join((a["agent_record"].get("conformal") or {}).get(
                         "set", []) or []),
                     "hostile_text": bool((a["agent_record"].get("text_facts") or {}).get(
                         "hostile_text_detected")),
                     "tainted": bool((a["agent_record"].get("quality") or {}).get("tainted")),
                     "latency_s": a["latency_s"], "tokens": a["tokens"],
                     "tool_calls": a["tool_calls"], "cost_usd": t.get("llm_cost_usd", 0.0),
                     "attestations": a["agent_record"].get("n_attestations", 0)})
    df = pd.DataFrame(recs)
    PATHS.eval_out.mkdir(parents=True, exist_ok=True)
    df.to_csv(PATHS.eval_out / "run_summary.csv", index=False)
    lat = df["latency_s"].tolist()
    md = ["# Run summary", "",
          f"Backend `{backend}` · {len(df)} cases · generated by `benchmark/run_case.py --all`", "",
          f"- p95 latency: **{p95(lat)} s** (mean {sum(lat)/len(lat):.1f} s)",
          f"- tokens per case: mean {df['tokens'].mean():.0f}; cost per case: "
          f"${df['cost_usd'].mean():.4f}",
          f"- verdicts: {df['verdict'].value_counts().to_dict()}",
          f"- harmful actions (block/report): "
          f"{int(df['final'].str.contains('BLOCK|FILE_REPORT').sum())}",
          f"- proof gate applied: {int(df['gate'].sum())}",
          f"- hostile text flagged: {int(df['hostile_text'].sum())}; tainted: "
          f"{int(df['tainted'].sum())}", "",
          df.to_markdown(index=False), ""]
    (PATHS.eval_out / "run_summary.md").write_text("\n".join(md), encoding="utf-8")
    log(f"wrote eval/reports/run_summary.csv and run_summary.md (p95 {p95(lat)} s)")


if __name__ == "__main__":
    raise SystemExit(main())

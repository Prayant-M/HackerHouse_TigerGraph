"""Recorded tool I/O, fail-closed wrapping and the temporal canary check.

Every graph tool call the agent makes passes through `RecordingStore`:

* **Recorded.** Method, parameters, latency and a SHA-256 of the canonical
  response are logged; the response itself is stored by content hash under
  `.cache/recordings/`. `replay` serves those responses back, so a decision can
  be reproduced bit-for-bit offline, and `diff` says whether a rerun changed
  because the *data* changed (a response digest differs) or the *code* changed
  (same responses, different decision). This is also the regulator's view (C6):
  "what the agent saw at that moment" is the stored response.
* **Fail closed.** Any exception from the graph becomes `DependencyFailure`
  naming the step and the dependency. Nothing downstream catches it into a
  partial answer; `benchmark/run_case.py` turns it into a FAILED_DEPENDENCY
  record and exit code 2, and leaves the previous answer file untouched.
* **Temporal wall.** Any response containing a `CANARY-` id (future-dated
  transactions planted by `eval/canaries.py`) aborts the run: a query leaked
  data from after `as_of`.
* **Drills.** `DRILL_GRAPH_FAIL_AFTER=N` kills the connection after N calls,
  so the graph-down drill is reproducible without touching the workspace.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pickle
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

from ..config import PATHS

RECORDINGS = Path(os.environ.get("RECORDINGS_DIR", "") or PATHS.repo / ".cache" / "recordings")

# Everything an investigation may call on the store. Anything else (health,
# close, attributes) passes straight through unrecorded.
TOOL_METHODS = frozenset({
    "get_transaction", "card_history", "card_baseline", "customer_cards", "velocity_burst",
    "card_testing_probe", "threshold_structuring_probe", "device_fanout", "device_first_use",
    "region_profile", "out_of_region_probe", "recurring_charge_probe", "episode_window",
    "email_mismatch_profile", "shared_entity_ring", "peer_purchases", "card_community",
    "fraud_proximity", "hybrid_case_recall", "behavioural_neighbours", "policy_retrieve",
    "mixed_channel_probe", "write_case", "case_chain", "ring_at_asof", "origin_counts",
    "origin_touchers", "ring_exposure", "precedent_by_facts", "compromise_watch", "data_gaps",
    "behaviour_vector",
})
WRITE_METHODS = frozenset({"write_case"})


class DependencyFailure(RuntimeError):
    """A dependency failed; the run must stop without a verdict."""

    def __init__(self, dependency: str, step: str, detail: str) -> None:
        super().__init__(f"{dependency} failed at {step}: {detail}")
        self.dependency, self.step, self.detail = dependency, step, detail


class TemporalWallBreach(RuntimeError):
    pass


def _plain(v: Any) -> Any:
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {k: _plain(x) for k, x in dataclasses.asdict(v).items()}
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    if isinstance(v, (list, tuple, set, frozenset)):
        items = [_plain(x) for x in v]
        return sorted(items, key=str) if isinstance(v, (set, frozenset)) else items
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, np.ndarray):
        return [_plain(x) for x in v.tolist()]
    if isinstance(v, (np.floating, float)):
        return round(float(v), 6)
    if isinstance(v, np.integer):
        return int(v)
    return v


def canonical(v: Any) -> str:
    return json.dumps(_plain(v), sort_keys=True, separators=(",", ":"), default=str)


def digest(v: Any) -> str:
    return hashlib.sha256(canonical(v).encode("utf-8")).hexdigest()


def _unordered(v: Any) -> Any:
    v = _plain(v)
    if isinstance(v, dict):
        return {k: _unordered(x) for k, x in v.items()}
    if isinstance(v, list):
        items = [_unordered(x) for x in v]
        return sorted(items, key=lambda x: json.dumps(x, sort_keys=True, default=str))
    return v


def digest_unordered(v: Any) -> str:
    """Digest that ignores list order. Graph set accumulators come back in
    arbitrary order, so attest-verify compares *content*, not order."""
    return hashlib.sha256(json.dumps(_unordered(v), sort_keys=True, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


class RecordingStore:
    """Transparent proxy over a GraphStore. See module docstring."""

    def __init__(self, inner: Any, case_id: str, mode: str = "record",
                 recording: dict[str, Any] | None = None) -> None:
        self._inner = inner
        self._case_id = case_id
        self._mode = mode
        self.calls: list[dict[str, Any]] = []
        self._replay_queue: dict[str, list[dict[str, Any]]] = {}
        if mode == "replay":
            for c in (recording or {}).get("calls", []):
                self._replay_queue.setdefault(c["key"], []).append(c)
        fail = os.environ.get("DRILL_GRAPH_FAIL_AFTER", "").strip()
        self._fail_after = int(fail) if fail.isdigit() else None
        self._dir = RECORDINGS / case_id
        if mode == "record":
            self._dir.mkdir(parents=True, exist_ok=True)

    # proxied attributes the agent reads (backend, call_count, graph ...)
    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if self._mode == "replay" and name in TOOL_METHODS:
            # Offline: every tool is served from the recording, so the stand-in
            # store need not implement it (and nothing can reach a live graph).
            def replayed(*args: Any, **kwargs: Any) -> Any:
                return self._invoke(name, None, args, kwargs)
            return replayed
        attr = getattr(self._inner, name)
        if name not in TOOL_METHODS or not callable(attr):
            return attr

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            return self._invoke(name, attr, args, kwargs)
        return wrapped

    @property
    def call_count(self) -> int:
        return getattr(self._inner, "call_count", len(self.calls))

    def _invoke(self, name: str, fn: Any, args: tuple, kwargs: dict) -> Any:
        params = canonical({"args": list(args), "kwargs": kwargs})
        key = hashlib.sha256(f"{name}:{params}".encode()).hexdigest()[:24]
        seq = len(self.calls) + 1
        if self._mode == "replay":
            queue = self._replay_queue.get(key)
            if not queue and name in WRITE_METHODS | {"case_chain"}:
                # The write payload carries wall-clock fields (latency), so it
                # never hashes the same twice; offline, the write and its
                # read-back are matched by method and order, not by payload.
                queue = [c for k, cs in self._replay_queue.items() for c in cs
                         if c["method"] == name][:1]
                if queue:
                    self._replay_queue[queue[0]["key"]].remove(queue[0])
            if not queue:
                raise DependencyFailure("recording", name,
                                        f"no recorded response for {name}{params[:160]}")
            rec = queue.pop(0)
            if name in WRITE_METHODS:
                result = rec.get("result_inline")
            else:
                result = pickle.loads((RECORDINGS / self._case_id /
                                       f"{rec['digest']}.pkl").read_bytes())
            self.calls.append({**rec, "seq": seq, "replayed": True})
            return result

        if self._fail_after is not None and seq > self._fail_after:
            self.calls.append({"seq": seq, "method": name, "key": key, "ok": False,
                               "error": "drill: graph connection killed"})
            raise DependencyFailure("graph", name,
                                    f"drill: connection killed after {self._fail_after} calls")
        t0 = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except DependencyFailure:
            raise
        except Exception as exc:
            self.calls.append({"seq": seq, "method": name, "key": key, "ok": False,
                               "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                               "latency_ms": round((time.perf_counter() - t0) * 1000, 1)})
            raise DependencyFailure("graph", name, f"{type(exc).__name__}: {str(exc)[:300]}") \
                from exc
        ms = round((time.perf_counter() - t0) * 1000, 1)
        body = canonical(result)
        if "CANARY-" in body:
            raise TemporalWallBreach(
                f"{name} returned a future-dated canary transaction; a query leaked data "
                f"from after as_of")
        d = hashlib.sha256(body.encode("utf-8")).hexdigest()
        rec = {"seq": seq, "method": name, "key": key, "params": params[:2000],
               "digest": d, "latency_ms": ms, "ok": True, "bytes": len(body)}
        if name in WRITE_METHODS:
            rec["result_inline"] = _plain(result)
        else:
            blob = self._dir / f"{d}.pkl"
            if not blob.exists():
                blob.write_bytes(pickle.dumps(result))
        self.calls.append(rec)
        return result

    # ------------------------------------------------------------- export ----
    def index(self) -> dict[str, Any]:
        return {"case_id": self._case_id, "mode": self._mode,
                "n_calls": len(self.calls),
                "calls": [{k: v for k, v in c.items() if k != "result_inline"} | (
                    {"result_inline": c["result_inline"]} if "result_inline" in c else {})
                    for c in self.calls]}

    def save_index(self, path: Path | None = None) -> Path:
        path = path or (self._dir / "index.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.index(), indent=1, default=str), encoding="utf-8")
        return path


def load_recording(case_id: str) -> dict[str, Any] | None:
    p = RECORDINGS / case_id / "index.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

"""The drift gate the loaders check (C12).

`ingest/00_drift.py` (file drift) and `ingest/graph_schema_diff.py` (graph
schema drift) write proposals to data/drift/. A proposal without its
`.approved` twin is pending, and while any is pending the loaders refuse to
run: new data is not acted on until a fraud manager approves the change.

`ingest/byo.py` sets DRIFT_GATE=off for its isolated ingest, because a foreign
dataset carries its own mapping approval and never touches the bank's data.
"""

from __future__ import annotations

import os
import sys

from ..config import PATHS

DRIFT_DIR = PATHS.repo / "data" / "drift"
EXIT_PENDING = 4


# The raw files the loaders read (config.Paths). A file-drift proposal about any
# other file, e.g. a one-off `00_drift.py --old a --new b` comparison, cannot
# change what is loaded, so it does not hold the loaders.
LOADED = {"transactions.csv", "transactions_2017q1.csv", "identity.csv", "identity_2017q1.csv",
          "closed_cases_history.csv", "case_pack.csv", "case_pack_final.csv"}


def _files(p) -> tuple[str, set[str]] | None:
    import json

    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("created_at", ""), {r["new"] for r in d.get("reports", [])}
    except Exception:  # noqa: BLE001 - an unreadable proposal holds the loaders
        return None


def pending() -> list[str]:
    """File-drift proposals hold the loaders unless approved, about files no
    loader reads, or superseded: a later approved proposal covers the same
    files (the same diff recomputed elsewhere, e.g. another pandas version,
    gets a new id; the fraud manager approved the newer one)."""
    approved = [f for p in DRIFT_DIR.glob("DRIFT-*.json")
                if p.with_suffix(".approved").exists() and (f := _files(p))]
    out = [p.stem for p in DRIFT_DIR.glob("GSCHEMA-*.json")
           if not p.with_suffix(".approved").exists()]
    for p in DRIFT_DIR.glob("DRIFT-*.json"):
        if p.with_suffix(".approved").exists():
            continue
        f = _files(p)
        if f is None or not f[1]:
            out.append(p.stem)
            continue
        at, files = f
        if not files & LOADED or any(files <= fs and a > at for a, fs in approved):
            continue
        out.append(p.stem)
    return sorted(out)


def require_open(step: str) -> None:
    """Exit 4 from a loader while a drift proposal waits for approval."""
    if os.environ.get("DRIFT_GATE", "").lower() == "off":
        print(f"[{step}] drift gate bypassed (DRIFT_GATE=off: isolated foreign-dataset ingest)",
              flush=True)
        return
    waiting = pending()
    if waiting:
        print(f"[{step}] refusing to load: drift proposal(s) {', '.join(waiting)} wait for a "
              f"fraud manager. Approve with `python ingest/00_drift.py --auto --approve --token "
              f"<fraud-manager token>` (graph schema: ingest/graph_schema_diff.py ... --approve)",
              flush=True)
        sys.exit(EXIT_PENDING)

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


def pending() -> list[str]:
    return sorted(p.stem for pat in ("DRIFT-*.json", "GSCHEMA-*.json")
                  for p in DRIFT_DIR.glob(pat) if not p.with_suffix(".approved").exists())


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

"""Install the schema, loading jobs, queries and algorithms into TigerGraph.

Idempotent and safe to re-run: the schema job uses `ADD`, the queries use
`CREATE OR REPLACE`, and the loading jobs upsert.

    python graph/install.py --step all          # everything, in order
    python graph/install.py --step schema
    python graph/install.py --step vectors
    python graph/install.py --step load
    python graph/install.py --step queries
    python graph/install.py --step projections
    python graph/install.py --step verify
    python graph/install.py --dry-run           # print the plan, touch nothing

`verify` is not optional in practice. TigerGraph builds the HNSW index
asynchronously, so vectors that have not finished indexing silently return no
search results, and RESTPP does not error on a misspelled vector attribute name
— it accepts the load and hands you an empty index. Both failure modes look
exactly like "the agent found no prior cases", which is the worst possible way
to discover them.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Windows consoles still default to cp1252, which cannot encode the arrows and
# box characters used below; without this a clean run dies on its own log line.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - non-reconfigurable stream
    pass


from fraudagent.config import PATHS, TG  # noqa: E402

GRAPH_DIR = ROOT / "graph"
STAGED_CSV = PATHS.staged / "graph_csv"

STEPS = ["schema", "vectors", "load", "queries", "projections", "verify"]

LOADING_JOBS = [
    ("load_entities", ["customers.csv", "cards.csv", "devices.csv", "regions.csv",
                       "email_domains.csv"]),
    ("load_transactions", ["transactions.csv"]),
    ("load_card_ownership", ["cards.csv"]),
    ("load_next_txn", ["next_txn.csv"]),
    ("load_closed_cases", ["closed_cases.csv", "closed_case_txns.csv",
                           "closed_case_connected.csv", "closed_case_devices.csv"]),
    ("load_policy", ["policy_docs.csv", "patterns.csv"]),
    ("load_behaviour_vectors", ["behaviour_emb.csv"]),
    ("load_analysts", ["analysts.csv"]),
]


def log(msg: str) -> None:
    print(f"[install] {msg}", flush=True)


def connect():
    import pyTigerGraph as tg

    if not TG.configured:
        raise SystemExit(
            "TigerGraph is not configured. Set TG_HOST and TG_PASSWORD (or TG_SECRET) in .env.\n"
            "See SETUP_REQUIRED_FROM_YOU.md §2 for exactly which values and where to get them.")
    conn = tg.TigerGraphConnection(
        host=TG.host, graphname=TG.graph, username=TG.username, password=TG.password,
        restppPort=TG.restpp_port, gsPort=TG.gsql_port)
    if TG.secret:
        conn.getToken(TG.secret)
    log(f"connected to {TG.host} (graph {TG.graph})")
    return conn


def run_gsql(conn, path: Path, dry: bool) -> None:
    text = path.read_text(encoding="utf-8")
    log(f"  {path.relative_to(ROOT)}  ({len(text.splitlines())} lines)")
    if dry:
        return
    out = conn.gsql(text)
    lowered = str(out).lower()
    if "error" in lowered or "failed" in lowered:
        log(f"  !! {path.name}:\n{out}")
        raise SystemExit(f"GSQL failed in {path.name}")


def step_schema(conn, dry: bool) -> None:
    log("schema")
    run_gsql(conn, GRAPH_DIR / "ddl" / "01_schema.gsql", dry)


def step_vectors(conn, dry: bool) -> None:
    log("vector attributes (TigerVector, requires TigerGraph 4.2+)")
    run_gsql(conn, GRAPH_DIR / "ddl" / "02_vectors.gsql", dry)


def step_queries(conn, dry: bool) -> None:
    log("investigation queries")
    for path in sorted((GRAPH_DIR / "queries").glob("*.gsql")):
        run_gsql(conn, path, dry)
    if not dry:
        log("  installing…")
        print(conn.gsql(f"USE GRAPH {TG.graph}\nINSTALL QUERY ALL"))


def step_load(conn, dry: bool) -> None:
    if not STAGED_CSV.exists():
        raise SystemExit(f"{STAGED_CSV} is missing — run `python ingest/06_stage_graph_csv.py`")
    log("loading jobs")
    run_gsql(conn, GRAPH_DIR / "loading" / "03_loading_jobs.gsql", dry)
    for job, files in LOADING_JOBS:
        paths = [STAGED_CSV / f for f in files]
        missing = [p.name for p in paths if not p.exists()]
        if missing:
            log(f"  skipping {job}: missing {missing}")
            continue
        size = sum(p.stat().st_size for p in paths) / 1e6
        log(f"  {job}  ({size:.1f} MB)")
        if dry:
            continue
        t0 = time.time()
        # A job with several DEFINE FILENAME sources is fed one file at a time
        # through the same job; RESTPP matches each upload to its filename.
        for path in paths:
            conn.runLoadingJobWithFile(str(path), "ANY", job, timeout=3_600_000,
                                       sizeLimit=2_000_000_000)
        log(f"    done in {time.time()-t0:.0f}s")


def step_projections(conn, dry: bool) -> None:
    log("derived projections and graph data science")
    run_gsql(conn, GRAPH_DIR / "algorithms" / "04_projections.gsql", dry)
    if not dry:
        log("  building CO_OCCURS_WITH…")
        print(conn.runInstalledQuery("build_card_co_occurrence",
                                     {"max_device_cards": 150}, timeout=3_600_000))


def step_verify(conn, dry: bool) -> None:
    """Counts, then the vector index, then a real traversal."""
    log("verify")
    if dry:
        return
    counts = conn.getVertexCount("*")
    log(f"  vertices: {counts}")
    for v, minimum in [("Transaction", 500_000), ("Card", 10_000),
                       ("ClosedCase", 5_000), ("PolicyDoc", 30)]:
        n = counts.get(v, 0)
        status = "ok" if n >= minimum else "LOW"
        log(f"    {v:<14} {n:>9,}  {status}")
    log(f"  edges: {conn.getEdgeCount('*')}")

    # The silent failure: vectors accepted, index not ready, search returns
    # nothing, memory recall looks merely "unlucky".
    try:
        res = conn.runInstalledQuery(
            "hybrid_case_recall",
            {"query_vec": [0.0] * 384, "entity_ids": [], "as_of": "2016-12-31 23:59:59",
             "k": 3}, timeout=60_000)
        n = len(res[0].get("result", [])) if res else 0
        log(f"  hybrid_case_recall returned {n} rows "
            f"{'ok' if n else '— EMPTY: the HNSW index is probably still building'}")
    except Exception as exc:
        log(f"  hybrid_case_recall failed: {exc}")

    try:
        res = conn.runInstalledQuery("card_baseline",
                                     {"card_id": "C12382-K1", "cutoff": "2016-12-05 01:55:28"})
        log(f"  card_baseline spot check: n_txns={res[0].get('n_txns') if res else 'n/a'}")
    except Exception as exc:
        log(f"  card_baseline failed: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", default="all", choices=STEPS + ["all"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = None if args.dry_run else connect()
    steps = STEPS if args.step == "all" else [args.step]
    handlers = {"schema": step_schema, "vectors": step_vectors, "load": step_load,
                "queries": step_queries, "projections": step_projections,
                "verify": step_verify}
    for s in steps:
        handlers[s](conn, args.dry_run)
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

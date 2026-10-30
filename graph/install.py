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

STEPS = ["schema", "vectors", "load", "queries", "projections", "algorithms", "final_round",
         "verify"]
FINAL_QUERIES = ["ring_at_asof", "origin_counts", "origin_touchers", "ring_exposure",
                 "precedent_by_facts", "compromise_watch", "data_gaps", "case_write",
                 "governance_write"]

# (job, [(DEFINE FILENAME variable, staged csv), ...]). RESTPP routes each
# upload to the job's filename variable, so the tag must match the GSQL.
LOADING_JOBS = [
    ("load_entities", [("f_customer", "customers.csv"), ("f_card", "cards.csv"),
                       ("f_device", "devices.csv"), ("f_region", "regions.csv"),
                       ("f_email", "email_domains.csv")]),
    ("load_transactions", [("f_txn", "transactions.csv")]),
    ("load_card_ownership", [("f_card", "cards.csv")]),
    ("load_next_txn", [("f_next", "next_txn.csv")]),
    ("load_closed_cases", [("f_cc", "closed_cases.csv"), ("f_cc_txn", "closed_case_txns.csv"),
                           ("f_cc_conn", "closed_case_connected.csv"),
                           ("f_cc_dev", "closed_case_devices.csv")]),
    ("load_policy", [("f_doc", "policy_docs.csv"), ("f_pattern", "patterns.csv")]),
    ("load_behaviour_vectors", [("f_beh", "behaviour_emb.csv")]),
    ("load_analysts", [("f_a", "analysts.csv")]),
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
    try:
        out = conn.gsql(text)
    except Exception as exc:  # pyTigerGraph raises on some failures itself
        out = f"failed: {exc}"
    # an install summary reports "failed: 0" on success
    lowered = str(out).lower().replace("failed: 0", "")
    # GSQL reports refusals as plain prose, not as errors: a missing privilege,
    # a reserved word or a graph that was never created would otherwise pass
    # silently. Plain "error" is too broad — float-comparison warnings say
    # "error margin" on queries that compiled fine.
    markers = ("syntax error", "check error", "semantic check fails", "failed",
               "does not have the permission", "does not exist", "reserved keyword",
               "encountered \"", "was expecting", "no viable alternative",
               "saved as draft", "type check error")
    if "already exists" in lowered and not any(
            m in lowered for m in ("syntax error", "check error", "reserved keyword",
                                   "was expecting", "saved as draft")):
        # Re-running an install on a graph that already has these objects is
        # the normal case after a workspace restore: keep going.
        log(f"  {path.name}: objects already exist, kept")
        return
    if any(m in lowered for m in markers):
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
        paths = [(tag, STAGED_CSV / f) for tag, f in files]
        missing = [p.name for _, p in paths if not p.exists()]
        if missing:
            log(f"  skipping {job}: missing {missing}")
            continue
        size = sum(p.stat().st_size for _, p in paths) / 1e6
        log(f"  {job}  ({size:.1f} MB)")
        if dry:
            continue
        t0 = time.time()
        # A job with several DEFINE FILENAME sources is fed one file at a time
        # through the same job; RESTPP matches each upload to its filename.
        for tag, path in paths:
            upload(conn, job, tag, path)
        log(f"    done in {time.time()-t0:.0f}s")


CHUNK_BYTES = 20_000_000


def upload(conn, job: str, tag: str, path: Path) -> None:
    """Post one staged CSV to a loading job, without its header row.

    The jobs name columns through DEFINE HEADER (Savanna has no server-side
    file to read a header from), and with a user-defined header the first
    line would otherwise be loaded as data. Large files are sent in chunks
    split on line boundaries — only the numeric files are that large, so no
    quoted field spans a chunk boundary."""
    def post(data: str) -> None:
        # Savanna occasionally resets a long upload; loading is an upsert, so a
        # chunk can be resent safely.
        for attempt in range(4):
            try:
                res = conn.runLoadingJobWithData(data, tag, job, timeout=3_600_000,
                                                 sizeLimit=2_000_000_000)
                break
            except Exception as exc:
                if attempt == 3:
                    raise
                log(f"      {tag}: upload failed ({str(exc)[:80]}); retry {attempt + 1}")
                time.sleep(15 * (attempt + 1))
        stats = res[0].get("statistics", res[0]) if isinstance(res, list) and res else res
        log(f"      {tag}: {str(stats)[:160]}")

    with path.open(encoding="utf-8", newline="") as fh:
        fh.readline()  # header
        if path.stat().st_size <= CHUNK_BYTES:
            post(fh.read())
            return
        buf, size = [], 0
        for line in fh:
            buf.append(line)
            size += len(line)
            if size >= CHUNK_BYTES:
                post("".join(buf))
                buf, size = [], 0
        if buf:
            post("".join(buf))


def step_projections(conn, dry: bool) -> None:
    log("derived projections and graph data science")
    run_gsql(conn, GRAPH_DIR / "algorithms" / "04_projections.gsql", dry)
    if not dry:
        log("  installing projection queries…")
        print(conn.gsql(f"USE GRAPH {TG.graph}\n"
                        "INSTALL QUERY build_card_co_occurrence, build_anon_projection, ring_candidates"))
        log("  building CO_OCCURS_WITH…")
        print(conn.runInstalledQuery("build_card_co_occurrence",
                                     {"max_device_cards": 150}, timeout=3_600_000))


def step_algorithms(conn, dry: bool) -> None:
    """GDS library WCC + PageRank over the anonymous-proxy card projection."""
    log("graph algorithms (GDBMS_ALGO: WCC, PageRank)")
    if not dry:
        log("  building ANON_CO_OCCURS…")
        print(conn.runInstalledQuery("build_anon_projection", {}, timeout=3_600_000))
    run_gsql(conn, GRAPH_DIR / "algorithms" / "05_graph_algorithms.gsql", dry)


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


def step_final_round(conn, dry: bool) -> None:
    """Final-round additions: schema change, the new queries, and the
    ClosedCase.fact_mask load (loader credentials, never the agent's)."""
    import json

    import pandas as pd

    log("final-round schema change (additive)")
    vc = conn.getVertexCount("ClosedCase") if not dry else 0
    try:
        has = "fact_mask" in json.dumps(conn.getSchema(force=True)) if not dry else False
    except Exception:
        has = False
    if not has:
        run_gsql(conn, GRAPH_DIR / "ddl" / "06_final_round.gsql", dry)
    log("final-round queries")
    for q in FINAL_QUERIES:
        run_gsql(conn, GRAPH_DIR / "queries" / f"{q}.gsql", dry)
    if not dry:
        print(conn.gsql(f"USE GRAPH {TG.graph}\nINSTALL QUERY {', '.join(FINAL_QUERIES)}")[-400:])
    facts = PATHS.staged / "closed_case_facts.parquet"
    if facts.exists() and not dry:
        df = pd.read_parquet(facts, columns=["case_id", "stratum", "fact_mask"])
        df = df[df["stratum"] == "closed_case"]
        rows = [(r.case_id, {"fact_mask": int(r.fact_mask), "fact_replayed": True})
                for r in df.itertuples()]
        for i in range(0, len(rows), 500):
            conn.upsertVertices("ClosedCase", rows[i:i + 500])
        log(f"fact_mask loaded on {len(rows)} of {vc} ClosedCase vertices")
    log("agent least-privilege user: see graph/rbac.gsql (run once as superuser)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", default="all", choices=STEPS + ["all"])
    ap.add_argument("--from", dest="from_step", choices=STEPS,
                    help="resume: run this step and every step after it")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = None if args.dry_run else connect()
    steps = STEPS if args.step == "all" else [args.step]
    if args.from_step:
        steps = STEPS[STEPS.index(args.from_step):]
    handlers = {"schema": step_schema, "vectors": step_vectors, "load": step_load,
                "queries": step_queries, "projections": step_projections,
                "algorithms": step_algorithms, "final_round": step_final_round,
                "verify": step_verify}
    for s in steps:
        handlers[s](conn, args.dry_run)
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

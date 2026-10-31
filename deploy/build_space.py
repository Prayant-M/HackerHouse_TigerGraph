"""Assemble a read-only analyst console bundle for public hosting.

    python deploy/build_space.py                 # → build/space/
    python deploy/build_space.py --out some/dir

The bundle is a Docker app (Hugging Face Spaces, Render, Railway, Fly — any
host that builds a Dockerfile). It contains the answer files, the
autonomous-monitoring results, the policy text, the measured likelihood ratios
and a snapshot of graph health and the answer audit, taken now from this
machine. It contains no credentials, no `.env`, and none of the 700 MB of
staged transaction data; the console runs with CONSOLE_READONLY=1, so live
re-runs are refused and approvals are never written to a graph.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

SNAPSHOT = ROOT / "ui" / "snapshot"

DOCKERFILE = """\
FROM python:3.11-slim

# Hugging Face Spaces runs containers as uid 1000; other hosts don't mind.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH \\
    CONSOLE_READONLY=1 GRAPH_BACKEND=local AGENT_USE_LLM=0 \\
    HOST=0.0.0.0 PORT=7860 PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
COPY --chown=user . .

EXPOSE 7860
CMD ["python", "ui/server.py"]
"""

REQUIREMENTS = """\
fastapi>=0.110
uvicorn>=0.29
pandas>=2.2
"""

SPACE_README = """\
---
title: FraudGraph Analyst Console
emoji: 🕵️
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: Agentic fraud investigation on TigerGraph, read-only demo
---

# FraudGraph Agent: analyst console (read-only)

A public, read-only copy of the analyst console from the TigerGraph × Hacker
House Goa 2026 agentic fraud investigation project. It shows the benchmark
investigations exactly as the agent wrote them: evidence and how
each piece moved the probability, the case subgraph, similar past cases, the
hash-chained audit trail, the approval queue, and the cases the agent raised
on its own.

The agent itself ran against TigerGraph Savanna through the TigerGraph MCP
server. This copy serves a snapshot of those results, so it needs no graph
connection or API key. Live re-runs are disabled here; clone the repository
and run `python ui/server.py` to watch the agent investigate.
"""

GITIGNORE = "__pycache__/\n*.pyc\n"


def fetch_health(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def capture_snapshot(console_url: str) -> None:
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    h = fetch_health(console_url)
    if h is None:
        from fraudagent.graphstore import get_store
        h = {"graph": get_store().health()}
    g = dict(h.get("graph", {}))
    for k in ("host", "mcp_calls", "mcp_fallbacks"):   # per-process counters and the private host
        g.pop(k, None)
    ids = h.get("graph_case_ids")
    if ids is None:  # read the case ids straight from the graph
        try:
            from fraudagent.graphstore.tigergraph import TigerGraphStore
            ids = sorted(v["v_id"] for v in TigerGraphStore().conn.getVertices(
                "FraudCase", select="status", limit=10000))
        except Exception as exc:  # noqa: BLE001
            print(f"[space] could not read case ids from the graph: {exc}")
    (SNAPSHOT / "health.json").write_text(json.dumps(
        {"captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "graph": g,
         "graph_case_ids": ids}, indent=2), encoding="utf-8")

    from audit_answers import audit
    from fraudagent.config import PATHS
    rows, total = audit(PATHS.cases_out, set(ids) if ids is not None else None)
    (SNAPSHOT / "audit.json").write_text(json.dumps({"rows": rows, "issues": total},
                                                    indent=2, default=str), encoding="utf-8")
    print(f"[space] snapshot: backend={g.get('backend')} "
          f"transactions={g.get('vertex_counts', {}).get('Transaction')} audit issues={total}")


def copy_tree(src: Path, dst: Path, patterns: tuple[str, ...] = ("*",)) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for pat in patterns:
        for f in src.glob(pat):
            if f.is_file():
                shutil.copy2(f, dst / f.name)


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(ROOT / "src" / "fraudagent", out / "src" / "fraudagent",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "ui", out / "ui",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "_probe.html"))
    copy_tree(ROOT / "cases", out / "cases", ("HHF-*.json", "HHG-*.json"))
    copy_tree(ROOT / "benchmark" / "autonomous", out / "benchmark" / "autonomous", ("AUTO-*.json",))
    copy_tree(ROOT / "data" / "policy", out / "data" / "policy")
    (out / "data" / "staged").mkdir(parents=True)
    shutil.copy2(ROOT / "data" / "staged" / "likelihood_ratios.json", out / "data" / "staged")
    (out / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
    (out / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")
    (out / "README.md").write_text(SPACE_README, encoding="utf-8")
    (out / ".gitignore").write_text(GITIGNORE, encoding="utf-8")

    leaked = [p for p in out.rglob("*") if p.name == ".env" or p.suffix == ".parquet"]
    assert not leaked, f"refusing to ship {leaked}"
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"[space] bundle at {out} · {size / 1e6:.1f} MB")


STATIC_README = SPACE_README.replace("sdk: docker\napp_port: 7860\n", "sdk: static\napp_file: index.html\n")


def build_static(out: Path) -> None:
    """Pre-render every read-only API response to JSON beside the page.

    No server at all: any static host (Hugging Face static Spaces, GitHub
    Pages, Netlify) can serve the result, including under a sub-path.
    """
    import os
    os.environ["CONSOLE_READONLY"] = "1"
    sys.path.insert(0, str(ROOT / "ui"))
    import server  # noqa: WPS433 - reads CONSOLE_READONLY at import

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "ui" / "static", out / "static",
                    ignore=shutil.ignore_patterns("_probe.html", "index.html"))
    page = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    page = page.replace('href="/static/', 'href="static/').replace('src="/static/', 'src="static/')
    page = page.replace("<html ", '<html data-static="1" ', 1)
    page = page.replace('href="/docs"', 'href="api-docs/"')
    assert 'data-static="1"' in page, "index.html has no <html ...> tag to mark"
    (out / "index.html").write_text(page, encoding="utf-8")

    def clean(x):
        # Python's json writes NaN, which no browser will parse; the page reads null.
        if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
            return None
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        return x

    def dump(rel: str, data) -> None:
        f = out / f"{rel}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(clean(data), default=str, allow_nan=False), encoding="utf-8")

    dump("api/health", server.health())
    cases = server.cases()
    dump("api/cases", cases)
    for c in cases:
        dump(f"api/cases/{c['case_id']}", server.case_detail(c["case_id"]))
        dump(f"api/graph/{c['case_id']}", server.case_graph(c["case_id"]))
        dump(f"api/replay/{c['case_id']}", server.regulator_replay(c["case_id"]))
        dump(f"api/lifecycle/{c['case_id']}", server.lifecycle_view(c["case_id"]))
        dump(f"api/ring/{c['case_id']}", server.ring_replay(c["case_id"]))
    dump("api/approvals", server.approvals())
    dump("api/calibration", server.calibration())
    dump("api/policy", server.policy())
    dump("api/audit", server.answer_audit())
    dump("api/autonomous", server.autonomous())
    (out / "README.md").write_text(STATIC_README, encoding="utf-8")

    leaked = [p for p in out.rglob("*") if p.name == ".env" or p.suffix == ".parquet"]
    assert not leaked, f"refusing to ship {leaked}"
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"[space] static site at {out} · {size / 1e6:.1f} MB")


# ------------------------------------------------------------------ live ----
# The real agent, not a snapshot: it investigates against TigerGraph through the
# MCP server and writes prose with the configured model. Credentials are never
# in the bundle; the host injects them as secrets (see docs/DEPLOY.md).
LIVE_DOCKERFILE = """\
FROM python:3.11-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH \\
    HF_HOME=/home/user/.cache/huggingface \\
    GRAPH_BACKEND=tigergraph GRAPH_STRICT=1 TG_VIA_MCP=1 \\
    CONSOLE_RUN_AUTH=1 CONSOLE_MAX_LIVE=1 \\
    EMBEDDING_PROVIDER=sentence-transformers \\
    EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 EMBEDDING_DIM=384 \\
    TG_LOAD_VERSION="{load_version}" \\
    HOST=0.0.0.0 PORT=7860 PYTHONUNBUFFERED=1
WORKDIR /home/user/app

# CPU-only torch first, so sentence-transformers does not pull the CUDA build.
RUN pip install --no-cache-dir --user torch --index-url https://download.pytorch.org/whl/cpu
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
# Bake the embedding model in, so a cold start does not download it.
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('sentence-transformers/all-MiniLM-L6-v2')"
COPY --chown=user . .

EXPOSE 7860
CMD ["python", "ui/server.py"]
"""

LIVE_README = SPACE_README.replace(
    "title: FraudGraph Analyst Console", "title: FraudGraph Agent (live)").replace(
    "short_description: Agentic fraud investigation on TigerGraph, read-only demo",
    "short_description: Agentic fraud investigation on TigerGraph, live agent").split(
    "# FraudGraph Agent", 1)[0] + """\
# FraudGraph Agent: live analyst console

The agent itself, running: press **Re-run live** on a case and it investigates
against TigerGraph Savanna through the TigerGraph MCP server, streaming each
step. Decisions come from the deterministic core; the model writes prose only.

Live runs need a token (ask the owner); one run at a time. Browsing the answer
files, evidence, audit trail and approval queue needs none. Setup and secrets:
`docs/DEPLOY.md` in the repository.
"""

# Small calibration artefacts the agent reads on the TigerGraph path. The 700 MB
# of staged transactions stay behind: the graph serves those.
LIVE_STAGED = ("likelihood_ratios.json", "conformal.json", "conformal_support.npy",
               "proof_gate.json", "closed_case_facts.parquet", "embedder.pkl")
LIVE_PARQUET_OK = {"closed_case_facts.parquet", "behaviour_emb.parquet"}


def build_live(out: Path) -> None:
    import pandas as pd

    from fraudagent.config import PATHS
    from fraudagent.core.attest import _staged_version

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    skip = shutil.ignore_patterns("__pycache__", "*.pyc", "_probe.html")
    shutil.copytree(ROOT / "src" / "fraudagent", out / "src" / "fraudagent", ignore=skip)
    shutil.copytree(ROOT / "ui", out / "ui", ignore=skip)
    for d in ("queries", "algorithms"):
        shutil.copytree(ROOT / "graph" / d, out / "graph" / d, ignore=skip)
    copy_tree(ROOT / "benchmark", out / "benchmark", ("*.py",))
    copy_tree(ROOT / "benchmark" / "autonomous", out / "benchmark" / "autonomous", ("AUTO-*.json",))
    copy_tree(ROOT / "cases", out / "cases", ("HHF-*.json", "HHG-*.json"))
    for d in ("policy", "detectors", "schema", "lifecycle", "approvals"):
        if (ROOT / "data" / d).exists():
            shutil.copytree(ROOT / "data" / d, out / "data" / d, ignore=skip)
    shutil.copy2(ROOT / "data" / "manifest.json", out / "data" / "manifest.json")
    pack = PATHS.case_pack_csv
    (out / pack.relative_to(ROOT)).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pack, out / pack.relative_to(ROOT))

    staged = out / "data" / "staged"
    staged.mkdir(parents=True)
    for name in LIVE_STAGED:
        shutil.copy2(PATHS.staged / name, staged / name)
    # Behaviour vectors for the pack's flagged transactions only (160 MB → KB).
    flagged = set(pd.read_csv(pack, dtype={"flagged_txn_id": str})["flagged_txn_id"])
    b = pd.read_parquet(PATHS.behaviour_parquet)
    b[b["txn_id"].astype(str).isin(flagged)].to_parquet(staged / "behaviour_emb.parquet")

    # The answer files' data_snapshot hashes the staged sizes; pin it, so a live
    # re-run attests against the same load the files were written from.
    load = os.environ.get("TG_LOAD_VERSION", "") or _staged_version()
    (out / "Dockerfile").write_text(LIVE_DOCKERFILE.replace("{load_version}", load), encoding="utf-8")
    shutil.copy2(ROOT / "requirements.txt", out / "requirements.txt")
    (out / "README.md").write_text(LIVE_README, encoding="utf-8")
    (out / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (out / ".dockerignore").write_text(".env\n.cache/\n__pycache__/\n", encoding="utf-8")

    leaked = [p for p in out.rglob("*") if p.name in {".env", "approval_signing_key"}
              or (p.suffix == ".parquet" and p.name not in LIVE_PARQUET_OK)]
    assert not leaked, f"refusing to ship {leaked}"
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"[live] bundle at {out} · {size / 1e6:.1f} MB · TG_LOAD_VERSION={load}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--static", action="store_true",
                    help="export a server-less static site instead of a Docker app")
    ap.add_argument("--live", action="store_true",
                    help="a Docker app that runs the real agent (secrets come from the host)")
    ap.add_argument("--console", default="http://127.0.0.1:8080",
                    help="a running live console to take the health snapshot from")
    ap.add_argument("--keep-snapshot", action="store_true",
                    help="reuse ui/snapshot/ instead of capturing a new one")
    args = ap.parse_args()
    if args.live:
        build_live(Path(args.out or ROOT / "build" / "live"))
        return 0
    if not args.keep_snapshot:
        capture_snapshot(args.console)
    if args.static:
        build_static(Path(args.out or ROOT / "build" / "static"))
    else:
        build(Path(args.out or ROOT / "build" / "space"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

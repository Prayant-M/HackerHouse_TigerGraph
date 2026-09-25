"""Assemble a read-only analyst console bundle for public hosting.

    python deploy/build_space.py                 # → build/space/
    python deploy/build_space.py --out some/dir

The bundle is a Docker app (Hugging Face Spaces, Render, Railway, Fly — any
host that builds a Dockerfile). It contains the twenty answer files, the
autonomous-monitoring results, the policy text, the measured likelihood ratios
and a snapshot of graph health and the answer audit, taken now from this
machine. It contains no credentials, no `.env`, and none of the 700 MB of
staged transaction data; the console runs with CONSOLE_READONLY=1, so live
re-runs are refused and approvals are never written to a graph.
"""

from __future__ import annotations

import argparse
import json
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
House Goa 2026 agentic fraud investigation project. It shows the twenty
benchmark investigations exactly as the agent wrote them: evidence and how
each piece moved the probability, the case subgraph, similar past cases, the
hash-chained audit trail, the approval queue, the scoreboard with its answer
audit, and the cases the agent raised on its own.

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
    (SNAPSHOT / "health.json").write_text(json.dumps(
        {"captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "graph": g},
        indent=2), encoding="utf-8")

    from audit_answers import audit
    from fraudagent.config import PATHS
    rows, total = audit(PATHS.cases_out)
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
    copy_tree(ROOT / "cases", out / "cases", ("HHG-*.json",))
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "build" / "space"))
    ap.add_argument("--console", default="http://127.0.0.1:8080",
                    help="a running live console to take the health snapshot from")
    ap.add_argument("--keep-snapshot", action="store_true",
                    help="reuse ui/snapshot/ instead of capturing a new one")
    args = ap.parse_args()
    if not args.keep_snapshot:
        capture_snapshot(args.console)
    build(Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

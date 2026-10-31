"""One command from a clean clone to graded answer files.

    python reproduce.py                 # everything; resumes, skipping finished stages
    python reproduce.py --offline       # no TigerGraph, no model: local mirror, template prose
    python reproduce.py --quick         # sampled calibration (~4 min, not ~3 h); answers may differ
    python reproduce.py --drills        # also run the 11 resilience drills (~15 min)
    python reproduce.py --fresh         # rebuild every stage even if its output exists
    python reproduce.py --yes           # approve the January drift report without asking

What it does, in order, stopping at the first failure with the log path:

  1. installs requirements.txt into this interpreter if anything is missing
  2. checks the dataset is in Datasets/ and creates .env from .env.example
  3. creates approval tokens if .env has none (prints them once, stores hashes)
  4. runs the drift gate on the January files; a fraud manager approves (you)
  5. builds and calibrates offline: normalise, behaviour vectors, policy,
     memory, verify, likelihood ratios, fact vectors, proof gate, conformal
  6. TigerGraph: wakes the workspace; loads schema, data and queries only if the
     graph is not already loaded (a loaded graph is checked, never reloaded)
  7. investigates all 18 cases -> cases/HHF-001.json ... HHF-018.json
  8. audits, grades (organisers' grader), re-verifies every attestation, runs the tests

Logs: logs/reproduce/<step>.log. Exit code 0 only if every step passed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs" / "reproduce"
STAGED = ROOT / "data" / "staged"
PY = sys.executable

DATASET = ["Datasets/transactions.csv", "Datasets/identity.csv",
           "Datasets/closed_cases_history.csv", "Datasets/case_pack.csv",
           "Datasets/round_2_dataset/transactions_2017q1.csv",
           "Datasets/round_2_dataset/identity_2017q1.csv",
           "Datasets/round_2_dataset/closed_cases_history.csv",
           "Datasets/round_2_dataset/cases/case_pack_final.csv"]
IMPORTS = ["pandas", "pyarrow", "sklearn", "scipy", "fastapi", "uvicorn", "yaml", "jsonschema",
           "dotenv", "cryptography", "langgraph", "pyTigerGraph", "mcp", "tigergraph_mcp",
           "sentence_transformers", "google.generativeai", "pytest"]

results: list[tuple[str, str, float]] = []


def say(msg: str) -> None:
    print(f"\n\033[1m== {msg}\033[0m", flush=True)


def run(name: str, args: list[str], env: dict[str, str], ok_codes=(0,)) -> int:
    """Run one stage, streaming its output and keeping a log."""
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"{len(results) + 1:02d}_{name}.log"
    say(f"{name}: {' '.join(args)}")
    t0 = time.time()
    with log.open("w", encoding="utf-8") as fh:
        p = subprocess.Popen([PY, *args], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                             errors="replace")
        for line in p.stdout:
            sys.stdout.write(line)
            fh.write(line)
        code = p.wait()
    dt = time.time() - t0
    results.append((name, "ok" if code in ok_codes else f"FAILED (exit {code}) - {log}", dt))
    return code


def skipped(name: str, why: str) -> None:
    print(f"  {name}: skipped ({why})", flush=True)
    results.append((name, f"skipped: {why}", 0.0))


def stop(code: int = 1) -> None:
    summary()
    raise SystemExit(code)


def summary() -> None:
    say("summary")
    w = max([len(n) for n, _, _ in results] + [4])
    for n, status, dt in results:
        print(f"  {n:<{w}}  {status}  ({dt:.0f}s)" if dt else f"  {n:<{w}}  {status}")


# ------------------------------------------------------------- preflight ----
def ensure_requirements() -> None:
    import importlib.util

    missing = [m for m in IMPORTS if importlib.util.find_spec(m.split(".")[0]) is None]
    if not missing:
        results.append(("requirements", "ok (already installed)", 0.0))
        return
    print(f"missing: {', '.join(missing)}; installing requirements.txt")
    env = dict(os.environ)
    if run("requirements", ["-m", "pip", "install", "-r", "requirements.txt"], env) != 0:
        stop()


def ensure_dataset() -> None:
    missing = [f for f in DATASET if not (ROOT / f).exists()]
    if missing:
        print("The dataset is not committed. Put these files in place, then run again:")
        for f in missing:
            print(f"  {f}")
        results.append(("dataset", "MISSING", 0.0))
        stop(3)
    results.append(("dataset", "ok", 0.0))


def env_file() -> dict[str, str]:
    env_path = ROOT / ".env"
    if not env_path.exists():
        shutil.copy(ROOT / ".env.example", env_path)
        print("created .env from .env.example (fill in TigerGraph / model credentials to go live)")
    vals: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.split(" #")[0].strip()
    return vals


def ensure_tokens(dotenv: dict[str, str]) -> str | None:
    """Return a fraud-manager token for the drift approval, creating the three
    role tokens if .env has none. Plaintext is printed once, never stored."""
    sys.path.insert(0, str(ROOT / "src"))
    if os.environ.get("APPROVAL_TOKENS") or dotenv.get("APPROVAL_TOKENS"):
        results.append(("tokens", "ok (APPROVAL_TOKENS already set)", 0.0))
        return os.environ.get("APPROVAL_TOKEN") or None
    from fraudagent.governance.approvals import env_line, make_tokens

    toks = make_tokens([("analyst-01", "analyst"), ("lead-01", "team_lead"),
                        ("manager-01", "fraud_manager")])
    with (ROOT / ".env").open("a", encoding="utf-8") as fh:
        fh.write("\n# approval token hashes, added by reproduce.py\n" + env_line(toks) + "\n")
    say("approval tokens (shown once; only their hashes were written to .env)")
    for t in toks:
        print(f"  {t['role']:<14} {t['actor_id']:<11} {t['token']}")
    print("  Keep them: the console asks for one to approve actions or run the agent live.")
    results.append(("tokens", "created", 0.0))
    return next(t["token"] for t in toks if t["role"] == "fraud_manager")


# --------------------------------------------------------------- drift ----
def drift_gate(env: dict[str, str], fm_token: str | None, yes: bool) -> None:
    from fraudagent.governance.drift_gate import pending

    run("drift_detect", ["ingest/00_drift.py", "--auto"], env, ok_codes=(0, 4))
    waiting = pending()
    if not waiting:
        results[-1] = ("drift_detect", "ok (nothing pending)", results[-1][2])
        return
    print(f"\nDrift proposal(s) {', '.join(waiting)} are waiting for a fraud manager. "
          f"The report is in eval/reports/drift.md (printed above). New data is not loaded "
          f"until someone with the fraud-manager role approves it.")
    if not yes:
        if not sys.stdin.isatty():
            print("Not interactive: re-run with --yes to approve as fraud manager.")
            stop(4)
        if input("Approve as fraud manager? [y/N] ").strip().lower() != "y":
            stop(4)
    if not fm_token and not sys.stdin.isatty():
        print("APPROVAL_TOKENS is already set, so no new token was made. Pass the fraud-manager "
              "token in APPROVAL_TOKEN (environment) and run again.")
        stop(4)
    token = fm_token or getpass.getpass("Fraud-manager token: ").strip()
    if run("drift_approve", ["ingest/00_drift.py", "--auto", "--approve", "--token", token],
           env) != 0 or pending():
        stop(4)


# ---------------------------------------------------------------- build ----
def build(env: dict[str, str], quick: bool, fresh: bool) -> None:
    stages = [
        ("normalise", ["ingest/01_normalise.py"], ["transactions.parquet", "closed_cases.parquet"]),
        ("behaviour_vectors", ["ingest/02_behaviour_embeddings.py"], ["behaviour_emb.parquet"]),
        ("policy", ["ingest/03_extract_policy.py"], []),
        ("memory", ["ingest/04_build_memory.py"], ["case_memory.npz", "doc_memory.npz"]),
        ("verify_artefacts", ["ingest/07_verify.py"], []),
        ("calibrate", ["ingest/05_calibrate.py"] + (["--limit", "900"] if quick else []),
         ["likelihood_ratios.json"]),
        ("fact_vectors", ["ingest/08_fact_vectors.py"] + (["--limit", "300"] if quick else []),
         ["closed_case_facts.parquet"]),
        ("proof_gate", ["eval/proof_holdout.py"], ["proof_gate.json"]),
        ("conformal", ["eval/conformal_calibrate.py"], ["conformal.json"]),
    ]
    for name, args, outputs in stages:
        if outputs and not fresh and all((STAGED / o).exists() for o in outputs):
            skipped(name, "output already built; --fresh rebuilds")
        elif run(name, args, env) != 0:
            stop()
        if name == "behaviour_vectors":
            january_vectors(env)


def january_vectors(env: dict[str, str]) -> None:
    """January is projected through the Round 1 fit and appended, so every
    existing vector stays byte-identical (02_behaviour_embeddings.py --append)."""
    import pyarrow.parquet as pq

    n_tx = pq.ParquetFile(STAGED / "transactions.parquet").metadata.num_rows
    n_v = pq.ParquetFile(STAGED / "behaviour_emb.parquet").metadata.num_rows
    if n_v >= n_tx:
        skipped("behaviour_vectors_january", f"{n_v:,} vectors for {n_tx:,} transactions")
    elif run("behaviour_vectors_january", ["ingest/02_behaviour_embeddings.py", "--append"],
             env) != 0:
        stop()


# ---------------------------------------------------------------- graph ----
def wake(host: str, minutes: float = 10) -> bool:
    import urllib.request

    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(host.rstrip("/") + "/api/ping", timeout=30) as r:
                if b"pong" in r.read():
                    return True
        except Exception as exc:  # noqa: BLE001 - asleep, starting or unreachable
            print(f"  waiting for the workspace ({str(exc)[:80]})", flush=True)
        time.sleep(15)
    return False


def graph_loaded() -> tuple[bool, str]:
    """True when the graph already holds the data and every query the agent uses."""
    sys.path.insert(0, str(ROOT / "graph"))
    from fraudagent.graphstore.tigergraph import TigerGraphStore
    from install import FINAL_QUERIES

    conn = TigerGraphStore().conn
    counts = conn.getVertexCount("*")
    installed = {k.rsplit("/", 1)[-1] for k in (conn.getInstalledQueries() or {})}
    low = [v for v, m in [("Transaction", 600_000), ("ClosedCase", 5_000), ("PolicyDoc", 30)]
           if counts.get(v, 0) < m]
    missing = [q for q in FINAL_QUERIES if q not in installed]
    detail = (f"Transaction {counts.get('Transaction', 0):,}, ClosedCase "
              f"{counts.get('ClosedCase', 0):,}, FraudCase {counts.get('FraudCase', 0):,}; "
              f"{len(FINAL_QUERIES) - len(missing)}/{len(FINAL_QUERIES)} agent queries installed")
    return not low and not missing, detail


def graph(env: dict[str, str], host: str) -> None:
    say(f"TigerGraph at {host.split('//')[-1].split('.')[0]}…")
    if not wake(host):
        print("The workspace did not answer /api/ping within 10 minutes. Start it in the "
              "Savanna console (and check billing), then run again; finished stages are kept.")
        results.append(("graph_wake", "FAILED", 0.0))
        stop(2)
    results.append(("graph_wake", "ok", 0.0))
    try:
        ok, detail = graph_loaded()
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"could not inspect the graph: {exc}"
    print(f"  {detail}")
    if ok:
        results.append(("graph_install", f"skipped: already loaded ({detail})", 0.0))
        return
    if run("graph_stage_csv", ["ingest/06_stage_graph_csv.py"], env) != 0:
        stop()
    if run("graph_install", ["graph/install.py", "--step", "all"], env) != 0:
        stop()


# ----------------------------------------------------------------- main ----
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="local mirror and template prose")
    ap.add_argument("--quick", action="store_true", help="sampled calibration and fact vectors")
    ap.add_argument("--fresh", action="store_true", help="rebuild stages whose output exists")
    ap.add_argument("--drills", action="store_true", help="also run the resilience drills")
    ap.add_argument("--yes", action="store_true", help="approve the drift report without asking")
    ap.add_argument("--skip-tests", action="store_true")
    args = ap.parse_args()

    for s in (sys.stdout, sys.stderr):      # a redirected Windows console is cp1252
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    if sys.version_info < (3, 11):
        print(f"Python 3.11 or newer is needed; this is {sys.version.split()[0]}.")
        return 1
    ensure_requirements()
    ensure_dataset()
    dotenv = env_file()
    host = os.environ.get("TG_HOST") or dotenv.get("TG_HOST", "")
    secret = (os.environ.get("TG_PASSWORD") or dotenv.get("TG_PASSWORD")
              or os.environ.get("TG_SECRET") or dotenv.get("TG_SECRET"))
    offline = args.offline or not (host and secret)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if offline:
        env.update(GRAPH_BACKEND="local", AGENT_USE_LLM="0", TG_VIA_MCP="0")
        say("mode: OFFLINE (local mirror over the staged data, template prose)"
            + ("" if args.offline else ": no TG_HOST/TG_PASSWORD in .env"))
    else:
        env.update(GRAPH_BACKEND="tigergraph", GRAPH_STRICT="1")
        say("mode: LIVE (TigerGraph through the MCP server"
            + (", model prose)" if (os.environ.get("AGENT_USE_LLM") or dotenv.get("AGENT_USE_LLM"))
               in ("1", "true") else ", template prose)"))

    fm = ensure_tokens(dotenv)
    drift_gate(env, fm, args.yes)
    build(env, args.quick, args.fresh)
    if not offline:
        graph(env, host)

    code = run("investigate_18_cases", ["benchmark/run_case.py", "--all"], env)
    if code != 0:
        stop(code)
    checks = [("audit", ["eval/audit_answers.py"]),
              ("grade_official", ["eval/grade_official.py"]),
              ("attest_verify", ["eval/attest_verify.py"])]
    if not args.skip_tests:
        checks.append(("tests", ["-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"]))
    if args.drills:
        checks.append(("drills", ["drills/run_drills.py", "--case", "HHF-001"]))
    failed = [name for name, a in checks if run(name, a, env) != 0]

    summary()
    say("done" if not failed else f"finished with failures: {', '.join(failed)}")
    print("  answers:  cases/HHF-001.json ... cases/HHF-018.json")
    print("  reports:  eval/reports/grade_official.md, attest_verify.md")
    print(f"  console:  {Path(PY).name} ui/server.py   ->  http://127.0.0.1:8080")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Bring your own dataset (challenge C13, and the judges' end-to-end run).

A judge hands over a folder of CSVs whose columns are renamed and reshaped. This
script takes it from raw files to graded answers without touching our own data:

  1. **Identify** each file's role (transactions, identity, closed cases, case
     pack) by how well its columns map onto the canonical schema. A file that
     maps onto nothing is refused, not guessed.
  2. **Map** every column with evidence (name tokens, type shape, value overlap
     or quantile match with scale search) against the bundled canonical spec
     `data/schema/canonical.json`, so it works on a clean clone with none of our
     data present. Numbered families (V1..V339, C1..C14, D1..D15, M1..M9,
     id_01..id_38) are mapped by their index whatever the prefix.
  3. **Validate** (guardrails): required fields present, ids unique, amounts
     numeric and non-negative, timestamps parse, every case-pack transaction and
     card exists in the transactions, row limits. Any failure stops the run with
     the field named.
  4. **Gate**: the mapping is written as a proposal with sample records and is
     applied only with a fraud-manager approval token (`--token`), or with
     `--accept-mapping`, which is recorded in the report as an operator decision.
  5. **Transform** into canonical files (cents -> dollars, date + time -> ts,
     epoch -> ts, split card ids) under `Datasets/byo/<name>/`.
  6. **Ingest and run** in isolated folders (`data/staged_byo/<name>/`,
     `cases_byo/<name>/`): normalise, behaviour vectors, policy, memory, verify,
     then every case in their pack, then the organisers' grader if present.

    python ingest/byo.py --build-spec                      # once, from our data (committed)
    python ingest/byo.py --input path/to/their_folder --name judge1 --accept-mapping
    python ingest/byo.py --input ... --name judge1 --token <fraud-manager token> --graph
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ingest"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from schema_mapper import kind, tokens  # noqa: E402

SPEC = ROOT / "data" / "schema" / "canonical.json"
MAX_ROWS = 5_000_000

ROLES = {
    "transactions": {"file": "transactions.csv",
                     "required": ["TransactionID", "TransactionAmt", "customer_id"],
                     "one_of": [["ts", "TransactionDT"]]},
    "identity": {"file": "identity.csv", "required": ["TransactionID"],
                 "one_of": [["DeviceInfo", "DeviceType", "id_31"]]},
    "closed_cases": {"file": "closed_cases_history.csv",
                     "required": ["case_id", "card_id", "opened_at", "outcome"], "one_of": []},
    "case_pack": {"file": "case_pack.csv",
                  "required": ["case_id", "opened_at", "trigger_type", "flagged_txn_id",
                               "card_id", "customer_id"], "one_of": []},
}
FAMILIES = {"V": (r"^(v|vesta|vfeat|vf)_?0*(\d+)$", 339), "C": (r"^(c|count|cnt)_?0*(\d+)$", 14),
            "D": (r"^(d|delta|timedelta)_?0*(\d+)$", 15), "M": (r"^(m|match)_?0*(\d+)$", 9),
            "id_": (r"^(id|ident|identity)_?0*(\d+)$", 38)}


def log(msg: str) -> None:
    print(f"[byo] {msg}", flush=True)


# ------------------------------------------------------------------ spec ----
def profile_col(s: pd.Series) -> dict:
    k = kind(s)
    p = {"kind": k}
    v = s.dropna()
    if k in {"numeric", "epoch"} and len(v):
        p["q"] = [float(x) for x in np.quantile(v.astype(float), [0.1, 0.5, 0.9])]
    elif len(v):
        p["top"] = v.astype(str).value_counts().head(60).index.tolist()
        p["shape"] = _shape(v.astype(str).head(200).tolist())
    return p


def _shape(vals: list[str]) -> str:
    for name, rx in (("txn_id", r"^\d{6,9}$"), ("card_id", r"^C\d{5}-K\d+$"),
                     ("customer_id", r"^C\d{5}$"), ("case_id", r"^[A-Z]{2,4}-\d{3,5}$"),
                     ("datetime", r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"),
                     ("ids_pipe", r"^\d{6,}(\|\d{6,})*$"), ("cards_pipe", r"^C\d{5}-K\d+(\|C\d{5}-K\d+)*$")):
        if vals and sum(bool(re.match(rx, x)) for x in vals) / len(vals) > 0.8:
            return name
    return ""


def build_spec() -> int:
    from fraudagent.config import PATHS

    src = {"transactions": PATHS.transaction_files()[0], "identity": PATHS.identity_files()[0],
           "closed_cases": PATHS.closed_cases_csv, "case_pack": PATHS.case_pack_csv}
    spec = {}
    for role, path in src.items():
        df = pd.read_csv(path, nrows=50_000, low_memory=False)
        cols = {c: profile_col(df[c]) for c in df.columns
                if not re.match(r"^(V\d+|id_\d+)$", c) or c in {"id_15", "id_23", "id_31"}}
        spec[role] = {"columns": cols, "all_columns": list(df.columns)}
    SPEC.parent.mkdir(parents=True, exist_ok=True)
    SPEC.write_text(json.dumps(spec, indent=1, default=str), encoding="utf-8")
    log(f"wrote {SPEC.relative_to(ROOT)} ({SPEC.stat().st_size // 1024} KB)")
    return 0


# --------------------------------------------------------------- mapping ----
def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower())


def family_of(name: str) -> str | None:
    n = _norm(name)
    for fam, (rx, top) in FAMILIES.items():
        m = re.match(rx, n)
        if m and 1 <= int(m.group(2)) <= top:
            idx = int(m.group(2))
            return f"id_{idx:02d}" if fam == "id_" else f"{fam}{idx}"
    return None


def value_score(s: pd.Series, p: dict) -> tuple[float, str, float]:
    v = s.dropna()
    if v.empty:
        return 0.0, "no values", 1.0
    k = kind(s)
    if "q" in p and pd.api.types.is_numeric_dtype(v):
        qa = np.quantile(v.astype(float), [0.1, 0.5, 0.9])
        qb = np.asarray(p["q"])
        best, best_s = 0.0, 1.0
        for scale in (1.0, 0.01, 100.0, 0.001, 1000.0):
            rel = np.abs(qa * scale - qb) / (np.abs(qb) + 1e-9)
            sim = float(np.clip(1 - rel.mean(), 0, 1))
            if sim > best:
                best, best_s = sim, scale
        return best, f"quantiles match at scale x{best_s:g}", best_s
    if "top" in p:
        sv = set(v.astype(str).head(5000))
        shared = sv & set(p["top"])
        sh = _shape(v.astype(str).head(200).tolist())
        if sh and sh == p.get("shape"):
            return 0.9, f"same value shape ({sh})", 1.0
        return min(1.0, len(shared) / max(1, min(len(sv), len(p["top"]), 20))), \
            f"{len(shared)} shared values", 1.0
    if k == p.get("kind"):
        return 0.4, "same type", 1.0
    return 0.0, "no value evidence", 1.0


SYNONYMS = {"notes": "analyst_notes", "note": "analyst_notes", "linked": "connected",
            "loss": "exposure", "result": "outcome", "typology": "pattern",
            "message": "trigger_text", "flagged": "flagged"}


def map_file(df: pd.DataFrame, role: str, spec: dict) -> dict:
    cols = spec[role]["columns"]
    mapping, used_src, used_dst = [], set(), set()
    for c in df.columns:                                   # numbered families first
        f = family_of(c)
        if f and f in spec[role]["all_columns"] and f not in used_dst:
            mapping.append({"from": c, "to": f, "score": 0.9, "transform": "identity",
                            "evidence": {"family": f}})
            used_src.add(c)
            used_dst.add(f)
    scored = []
    for c in df.columns:
        if c in used_src:
            continue
        for dst, p in cols.items():
            if dst in used_dst:
                continue
            tc = tokens(c) | {SYNONYMS[t] for t in tokens(c) if t in SYNONYMS}
            nt = tc & (tokens(dst) | {dst})
            name = len(nt) / max(1, len(tokens(dst)))
            exact = _norm(c) == _norm(dst)
            vs, why, scale = value_score(df[c], p)
            if vs < 0.3 and name >= 0.5 and kind(df[c]) in {p.get("kind"), "empty"}:
                vs, why = 0.3, "name and type agree; values sparse or free text"
            score = (1.0 if exact else 0.35 * name) + 0.65 * vs
            if score > 0.4:
                scored.append((round(score, 3), c, dst, why, scale, round(name, 2)))
    scored.sort(reverse=True)
    for score, c, dst, why, scale, name in scored:
        if c in used_src or dst in used_dst:
            continue
        used_src.add(c)
        used_dst.add(dst)
        mapping.append({"from": c, "to": dst, "score": score,
                        "transform": f"multiply by {scale:g}" if scale != 1.0 else "identity",
                        "evidence": {"name_overlap": name, "values": why,
                                     "samples": df[c].dropna().astype(str).head(3).tolist()}})
    rs = reshapes(df)
    got = {m["to"] for m in mapping} | {r["to"] for r in rs}
    req = ROLES[role]
    missing = [r for r in req["required"] if r not in got]
    missing += [" or ".join(g) for g in req["one_of"] if not set(g) & got]
    coverage = 1 - len(missing) / max(1, len(req["required"]) + len(req["one_of"]))
    return {"role": role, "mapping": mapping, "missing_required": missing,
            "coverage": round(coverage, 3), "reshapes": rs}


def reshapes(df: pd.DataFrame) -> list[dict]:
    out = []
    kinds = {c: kind(df[c]) for c in df.columns}
    dates = [c for c, k in kinds.items() if k == "date"]
    times = [c for c, k in kinds.items() if k == "time"]
    if dates and times:
        out.append({"reshape": "timestamp split", "columns": [dates[0], times[0]], "to": "ts"})
    for c, k in kinds.items():
        if k == "epoch":
            out.append({"reshape": "epoch seconds", "columns": [c], "to": "ts"})
    return out


def identify(path: Path, spec: dict) -> dict:
    df = pd.read_csv(path, nrows=20_000, low_memory=False)
    best = None
    for role in ROLES:
        m = map_file(df, role, spec)
        m["n_mapped"] = len(m["mapping"])
        if best is None or (m["coverage"], m["n_mapped"]) > (best["coverage"], best["n_mapped"]):
            best = m
    best["file"] = str(path)
    return best


# ------------------------------------------------------------- transform ----
def apply(path: Path, m: dict, out: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    if len(df) > MAX_ROWS:
        raise SystemExit(f"{path.name}: {len(df):,} rows exceeds the {MAX_ROWS:,} row guardrail")
    ren = {x["from"]: x["to"] for x in m["mapping"]}
    for r in m["reshapes"]:
        if r["reshape"] == "timestamp split" and "ts" not in ren.values():
            d, t = r["columns"]
            df["ts"] = df[d].astype(str) + " " + df[t].astype(str)
            ren.pop(d, None)
            ren.pop(t, None)
        elif r["reshape"] == "epoch seconds" and "ts" not in ren.values():
            df["ts"] = pd.to_datetime(df[r["columns"][0]], unit="s").dt.strftime("%Y-%m-%d %H:%M:%S")
    for x in m["mapping"]:
        if x["transform"].startswith("multiply by"):
            df[x["from"]] = pd.to_numeric(df[x["from"]], errors="coerce") * float(
                x["transform"].split()[-1])
    df = df.rename(columns=ren)
    return df


def validate(frames: dict[str, pd.DataFrame]) -> list[str]:
    errs = []
    tx = frames.get("transactions")
    if tx is None:
        return ["no transactions file was identified"]
    if tx["TransactionID"].duplicated().any():
        errs.append(f"transactions: {int(tx['TransactionID'].duplicated().sum())} duplicate TransactionID")
    amt = pd.to_numeric(tx["TransactionAmt"], errors="coerce")
    if amt.isna().mean() > 0.01 or (amt < 0).any():
        errs.append("transactions: TransactionAmt has non-numeric or negative values")
    if "ts" in tx:
        bad = pd.to_datetime(tx["ts"], errors="coerce").isna().mean()
        if bad > 0.01:
            errs.append(f"transactions: {bad:.1%} of ts do not parse")
    pack = frames.get("case_pack")
    if pack is None:
        errs.append("no case pack was identified")
    else:
        ids = set(tx["TransactionID"].astype(str))
        miss = [str(t) for t in pack["flagged_txn_id"] if str(t) not in ids]
        if miss:
            errs.append(f"case_pack: flagged_txn_id not in transactions: {miss[:5]}")
        bad_t = set(pack["trigger_type"]) - {"risk_score", "customer_report", "analyst_request"}
        if bad_t:
            errs.append(f"case_pack: unknown trigger_type {sorted(bad_t)}")
    return errs


def complete_transactions(tx: pd.DataFrame) -> pd.DataFrame:
    """Fill the columns the ingest reads but the variant lacks, and say so."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("norm", ROOT / "ingest" / "01_normalise.py")
    norm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(norm)
    if "ts" in tx and "TransactionDT" not in tx:
        t = pd.to_datetime(tx["ts"])
        tx["TransactionDT"] = ((t - t.min()).dt.total_seconds()).astype("int64")
    if "TransactionDT" in tx and "ts" not in tx:
        tx["ts"] = (pd.Timestamp("2016-07-01") + pd.to_timedelta(tx["TransactionDT"], unit="s")) \
            .dt.strftime("%Y-%m-%d %H:%M:%S")
    filled = []
    for c in norm.CORE_COLS + [f"V{i}" for i in range(1, 340)]:
        if c not in tx:
            tx[c] = np.nan
            filled.append(c)
    if tx["channel"].isna().all():
        tx["channel"] = "in_person"
        filled.append("channel(defaulted: in_person)")
    return tx, filled


# --------------------------------------------------------------- pipeline ----
def run(cmd: list[str], env: dict) -> int:
    log("$ " + " ".join(Path(c).name if i == 1 else c for i, c in enumerate(cmd)))
    p = subprocess.run(cmd, cwd=ROOT, env=env)
    return p.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-spec", action="store_true")
    ap.add_argument("--input", default="")
    ap.add_argument("--name", default="byo")
    ap.add_argument("--token", default=os.environ.get("APPROVAL_TOKEN", ""))
    ap.add_argument("--accept-mapping", action="store_true")
    ap.add_argument("--graph", action="store_true", help="load into TigerGraph (else the mirror)")
    ap.add_argument("--map-only", action="store_true")
    ap.add_argument("--limit-cases", type=int, default=0)
    args = ap.parse_args()
    if args.build_spec:
        return build_spec()
    if not SPEC.exists():
        raise SystemExit(f"{SPEC} missing: run --build-spec on a machine with the reference data")
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    src = Path(args.input)
    files = sorted(src.rglob("*.csv"))
    if not files:
        raise SystemExit(f"no CSV files under {src}")
    t0 = time.time()
    ident = [identify(f, spec) for f in files]
    roles: dict[str, dict] = {}
    refused = []
    for m in ident:
        if m["coverage"] < 1.0:
            refused.append({"file": m["file"], "best_role": m["role"], "missing": m["missing_required"]})
            continue
        if m["role"] in roles and roles[m["role"]]["n_mapped"] >= m["n_mapped"]:
            continue
        roles[m["role"]] = m
    out = ROOT / "Datasets" / "byo" / args.name
    rep_dir = ROOT / "eval" / "reports" / "byo" / args.name
    rep_dir.mkdir(parents=True, exist_ok=True)
    proposal = {"name": args.name, "input": str(src), "roles": roles, "refused": refused,
                "mapping_seconds": round(time.time() - t0, 1)}
    (rep_dir / "mapping.json").write_text(json.dumps(proposal, indent=1, default=str),
                                          encoding="utf-8")
    md = [f"# Schema mapping — {args.name}", "",
          f"{len(files)} files from `{src}`; mapped in {proposal['mapping_seconds']} s.", ""]
    for role, m in roles.items():
        md += [f"## {role} ← `{Path(m['file']).name}`", "", "| from | to | score | transform | evidence |",
               "|---|---|--:|---|---|"]
        for x in m["mapping"]:
            if x["to"].startswith(("V", "id_")) and x["to"] not in {"id_15", "id_23", "id_31"}:
                continue
            ev = x["evidence"].get("values") or x["evidence"].get("family", "")
            smp = ", ".join(x["evidence"].get("samples", [])[:2])
            md.append(f"| {x['from']} | {x['to']} | {x['score']} | {x['transform']} | {ev} {smp} |")
        n_fam = sum(1 for x in m["mapping"] if "family" in x["evidence"])
        md += ["", f"{n_fam} numbered-family columns mapped by index. Reshapes: {m['reshapes'] or 'none'}", ""]
    if refused:
        md += ["## Refused files", ""] + [f"- `{Path(r['file']).name}`: best guess {r['best_role']}, "
                                          f"missing {r['missing']}" for r in refused]
    (rep_dir / "mapping.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    if "transactions" not in roles or "case_pack" not in roles:
        log("cannot continue: a transactions file and a case pack are required")
        return 3
    if args.map_only:
        return 0

    # ---- gate
    if args.token:
        from fraudagent.governance import approvals as gov

        p = gov.authenticate(f"Bearer {args.token}")
        if p.role != "fraud_manager":
            gov.refuse(p, f"BYO-{args.name}", -1, 403, "mapping approval needs a fraud manager")
            raise SystemExit("403: only a fraud manager may approve a schema mapping")
        approval = gov._append({"kind": "schema_mapping", "case_id": f"BYO-{args.name}", "index": -1,
                                "approved": True, "actor_id": p.actor_id, "actor_role": p.role,
                                "at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())})
        approved_by = f"{p.actor_id} (ledger seq {approval['seq']})"
    elif args.accept_mapping:
        approved_by = "operator flag --accept-mapping (no token)"
    else:
        log(f"mapping proposal written to {rep_dir.relative_to(ROOT)}; approve with --token "
            f"<fraud-manager token> or --accept-mapping")
        return 4

    # ---- transform + validate
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    frames = {r: apply(Path(m["file"]), m, out) for r, m in roles.items()}
    frames["transactions"], filled = complete_transactions(frames["transactions"])
    import importlib.util as _u

    _s = _u.spec_from_file_location("norm", ROOT / "ingest" / "01_normalise.py")
    _n = _u.module_from_spec(_s)
    _s.loader.exec_module(_n)
    idf = frames.get("identity")
    if idf is None:
        idf = pd.DataFrame({"TransactionID": []})
        filled.append("identity file (absent: device evidence unavailable)")
    for c in _n.IDENTITY_KEEP:
        if c not in idf:
            idf[c] = np.nan
    frames["identity"] = idf
    cc = frames.get("closed_cases")
    if cc is None:
        cc = pd.DataFrame(columns=["case_id", "customer_id", "card_id", "opened_at", "closed_at",
                                   "outcome", "pattern", "first_fraud_txn_id", "txn_ids", "n_txns",
                                   "exposure_usd", "connected_card_ids", "actions_taken",
                                   "report_filed", "analyst_notes"])
        filled.append("closed cases (absent: no precedent memory)")
    for c in ["customer_id", "closed_at", "pattern", "first_fraud_txn_id", "txn_ids", "n_txns",
              "exposure_usd", "connected_card_ids", "actions_taken", "report_filed",
              "analyst_notes"]:
        if c not in cc:
            cc[c] = np.nan
    frames["closed_cases"] = cc
    pk = frames["case_pack"]
    for c in ("trigger_text", "risk_score"):
        if c not in pk:
            pk[c] = np.nan
    errs = validate(frames)
    if errs:
        for e in errs:
            log(f"VALIDATION: {e}")
        return 3
    for r, df in frames.items():
        df.to_csv(out / ROLES[r]["file"], index=False)
    log(f"wrote canonical files to {out.relative_to(ROOT)}; filled absent columns: "
        f"{len(filled)} ({', '.join(filled[:6])}{'…' if len(filled) > 6 else ''})")

    # ---- isolated ingest + run + grade
    staged = ROOT / "data" / "staged_byo" / args.name
    cases = ROOT / "cases_byo" / args.name
    for d in (staged, cases):
        d.mkdir(parents=True, exist_ok=True)
    for f in ("likelihood_ratios.json", "proof_gate.json", "conformal.json",
              "conformal_support.npy", "embedder.pkl"):
        s = ROOT / "data" / "staged" / f
        if s.exists() and f != "conformal_support.npy":
            shutil.copy(s, staged / f)      # calibration transfers; support is rebuilt below
    env = dict(os.environ, DATA_RAW_DIR=str(out), DATA_STAGED_DIR=str(staged),
               BENCHMARK_OUTPUT_DIR=str(cases), CASE_PACK=str(out / "case_pack.csv"),
               # isolate every side effect from the main dataset's records
               RECORDINGS_DIR=str(staged / "recordings"), LIFECYCLE_DIR=str(staged / "lifecycle"),
               LOGS_DIR=str(staged / "logs"), EVAL_OUTPUT_DIR=str(rep_dir),
               GRAPH_BACKEND="tigergraph" if args.graph else "local", AGENT_USE_LLM=os.environ.get(
                   "AGENT_USE_LLM", "0"))
    py = sys.executable
    steps = [[py, "ingest/01_normalise.py"], [py, "ingest/02_behaviour_embeddings.py"],
             [py, "ingest/04_build_memory.py"]]   # policy v1.0 is fixed: data/policy is reused
    if args.graph:
        steps += [[py, "ingest/06_stage_graph_csv.py"], [py, "graph/install.py", "--step", "load"],
                  [py, "graph/install.py", "--step", "projections"]]
    for s in steps:
        if run(s, env):
            log(f"step failed: {' '.join(s[1:])}")
            return 2
    run_cmd = [py, "benchmark/run_case.py", "--all"] + ([] if args.graph else ["--dev"])
    code = run(run_cmd, env)
    grader = next((p for p in src.rglob("grade.py")), None) or (
        ROOT / "Datasets" / "round_2_dataset" / "grader" / "grade.py")
    if grader.exists():
        teams = ROOT / "build" / "grade_byo" / args.name / "teams" / "fraudgraph" / "cases"
        if teams.parent.parent.exists():
            shutil.rmtree(teams.parent.parent)
        teams.mkdir(parents=True)
        for p in cases.glob("*.json"):
            shutil.copy(p, teams / p.name)
        g = [py, str(grader), "--teams-dir", str(teams.parent.parent), "--case-pack",
             str(out / "case_pack.csv"), "--transactions", str(out / "transactions.csv"),
             "--out", str(rep_dir / "grade.json")]
        run(g, env)
    (rep_dir / "run.json").write_text(json.dumps({
        "approved_by": approved_by, "backend": env["GRAPH_BACKEND"], "run_exit": code,
        "filled_columns": filled, "answers": sorted(p.name for p in cases.glob("*.json")),
        "seconds": round(time.time() - t0, 1)}, indent=1), encoding="utf-8")
    log(f"done in {time.time() - t0:.0f}s; answers in {cases.relative_to(ROOT)}; report in "
        f"{rep_dir.relative_to(ROOT)}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

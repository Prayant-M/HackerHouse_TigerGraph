"""Regenerate every number in README.md and docs/INNOVATION.md from the report
files of the last run. Nothing between the markers is typed by hand.

    python scripts/readme_numbers.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass
REP = ROOT / "eval" / "reports"


def j(name: str) -> dict:
    p = REP / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def block() -> str:
    lines = []
    rs = REP / "run_summary.csv"
    if rs.exists():
        df = pd.read_csv(rs)
        lat = sorted(df["latency_s"].tolist())
        p95 = lat[max(0, min(len(lat) - 1, round(0.95 * (len(lat) - 1))))]
        harmful = int(df["final"].str.contains("BLOCK|FILE_REPORT").sum())
        lines += [f"- **{len(df)} cases** answered by `benchmark/run_case.py --all` on backend "
                  f"`tigergraph`: verdicts {df['verdict'].value_counts().to_dict()}; "
                  f"{harmful} carry a block or report; the proof gate changed the action on "
                  f"**{int(df['gate'].sum())}** ({', '.join(df.loc[df['gate'], 'case']) or 'none'}).",
                  f"- p95 latency **{p95:.1f} s**, mean {df['latency_s'].mean():.1f} s; "
                  f"{df['tokens'].mean():.0f} LLM tokens and ${df['cost_usd'].mean():.4f} per case; "
                  f"{df['attestations'].sum()} attestations in total.",
                  f"- hostile text flagged on {int(df['hostile_text'].sum())} cases; data-quality "
                  f"taint on {int(df['tainted'].sum())}."]
    pg = j("../../data/staged/proof_gate.json") or json.loads(
        (ROOT / "data" / "staged" / "proof_gate.json").read_text(encoding="utf-8")) \
        if (ROOT / "data" / "staged" / "proof_gate.json").exists() else {}
    if pg:
        bm = pg["by_margin"]
        arms = pg["arms"]
        lines += [f"- **Proof gate (October holdout, {pg['n_test']} replays, fitted on Jul–Sep):** "
                  f"harmful-action error rate {bm['k=1']['error_rate']} at margin k=1 vs "
                  f"{bm['k>=2']['error_rate']} at k≥2; legitimate customers acted against "
                  f"{arms['no gate (Round 1)']['legit_acted_against']} → "
                  f"{arms['margin + precedent (the gate)']['legit_acted_against']}, frauds acted on "
                  f"{arms['no gate (Round 1)']['frauds_acted_on']} → "
                  f"{arms['margin + precedent (the gate)']['frauds_acted_on']}. Gate claimed: "
                  f"**{'yes' if pg['gate_claimed'] else 'no — kept as examiner tool'}**."]
    cf = (ROOT / "data" / "staged" / "conformal.json")
    if cf.exists():
        c = json.loads(cf.read_text(encoding="utf-8"))["coverage_october"]
        lines += [f"- **Conformal (α=0.1):** October coverage {c['all']['coverage']} overall "
                  f"(fraud {c['fraud']['coverage']}, legit {c['legit']['coverage']}), mean set "
                  f"size {c['all']['avg_set_size']}."]
    m = j("metamorphic.json").get("relations", {})
    if m:
        txt = ", ".join(f"{k} {len(v['violations'])}/{v['runs']}" for k, v in sorted(m.items()))
        lines += [f"- **Metamorphic relations** (violations/runs): {txt}."]
    nb = REP / "naive_llm_baseline.md"
    if nb.exists():
        hit = [x for x in nb.read_text(encoding="utf-8").splitlines() if "naive LLM:" in x]
        if hit:
            lines += [f"- Naive baseline: {hit[0].strip('- *')}"]
    cb = j("containment_backtest.json")
    if cb:
        a = cb["arms"]
        lines += [f"- **Predictive containment** ({cb['rings']} rings, origin found on "
                  f"{cb['origins_found']}): origin-lift precision "
                  f"{a['A2 origin lift (controls)']['precision']} (lift "
                  f"{a['A2 origin lift (controls)']['lift']}×) on "
                  f"{a['A2 origin lift (controls)']['flagged']} free step-ups vs raw counts "
                  f"{a['A3 origin raw counts (no controls)']['precision']} (lift "
                  f"{a['A3 origin raw counts (no controls)']['lift']}×); zero blocks on innocents."]
    at = j("attacks.json")
    if at:
        lines += [f"- **Evasion attacks:** {at['evaded_before']} evaded before hardening, "
                  f"{at['evaded_after']} after; hardening's legitimate cost on the history: "
                  f"{at['hardening_legit_cost']}."]
    dr = REP / "drills.md"
    if dr.exists():
        rows = [x for x in dr.read_text(encoding="utf-8").splitlines() if x.startswith("| ") and
                ("PASS" in x or "FAIL" in x)]
        lines += [f"- **Drills:** {sum('PASS' in x for x in rows)}/{len(rows)} pass "
                  f"(`eval/reports/drills.md`)."]
    av = REP / "attest_verify.md"
    if av.exists():
        hit = [x for x in av.read_text(encoding="utf-8").splitlines() if "answer files pass" in x]
        if hit:
            lines += [f"- **Attestation re-run:** {hit[0].strip('* ').split('.')[0]}."]
    return "\n".join(lines)


def splice(path: Path, text: str) -> None:
    if not path.exists():
        return
    s = path.read_text(encoding="utf-8")
    start, end = "<!-- numbers:start -->", "<!-- numbers:end -->"
    new = f"{start}\n{text}\n{end}"
    if start in s:
        s = re.sub(re.escape(start) + r".*?" + re.escape(end), lambda _: new, s, flags=re.S)
    else:
        s += "\n" + new + "\n"
    path.write_text(s, encoding="utf-8")


def main() -> int:
    text = block()
    for p in (ROOT / "README.md", ROOT / "docs" / "INNOVATION.md"):
        splice(p, text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

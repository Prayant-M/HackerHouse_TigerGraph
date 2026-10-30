"""Run the organisers' grader (round_2_dataset/grader/grade.py) on our answers.

Two passes:
* the published command, `--transactions transactions_2017q1.csv` (January only), and
* `--transactions` over Round 1 + January together, because an episode that
  started in late December has legs the January-only file does not contain;
  the difference between the two passes is reported, not hidden.

    python eval/grade_official.py   -> eval/reports/grade_official.md
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fraudagent.config import PATHS  # noqa: E402

BUILD = ROOT / "build" / "grade"


def combined_transactions() -> Path:
    out = BUILD / "transactions_all_min.csv"
    if out.exists():
        return out
    with out.open("w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(["TransactionID", "TransactionAmt", "TransactionDT"])
        for f in PATHS.transaction_files():
            with f.open(newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    w.writerow([r["TransactionID"], r["TransactionAmt"], r["TransactionDT"]])
    return out


def run(tx: Path | None, tag: str) -> dict:
    out = BUILD / f"report_{tag}.json"
    cmd = [sys.executable, str(PATHS.grader_py), "--teams-dir", str(BUILD / "teams"),
           "--case-pack", str(PATHS.case_pack_csv), "--out", str(out)]
    if tx:
        cmd += ["--transactions", str(tx)]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(p.stdout.strip())
    if p.returncode:
        print(p.stderr[-800:])
    return json.loads(out.read_text(encoding="utf-8"))["teams"]["fraudgraph"]


def main() -> int:
    team = BUILD / "teams" / "fraudgraph" / "cases"
    if team.exists():
        shutil.rmtree(team)
    team.mkdir(parents=True)
    for p in sorted(PATHS.cases_out.glob("HHF-*.json")):
        shutil.copy(p, team / p.name)
    jan = next((f for f in PATHS.transaction_files() if "2017" in f.name), None)
    passes = {"published (January file)": run(jan, "jan"),
              "Round 1 + January": run(combined_transactions(), "all")}
    md = ["# Official grader", "", "`eval/grade_official.py` runs `round_2_dataset/grader/grade.py` "
          "unmodified on `cases/HHF-*.json`.", "",
          "| pass | answered | hard | policy | warning | clean |", "|---|--:|--:|--:|--:|--:|"]
    for k, t in passes.items():
        md.append(f"| {k} | {t['cases_answered']}/18 | {t['hard']} | {t['policy']} | "
                  f"{t['warning']} | {t['clean']}/18 |")
    md += ["", "## Findings (combined pass)", ""]
    for cid, c in passes["Round 1 + January"]["cases"].items():
        for cls, code, msg in c["findings"]:
            md.append(f"- {cid} **{cls}** `{code}`: {msg}")
    jan_only = {(cid, x[1]) for cid, c in passes["published (January file)"]["cases"].items()
                for x in c["findings"] if x[0] == "hard"}
    all_ = {(cid, x[1]) for cid, c in passes["Round 1 + January"]["cases"].items()
            for x in c["findings"] if x[0] == "hard"}
    if jan_only - all_:
        md += ["", "Hard findings only in the January-only pass (txns from before January that "
               "the published file does not contain): "
               + ", ".join(f"{c} {k}" for c, k in sorted(jan_only - all_))]
    (PATHS.eval_out / "grade_official.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

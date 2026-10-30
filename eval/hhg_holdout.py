"""Score the Round 1 answers against the real outcomes the bank published.

The final-round closed_cases_history.csv adds the 20 HHG investigations as
ordinary CC-xxxx records with their real outcomes. Each is matched to its HHG
case by card and opening time. Two answer sets are scored:

* `round1`  — the answers committed at the end of Round 1 (git HEAD~ history), and
* `current` — the answers in cases/ now (final-round code).

    python eval/hhg_holdout.py   -> eval/reports/hhg_holdout.md
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fraudagent.config import PATHS  # noqa: E402

HARM = {"BLOCK_CARD", "BLOCK_ALL_CARDS", "FILE_REPORT"}


def twins() -> pd.DataFrame:
    pack = pd.read_csv(PATHS.raw / "case_pack.csv")
    cc = pd.read_csv(PATHS.closed_cases_csv)
    old = set(pd.read_csv(PATHS.raw / "closed_cases_history.csv")["case_id"])
    new = cc[~cc["case_id"].isin(old)].copy()
    new["opened_at"] = pd.to_datetime(new["opened_at"])
    pack["opened_at"] = pd.to_datetime(pack["opened_at"])
    rows = []
    for r in pack.itertuples():
        c = new[new["card_id"] == r.card_id]
        if c.empty:
            continue
        c = c.iloc[(c["opened_at"] - r.opened_at).abs().argsort()[:1]]
        x = c.iloc[0]
        rows.append({"case_id": r.case_id, "cc_id": x.case_id, "outcome": x.outcome,
                     "pattern": x.pattern, "exposure": x.exposure_usd})
    return pd.DataFrame(rows)


def answers(source: str) -> dict[str, dict]:
    out = {}
    for i in range(1, 21):
        cid = f"HHG-{i:03d}"
        if source == "round1":
            try:
                txt = subprocess.run(["git", "show", f"HEAD:cases/{cid}.json"], cwd=ROOT,
                                     capture_output=True, text=True, encoding="utf-8",
                                     check=True).stdout
            except subprocess.CalledProcessError:
                continue
        else:
            p = PATHS.cases_out / f"{cid}.json"
            if not p.exists():
                continue
            txt = p.read_text(encoding="utf-8")
        out[cid] = json.loads(txt)
    return out


def score(tw: pd.DataFrame, ans: dict[str, dict]) -> dict:
    rows = []
    for t in tw.itertuples():
        a = ans.get(t.case_id)
        if a is None:
            continue
        fin = {x["action"] for x in a["next_best_actions"]["final"]}
        fraud = t.outcome == "confirmed_fraud"
        v = a["case"]["verdict"]
        rows.append({"case": t.case_id, "truth": "fraud" if fraud else "legit",
                     "verdict": v, "p": a["case"]["fraud_probability"],
                     "harmful": bool(fin & HARM),
                     "correct": (v == "fraud" and fraud) or (v == "legitimate" and not fraud)
                     or (v == "uncertain" and "ESCALATE_TO_ANALYST" in fin),
                     "innocent_harmed": bool(fin & HARM) and not fraud,
                     "fraud_missed": fraud and not (fin & HARM) and v == "legitimate",
                     "true_pattern": t.pattern, "our_pattern": a["case"]["pattern"]})
    df = pd.DataFrame(rows)
    if df.empty:
        return {"n": 0}
    brier = float(((df["p"] - (df["truth"] == "fraud").astype(float)) ** 2).mean())
    return {"n": len(df), "correct": int(df["correct"].sum()),
            "innocents_harmed": int(df["innocent_harmed"].sum()),
            "frauds_missed": int(df["fraud_missed"].sum()), "brier": round(brier, 4),
            "rows": df.to_dict("records")}


def main() -> int:
    tw = twins()
    res = {s: score(tw, answers(s)) for s in ("round1", "current")}
    (PATHS.eval_out / "hhg_holdout.json").write_text(json.dumps(res, indent=2, default=str),
                                                    encoding="utf-8")
    md = ["# Round 1 answers vs the real outcomes", "",
          f"`eval/hhg_holdout.py`. The final-round closed-case file adds the 20 HHG "
          f"investigations with their real outcomes ({len(tw)} matched by card and date: "
          f"{int((tw['outcome'] == 'confirmed_fraud').sum())} fraud, "
          f"{int((tw['outcome'] != 'confirmed_fraud').sum())} cleared). Uncertain + escalate "
          f"counts as correct, as the brief scores it.", "",
          "| answers | scored | correct | innocent customers harmed | frauds cleared | Brier |",
          "|---|--:|--:|--:|--:|--:|"]
    for s, r in res.items():
        if r.get("n"):
            md.append(f"| {s} | {r['n']} | {r['correct']} | {r['innocents_harmed']} | "
                      f"{r['frauds_missed']} | {r['brier']} |")
    md += ["", "| case | truth | Round 1 verdict | current verdict | current harmful | true pattern |",
           "|---|---|---|---|---|---|"]
    cur = {r["case"]: r for r in res["current"].get("rows", [])}
    for r in res["round1"].get("rows", []):
        c = cur.get(r["case"], {})
        md.append(f"| {r['case']} | {r['truth']} | {r['verdict']} | {c.get('verdict', '—')} | "
                  f"{c.get('harmful', '—')} | {r['true_pattern']} |")
    (PATHS.eval_out / "hhg_holdout.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

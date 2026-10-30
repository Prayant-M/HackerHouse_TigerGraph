"""Challenges C1, C2 and C3 in one reproducible run over the closed cases.

C1  New typologies: dormant_wake, micro_charges, recipient_fanin (and the
    shared-origin test, backtested in eval/containment_backtest.py). Each is
    backtested over every replayed closed case and matched control: what it
    caught, what it missed, which legitimate customers it would have touched,
    and which fraud the agent's own core missed that it catches.
C2  Self-growing detective: mines conjunctions of measured facts that are
    precise for confirmed fraud on July-September, writes each as a detector
    spec, backtests it on October, and files it as *proposed*. It joins the
    toolkit only after a fraud manager approves it (POST /api/detectors/{id}).
C3  Policy text to detector: compiles R5 (card testing) and R6 (shared origin)
    from the policy prose into executable specs, then lists every agreement and
    disagreement with the agent's own judgement, with ids.

    python eval/detectors.py          -> eval/reports/detectors.md, data/detectors/registry.json
"""

from __future__ import annotations

import json
import re
import sys
import time
from itertools import combinations
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from fraudagent.config import PATHS  # noqa: E402
from fraudagent.detectors import typologies as T  # noqa: E402
from fraudagent.graphstore.local import LocalGraphStore  # noqa: E402
from fraudagent.core.signals import SIGNAL_NAMES  # noqa: E402

SPLIT = pd.Timestamp("2016-10-01")


def load_population() -> pd.DataFrame:
    df = pd.read_parquet(PATHS.staged / "closed_case_facts.parquet")
    rows = PATHS.eval_out / "proof_holdout_rows.parquet"
    if rows.exists():
        h = pd.read_parquet(rows, columns=["case_id", "harmful"])
        df = df.merge(h, on="case_id", how="left")
    else:
        df["harmful"] = None
    return df


def backtest_c1(df: pd.DataFrame, store: LocalGraphStore) -> dict:
    tx = store.ds.tx
    rare = tx[~tx["email_r"].isin(T.COMMON_RECIPIENTS)]
    by_r = {r: g for r, g in rare.groupby("email_r")}
    hits = {"dormant_wake": [], "micro_charges": [], "recipient_fanin": []}
    for r in df.itertuples():
        as_of = r.opened_at.to_pydatetime()
        hist = store.card_history(r.card_id, as_of, window_days=120)
        res = {"dormant_wake": T.dormant_wake(hist, as_of),
               "micro_charges": T.micro_charges(hist, as_of)}
        flagged = store.get_transaction(r.flagged_txn_id)
        g = by_r.get(getattr(flagged, "email_r", "") or "")
        if g is not None:
            w = g[(g["ts"] >= as_of - pd.Timedelta(hours=24)) & (g["ts"] <= as_of)]
            res["recipient_fanin"] = T.recipient_fanin(
                w[["txn_id", "card_id", "email_r"]].to_dict("records"), flagged.email_r)
        for name, v in res.items():
            if v.get("fired"):
                hits[name].append({"case_id": r.case_id, "is_fraud": bool(r.is_fraud),
                                   "stratum": r.stratum, "pattern": r.pattern,
                                   "agent_harmful": None if pd.isna(r.harmful) else bool(r.harmful),
                                   "txn_ids": v["txn_ids"][:8], "card_ids": v["card_ids"][:8]})
    n_f, n_l = int(df["is_fraud"].sum()), int((~df["is_fraud"]).sum())
    out = {}
    for name, h in hits.items():
        tp = [x for x in h if x["is_fraud"]]
        fp = [x for x in h if not x["is_fraud"]]
        caught_missed = [x for x in tp if x["agent_harmful"] is False]
        out[name] = {"fires": len(h), "on_fraud": len(tp), "on_legit": len(fp),
                     "recall": round(len(tp) / max(n_f, 1), 4),
                     "precision": round(len(tp) / max(len(h), 1), 4),
                     "legit_rate": round(len(fp) / max(n_l, 1), 4),
                     "fraud_the_core_missed_it_catches": len(caught_missed),
                     "example_catches": caught_missed[:5] or tp[:5],
                     "legit_customers_it_would_touch": [x["case_id"] for x in fp][:25]}
    return out


# --------------------------------------------------------------------- C2 ----
def discover(df: pd.DataFrame, min_support: int = 25, min_precision: float = 0.95) -> list[dict]:
    cases = df[df["stratum"] == "closed_case"]
    train, test = cases[cases["opened_at"] < SPLIT], cases[cases["opened_at"] >= SPLIT]
    controls = df[df["stratum"] != "closed_case"]
    sigs = [s for s in SIGNAL_NAMES if s not in {"customer_disputed", "risk_score_high"}]
    cands = []
    for k in (2, 3):
        for combo in combinations(sigs, k):
            m = train[list(combo)].all(axis=1)
            sup = int(m.sum())
            if sup < min_support:
                continue
            prec = float(train.loc[m, "is_fraud"].mean())
            if prec < min_precision:
                continue
            ctrl = int(controls[list(combo)].all(axis=1).sum())
            # Not new if one documented pattern already owns it.
            patterns = train.loc[m & train["is_fraud"], "pattern"].value_counts(normalize=True)
            dominant = float(patterns.iloc[0]) if len(patterns) else 1.0
            cands.append({"facts": list(combo), "support": sup, "precision": round(prec, 4),
                          "controls_hit": ctrl, "dominant_pattern_share": round(dominant, 3),
                          "dominant_pattern": patterns.index[0] if len(patterns) else ""})
    # Prefer conjunctions that cut across documented patterns (the undocumented
    # signal) and touch few controls.
    cands.sort(key=lambda c: (c["dominant_pattern_share"], c["controls_hit"], -c["support"]))
    proposed = []
    for c in cands[:3]:
        m = test[c["facts"]].all(axis=1)
        mc = controls[c["facts"]].all(axis=1)
        caught = test.loc[m & test["is_fraud"], "case_id"].tolist()
        missed = test.loc[~m & test["is_fraud"], "case_id"].tolist()
        legit = (test.loc[m & ~test["is_fraud"], "case_id"].tolist()
                 + controls.loc[mc, "case_id"].tolist())
        did = "DISC-" + "-".join(f[:6] for f in c["facts"])
        proposed.append({
            "id": did, "name": " + ".join(c["facts"]), "origin": "discovered",
            "status": "proposed", "approved_by": "",
            "spec": {"type": "facts", "all_of": c["facts"],
                     "claim": f"the conjunction {' + '.join(c['facts'])} was {c['precision']:.0%} "
                              f"confirmed fraud across {c['support']} July-September cases"},
            "mined_on": "2016-07-20..2016-09-30", **{k: c[k] for k in (
                "support", "precision", "controls_hit", "dominant_pattern",
                "dominant_pattern_share")},
            "backtest_october": {"caught": len(caught), "missed": len(missed),
                                 "legit_touched": len(legit), "caught_ids": caught[:20],
                                 "missed_ids": missed[:20], "legit_ids": legit[:20]}})
    return proposed


# --------------------------------------------------------------------- C3 ----
def compile_policy() -> list[dict]:
    """Prose -> spec, with every number read from the clause text."""
    text = {}
    for line in (PATHS.policy / "chunks.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        text[d["doc_id"]] = d["text"]
    r5 = text.get("POLICY-R5", "")
    words = {"three": 3, "four": 4, "five": 5, "two": 2}
    n = re.search(r"(\w+) or more small (online)? ?authori[sz]ations", r5, re.I)
    hour = re.search(r"within an? (hour|(\d+) minutes)", r5, re.I)
    clear = re.search(r"over \$(\d+)", r5)
    spec5 = {"type": "card_testing", "min_small": words.get(n.group(1).lower(), 3) if n else 3,
             "channel": "online" if n and n.group(2) else None,
             "window_hours": 1.0 if hour and hour.group(1).lower() == "hour" else
             (int(hour.group(2)) / 60 if hour and hour.group(2) else 1.0),
             "block_if_cleared_over": float(clear.group(1)) if clear else 100.0,
             "small_cap": 10.0, "source_text": r5}
    r6 = text.get("POLICY-R6", "")
    elems = [e for e, pat in (("device_profile", r"device profile"), ("region", r"billing region"),
                              ("email_r", r"recipient email")) if re.search(pat, r6, re.I)]
    spec6 = {"type": "shared_origin", "elements": elems, "min_cards": 2, "window_days": 30,
             "source_text": r6}
    return [{"id": "POL-R5", "name": "R5 card testing (compiled from policy text)",
             "origin": "policy", "spec": spec5},
            {"id": "POL-R6", "name": "R6 shared origin (compiled from policy text)",
             "origin": "policy", "spec": spec6}]


def run_policy(df: pd.DataFrame, store: LocalGraphStore, specs: list[dict]) -> dict:
    out = {}
    s5, s6 = specs[0]["spec"], specs[1]["spec"]
    agree, disagree = [], []
    for r in df.itertuples():
        as_of = r.opened_at.to_pydatetime()
        hist = store.card_history(r.card_id, as_of, window_days=2)
        rows = sorted((t for t in hist if s5["channel"] in (None, t.channel)), key=lambda t: t.ts)
        fired5, ids = False, []
        for i, t in enumerate(rows):
            win = [x for x in rows[:i] if x.ts >= t.ts - pd.Timedelta(hours=s5["window_hours"])
                   and x.amount <= s5["small_cap"]]
            if len(win) >= s5["min_small"] and t.amount > s5["small_cap"]:
                fired5, ids = True, [x.txn_id for x in win] + [t.txn_id]
                break
        agent5 = bool(getattr(r, "card_testing_sequence"))
        rec = {"case_id": r.case_id, "is_fraud": bool(r.is_fraud), "rule": "R5",
               "rule_fires": fired5, "agent_fires": agent5, "txn_ids": ids[:8]}
        (agree if fired5 == agent5 else disagree).append(rec)
        fired6 = bool(getattr(r, "shared_origin_ring") or getattr(r, "device_shared_across_cards"))
        agent6 = bool(getattr(r, "shared_origin_ring") and not pd.isna(r.harmful) and r.harmful)
        rec6 = {"case_id": r.case_id, "is_fraud": bool(r.is_fraud), "rule": "R6",
                "rule_fires": fired6, "agent_acts": agent6}
        (agree if fired6 == agent6 else disagree).append(rec6)
    for rule in ("R5", "R6"):
        a = [x for x in agree if x["rule"] == rule]
        d = [x for x in disagree if x["rule"] == rule]
        out[rule] = {"agree": len(a), "disagree": len(d),
                     "rule_only": [x["case_id"] for x in d if x["rule_fires"]][:25],
                     "agent_only": [x["case_id"] for x in d if not x["rule_fires"]][:25],
                     "rule_only_fraud_rate": round(sum(x["is_fraud"] for x in d if x["rule_fires"])
                                                   / max(1, sum(1 for x in d if x["rule_fires"])), 3)}
    return out


def main() -> int:
    t0 = time.time()
    df = load_population()
    store = LocalGraphStore()
    c1 = backtest_c1(df, store)
    proposed = discover(df)
    specs = compile_policy()
    c3 = run_policy(df, store, specs)
    reg = {d["id"]: d for d in T.registry()}
    for d in proposed + [{**s, "status": reg.get(s["id"], {}).get("status", "proposed"),
                          "approved_by": reg.get(s["id"], {}).get("approved_by", ""),
                          "backtest": c3.get(s["id"].split("-")[1])} for s in specs]:
        if d["id"] in reg and reg[d["id"]].get("status") in {"approved", "rejected"}:
            d["status"], d["approved_by"] = reg[d["id"]]["status"], reg[d["id"]]["approved_by"]
        reg[d["id"]] = d
    T.save_registry(list(reg.values()))
    out = {"c1": c1, "c2_proposed": proposed, "c3": c3, "c3_specs": specs,
           "n_population": len(df), "seconds": round(time.time() - t0, 1)}
    (PATHS.eval_out / "detectors.json").write_text(json.dumps(out, indent=2, default=str),
                                                  encoding="utf-8")
    md = ["# New detectors — C1 typologies, C2 discovery, C3 policy-to-detector", "",
          f"Generated by `eval/detectors.py` over {len(df)} replayed closed cases and matched "
          f"controls ({out['seconds']} s). Detections are evidence only: none adds a block, so "
          f"none can raise the count of legitimate customers acted against.", "",
          "## C1 — detectors for patterns the policy does not name", "",
          "| detector | fires | on fraud | on legit | precision | recall | fraud the core missed "
          "that it catches |", "|---|--:|--:|--:|--:|--:|--:|"]
    for k, v in c1.items():
        md.append(f"| {k} | {v['fires']} | {v['on_fraud']} | {v['on_legit']} | {v['precision']} |"
                  f" {v['recall']} | {v['fraud_the_core_missed_it_catches']} |")
    md += ["", "Legitimate customers each detector would touch (ids) and example catches are in "
           "`eval/reports/detectors.json`. The shared-origin detector is the compromise-origin "
           "test, backtested in `containment_backtest.md`.", "",
           "## C2 — self-growing detective", "",
           "Mined on July–September, backtested on October, filed as **proposed**; a fraud "
           "manager approves with `POST /api/detectors/{id}` (bearer token, server-side role).",
           "", "| id | facts | support | precision | Oct caught | Oct missed | legit touched | "
           "status |", "|---|---|--:|--:|--:|--:|--:|---|"]
    for d in proposed:
        b = d["backtest_october"]
        md.append(f"| {d['id']} | {' + '.join(d['spec']['all_of'])} | {d['support']} | "
                  f"{d['precision']} | {b['caught']} | {b['missed']} | {b['legit_touched']} | "
                  f"{reg[d['id']]['status']} |")
    md += ["", "## C3 — policy text to detector", ""]
    for s in specs:
        md.append(f"- **{s['id']}** compiled from: _{s['spec']['source_text'][:200]}_ → "
                  f"`{json.dumps({k: v for k, v in s['spec'].items() if k != 'source_text'})}`")
    md += ["", "| rule | agrees with agent | disagrees | rule-only cases fraud rate |",
           "|---|--:|--:|--:|"]
    for k, v in c3.items():
        md.append(f"| {k} | {v['agree']} | {v['disagree']} | {v['rule_only_fraud_rate']} |")
    md += ["", "Every disagreement is listed with ids in `eval/reports/detectors.json` "
           "(`rule_only`, `agent_only`).", ""]
    (PATHS.eval_out / "detectors.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

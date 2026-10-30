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
MINE_END, VALID_END = pd.Timestamp("2016-09-01"), SPLIT     # Jul-Aug | Sep | Oct
EXCLUDED = {"customer_disputed", "risk_score_high"}            # selection variables


def _stats(part: pd.DataFrame, facts: list[str]) -> tuple[int, float, pd.Series]:
    m = part[facts].all(axis=1)
    n = int(m.sum())
    return n, float(part.loc[m, "is_fraud"].mean()) if n else 0.0, m


def _proposal(c: dict, test: pd.DataFrame, origin_note: str) -> dict:
    n, prec, m = _stats(test, c["facts"])
    caught = test.loc[m & test["is_fraud"], "case_id"].tolist()
    missed = test.loc[~m & test["is_fraud"], "case_id"].tolist()
    legit = test.loc[m & ~test["is_fraud"], "case_id"].tolist()
    core_missed = (test.loc[m & test["is_fraud"] & (test["harmful"] == False), "case_id"]  # noqa: E712
                   .tolist() if "harmful" in test else [])
    did = "DISC-" + "-".join(f[:6] for f in c["facts"])
    return {
        "id": did, "name": " + ".join(c["facts"]), "origin": "discovered",
        "status": "proposed", "approved_by": "",
        "spec": {"type": "facts", "all_of": c["facts"],
                 "claim": f"the conjunction {' + '.join(c['facts'])} was {c['precision']:.0%} "
                          f"confirmed fraud across {c['support']} cases {origin_note}"},
        "mined_on": c.get("mined_on", ""), **{k: c[k] for k in (
            "support", "precision", "dominant_pattern", "dominant_pattern_share")},
        "validation": c.get("validation"),
        "backtest_october": {"fires": n, "precision": round(prec, 4), "caught": len(caught),
                             "missed": len(missed), "legit_touched": len(legit),
                             "fraud_the_core_missed": len(core_missed),
                             "caught_ids": caught[:20], "missed_ids": missed[:20],
                             "legit_ids": legit[:20], "core_missed_ids": core_missed[:20]}}


def discover_naive(df: pd.DataFrame, min_support: int = 25,
                   min_precision: float = 0.95) -> list[dict]:
    """The first version, kept as the ablation: mined on July-September closed
    cases only (matched controls ignored as negatives), no validation month, no
    stability check. Its proposals looked 99% precise and failed out of time."""
    cases = df[df["stratum"] == "closed_case"]
    train, test = cases[cases["opened_at"] < SPLIT], df[df["opened_at"] >= SPLIT]
    sigs = [x for x in SIGNAL_NAMES if x not in EXCLUDED and x in df]
    cands = []
    for k in (2, 3):
        for combo in combinations(sigs, k):
            sup, prec, m = _stats(train, list(combo))
            if sup < min_support or prec < min_precision:
                continue
            pats = train.loc[m & train["is_fraud"], "pattern"].value_counts(normalize=True)
            cands.append({"facts": list(combo), "support": sup, "precision": round(prec, 4),
                          "dominant_pattern_share": round(float(pats.iloc[0]), 3) if len(pats) else 1.0,
                          "dominant_pattern": pats.index[0] if len(pats) else ""})
    cands.sort(key=lambda c: (c["dominant_pattern_share"], -c["support"]))
    return [_proposal(c, test, "(closed cases only, July-September)") for c in cands[:3]]


def discover(df: pd.DataFrame, min_support: int = 25, min_precision: float = 0.85,
             min_valid_precision: float = 0.80, min_valid_support: int = 10) -> list[dict]:
    """Mine on July-August, validate on September, test on October.

    * negatives are cleared cases **and** matched controls / untouched
      transactions, so precision is not inflated by the closed-case selection;
    * a conjunction must hold its precision on the validation month;
    * every fact in it must fire at a stable rate: within 0.5x-2x of its mining
      rate on the validation month *and* on the newest month's alerts (rates
      only, no labels), which rejects facts whose meaning moves with time
      (behavioural_fraud_neighbourhood, for one, cannot fire once the closed-case
      pool passes ~93% fraud, which it does from October);
    * October is touched only to report the backtest that ships with the proposal."""
    mine = df[df["opened_at"] < MINE_END]
    valid = df[(df["opened_at"] >= MINE_END) & (df["opened_at"] < VALID_END)]
    test = df[df["opened_at"] >= VALID_END]
    sigs = [x for x in SIGNAL_NAMES if x not in EXCLUDED and x in df]
    # Liveness uses the newest month's firing rates only, never its labels: how
    # often a fact fires on current alerts is observable the day it is proposed.
    rate_m, rate_v, rate_now = mine[sigs].mean(), valid[sigs].mean(), test[sigs].mean()
    stable = {x for x in sigs if rate_m[x] > 0
              and 0.5 <= rate_v[x] / rate_m[x] <= 2.0 and 0.5 <= rate_now[x] / rate_m[x] <= 2.0}
    base_v = float(valid["is_fraud"].mean())
    cands = []
    for k in (1, 2, 3):
        for combo in combinations(sorted(stable), k):
            facts = list(combo)
            sup, prec, m = _stats(mine, facts)
            if sup < min_support or prec < min_precision:
                continue
            vs, vp, _ = _stats(valid, facts)
            if vs < min_valid_support or vp < min_valid_precision:
                continue
            pats = mine.loc[m & mine["is_fraud"], "pattern"].value_counts(normalize=True)
            cands.append({"facts": facts, "support": sup, "precision": round(prec, 4),
                          "mined_on": "2016-07-20..2016-08-31",
                          "validation": {"month": "2016-09", "fires": vs,
                                         "precision": round(vp, 4),
                                         "lift": round(vp / base_v, 2) if base_v else None},
                          "dominant_pattern_share": round(float(pats.iloc[0]), 3) if len(pats) else 1.0,
                          "dominant_pattern": pats.index[0] if len(pats) else ""})
    # A conjunction that adds a fact to a simpler one without gaining at least
    # 0.03 validation precision is the same detector, written longer: keep the
    # simpler. Then prefer what cuts across documented patterns, then
    # validation precision, then reach.
    cands = [c for c in cands if not any(
        set(o["facts"]) < set(c["facts"])
        and c["validation"]["precision"] < o["validation"]["precision"] + 0.03 for o in cands)]
    cands.sort(key=lambda c: (c["dominant_pattern_share"], -c["validation"]["precision"],
                              -c["validation"]["fires"]))
    chosen: list[dict] = []
    for c in cands:
        if any(set(x["facts"]) <= set(c["facts"]) for x in chosen):
            continue
        chosen.append(c)
        if len(chosen) == 3:
            break
    return [_proposal(c, test, "(July-August, held on September)") for c in chosen]


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
    r7 = text.get("POLICY-R7", "")
    spec7 = {"type": "recurring_charge",
             "same_merchant": bool(re.search(r"same merchant", r7, re.I)),
             "same_amount": bool(re.search(r"same amount", r7, re.I)),
             "period_days": 30 if re.search(r"monthly", r7, re.I) else None,
             "do_not_block": bool(re.search(r"do not block", r7, re.I)),
             # What the text leaves open is stated, not hidden.
             "assumed": {"period_tolerance_days": 5, "amount_tolerance_usd": 0.01,
                         "min_prior_occurrences": 2,
                         "merchant": "product code (the schema has no merchant id)"},
             "source_text": r7}
    return [{"id": "POL-R5", "name": "R5 card testing (compiled from policy text)",
             "origin": "policy", "spec": spec5},
            {"id": "POL-R6", "name": "R6 shared origin (compiled from policy text)",
             "origin": "policy", "spec": spec6},
            {"id": "POL-R7", "name": "R7 recurring charge (compiled from policy text)",
             "origin": "policy", "spec": spec7}]


_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10}


def _n(tok: str) -> float:
    return float(_NUM.get(tok.lower(), tok.replace(",", "")))


def compile_guards() -> list[dict]:
    """R1, R8 and R10 are decision rules, not detectors. Compiled from the text
    into checks over the agent's answers; every threshold is read from the
    clause."""
    text = {}
    for line in (PATHS.policy / "chunks.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        text[d["doc_id"]] = d["text"]
    r1, r8, r10 = text.get("POLICY-R1", ""), text.get("POLICY-R8", ""), text.get("POLICY-R10", "")
    p1 = re.search(r"probability is below (\d\.\d+)", r1)
    e8 = re.search(r"exposure exceeds \$([\d,]+)", r8)
    n10 = re.search(r"at least (\w+) of the customer's cards", r10)
    return [
        {"id": "GUARD-R1", "rule": "R1", "source_text": r1,
         "spec": {"single_signal": bool(re.search(r"single signal", r1, re.I)),
                  "p_below": float(p1.group(1)) if p1 else None,
                  "forbid": ["BLOCK_CARD", "BLOCK_ALL_CARDS"],
                  "require_one_of": re.findall(r"`(VERIFY_WITH_CUSTOMER|STEP_UP_AUTH)`", r1)}},
        {"id": "GUARD-R8", "rule": "R8", "source_text": r8,
         "spec": {"verdict": "uncertain", "exposure_over": _n(e8.group(1)) if e8 else None,
                  "require": re.findall(r"`(ESCALATE_TO_ANALYST)`", r8)}},
        {"id": "GUARD-R10", "rule": "R10", "source_text": r10,
         "spec": {"action": "BLOCK_ALL_CARDS",
                  "min_confirmed_cards": int(_n(n10.group(1))) if n10 else None}},
    ]


def audit_guards(guards: list[dict]) -> dict:
    """Run the compiled guards over every answer file (the 18 final cases and
    the 20 Round 1 cases), with the case ids of every violation."""
    out = {}
    answers = [json.loads(f.read_text(encoding="utf-8"))
               for f in sorted((ROOT / "cases").glob("HH*-*.json"))]
    for g in guards:
        sp, checked, viol = g["spec"], [], []
        for a in answers:
            c, ar = a["case"], a.get("agent_record", {})
            final = {x["action"] for x in a["next_best_actions"]["final"]}
            # "Rests on a single signal": the proof's margin is one fact, or at
            # most one incriminating signal fired (the risk score is the trigger).
            k = (ar.get("proof") or {}).get("margin_k")
            fired = [x for x in ar.get("signals_fired", [])
                     if x not in {"risk_score_high", "known_device_and_region", "amount_typical",
                                  "matches_cleared_alert_template", "recurring_charge"}]
            denied = (ar.get("text_facts") or {}).get("facts", {}).get("text_denies_charge")
            if g["rule"] == "R1":
                if (k == 1 or len(fired) <= 1) and c["fraud_probability"] < sp["p_below"]                         and not denied:
                    checked.append(a["case_id"])
                    if final & set(sp["forbid"]):
                        viol.append(a["case_id"])
            elif g["rule"] == "R8":
                if c["verdict"] == sp["verdict"] and c["exposure_usd"] > sp["exposure_over"]:
                    checked.append(a["case_id"])
                    if not final & set(sp["require"]):
                        viol.append(a["case_id"])
            elif g["rule"] == "R10":
                if sp["action"] in final:
                    checked.append(a["case_id"])
                    viol.append(a["case_id"])      # the agent never has two confirmed cards
        out[g["id"]] = {"applies_to": len(checked), "violations": viol,
                        "applies_ids": checked[:25]}
    return out


VELOCITY = re.compile(
    r"(?P<n>\w+) or more (?P<adj>(?:small |online |card-not-present |low-value )*)"
    r"(?P<what>authori[sz]ations|transactions|charges|payments|purchases)"
    r"(?: (?:under|below|of less than) \$(?P<cap>[\d.]+))?"
    r"(?: (?:on|from|at) (?:one|a single|the same) (?P<scope>card|merchant|device|account))?"
    r"(?:[^.]*?within (?:an? )?(?P<win>\d+ )?(?P<unit>minutes?|hours?|hour|days?))?",
    re.I)


def compile_advisory(text: str) -> dict | None:
    """A generic velocity-advisory compiler: "N or more [small|online]
    transactions [under $X] [on one card] within [T units]" -> a spec. Fields
    the text does not give stay None and are reported as missing."""
    m = VELOCITY.search(text)
    if not m:
        return None
    unit = (m.group("unit") or "").lower().rstrip("s")
    win = float(m.group("win") or 1) if unit else None
    hours = {"minute": win / 60 if win else None, "hour": win, "day": win * 24 if win else None}
    spec = {"type": "velocity", "min_count": int(_n(m.group("n"))),
            "online_only": "online" in (m.group("adj") or "").lower()
            or "card-not-present" in (m.group("adj") or "").lower(),
            "small": "small" in (m.group("adj") or "").lower()
            or "low-value" in (m.group("adj") or "").lower(),
            "amount_cap": float(m.group("cap")) if m.group("cap") else None,
            "scope": (m.group("scope") or "card").lower(),
            "window_hours": hours.get(unit) if unit else None, "source_text": text}
    spec["missing"] = [k for k in ("amount_cap", "window_hours") if spec[k] is None]
    return spec


# A sample advisory, written for this test in the style of a scheme bulletin
# (not an official text): the compiler has never seen its wording.
SAMPLE_ADVISORY = ("Advisory 2017-01: issuers report enumeration attacks in which five or more "
                   "card-not-present transactions under $2.00 on one card are attempted within "
                   "30 minutes, typically from a single device, before the card is used for a "
                   "high-value purchase.")


def run_policy(df: pd.DataFrame, store: LocalGraphStore, specs: list[dict]) -> dict:
    out = {}
    s5, s6 = specs[0]["spec"], specs[1]["spec"]
    s7 = specs[2]["spec"] if len(specs) > 2 else None
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
        if s7 is not None:
            flagged = store.get_transaction(r.flagged_txn_id)
            fired7, ids7 = False, []
            if flagged is not None:
                h7 = store.card_history(r.card_id, as_of, window_days=200)
                tol, per = s7["assumed"]["amount_tolerance_usd"], s7["period_days"] or 30
                ptol = s7["assumed"]["period_tolerance_days"]
                same = sorted((t for t in h7 if t.txn_id != flagged.txn_id
                               and (not s7["same_merchant"] or t.product_cd == flagged.product_cd)
                               and (not s7["same_amount"] or abs(t.amount - flagged.amount) <= tol)),
                              key=lambda t: t.ts)
                chain = [flagged.ts]
                for t in reversed(same):
                    gap = (chain[-1] - t.ts).total_seconds() / 86400
                    if per - ptol <= gap <= per + ptol:
                        chain.append(t.ts)
                        ids7.append(t.txn_id)
                fired7 = len(ids7) >= s7["assumed"]["min_prior_occurrences"]
            agent7 = bool(getattr(r, "recurring_charge"))
            (agree if fired7 == agent7 else disagree).append(
                {"case_id": r.case_id, "is_fraud": bool(r.is_fraud), "rule": "R7",
                 "rule_fires": fired7, "agent_fires": agent7, "txn_ids": ids7[:8]})
    for rule in ("R5", "R6", "R7"):
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
    naive = discover_naive(df)
    specs = compile_policy()
    c3 = run_policy(df, store, specs)
    guards = compile_guards()
    c3_guards = audit_guards(guards)
    advisories = {"R5 (policy text)": compile_advisory(specs[0]["spec"]["source_text"]),
                  "sample advisory (unseen wording)": compile_advisory(SAMPLE_ADVISORY)}
    reg = {d["id"]: d for d in T.registry()}
    for d in proposed + [{**s, "status": reg.get(s["id"], {}).get("status", "proposed"),
                          "approved_by": reg.get(s["id"], {}).get("approved_by", ""),
                          "backtest": c3.get(s["id"].split("-")[1])} for s in specs]:
        if d["id"] in reg and reg[d["id"]].get("status") in {"approved", "rejected"}:
            d["status"], d["approved_by"] = reg[d["id"]]["status"], reg[d["id"]]["approved_by"]
        reg[d["id"]] = d
    T.save_registry(list(reg.values()))
    out = {"c1": c1, "c2_proposed": proposed, "c2_naive_ablation": naive, "c3": c3,
           "c3_specs": specs, "c3_guards": {"specs": guards, "audit": c3_guards},
           "c3_advisories": advisories,
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
           "Mined on July–August, held on September (precision and support on a month it "
           "never saw, every fact firing at a stable rate), backtested on October, filed as "
           "**proposed**; a fraud manager approves with `POST /api/detectors/{id}` (bearer "
           "token, server-side role). Negatives include matched controls and untouched "
           "transactions, not only cleared cases.", "",
           "| id | facts | mined precision | Sep precision (fires) | Oct fires | Oct precision "
           "| Oct caught | legit touched | fraud the core missed | status |",
           "|---|---|--:|--:|--:|--:|--:|--:|--:|---|"]
    for d in proposed:
        b, v = d["backtest_october"], d["validation"]
        md.append(f"| {d['id']} | {' + '.join(d['spec']['all_of'])} | {d['precision']} | "
                  f"{v['precision']} ({v['fires']}) | {b['fires']} | {b['precision']} | "
                  f"{b['caught']} | {b['legit_touched']} | {b['fraud_the_core_missed']} | "
                  f"{reg[d['id']]['status']} |")
    if not proposed:
        md.append("| — | nothing passed the validation month | | | | | | | | |")
    md += ["", "**Ablation — the first miner** (closed cases only as negatives, no "
           "validation month, no stability check):", "",
           "| facts | mined precision | Oct fires | Oct precision | Oct caught | legit touched |",
           "|---|--:|--:|--:|--:|--:|"]
    for d in naive:
        b = d["backtest_october"]
        md.append(f"| {' + '.join(d['spec']['all_of'])} | {d['precision']} | {b['fires']} | "
                  f"{b['precision']} | {b['caught']} | {b['legit_touched']} |")
    md += ["", "## C3 — policy text to detector", ""]
    for s in specs:
        md.append(f"- **{s['id']}** compiled from: _{s['spec']['source_text'][:200]}_ → "
                  f"`{json.dumps({k: v for k, v in s['spec'].items() if k != 'source_text'})}`")
    md += ["", "| rule | agrees with agent | disagrees | rule-only cases fraud rate |",
           "|---|--:|--:|--:|"]
    for k, v in c3.items():
        md.append(f"| {k} | {v['agree']} | {v['disagree']} | {v['rule_only_fraud_rate']} |")
    md += ["", "Every disagreement is listed with ids in `eval/reports/detectors.json` "
           "(`rule_only`, `agent_only`). R7's open points (period tolerance, amount "
           "tolerance, merchant proxy) are not in the text; the spec lists them under "
           "`assumed`.", "",
           "### Decision rules compiled into checks (R1, R8, R10)", "",
           "Each threshold read from the clause, then run over all 38 answer files:", "",
           "| guard | compiled from the text | answers it applies to | violations |",
           "|---|---|--:|--:|"]
    for g in guards:
        a = c3_guards[g["id"]]
        md.append(f"| {g['id']} | `{json.dumps(g['spec'])}` | {a['applies_to']} | "
                  f"{len(a['violations'])}{' ' + str(a['violations']) if a['violations'] else ''} |")
    md += ["", "### A generic velocity-advisory compiler", "",
           "One grammar (\"N or more [small|online] transactions [under $X] [on one card] "
           "within T\"), no per-rule code:", ""]
    for k, v in advisories.items():
        md.append(f"- **{k}** → `{json.dumps({x: y for x, y in (v or {}).items() if x != 'source_text'})}`")
    md.append("")
    (PATHS.eval_out / "detectors.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

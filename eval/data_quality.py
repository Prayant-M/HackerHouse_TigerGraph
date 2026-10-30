"""Data quality detective (challenge C11).

Two halves, both attested by record ids:

1. **The dataset.** Identity coverage, empty billing regions, placeholder
   values (the `anonymous.com` email domain, device strings with empty
   components), and cards whose history is too thin to judge — each with
   counts and sample ids, and what it blinds.
2. **Our own investigations.** For every answer file, the gaps that touch *that*
   decision (`agent_record.quality`), re-checked against the graph with the
   installed `data_gaps` query, and whether the case is tainted (taint widens
   the conformal set and routes to uncertain + escalate under R8).

    python eval/data_quality.py      -> eval/reports/data_quality.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from fraudagent.config import PATHS  # noqa: E402
from fraudagent.core.quality import BLINDS, THIN_HISTORY_TXNS  # noqa: E402
from fraudagent.graphstore import get_store  # noqa: E402


def dataset_report() -> dict:
    tx = pd.read_parquet(PATHS.tx_parquet, columns=["txn_id", "card_id", "channel", "region",
                                                    "email_p", "device_profile", "has_identity"])
    n = len(tx)
    online = tx[tx["channel"] == "online"]
    dp = tx["device_profile"].astype(str)
    placeholder_dev = dp.str.split("|").apply(lambda p: len(p) > 1 and sum(1 for x in p
                                                                           if not x.strip()) >= 2)
    per_card = tx.groupby("card_id").size()
    out = {
        "transactions": n,
        "no_identity": {"n": int((~tx["has_identity"].astype(bool)).sum()),
                        "share": round(float((~tx["has_identity"].astype(bool)).mean()), 4),
                        "online_share_without": round(float((~online["has_identity"]
                                                             .astype(bool)).mean()), 4),
                        "sample": tx.loc[~tx["has_identity"].astype(bool), "txn_id"].head(5)
                        .astype(str).tolist(), "blinds": list(BLINDS["missing_identity"])},
        "empty_billing_region": {"n": int((tx["region"].astype(str).isin(["", "nan"])).sum()),
                                 "sample": tx.loc[tx["region"].astype(str).isin(["", "nan"]),
                                                  "txn_id"].head(5).astype(str).tolist(),
                                 "blinds": list(BLINDS["empty_billing_region"])},
        "placeholder_email": {"n": int(tx["email_p"].astype(str).isin(["anonymous.com"]).sum()),
                              "sample": tx.loc[tx["email_p"] == "anonymous.com", "txn_id"]
                              .head(5).astype(str).tolist(),
                              "blinds": list(BLINDS["placeholder_email"])},
        "placeholder_device": {"n": int(placeholder_dev.sum()),
                               "sample": tx.loc[placeholder_dev, "txn_id"].head(5).astype(str)
                               .tolist(), "blinds": list(BLINDS["placeholder_device"])},
        "thin_cards": {"n": int((per_card < THIN_HISTORY_TXNS).sum()),
                       "of_cards": int(per_card.size),
                       "sample": per_card[per_card < THIN_HISTORY_TXNS].head(5).index.tolist(),
                       "blinds": list(BLINDS["thin_history"])},
    }
    return out


def investigations() -> list[dict]:
    store = get_store()
    rows = []
    for p in sorted(list(PATHS.cases_out.glob("HHF-*.json")) + list(PATHS.cases_out.glob("HHG-*.json"))):
        a = json.loads(p.read_text(encoding="utf-8"))
        q = a.get("agent_record", {}).get("quality", {})
        ids = [a["agent_record"]["trigger"]["flagged_txn_id"]] + list(a["case"]["affected_txn_ids"])
        try:
            g = store.data_gaps(ids)
        except Exception as exc:
            g = {"error": str(exc)}
        rows.append({"case": a["case_id"], "verdict": a["case"]["verdict"],
                     "tainted": q.get("tainted"), "severity": q.get("severity"),
                     "issues": [i["kind"] for i in q.get("issues", [])],
                     "record_ids": sorted({r for i in q.get("issues", []) for r in i["record_ids"]})[:6],
                     "graph_check": {k: v for k, v in g.items() if k != "n"},
                     "conformal_widened": "data_quality_taint" in (
                         a.get("agent_record", {}).get("conformal", {}).get("widened_by") or [])})
    return rows


def main() -> int:
    ds = dataset_report()
    inv = investigations()
    (PATHS.eval_out / "data_quality.json").write_text(json.dumps({"dataset": ds,
                                                                 "investigations": inv},
                                                                indent=2, default=str),
                                                     encoding="utf-8")
    md = ["# Data quality detective", "", "Generated by `eval/data_quality.py`.", "",
          "## Gaps in the data that matter", "", "| gap | records | sample ids | what it blinds |",
          "|---|--:|---|---|"]
    for k, v in ds.items():
        if isinstance(v, dict):
            md.append(f"| {k} | {v['n']:,} | {', '.join(map(str, v['sample'][:3]))} | "
                      f"{', '.join(v['blinds'])} |")
    md += ["", f"{ds['no_identity']['share']:.0%} of transactions have no identity record "
           f"({ds['no_identity']['online_share_without']:.0%} of online ones), so device and "
           "proxy evidence is *unavailable*, not clean.", "",
           "## Which of our investigations the gaps taint", "",
           "| case | verdict | tainted | gaps | record ids | graph re-check | conformal widened |",
           "|---|---|---|---|---|---|---|"]
    for r in inv:
        gc = r["graph_check"]
        gtxt = ("error" if "error" in gc else
                ", ".join(f"{k}:{len(v)}" for k, v in gc.items() if isinstance(v, list) and v)
                or "none")
        md.append(f"| {r['case']} | {r['verdict']} | {'**yes**' if r['tainted'] else 'no'} | "
                  f"{', '.join(r['issues']) or '—'} | {', '.join(r['record_ids'][:3])} | {gtxt} | "
                  f"{'yes' if r['conformal_widened'] else 'no'} |")
    md += ["", f"**{sum(1 for r in inv if r['tainted'])} of {len(inv)} investigations are "
           "tainted** by a gap that blinds evidence the decision could have used. A tainted case "
           "cannot be called fraud with a block: the conformal set widens to {fraud, legit}.", ""]
    conf = PATHS.staged / "card_label_conflicts.json"
    if conf.exists():
        md += ["## Conflicting labels in the supplied data", ""]
        for c in json.loads(conf.read_text(encoding="utf-8")):
            md.append(f"- {c['case_id']}: transaction {c['txn_id']} is labelled "
                      f"`{c['pack_card_id']}` by the case pack, but every closed case on that "
                      f"card tuple says `{c['history_card_id']}`. The pack wins for its own "
                      f"flagged transaction (ingest/01_normalise.py), and the conflict is "
                      f"reported here rather than resolved silently.")
        md.append("")
    (PATHS.eval_out / "data_quality.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Stage 8 — a fact vector for every closed investigation.

Proof-carrying verdicts (core/proof.py) need to ask "how did the bank rule on
past cases that had exactly these facts?", and conformal abstention
(core/conformal.py) needs a calibrated probability for every closed case. Both
come from the same replay: each closed case is run through the *same* signal
extractor the agent uses, under its own `as_of`, and the fired signals are
stored as a bitmask.

The bitmask is also what `graph/queries/precedent_by_facts.gsql` matches on
(`ClosedCase.fact_mask`), so the precedent count in an answer file is a query
anyone can re-run.

    python ingest/08_fact_vectors.py              # every closed case + controls
    python ingest/08_fact_vectors.py --limit 300  # quick pass
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from fraudagent.config import PATHS  # noqa: E402
from fraudagent.core.proof import FACT_BITS, mask_of  # noqa: E402
from fraudagent.core.signals import SIGNAL_NAMES, extract  # noqa: E402
from fraudagent.graphstore import get_store  # noqa: E402


def _calibrate_module():
    spec = importlib.util.spec_from_file_location("calib", ROOT / "ingest" / "05_calibrate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--only-new", action="store_true",
                    help="append replays for closed cases not yet in the fact table")
    args = ap.parse_args()

    calib = _calibrate_module()
    store = get_store("local")
    pop = calib.build_alert_population(args.limit or None, args.seed)
    out_path = PATHS.staged / "closed_case_facts.parquet"
    existing = None
    if args.only_new and out_path.exists():
        existing = pd.read_parquet(out_path)
        pop = pop[(pop["stratum"] == "closed_case") & ~pop["alert_id"].isin(existing["case_id"])]
        print(f"[facts] {len(pop)} new closed cases to replay", flush=True)
    rows: list[dict] = []
    t0 = time.time()
    for i, r in enumerate(pop.itertuples(), 1):
        try:
            ctx = extract(store, r.alert_id, r.flagged_txn_id, r.card_id, r.customer_id,
                          r.as_of, "risk_score")
        except KeyError:
            continue
        fired = {s: bool(ctx.fired(s)) for s in SIGNAL_NAMES}
        row = {"case_id": r.alert_id, "stratum": r.stratum, "opened_at": r.as_of,
               "card_id": r.card_id, "flagged_txn_id": str(r.flagged_txn_id),
               "outcome": r.outcome, "pattern": r.pattern, "is_fraud": bool(r.is_fraud),
               "exposure_usd": float(r.exposure_usd),
               "risk_score": float(ctx.flagged.risk_score),
               "fact_mask": mask_of(k for k, v in fired.items() if v)}
        row.update(fired)
        rows.append(row)
        if i % 250 == 0:
            rate = (time.time() - t0) / i
            print(f"[facts] {i}/{len(pop)} ({rate*1000:.0f} ms/case, "
                  f"{rate*(len(pop)-i)/60:.1f} min left)", flush=True)
    df = pd.DataFrame(rows)
    if existing is not None:
        df = pd.concat([existing, df], ignore_index=True)
    out = out_path
    df.to_parquet(out, index=False)
    print(f"[facts] wrote {len(df)} fact vectors ({len(FACT_BITS)} bits) to {out} "
          f"in {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

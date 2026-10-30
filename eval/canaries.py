"""Future-dated canaries: a temporal-wall proof a judge can run in a minute.

Plants transactions with ids `CANARY-*` and timestamps in 2099 on the case's
own card, runs the investigation, and removes them. Every graph query is
bounded by `as_of`, so none may come back; `agent/recorder.py` aborts the run
with TemporalWallBreach if one does. A negative control queries the same card
*without* an as_of bound and must see the canaries, proving they were planted.

On TigerGraph the canaries are written with the loader (superuser) connection,
never the agent's, and deleted afterwards. On the local mirror they are
injected in memory.

    python eval/canaries.py --case HHG-014
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmark"))
os.environ.setdefault("AGENT_USE_LLM", "0")

from fraudagent.agent.graph import Investigator, trigger_from_row  # noqa: E402
from fraudagent.agent.recorder import RecordingStore, TemporalWallBreach  # noqa: E402
from fraudagent.graphstore import get_store  # noqa: E402
from run_case import load_row, pack_path  # noqa: E402

N = 3


def plant_local(store, card: str, customer: str) -> list[str]:
    import pandas as pd

    ds = store.ds
    tmpl = ds.tx.iloc[ds.card_rows[card][-1]].to_dict()
    rows = []
    for i in range(N):
        r = dict(tmpl)
        r.update(txn_id=f"CANARY-{i}", ts=pd.Timestamp(datetime(2099, 1, 1 + i, 12)),
                 amount=999.0 + i)
        rows.append(r)
    store.inject_rows(rows)
    return [r["txn_id"] for r in rows]


def plant_tg(store, card: str, customer: str) -> list[str]:
    ids = [f"CANARY-{i}" for i in range(N)]
    conn = store.conn
    for i, t in enumerate(ids):
        conn.upsertVertex("Transaction", t, {"ts": f"2099-01-0{i + 1} 12:00:00", "amount": 999.0,
                                             "card_id": card, "customer_id": customer,
                                             "channel": "online", "product_cd": "W"})
        conn.upsertEdge("Transaction", t, "MADE_WITH", "Card", card)
    return ids


def remove_tg(store, ids: list[str]) -> None:
    for t in ids:
        try:
            store.conn.delVerticesById("Transaction", t)
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="HHG-014")
    args = ap.parse_args()
    row = load_row(pack_path(), args.case)
    store = get_store()
    tg = store.backend == "tigergraph"
    ids = (plant_tg if tg else plant_local)(store, row["card_id"], row["customer_id"])
    try:
        unbounded = store.card_history(row["card_id"], datetime(2100, 1, 1))
        seen = sum(1 for t in unbounded if t.txn_id.startswith("CANARY-"))
        rec = RecordingStore(store, f"canary-{args.case}")
        try:
            Investigator(rec).run(trigger_from_row(row), args.case)
            leaked = False
        except TemporalWallBreach as exc:
            leaked = True
            print(f"LEAK: {exc}")
    finally:
        if tg:
            remove_tg(store, ids)
    ok = seen == N and not leaked
    print(f"{'PASS' if ok else 'FAIL'}: {N} canaries planted on {row['card_id']} "
          f"({'tigergraph' if tg else 'mirror'}); negative control saw {seen}; "
          f"investigation saw {'some' if leaked else 'none'} across {len(rec.calls)} tool calls")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

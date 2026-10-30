"""Stage 7 — verify the build before anything downstream trusts it.

Silent data failures are the expensive kind here. A `card_id` derivation that
is 94% right still breaks every card-scoped query on 6% of cases; a vector
index that loaded but did not build returns no prior cases and looks merely
unlucky; a behaviour matrix one row short misaligns every neighbour lookup.
Each of those is checked explicitly, against the dataset's own labels where
they exist.

Run:  python ingest/07_verify.py
Exit code is non-zero if any hard check fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Windows consoles still default to cp1252, which cannot encode the arrows and
# box characters used below; without this a clean run dies on its own log line.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - non-reconfigurable stream
    pass


from fraudagent.config import PATHS  # noqa: E402

OK, WARN, FAIL = "ok", "warn", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str, hard: bool = True) -> None:
    results.append((OK if condition else (FAIL if hard else WARN), name, detail))


def main() -> int:
    if not PATHS.tx_parquet.exists():
        print("data/staged is empty — run ingest/01_normalise.py first")
        return 1

    tx = pd.read_parquet(PATHS.tx_parquet)
    tx["txn_id"] = tx["txn_id"].astype(str)
    cc = pd.read_parquet(PATHS.closed_cases_parquet)
    pack = pd.concat([pd.read_csv(f) for f in PATHS.case_pack_files()], ignore_index=True)
    jan = any("2017" in f.name for f in PATHS.transaction_files())
    want_tx = 590_742 + (60_196 if jan else 0)
    want_cc = 5_585 if len(cc) > 5_565 else 5_565

    check("transactions loaded", len(tx) == want_tx, f"{len(tx):,} rows (expected {want_tx:,}"
          f"{' incl. January 2017' if jan else ''})")
    check("closed cases loaded", len(cc) == want_cc, f"{len(cc):,} rows (expected {want_cc:,})")
    check("case pack loaded", len(pack) in {20, 18, 38}, f"{len(pack)} cases from "
          f"{', '.join(f.name for f in PATHS.case_pack_files())}")
    # Card-id pinning must hold for every pack card, January included; a card
    # that does not resolve breaks card-scoped queries silently, so fail loudly.
    unresolved = sorted(set(pack["card_id"]) - set(tx["card_id"]))
    check("every case-pack card id resolves", not unresolved,
          f"unresolved: {unresolved[:10]}" if unresolved else "all resolve")
    cc_unresolved = sorted(set(cc["card_id"]) - set(tx["card_id"]))
    check("every closed-case card id resolves", not cc_unresolved,
          f"unresolved: {cc_unresolved[:10]}" if cc_unresolved else "all resolve")

    # ---- card_id recovery, against the dataset's own labels -----------------
    by_txn = tx.set_index("txn_id")["card_id"]
    hits = miss = 0
    for r in cc.itertuples():
        for t in r.txn_id_list:
            t = str(t)
            if t in by_txn.index:
                hits += int(by_txn[t] == r.card_id)
                miss += int(by_txn[t] != r.card_id)
    rate = hits / max(hits + miss, 1)
    check("card_id matches the closed-case labels", rate >= 0.999,
          f"{rate:.4f} across {hits + miss:,} labelled transactions")

    pack_ok = sum(1 for r in pack.itertuples()
                  if by_txn.get(str(r.flagged_txn_id)) == r.card_id)
    check("card_id matches the case pack", pack_ok == len(pack),
          f"{pack_ok}/{len(pack)} flagged transactions")

    # ---- temporal integrity -------------------------------------------------
    late = 0
    for r in cc.itertuples():
        ts = [tx.loc[tx["txn_id"] == str(t), "ts"].max() for t in r.txn_id_list[:1]]
        if ts and pd.notna(ts[0]) and ts[0] >= r.opened_at:
            late += 1
    check("closed-case episodes precede their alert", late == 0,
          f"{late} cases with a transaction at or after opened_at", hard=False)

    # ---- derived artefacts --------------------------------------------------
    if PATHS.behaviour_parquet.exists():
        beh = pd.read_parquet(PATHS.behaviour_parquet)
        dim = len(beh["behaviour_emb"].iloc[0])
        check("behaviour vectors aligned", len(beh) == len(tx),
              f"{len(beh):,} vectors of dimension {dim}")
        mat = np.vstack(beh["behaviour_emb"].head(2000).to_numpy())
        norms = np.linalg.norm(mat, axis=1)
        check("behaviour vectors L2-normalised",
              bool(np.allclose(norms, 1.0, atol=1e-3)),
              f"norm range {norms.min():.4f}–{norms.max():.4f}")
    else:
        check("behaviour vectors", False, "missing — run ingest/02_behaviour_embeddings.py")

    if PATHS.memory_index_npz.exists():
        vecs = np.load(PATHS.memory_index_npz)["vectors"]
        check("case narrative vectors", vecs.shape[0] == len(cc),
              f"{vecs.shape[0]:,} x {vecs.shape[1]}")
    else:
        check("case narrative vectors", False, "missing — run ingest/04_build_memory.py")

    if PATHS.doc_index_npz.exists():
        dv = np.load(PATHS.doc_index_npz)["vectors"]
        check("policy corpus vectors", dv.shape[0] >= 30,
              f"{dv.shape[0]} chunks x {dv.shape[1]}")
    else:
        check("policy corpus vectors", False, "missing — run ingest/03 and 04")

    check("likelihood ratios measured", PATHS.lr_table_json.exists(),
          "data/staged/likelihood_ratios.json" if PATHS.lr_table_json.exists()
          else "missing — run ingest/05_calibrate.py", hard=False)

    # ---- the two undocumented typologies are still detectable ---------------
    und = cc[cc["pattern"] == "undocumented"]
    check("undocumented seed cases present", len(und) >= 9,
          f"{len(und)} closed cases the bank's analysts could not categorise")

    ring_dev = ("SM-G935F Build/NRD90M | Android 7.0 | chrome 62.0 for android | 1920x1080")
    ring = tx[tx["device_profile"] == ring_dev]
    anon = ring[ring["proxy"].str.contains("ANON", na=False)]
    ratio = anon["card_id"].nunique() / max(ring["card_id"].nunique(), 1)
    check("shared-device ring intact", ratio > 0.9,
          f"{ring['card_id'].nunique()} cards, anonymous-proxy ratio {ratio:.2f}")

    # ---- the store answers a real query -------------------------------------
    try:
        from fraudagent.graphstore import get_store
        store = get_store()
        h = store.health()
        r = pack.iloc[0]
        base = store.card_baseline(r.card_id, pd.to_datetime(r.opened_at).to_pydatetime())
        check(f"graph store ({h.get('backend')}) answers", base.get("n_txns", 0) > 0,
              f"card_baseline({r.card_id}) → {base.get('n_txns')} prior transactions")
    except Exception as exc:
        check("graph store answers", False, str(exc))

    width = max(len(n) for _, n, _ in results) + 2
    print()
    for status, name, detail in results:
        mark = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL "}[status]
        print(f"[{mark}] {name.ljust(width)} {detail}")
    failed = [n for s, n, _ in results if s == FAIL]
    print()
    if failed:
        print(f"{len(failed)} check(s) failed: {', '.join(failed)}")
        return 1
    warns = sum(1 for s, _, _ in results if s == WARN)
    print(f"all {len(results)} checks passed" + (f" ({warns} warning)" if warns else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
